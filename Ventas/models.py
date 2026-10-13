from django.db import models
from decimal import Decimal, ROUND_HALF_UP
from Usuario.models import Clientes
from Inventario.models import Productos
from django.db.models.signals import post_save
from django.dispatch import receiver
from Inventario.utils import registrar_movimiento


def _importe_monetario(valor):
    return Decimal(str(valor or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


class Ventas(models.Model):
    numero = models.AutoField(primary_key=True)
    codigo = models.CharField(max_length=25, unique=True)
    articulo = models.CharField(max_length=25)
    cantidad = models.IntegerField()
    precio = models.DecimalField(max_digits=10, decimal_places=2)
    descuento = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    iva = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    Fecha = models.DateTimeField(auto_now_add=True)
    ESTADOS = (
        ('facturada', 'Facturada'),
        ('anulada', 'Anulada'),
    )
    estado = models.CharField(max_length=10, choices=ESTADOS, default='facturada')
    
    def __str__(self):
        return self.codigo

class Factura(models.Model):
    numero = models.AutoField(primary_key=True)
    pedido = models.OneToOneField('dashboard.Pedido', on_delete=models.CASCADE, related_name='factura', null=True, blank=True)
    cliente = models.ForeignKey(Clientes, on_delete=models.CASCADE)
    fecha = models.DateTimeField(auto_now_add=True)
    estado = models.CharField(max_length=10, choices=(('facturada', 'Facturada'), ('anulada', 'Anulada')), default='facturada')
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    iva = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    moneda = models.CharField(max_length=10, default='Bs.')
    # Campos adicionales para formato SENIAT
    razon_social = models.CharField(max_length=200, blank=True)
    rif = models.CharField(max_length=30, blank=True)
    direccion_fiscal = models.CharField(max_length=300, blank=True)
    autorizacion = models.CharField(max_length=200, blank=True)

    @property
    def iva_16(self):
        return self.iva or Decimal('0.00')

    def calcular_totales(self):
        total = Decimal(self.total or 0)
        self.subtotal = (total / Decimal('1.16')).quantize(Decimal('0.01'))
        self.iva = (total - self.subtotal).quantize(Decimal('0.01'))
        return self.subtotal, self.iva, self.total

    def resumen_tributario(self, detalles=None):
        grupos = {}
        for detalle in detalles if detalles is not None else self.detalles.all():
            alicuota = _importe_monetario(detalle.iva)
            grupo = grupos.setdefault(alicuota, {
                'alicuota': alicuota,
                'base_imponible': Decimal('0.00'),
                'monto_iva': Decimal('0.00'),
            })
            grupo['base_imponible'] += detalle.base_imponible
            grupo['monto_iva'] += detalle.monto_iva
        return [grupos[alicuota] for alicuota in sorted(grupos)]

    class Meta:
        verbose_name = 'Factura'
        verbose_name_plural = 'Facturas'

class DetalleFactura(models.Model):
    factura = models.ForeignKey(Factura, related_name='detalles', on_delete=models.CASCADE)
    producto = models.ForeignKey(Productos, on_delete=models.PROTECT)
    cantidad = models.PositiveIntegerField()
    precio = models.DecimalField(max_digits=10, decimal_places=2)
    costo_unitario = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    descuento = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    iva = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    @property
    def importe_bruto(self):
        return _importe_monetario(Decimal(str(self.precio or 0)) * int(self.cantidad or 0))

    @property
    def importe_descuento(self):
        return _importe_monetario(self.importe_bruto * Decimal(str(self.descuento or 0)) / Decimal('100'))

    @property
    def base_imponible(self):
        return _importe_monetario(self.importe_bruto - self.importe_descuento)

    @property
    def monto_iva(self):
        return _importe_monetario(self.base_imponible * Decimal(str(self.iva or 0)) / Decimal('100'))

    @property
    def total_linea(self):
        return _importe_monetario(self.base_imponible + self.monto_iva)

    def subtotal(self):
        return self.total_linea

@receiver(post_save, sender=DetalleFactura)
def crear_movimiento_venta(sender, instance, created, **kwargs):
    if created:
        pedido = instance.factura.pedido
        if pedido and pedido.stock_descontado:
            return
        registrar_movimiento(
            producto=instance.producto,
            tipo='salida',
            cantidad=instance.cantidad,
            descripcion=f'Venta Factura #{instance.factura.numero}'
        )

class PrecioProducto(models.Model):
    producto = models.ForeignKey('Inventario.Productos', on_delete=models.CASCADE)
    precio_venta = models.DecimalField(max_digits=10, decimal_places=2)
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField(null=True, blank=True)
    en_promocion = models.BooleanField(default=False)
    # Otros campos según tu lógica