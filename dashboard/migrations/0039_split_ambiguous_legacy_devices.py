import uuid

from django.db import migrations


def split_ambiguous_legacy_devices(apps, schema_editor):
    AdminDevice = apps.get_model('dashboard', 'AdminDevice')
    database = schema_editor.connection.alias
    ambiguous_devices = AdminDevice.objects.using(database).filter(
        name__in=('', 'Dispositivo anterior'),
    ).order_by('pk')

    for device in ambiguous_devices.iterator():
        sessions = list(device.sessions.using(database).order_by('-last_seen_at', 'pk'))
        if not sessions:
            device.name = ''
            device.save(update_fields=['name'], using=database)
            continue

        device.name = ''
        device.first_seen_at = min(session.last_seen_at for session in sessions)
        latest_session = sessions[0]
        device.last_seen_at = latest_session.last_seen_at
        device.ip_address = latest_session.ip_address
        device.user_agent = (latest_session.user_agent or '')[:1000]
        device.is_active = any(session.is_active for session in sessions)
        device.save(
            update_fields=[
                'name', 'first_seen_at', 'last_seen_at', 'ip_address', 'user_agent', 'is_active',
            ],
            using=database,
        )

        for session in sessions[1:]:
            separate_device = AdminDevice.objects.using(database).create(
                user_id=device.user_id,
                device_id=uuid.uuid4(),
                passkey_id=session.passkey_id,
                name='',
                ip_address=session.ip_address,
                user_agent=(session.user_agent or '')[:1000],
                first_seen_at=session.last_seen_at,
                last_seen_at=session.last_seen_at,
                is_active=session.is_active,
                is_primary=False,
            )
            session.device_id = separate_device.pk
            session.save(update_fields=['device'], using=database)


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0038_admindevice_registry'),
    ]

    operations = [
        migrations.RunPython(split_ambiguous_legacy_devices, migrations.RunPython.noop),
    ]