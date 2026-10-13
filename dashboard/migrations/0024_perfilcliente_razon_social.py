from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0023_pago_transferencia_manual'),
    ]

    operations = [
        migrations.AddField(
            model_name='perfilcliente',
            name='razon_social',
            field=models.CharField(blank=True, default='', max_length=200),
        ),
    ]