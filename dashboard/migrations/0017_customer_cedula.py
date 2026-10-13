from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0016_alter_pedido_estado_perfilcliente'),
    ]

    operations = [
        migrations.AddField(
            model_name='customer',
            name='cedula',
            field=models.CharField(blank=True, db_index=True, default=None, max_length=20, null=True, unique=True),
        ),
    ]
