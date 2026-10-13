from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from dashboard.models import AuditLog

class Command(BaseCommand):
    help = 'Elimina registros de auditoría con más de 7 días'

    def handle(self, *args, **kwargs):
        hace_7_dias = timezone.now() - timedelta(days=7)
        eliminados, _ = AuditLog.objects.filter(timestamp__lt=hace_7_dias).delete()
        self.stdout.write(self.style.SUCCESS(f'Registros eliminados: {eliminados}'))