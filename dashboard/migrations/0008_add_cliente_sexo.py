from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0007_alter_cliente_user_alter_pedido_estado_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='cliente',
            name='sexo',
            field=models.CharField(blank=True, choices=[('m', 'Masculino'), ('f', 'Femenino'), ('o', 'Otro')], max_length=1, null=True),
        ),
    ]
