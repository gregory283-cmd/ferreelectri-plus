from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0005_merge_20251122_1546'),
        ('Inventario', '0007_remove_productos_existencia_min_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='carritoitem',
            name='producto',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='Inventario.Productos'),
        ),
        migrations.AlterField(
            model_name='pedidoitem',
            name='producto',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='Inventario.Productos', null=True, blank=True),
        ),
    ]
