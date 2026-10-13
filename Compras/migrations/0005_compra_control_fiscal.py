from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('Compras', '0004_remove_compra_numero_compra'),
    ]

    operations = [
        migrations.AddField(
            model_name='compra',
            name='control_fiscal',
            field=models.CharField(blank=True, default='', max_length=50),
        ),
    ]