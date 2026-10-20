import json
import urllib.error
import urllib.request

from django.conf import settings


class RenderBackupError(RuntimeError):
    pass


def render_backup_configured() -> bool:
    return bool(
        str(getattr(settings, 'RENDER_API_KEY', '') or '').strip()
        and str(getattr(settings, 'RENDER_POSTGRES_ID', '') or '').strip()
    )


def render_postgres_dashboard_url() -> str:
    postgres_id = str(getattr(settings, 'RENDER_POSTGRES_ID', '') or '').strip()
    if not postgres_id.startswith('dpg-'):
        return ''
    return f'https://dashboard.render.com/d/{postgres_id}'


def create_postgres_export() -> dict:
    if not render_backup_configured():
        raise RenderBackupError('Configura RENDER_API_KEY y RENDER_POSTGRES_ID en Render.')

    postgres_id = str(settings.RENDER_POSTGRES_ID).strip()
    if not postgres_id.startswith('dpg-'):
        raise RenderBackupError('RENDER_POSTGRES_ID no parece ser un ID de PostgreSQL de Render.')

    request = urllib.request.Request(
        f'https://api.render.com/v1/postgres/{postgres_id}/export',
        headers={
            'Authorization': f'Bearer {settings.RENDER_API_KEY}',
            'Accept': 'application/json',
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read()
    except urllib.error.HTTPError as error:
        raise RenderBackupError(f'Render rechazó la exportación (HTTP {error.code}).') from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise RenderBackupError('No se pudo contactar la API de Render para crear la exportación.') from error

    if not payload:
        return {'status': 'requested'}
    try:
        result = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise RenderBackupError('Render respondió con un estado de exportación no válido.') from error
    return result if isinstance(result, dict) else {'status': 'requested'}


def list_postgres_exports() -> list[dict]:
    if not render_backup_configured():
        return []

    postgres_id = str(settings.RENDER_POSTGRES_ID).strip()
    request = urllib.request.Request(
        f'https://api.render.com/v1/postgres/{postgres_id}/export',
        headers={
            'Authorization': f'Bearer {settings.RENDER_API_KEY}',
            'Accept': 'application/json',
        },
        method='GET',
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            result = json.loads(response.read())
    except urllib.error.HTTPError as error:
        raise RenderBackupError(f'Render no permitió consultar las exportaciones (HTTP {error.code}).') from error
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        raise RenderBackupError('No se pudo consultar el historial de exportaciones de Render.') from error

    if not isinstance(result, list):
        raise RenderBackupError('Render respondió con una lista de exportaciones no válida.')
    exports = [item for item in result if isinstance(item, dict) and isinstance(item.get('url'), str)]
    exports.sort(key=lambda item: item.get('createdAt', ''), reverse=True)
    return exports


def retrieve_recovery_status() -> dict:
    if not render_backup_configured():
        return {'recoveryStatus': 'NOT_CONFIGURED'}

    postgres_id = str(settings.RENDER_POSTGRES_ID).strip()
    request = urllib.request.Request(
        f'https://api.render.com/v1/postgres/{postgres_id}/recovery',
        headers={
            'Authorization': f'Bearer {settings.RENDER_API_KEY}',
            'Accept': 'application/json',
        },
        method='GET',
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            result = json.loads(response.read())
    except urllib.error.HTTPError as error:
        raise RenderBackupError(f'Render no permitió consultar la recuperación (HTTP {error.code}).') from error
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        raise RenderBackupError('No se pudo consultar el estado de recuperación de Render.') from error
    return result if isinstance(result, dict) else {'recoveryStatus': 'UNKNOWN'}