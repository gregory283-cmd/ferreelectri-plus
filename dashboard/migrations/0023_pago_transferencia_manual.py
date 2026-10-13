import os

from django.conf import settings
from django.core.files.storage import default_storage
from django.db import migrations, models

from dashboard.storage import PrivatePaymentStorage


def move_payment_proofs_to_private_storage(apps, schema_editor):
    Pago = apps.get_model('dashboard', 'Pago')
    private_storage = PrivatePaymentStorage()
    for payment in Pago.objects.exclude(comprobante='').iterator():
        name = payment.comprobante.name
        if private_storage.exists(name):
            private_name = name
        elif default_storage.exists(name):
            with default_storage.open(name, 'rb') as proof:
                private_name = private_storage.save(name, proof)
        else:
            continue
        Pago.objects.filter(pk=payment.pk).update(comprobante=private_name)
        if os.path.abspath(settings.PRIVATE_MEDIA_ROOT) != os.path.abspath(settings.MEDIA_ROOT):
            default_storage.delete(name)


def move_payment_proofs_to_media_storage(apps, schema_editor):
    Pago = apps.get_model('dashboard', 'Pago')
    private_storage = PrivatePaymentStorage()
    for payment in Pago.objects.exclude(comprobante='').iterator():
        name = payment.comprobante.name
        if default_storage.exists(name):
            media_name = name
        elif private_storage.exists(name):
            with private_storage.open(name, 'rb') as proof:
                media_name = default_storage.save(name, proof)
        else:
            continue
        Pago.objects.filter(pk=payment.pk).update(comprobante=media_name)
        if os.path.abspath(settings.PRIVATE_MEDIA_ROOT) != os.path.abspath(settings.MEDIA_ROOT):
            private_storage.delete(name)


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0022_payment_data_and_stock_reservation'),
    ]

    operations = [
        migrations.RunPython(
            move_payment_proofs_to_private_storage,
            move_payment_proofs_to_media_storage,
        ),
        migrations.AlterField(
            model_name='pago',
            name='metodo',
            field=models.CharField(
                choices=[
                    ('STRIPE', 'Stripe'),
                    ('PAYPAL', 'PayPal'),
                    ('PAGO_MOVIL', 'Pago Móvil'),
                    ('TRANSFERENCIA', 'Transferencia bancaria'),
                    ('COMPROBANTE', 'Comprobante manual'),
                    ('ZELLE', 'Zelle'),
                    ('BINANCE', 'Binance'),
                ],
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name='pago',
            name='comprobante',
            field=models.ImageField(
                blank=True,
                null=True,
                storage=PrivatePaymentStorage(),
                upload_to='comprobantes/',
            ),
        ),
    ]