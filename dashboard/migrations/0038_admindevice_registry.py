import uuid

from django.db import migrations, models
import django.db.models.deletion
from django.utils.timezone import now


def link_existing_device_sessions(apps, schema_editor):
    AdminDevice = apps.get_model('dashboard', 'AdminDevice')
    AdminDeviceSession = apps.get_model('dashboard', 'AdminDeviceSession')
    AdminSecurityConfig = apps.get_model('dashboard', 'AdminSecurityConfig')
    database = schema_editor.connection.alias
    config = AdminSecurityConfig.objects.using(database).filter(pk=1).first()
    devices = {}
    primary_users = set()

    sessions = AdminDeviceSession.objects.using(database).order_by(
        'user_id', '-last_seen_at', 'pk',
    )
    for device_session in sessions.iterator():
        name = (device_session.name or '').strip()
        user_agent = (device_session.user_agent or '')[:1000]
        key = (device_session.user_id, device_session.passkey_id, name.casefold(), user_agent)
        device = devices.get(key)
        if device is None:
            is_primary = bool(
                config
                and config.owner_user_id == device_session.user_id
                and config.primary_passkey_id == device_session.passkey_id
                and device_session.passkey_id
                and device_session.user_id not in primary_users
            )
            device = AdminDevice.objects.using(database).create(
                user_id=device_session.user_id,
                passkey_id=device_session.passkey_id,
                device_id=uuid.uuid4(),
                name=name,
                ip_address=device_session.ip_address,
                user_agent=user_agent,
                first_seen_at=device_session.last_seen_at,
                last_seen_at=device_session.last_seen_at,
                is_active=True,
                is_primary=is_primary,
            )
            devices[key] = device
            if is_primary:
                primary_users.add(device_session.user_id)
        else:
            update_fields = []
            if device_session.last_seen_at < device.first_seen_at:
                device.first_seen_at = device_session.last_seen_at
                update_fields.append('first_seen_at')
            if device_session.last_seen_at > device.last_seen_at:
                device.last_seen_at = device_session.last_seen_at
                device.ip_address = device_session.ip_address
                device.user_agent = user_agent
                update_fields.extend(['last_seen_at', 'ip_address', 'user_agent'])
            if update_fields:
                device.save(update_fields=update_fields, using=database)

        device_session.device_id = device.pk
        device_session.save(update_fields=['device'], using=database)


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0037_developmentrequest'),
    ]

    operations = [
        migrations.CreateModel(
            name='AdminDevice',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('device_id', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('name', models.CharField(blank=True, max_length=80)),
                ('ip_address', models.GenericIPAddressField(blank=True, null=True)),
                ('user_agent', models.TextField(blank=True)),
                ('first_seen_at', models.DateTimeField(default=now)),
                ('last_seen_at', models.DateTimeField(default=now)),
                ('is_active', models.BooleanField(default=True)),
                ('is_primary', models.BooleanField(default=False)),
                ('passkey', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='admin_devices', to='dashboard.adminpasskey')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='admin_devices', to='auth.user')),
            ],
            options={
                'verbose_name': 'Dispositivo administrativo',
                'verbose_name_plural': 'Dispositivos administrativos',
                'indexes': [models.Index(fields=['user', 'is_active', 'last_seen_at'], name='dashboard_a_user_id_304a82_idx')],
                'constraints': [models.UniqueConstraint(condition=models.Q(('is_primary', True)), fields=('user',), name='dash_one_primary_device_user')],
            },
        ),
        migrations.AddField(
            model_name='admindevicesession',
            name='device',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='sessions', to='dashboard.admindevice'),
        ),
        migrations.RunPython(link_existing_device_sessions, migrations.RunPython.noop),
    ]