from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.core.management.color import no_style
from django.db import connection, transaction
from django.db.models import Sum

from Compras.models import Compra, DetalleCompra
from CxC.models import CuentaCobro, PagoCxC, ReversionPagoCxC
from FERREELECTRI_PLUS.backup_utils import BackupError, create_backup
from Inventario.models import CostoCambio, MovimientoInventario, Productos
from Proveedores.models import Proveedores
from Usuario.models import Clientes as ClientesOperativos
from Ventas.models import DetalleFactura, Factura, PrecioProducto, Ventas
from dashboard.models import (
    Carrito,
    CarritoItem,
    ChatMessage,
    ChatSession,
    Cliente,
    Customer,
    Pago,
    Pedido,
    PedidoArchivado,
    PedidoItem,
    PerfilCliente,
)


class Command(BaseCommand):
    help = 'Reinicia datos operativos conservando el catálogo, precios, existencias y usuarios administrativos.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--confirm',
            action='store_true',
            help='Crear y verificar un backup completo y luego borrar los datos mostrados.',
        )
        parser.add_argument(
            '--allow-production',
            action='store_true',
            help='Permite ejecutar contra DEBUG=False; requiere además --confirm.',
        )

    def handle(self, *args, **options):
        if not options['confirm']:
            self.stderr.write(self.style.WARNING(
                'Modo de previsualización: no se modificó ningún dato. Revisa los conteos y usa --confirm para continuar.'
            ))

        if not options['confirm']:
            self._report_counts()
            return

        from django.conf import settings
        if not settings.DEBUG and not options['allow_production']:
            raise CommandError('DEBUG=False. Repite con --allow-production solo si confirmas este entorno.')

        try:
            backup_path = create_backup()
        except (BackupError, OSError, ValueError) as error:
            raise CommandError(f'No se borró ningún dato porque el backup falló: {error}') from error

        models_to_clear = [
            ReversionPagoCxC,
            PagoCxC,
            CuentaCobro,
            DetalleFactura,
            Factura,
            Ventas,
            DetalleCompra,
            Compra,
            Proveedores,
            Pago,
            PedidoItem,
            Pedido,
            PedidoArchivado,
            CarritoItem,
            Carrito,
            ChatMessage,
            ChatSession,
            MovimientoInventario,
            CostoCambio,
            PrecioProducto,
            Customer,
            Cliente,
            PerfilCliente,
            ClientesOperativos,
        ]
        product_snapshot = list(
            Productos.objects.order_by('Codigo').values_list(
                'Codigo', 'Precio', 'Costo', 'Cantidad', 'iva', 'Categoria_id', 'Imagen', 'presentations',
            )
        )
        payment_proofs = list(
            Pago.objects.exclude(comprobante='').values_list('comprobante', flat=True)
        )
        sequence_models = [model for model in models_to_clear if model._meta.auto_created is False]
        user_model = get_user_model()

        try:
            with transaction.atomic():
                for model in models_to_clear:
                    model.objects.all().delete()
                user_model.objects.filter(is_staff=False, is_superuser=False).delete()

                with connection.cursor() as cursor:
                    for statement in connection.ops.sequence_reset_sql(no_style(), sequence_models):
                        cursor.execute(statement)

                current_products = list(
                    Productos.objects.order_by('Codigo').values_list(
                        'Codigo', 'Precio', 'Costo', 'Cantidad', 'iva', 'Categoria_id', 'Imagen', 'presentations',
                    )
                )
                if current_products != product_snapshot:
                    raise CommandError('Se detectó un cambio inesperado en el catálogo; la transacción fue cancelada.')
        except Exception:
            raise

        storage = Pago._meta.get_field('comprobante').storage
        for proof_name in payment_proofs:
            try:
                storage.delete(proof_name)
            except Exception as error:
                self.stderr.write(self.style.WARNING(
                    f'No se pudo borrar un comprobante privado ({type(error).__name__}); permanece en el backup.'
                ))

        self.stdout.write(self.style.SUCCESS(f'Backup completo verificado: {backup_path}'))
        self.stdout.write(self.style.SUCCESS(
            f'Datos operativos reiniciados. Se conservaron {len(product_snapshot)} productos, sus precios, stock, imágenes y presentaciones.'
        ))
        self.stdout.write('Se conservaron los usuarios administrativos y los registros de auditoría.')

    def _report_counts(self):
        from django.conf import settings

        self.stdout.write(f'Base activa: {connection.vendor}; DEBUG={settings.DEBUG}')
        self.stdout.write('Registros que se eliminarían:')
        for model in (
            Factura, Ventas, Compra, Proveedores, Pedido, Pago, PedidoArchivado,
            CuentaCobro, PagoCxC, MovimientoInventario, CostoCambio, PrecioProducto,
            Customer, Cliente, PerfilCliente, ClientesOperativos, ChatSession,
        ):
            self.stdout.write(f'  {model._meta.label}: {model.objects.count()}')
        stock = Productos.objects.aggregate(total=Sum('Cantidad'))['total'] or 0
        self.stdout.write(f'Productos que se conservarían: {Productos.objects.count()} (stock total: {stock})')