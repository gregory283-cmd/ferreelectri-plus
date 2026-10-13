from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from FERREELECTRI_PLUS.backup_utils import BackupError, create_backup


class Command(BaseCommand):
    help = 'Crea y verifica una copia completa de base de datos y archivos subidos.'

    def handle(self, *args, **options):
        try:
            backup_path = create_backup()
        except (BackupError, OSError, ValueError) as error:
            raise CommandError(str(error)) from error

        self.stdout.write(self.style.SUCCESS(f'Backup verificado: {backup_path}'))
        if not getattr(settings, 'BACKUP_MIRROR_DIRECTORY', '').strip():
            self.stderr.write(
                self.style.WARNING(
                    'No hay copia secundaria configurada. Una copia en el mismo equipo '
                    'no protege ante pérdida del disco o del servidor.'
                )
            )