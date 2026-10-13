from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone
from decimal import Decimal, ROUND_HALF_UP

from .models import CostoCambio, CostoLote, CostoPendiente, MovimientoInventario, Productos


def aplicar_costo_y_recalcular_precio(producto, nuevo_costo, usuario=None, motivo=''):
    nuevo_costo = Decimal(str(nuevo_costo)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    costo_anterior = producto.Costo or Decimal('0.00')
    precio_anterior = producto.Precio or Decimal('0.00')
    if costo_anterior > 0 and precio_anterior > 0:
        precio_nuevo = (precio_anterior * nuevo_costo / costo_anterior).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
    else:
        precio_nuevo = precio_anterior

    if nuevo_costo != costo_anterior:
        CostoCambio.objects.create(
            producto=producto,
            anterior=costo_anterior,
            nuevo=nuevo_costo,
            usuario=usuario,
            motivo=motivo,
        )
    producto.Costo = nuevo_costo
    producto.Precio = precio_nuevo
    producto.save(update_fields=['Costo', 'Precio'])
    return costo_anterior, precio_anterior, precio_nuevo


def asegurar_lote_inicial(producto):
    cantidad_en_lotes = CostoLote.objects.filter(producto=producto).aggregate(
        total=Sum('cantidad_disponible')
    )['total'] or 0
    diferencia = int(producto.Cantidad or 0) - int(cantidad_en_lotes)
    if diferencia > 0:
        CostoLote.objects.create(
            producto=producto,
            costo_unitario=producto.Costo or 0,
            cantidad_recibida=diferencia,
            cantidad_disponible=diferencia,
        )


def _consumir_lotes_fifo(producto, cantidad, costo_lote_id=None):
    restante = cantidad
    lotes = CostoLote.objects.select_for_update().filter(
        producto=producto,
        cantidad_disponible__gt=0,
    )
    if costo_lote_id is not None:
        lotes = lotes.filter(pk=costo_lote_id)
    else:
        lotes = lotes.order_by('recibido_en', 'pk')
    for lote in lotes:
        consumido = min(restante, lote.cantidad_disponible)
        lote.cantidad_disponible -= consumido
        lote.save(update_fields=['cantidad_disponible'])
        restante -= consumido
        if not restante:
            break
    if restante:
        raise ValidationError('El stock físico no coincide con los lotes de costo registrados.')

    propuestas = CostoPendiente.objects.select_for_update().filter(
        producto=producto,
        estado='espera_stock',
    )
    for propuesta in propuestas:
        quedan_costos_mayores = CostoLote.objects.filter(
            producto=producto,
            cantidad_disponible__gt=0,
            costo_unitario__gt=propuesta.costo_propuesto,
        ).exists()
        if not quedan_costos_mayores:
            propuesta.estado = 'pendiente'
            propuesta.pendiente_desde = timezone.now()
            propuesta.save(update_fields=['estado', 'pendiente_desde'])


def registrar_movimiento(
    producto, tipo, cantidad, descripcion='', usuario=None,
    costo_unitario=None, compra_id=None, costo_lote_id=None,
):
    """
    Registra un movimiento de inventario.
    - producto: instancia de Productos o su id
    - tipo: 'entrada' o 'salida'
    - cantidad: cantidad del movimiento
    - descripcion: texto opcional
    """
    cantidad = int(cantidad)
    if cantidad <= 0:
        raise ValidationError('La cantidad del movimiento debe ser mayor que cero.')
    if tipo not in {'entrada', 'salida'}:
        raise ValidationError('El tipo de movimiento no es válido.')

    producto_id = producto.pk if isinstance(producto, Productos) else producto
    with transaction.atomic():
        producto_actual = Productos.objects.select_for_update().filter(pk=producto_id).first()
        if producto_actual is None:
            raise Productos.DoesNotExist(f'No existe el producto {producto_id}.')
        asegurar_lote_inicial(producto_actual)
        productos = Productos.objects.filter(pk=producto_id)
        if tipo == 'salida':
            actualizado = productos.filter(Cantidad__gte=cantidad).update(Cantidad=F('Cantidad') - cantidad)
            if not actualizado:
                stock = productos.values_list('Cantidad', flat=True).first()
                if stock is None:
                    raise Productos.DoesNotExist(f'No existe el producto {producto_id}.')
                raise ValidationError(f'Stock insuficiente. Disponible: {stock}; solicitado: {cantidad}.')
            _consumir_lotes_fifo(producto_actual, cantidad, costo_lote_id=costo_lote_id)
        else:
            actualizado = productos.update(Cantidad=F('Cantidad') + cantidad)
            if not actualizado:
                raise Productos.DoesNotExist(f'No existe el producto {producto_id}.')
            costo_lote = producto_actual.Costo if costo_unitario is None else costo_unitario
            CostoLote.objects.create(
                producto=producto_actual,
                compra_id=compra_id,
                costo_unitario=costo_lote or 0,
                cantidad_recibida=cantidad,
                cantidad_disponible=cantidad,
            )

        producto_actualizado = Productos.objects.get(pk=producto_id)
        movimiento = MovimientoInventario.objects.create(
            producto=producto_actualizado,
            tipo=tipo,
            cantidad=cantidad,
            descripcion=descripcion,
            usuario=usuario,
        )
        if isinstance(producto, Productos):
            producto.Cantidad = producto_actualizado.Cantidad
        return movimiento