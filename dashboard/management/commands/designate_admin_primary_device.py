import uuid

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from dashboard.models import AdminDevice, AdminPasskey, AdminSecurityConfig, AuditLog


class Command(BaseCommand):
    help = 'Designa el dispositivo principal de auditoría de un superusuario.'

    def add_arguments(self, parser):
        parser.add_argument('--username', required=True)
        parser.add_argument('--device-id', required=True, help='UUID del dispositivo registrado.')
        parser.add_argument('--passkey-id', type=int, help='ID de una passkey activa de ese usuario.')

    def handle(self, *args, **options):
        user_model = get_user_model()
        user = user_model.objects.filter(username=options['username']).first()
        if not user or not user.is_active or not user.is_staff or not user.is_superuser:
            raise CommandError('El usuario debe ser un superusuario activo.')

        try:
            device_id = uuid.UUID(options['device_id'])
        except (TypeError, ValueError, AttributeError) as error:
            raise CommandError('--device-id debe ser un UUID válido.') from error

        with transaction.atomic():
            config = AdminSecurityConfig.objects.select_for_update().filter(pk=1).first()
            create_config = config is None
            if config and config.owner_user_id and config.owner_user_id != user.pk:
                raise CommandError('La configuración de seguridad ya pertenece a otra cuenta.')

            device = AdminDevice.objects.select_for_update().filter(
                user=user, device_id=device_id, is_active=True,
            ).first()
            if not device:
                raise CommandError('No existe un dispositivo activo con ese UUID para el usuario.')

            passkey_id = options.get('passkey_id') or device.passkey_id
            passkey = AdminPasskey.objects.filter(
                pk=passkey_id, user=user, is_active=True,
            ).first()
            if not passkey:
                raise CommandError('El dispositivo debe estar asociado a una passkey activa del usuario.')

            if config is None:
                config = AdminSecurityConfig(pk=1)
            AdminDevice.objects.filter(user=user).update(is_primary=False)
            device.passkey = passkey
            device.is_primary = True
            device.save(update_fields=['passkey', 'is_primary'])
            config.owner_user = user
            config.primary_passkey = passkey
            if create_config:
                config.save()
            else:
                config.save(update_fields=['owner_user', 'primary_passkey', 'updated_at'])
            AuditLog.objects.create(
                user=user,
                action='ADMIN_PRIMARY_DEVICE_SET',
                model_name='AdminDevice',
                object_id=str(device.pk),
                details=f'Dispositivo principal designado por consola: {device.name or device.device_id}.',
            )

        self.stdout.write(self.style.SUCCESS(
            f'Dispositivo "{device.name or device.device_id}" designado. Cierra sesión y vuelve a entrar con esa passkey.'
        ))