from django.core.management.base import BaseCommand
from django.conf import settings
import urllib.parse


class Command(BaseCommand):
    help = 'Verifica la configuración mínima de Google OAuth y genera una URL de autorización de prueba.'

    def handle(self, *args, **options):
        client_id = getattr(settings, 'GOOGLE_CLIENT_ID', '')
        client_secret = getattr(settings, 'GOOGLE_CLIENT_SECRET', '')
        redirect_uris = getattr(settings, 'GOOGLE_REDIRECT_URIS', [])

        self.stdout.write('--- Verificación Google OAuth ---')
        if not client_id:
            self.stdout.write(self.style.ERROR('GOOGLE_CLIENT_ID no está configurado.'))
        else:
            self.stdout.write(self.style.SUCCESS(f'GOOGLE_CLIENT_ID: {client_id}'))

        if not client_secret:
            self.stdout.write(self.style.WARNING('GOOGLE_CLIENT_SECRET no está configurado.'))
        else:
            self.stdout.write(self.style.SUCCESS('GOOGLE_CLIENT_SECRET: configurado'))

        if not redirect_uris:
            self.stdout.write(self.style.WARNING('GOOGLE_REDIRECT_URIS está vacío. Asegure las URIs en la consola de Google.'))
        else:
            self.stdout.write('GOOGLE_REDIRECT_URIS:')
            for u in redirect_uris:
                self.stdout.write(f'  - {u}')

        if client_id and redirect_uris:
            self.stdout.write('\nPara probar el login correctamente, abre la página de inicio de sesión de la app y usa el botón "Continuar con Google" o el flujo de Google One Tap:\n')
            self.stdout.write('  http://localhost:8000/cliente/login/')
            self.stdout.write('\nNo copies y pegues directamente una URL de autorización construida manualmente desde este comando, porque esa URL puede carecer del parámetro `state` y producir errores como `AuthMissingParameter`.')
            self.stdout.write('')
            self.stdout.write('Si ves "deleted_client" en la pantalla de Google, recrea el OAuth Client en Google Cloud Console y actualiza `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`.')

        self.stdout.write('--- Fin ---')
