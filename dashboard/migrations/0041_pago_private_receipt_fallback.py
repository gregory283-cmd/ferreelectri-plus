from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0040_admindevice_uuid_per_user'),
    ]

    operations = [
        migrations.AddField(
            model_name='pago',
            name='comprobante_data',
            field=models.BinaryField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name='pago',
            name='comprobante_content_type',
            field=models.CharField(blank=True, default='', max_length=100),
        ),
        migrations.AddField(
            model_name='pago',
            name='comprobante_filename',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
    ]