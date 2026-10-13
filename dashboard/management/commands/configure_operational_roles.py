from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand, CommandError


ROLE_PERMISSIONS = {
    'FERREELECTRI - Consulta operativa': (
        'view_operational_orders',
    ),
    'FERREELECTRI - Operadores de pagos': (
        'view_operational_orders',
        'verify_order_payments',
        'view_payment_evidence',
    ),
    'FERREELECTRI - Almacen': (
        'view_operational_orders',
        'manage_fulfillment',
    ),
}


class Command(BaseCommand):
    help = 'Crea grupos operativos y agrega los permisos mínimos de pedidos, pagos y almacén.'

    def handle(self, *args, **options):
        all_codenames = {
            codename
            for permissions in ROLE_PERMISSIONS.values()
            for codename in permissions
        }
        permissions = {
            permission.codename: permission
            for permission in Permission.objects.filter(
                content_type__app_label='dashboard',
                codename__in=all_codenames,
            )
        }
        missing = all_codenames - permissions.keys()
        if missing:
            raise CommandError(
                'Faltan permisos operativos. Ejecuta primero las migraciones: '
                + ', '.join(sorted(missing))
            )

        for role_name, codenames in ROLE_PERMISSIONS.items():
            group, created = Group.objects.get_or_create(name=role_name)
            group.permissions.add(*(permissions[codename] for codename in codenames))
            action = 'creado' if created else 'actualizado'
            self.stdout.write(self.style.SUCCESS(f'Grupo {role_name}: {action}.'))