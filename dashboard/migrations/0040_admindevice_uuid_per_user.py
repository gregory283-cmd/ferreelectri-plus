import uuid

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0039_split_ambiguous_legacy_devices'),
    ]

    operations = [
        migrations.AlterField(
            model_name='admindevice',
            name='device_id',
            field=models.UUIDField(default=uuid.uuid4, editable=False),
        ),
        migrations.AddConstraint(
            model_name='admindevice',
            constraint=models.UniqueConstraint(
                fields=('user', 'device_id'),
                name='dash_device_uuid_per_user',
            ),
        ),
    ]