import shutil
import tarfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from FERREELECTRI_PLUS.backup_utils import (
    BackupError,
    restore_backup_database,
)


class Command(BaseCommand):
    help = 'Valida e importa una copia PostgreSQL en la base de ensayo configurada.'

    def add_arguments(self, parser):
        parser.add_argument('--archive', required=True, help='Ruta local al paquete .tar.gz')
        parser.add_argument(
            '--files-directory',
            help='Directorio vacío donde extraer media/ y private-media/ para revisión manual',
        )
        parser.add_argument('--confirm', action='store_true', help='Confirmar restauración sobre RESTORE_DATABASE_URL')

    def handle(self, *args, **options):
        if not options['confirm']:
            raise CommandError('La restauración requiere --confirm y usa únicamente RESTORE_DATABASE_URL.')
        if not settings.RESTORE_DATABASE_URL:
            raise CommandError('Configura RESTORE_DATABASE_URL con una base PostgreSQL de ensayo.')

        try:
            archive_path = Path(options['archive']).expanduser().resolve()
            if not archive_path.is_file():
                raise BackupError('No existe el archivo de respaldo indicado.')
            database_name = restore_backup_database(archive_path, settings.RESTORE_DATABASE_URL)
            if options['files_directory']:
                self._extract_files(archive_path, Path(options['files_directory']).expanduser().resolve())
        except (BackupError, OSError, ValueError) as error:
            raise CommandError(str(error)) from error

        self.stdout.write(self.style.SUCCESS(f'Database restaurada en la base de ensayo: {database_name}'))
        if not options['files_directory']:
            self.stderr.write('Archivos media/ y private-media/ no se extrajeron; usa --files-directory para prepararlos.')

    def _extract_files(self, archive_path, destination):
        active_roots = {
            Path(settings.MEDIA_ROOT).resolve(),
            Path(settings.PRIVATE_MEDIA_ROOT).resolve(),
        }
        if any(
            destination == root or destination in root.parents or root in destination.parents
            for root in active_roots
        ):
            raise BackupError('El directorio de archivos debe ser de staging, no solaparse con media activa.')
        if destination.exists() and any(destination.iterdir()):
            raise BackupError('El directorio de staging debe estar vacío para evitar sobrescribir archivos.')
        destination.mkdir(parents=True, exist_ok=True)
        try:
            with tarfile.open(archive_path, 'r:gz') as archive:
                for member in archive.getmembers():
                    if not (member.name == 'media' or member.name.startswith('media/')
                            or member.name == 'private-media' or member.name.startswith('private-media/')):
                        continue
                    if member.issym() or member.islnk():
                        raise BackupError('El paquete contiene enlaces no permitidos en archivos media.')
                    output_path = (destination / member.name).resolve()
                    if destination not in output_path.parents and output_path != destination:
                        raise BackupError('El paquete contiene una ruta de archivo no permitida.')
                    if member.isdir():
                        output_path.mkdir(parents=True, exist_ok=True)
                        continue
                    if not member.isfile():
                        continue
                    source = archive.extractfile(member)
                    if source is None:
                        raise BackupError(f'No se pudo leer {member.name} del paquete.')
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    with source, output_path.open('xb') as output:
                        shutil.copyfileobj(source, output)
        except (OSError, tarfile.TarError) as error:
            raise BackupError(f'No se pudieron extraer los archivos del respaldo: {error}') from error