import hashlib
import json
import logging
import os
import shutil
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from django.conf import settings

logger = logging.getLogger(__name__)


class BackupError(RuntimeError):
    pass


def _find_postgres_tool(name: str) -> str:
    configured_path = getattr(settings, 'PG_DUMP_PATH', '')
    if configured_path:
        candidate = Path(configured_path)
        tool = candidate if name == 'pg_dump' else candidate.with_name(
            'pg_restore.exe' if candidate.suffix.lower() == '.exe' else 'pg_restore'
        )
        if tool.is_file():
            return str(tool)

    found = shutil.which(name)
    if found:
        return found

    if os.name == 'nt':
        program_files = Path(os.environ.get('ProgramFiles', r'C:\Program Files'))
        candidates = sorted(
            (program_files / 'PostgreSQL').glob(f'*/bin/{name}.exe'),
            reverse=True,
        )
        if candidates:
            return str(candidates[0])

    raise BackupError(f'No se encontró {name}; instala las herramientas cliente de PostgreSQL o configura PG_DUMP_PATH.')


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _run_pg_dump(dump_path: Path, database: dict[str, Any]) -> tuple[str, dict[str, str]]:
    executable = _find_postgres_tool('pg_dump')
    environment = os.environ.copy()
    password = database.get('PASSWORD')
    if password:
        environment['PGPASSWORD'] = str(password)
    options = database.get('OPTIONS') or {}
    if options.get('connect_timeout'):
        environment['PGCONNECT_TIMEOUT'] = str(options['connect_timeout'])
    if options.get('sslmode'):
        environment['PGSSLMODE'] = str(options['sslmode'])

    command = [
        executable,
        '--format=custom',
        '--no-owner',
        '--no-privileges',
        '--no-password',
        '--file', str(dump_path),
    ]
    for setting, flag in (('HOST', '--host'), ('PORT', '--port'), ('USER', '--username')):
        if database.get(setting):
            command.extend((flag, str(database[setting])))
    command.append(str(database['NAME']))

    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=getattr(settings, 'BACKUP_DUMP_TIMEOUT_SECONDS', 3600),
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise BackupError(f'No se pudo ejecutar pg_dump: {error}') from error
    if result.returncode:
        raise BackupError(f'pg_dump falló: {result.stderr.strip() or result.returncode}')

    restore_executable = _find_postgres_tool('pg_restore')
    try:
        validation = subprocess.run(
            [restore_executable, '--list', str(dump_path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise BackupError(f'No se pudo validar el dump con pg_restore: {error}') from error
    if validation.returncode:
        raise BackupError(f'El dump PostgreSQL no pasó la validación: {validation.stderr.strip()}')
    return 'postgresql-custom', environment


def _make_database_dump(dump_path: Path) -> tuple[str, dict[str, str]]:
    database = settings.DATABASES['default']
    engine = database.get('ENGINE', '')
    if 'postgresql' not in engine:
        raise BackupError(f'Este proyecto requiere PostgreSQL para generar backups; motor actual: {engine}')
    return _run_pg_dump(dump_path, database)


def _directory_manifest(path: Path) -> dict[str, int]:
    file_count = 0
    total_bytes = 0
    if path.exists():
        for item in path.rglob('*'):
            if item.is_file() and not item.is_symlink():
                file_count += 1
                total_bytes += item.stat().st_size
    return {'files': file_count, 'bytes': total_bytes}


def _verify_archive(archive_path: Path, database_member: str) -> None:
    try:
        with tarfile.open(archive_path, 'r:gz') as archive:
            names = set()
            database_digest = hashlib.sha256()
            for member in archive.getmembers():
                names.add(member.name)
                if not member.isfile():
                    continue
                source = archive.extractfile(member)
                if source is None:
                    raise BackupError(f'No se pudo leer {member.name} del paquete de backup.')
                with source:
                    for chunk in iter(lambda: source.read(1024 * 1024), b''):
                        if member.name == database_member:
                            database_digest.update(chunk)
            required = {database_member, 'backup-manifest.json', 'RESTORE.txt'}
            if not required.issubset(names):
                raise BackupError('El paquete de backup no contiene todos los archivos requeridos.')
            manifest_source = archive.extractfile('backup-manifest.json')
            if manifest_source is None:
                raise BackupError('No se pudo leer el manifiesto de integridad del respaldo.')
            with manifest_source:
                manifest = json.load(manifest_source)
            if manifest.get('database_member') != database_member:
                raise BackupError('El manifiesto apunta a una base de datos diferente del paquete.')
            if manifest.get('database_sha256') != database_digest.hexdigest():
                raise BackupError('La huella SHA-256 de la base de datos no coincide con el manifiesto.')
    except (OSError, tarfile.TarError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise BackupError(f'El archivo de backup no pasó la verificación de integridad: {error}') from error


def _prune_backups(directory: Path, keep: int) -> None:
    archives = sorted(
        directory.glob('ferreelectri-backup-*.tar.gz'),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    for expired in archives[max(1, keep):]:
        expired.unlink()


def create_backup(*args, **kwargs) -> str:
    """Crea y verifica un paquete autocontenido con DB, auditoría y archivos."""
    backup_directory = Path(getattr(settings, 'BACKUP_DIRECTORY', Path(settings.BASE_DIR) / 'backups' / 'weekly'))
    backup_directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().astimezone().strftime('%Y%m%d-%H%M%S')
    filename = f'ferreelectri-backup-{stamp}.tar.gz'
    archive_path = backup_directory / filename
    partial_path = backup_directory / f'.{filename}.partial'
    media_roots = (
        ('media', Path(settings.MEDIA_ROOT)),
        ('private-media', Path(settings.PRIVATE_MEDIA_ROOT)),
    )
    try:
        with tempfile.TemporaryDirectory(prefix='ferreelectri-backup-') as temporary_directory:
            work_directory = Path(temporary_directory)
            database_dump = work_directory / 'database.dump'
            database_format, _environment = _make_database_dump(database_dump)
            database_member = 'database.dump'

            manifest = {
                'format_version': 1,
                'created_at': datetime.now(timezone.utc).isoformat(),
                'database_engine': settings.DATABASES['default'].get('ENGINE', ''),
                'database_name': str(settings.DATABASES['default'].get('NAME', '')),
                'database_format': database_format,
                'database_member': database_member,
                'database_sha256': _sha256(database_dump),
                'media': {name: _directory_manifest(path) for name, path in media_roots},
                'audit_table_included': True,
            }
            manifest_path = work_directory / 'backup-manifest.json'
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
            restore_path = work_directory / 'RESTORE.txt'
            restore_path.write_text(
                'Paquete de restauración FERREELECTRI PLUS\n'
                'Incluye la base de datos completa (incluida AuditLog), media/ y private-media/.\n\n'
                'PostgreSQL: restaura database.dump con pg_restore sobre una base NUEVA y vacía; '
                'no ejecutes --clean contra la base activa.\n'
                'Copia media/ y private-media/ a MEDIA_ROOT y PRIVATE_MEDIA_ROOT antes de habilitar tráfico.\n'
                'Comprueba el manifiesto y valida acceso a pedidos, pagos y comprobantes antes de volver a producción.\n',
                encoding='utf-8',
            )

            with tarfile.open(partial_path, mode='w:gz', compresslevel=6) as archive:
                archive.add(database_dump, arcname=database_member)
                archive.add(manifest_path, arcname='backup-manifest.json')
                archive.add(restore_path, arcname='RESTORE.txt')
                for archive_name, source_path in media_roots:
                    if source_path.exists():
                        archive.add(source_path, arcname=archive_name, recursive=True)

        _verify_archive(partial_path, database_member)
        os.replace(partial_path, archive_path)

        mirror = str(getattr(settings, 'BACKUP_MIRROR_DIRECTORY', '') or '').strip()
        if mirror:
            mirror_directory = Path(mirror)
            mirror_directory.mkdir(parents=True, exist_ok=True)
            mirror_path = mirror_directory / filename
            shutil.copy2(archive_path, mirror_path)
            if _sha256(archive_path) != _sha256(mirror_path):
                mirror_path.unlink(missing_ok=True)
                raise BackupError('La copia secundaria no coincide con el archivo principal.')

        status_path = backup_directory / 'backup-status.json'
        status_partial = backup_directory / '.backup-status.json.partial'
        status = {
            'created_at': datetime.now(timezone.utc).isoformat(),
            'archive_name': filename,
            'archive_sha256': _sha256(archive_path),
            'archive_bytes': archive_path.stat().st_size,
            'database_format': database_format,
            'mirror_configured': bool(mirror),
            'mirror_verified': bool(mirror),
        }
        try:
            status_partial.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding='utf-8')
            os.replace(status_partial, status_path)
        except OSError:
            status_partial.unlink(missing_ok=True)
            logger.exception('El respaldo quedó verificado, pero no se pudo actualizar su archivo de estado.')

        retention = int(getattr(settings, 'BACKUP_RETENTION_COUNT', 12))
        _prune_backups(backup_directory, retention)
        return str(archive_path)
    except Exception:
        partial_path.unlink(missing_ok=True)
        raise
