from django.db import migrations, models


def mark_existing_orders_as_stocked(apps, schema_editor):
    Pedido = apps.get_model('dashboard', 'Pedido')
    Pedido.objects.all().update(stock_descontado=True)


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0021_alter_chatmessage_action_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='pedido',
            name='stock_descontado',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='pago',
            name='banco_origen',
            field=models.CharField(blank=True, default='', max_length=100),
        ),
        migrations.AddField(
            model_name='pago',
            name='cedula_pagador',
            field=models.CharField(blank=True, default='', max_length=30),
        ),
        migrations.AddField(
            model_name='pago',
            name='numero_referencia',
            field=models.CharField(blank=True, default='', max_length=100),
        ),
        migrations.RunPython(mark_existing_orders_as_stocked, migrations.RunPython.noop),
    ]