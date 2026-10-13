# Generated manually: add presentacion_type and presentacion_factor to CarritoItem
from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0013_pago_gateway_pago_gateway_payload_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='carritoitem',
            name='presentacion_type',
            field=models.CharField(blank=True, max_length=120, null=True),
        ),
        migrations.AddField(
            model_name='carritoitem',
            name='presentacion_factor',
            field=models.PositiveIntegerField(default=1),
        ),
    ]
