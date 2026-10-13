import csv
import json
import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from django.shortcuts import render, get_object_or_404, redirect
from django.core.paginator import Paginator
from django.utils import timezone
from django.db import transaction
from django.db.models import Q
from .models import Compra, DetalleCompra
from Inventario.models import CostoLote, CostoPendiente, Productos, MovimientoInventario
from Proveedores.models import Proveedores
from django.contrib.auth.decorators import login_required, permission_required
from django.views.decorators.http import require_POST
from django.http import JsonResponse, HttpResponse
from Inventario.utils import registrar_movimiento
from Inventario.utils import aplicar_costo_y_recalcular_precio
from Inventario.models import CostoCambio
from django.contrib import messages

logger = logging.getLogger(__name__)


def _registrar_lote_compra(producto, cantidad, precio, compra, usuario, politica_costo='pendiente'):
    producto = Productos.objects.select_for_update().get(pk=producto.pk)
    costo_anterior = producto.Costo or Decimal('0.00')
    registrar_movimiento(
        producto,
        'entrada',
        cantidad,
        f'Entrada por compra (Compra #{compra.id})',
        usuario,
        costo_unitario=precio,
        compra_id=compra.id,
    )
    lote = CostoLote.objects.filter(
        producto=producto, compra_id=compra.id
    ).order_by('-pk').first()
    if politica_costo == 'vigente':
        CostoLote.objects.filter(producto=producto, cantidad_disponible__gt=0).update(
            costo_unitario=precio
        )
        for propuesta in CostoPendiente.objects.select_for_update().filter(
            producto=producto, estado__in=['pendiente', 'espera_stock']
        ):
            propuesta.estado = 'rechazado'
            propuesta.revisado_en = timezone.now()
            propuesta.revisado_por = usuario
            propuesta.motivo = f'{propuesta.motivo} · Reemplazado por compra #{compra.id}'.strip(' ·')[:255]
            propuesta.save(update_fields=['estado', 'revisado_en', 'revisado_por', 'motivo'])
        if precio != costo_anterior:
            aplicar_costo_y_recalcular_precio(
                producto,
                precio,
                usuario=usuario,
                motivo=f'Reemplazo explícito del costo por compra #{compra.id}',
            )
    elif precio != costo_anterior:
        hay_costo_anterior = CostoLote.objects.filter(
            producto=producto,
            cantidad_disponible__gt=0,
            costo_unitario__gt=precio,
        ).exists()
        CostoPendiente.objects.create(
            producto=producto,
            lote=lote,
            cantidad_compra=cantidad,
            unidad_compra='unidades',
            costo_propuesto=precio,
            motivo=f'Compra #{compra.id}',
            creado_por=usuario,
            estado='espera_stock' if hay_costo_anterior else 'pendiente',
            pendiente_desde=None if hay_costo_anterior else timezone.now(),
        )
    return lote


def listar_compras(request):
    search_query = request.GET.get('q', '').strip()
    compras_list = Compra.objects.select_related('proveedor').all()
    if search_query:
        search_filter = (
            Q(control_fiscal__icontains=search_query)
            | Q(proveedor__nombre__icontains=search_query)
            | Q(proveedor__cedula__icontains=search_query)
        )
        if search_query.isdigit():
            search_filter |= Q(id=int(search_query))
        compras_list = compras_list.filter(search_filter).distinct()
    compras_list = compras_list.order_by('-id')
    paginator = Paginator(compras_list, 5)
    page_number = request.GET.get('page')
    compras = paginator.get_page(page_number)

    total_compras = sum(c.total() for c in Compra.objects.all())
    hoy = timezone.now()
    compras_mes = Compra.objects.filter(
        fecha_emision__year=hoy.year,
        fecha_emision__month=hoy.month
    )
    total_compras_mes = sum(c.total() for c in compras_mes)

    return render(request, 'compras.html', {
        'compras': compras,
        'total_compras': total_compras,
        'total_compras_mes': total_compras_mes,
        'search_query': search_query,
    })

def reporte_compras_csv(request):
    compras = Compra.objects.select_related('proveedor').prefetch_related('detallecompra_set').order_by('-fecha_emision')
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="compras.csv"'
    writer = csv.writer(response)
    writer.writerow(['Compra ID', 'Proveedor', 'Cédula', 'Fecha de emisión', 'Estado', 'Producto', 'Cantidad', 'Precio', 'Subtotal', 'Total Compra'])

    for compra in compras:
        detalles = compra.detallecompra_set.all()
        total_compra = compra.total() if hasattr(compra, 'total') else sum(detalle.subtotal for detalle in detalles)
        if detalles:
            for detalle in detalles:
                writer.writerow([
                    compra.id,
                    compra.proveedor.nombre,
                    compra.proveedor.cedula,
                    compra.fecha_emision,
                    compra.estado,
                    detalle.producto.Codigo if hasattr(detalle.producto, 'Codigo') else detalle.producto.id,
                    detalle.cantidad,
                    detalle.precio,
                    detalle.subtotal,
                    total_compra,
                ])
        else:
            writer.writerow([
                compra.id,
                compra.proveedor.nombre,
                compra.proveedor.cedula,
                compra.fecha_emision,
                compra.estado,
                '',
                '',
                '',
                '',
                total_compra,
            ])
    return response

@login_required
@permission_required('Compras.view_compra', raise_exception=True)
def ver_compra(request, compra_id):
    compra = get_object_or_404(
        Compra.objects.select_related('proveedor').prefetch_related('detallecompra_set__producto'),
        id=compra_id,
    )
    return render(request, 'ver_compra.html', {'compra': compra})

@login_required
@permission_required('Compras.change_compra', raise_exception=True)
@require_POST
@transaction.atomic
def anular_compra(request, compra_id):
    compra = get_object_or_404(Compra.objects.select_for_update(), id=compra_id)
    if compra.estado != 'ANULADA':
        for detalle in compra.detallecompra_set.select_related('producto').order_by('producto_id'):
            producto = Productos.objects.select_for_update().get(pk=detalle.producto_id)
            lote = CostoLote.objects.select_for_update().filter(
                producto=producto, compra_id=compra.id, cantidad_disponible__gt=0,
            ).order_by('-pk').first()
            if lote:
                cantidad_retirar = lote.cantidad_disponible
            else:
                cantidad_retirar = min(detalle.cantidad, producto.Cantidad)
            if cantidad_retirar <= 0:
                if not lote:
                    CostoLote.objects.create(
                        producto=producto,
                        compra_id=compra.id,
                        costo_unitario=detalle.precio,
                        cantidad_recibida=0,
                        cantidad_disponible=0,
                        cantidad_anulada=0,
                    )
                continue
            registrar_movimiento(
                producto,
                'salida',
                cantidad_retirar,
                f'Anulación de compra (Compra #{compra.id})',
                request.user,
                costo_lote_id=lote.pk if lote else None,
            )
            if lote:
                lote.refresh_from_db()
                lote.cantidad_anulada += cantidad_retirar
                lote.save(update_fields=['cantidad_anulada'])
                propuestas_abiertas = lote.propuestas_costo.filter(estado__in=['pendiente', 'espera_stock'])
                for propuesta in propuestas_abiertas:
                    propuesta.estado = 'rechazado'
                    propuesta.revisado_en = timezone.now()
                    propuesta.revisado_por = request.user
                    propuesta.motivo = f'{propuesta.motivo} · Compra anulada'.strip(' ·')[:255]
                    propuesta.save(update_fields=['estado', 'revisado_en', 'revisado_por', 'motivo'])
            else:
                CostoLote.objects.create(
                    producto=producto,
                    compra_id=compra.id,
                    costo_unitario=detalle.precio,
                    cantidad_recibida=cantidad_retirar,
                    cantidad_disponible=0,
                    cantidad_anulada=cantidad_retirar,
                )
        compra.estado = 'ANULADA'
        compra.save()
        messages.success(request, 'Compra anulada correctamente y stock descontado.')
    else:
        messages.info(request, 'La compra ya está anulada.')
    return redirect('listar_compras')

@login_required
@permission_required('Compras.delete_compra', raise_exception=True)
@require_POST
def eliminar_compra(request, compra_id):
    compra = get_object_or_404(Compra, id=compra_id)
    if compra.estado != 'ANULADA':
        messages.error(request, 'Solo puedes eliminar compras anuladas.')
        return redirect('listar_compras')
    # No modificar stock aquí, ya fue devuelto al anular
    compra.delete()
    messages.success(request, 'Compra eliminada correctamente.')
    return redirect('listar_compras')

@login_required
@permission_required('Compras.add_compra', raise_exception=True)
def formato_compras(request):
    return render(request, 'formato_compras.html')


@transaction.atomic
@login_required
@permission_required('Compras.change_compra', raise_exception=True)
def modificar_compra(request, compra_id):
    compra = get_object_or_404(Compra, id=compra_id)
    if request.method == 'POST':
        for idx, detalle in enumerate(compra.detallecompra_set.all()):
            producto = detalle.producto
            anterior = producto.Costo or Decimal('0.00')
            try:
                precio = float(request.POST.get(f'precio_{idx}', detalle.precio))
                cantidad = int(request.POST.get(f'cantidad_{idx}', detalle.cantidad))
            except (TypeError, ValueError):
                messages.error(request, 'El precio y la cantidad deben ser valores válidos.')
                return redirect('modificar_compra', compra_id=compra.id)
            if precio < 0 or cantidad <= 0:
                messages.error(request, 'El precio no puede ser negativo y la cantidad debe ser mayor que cero.')
                return redirect('modificar_compra', compra_id=compra.id)
            detalle.precio = precio
            detalle.cantidad = cantidad
            detalle.subtotal = detalle.precio * detalle.cantidad
            detalle.save()
            nuevo = Decimal(str(detalle.precio or 0))
            if nuevo > anterior:
                aplicar_costo_y_recalcular_precio(
                    producto,
                    nuevo,
                    usuario=request.user,
                    motivo=f'Aumento al modificar la compra #{compra.id}',
                )
            elif nuevo < anterior:
                lote = CostoLote.objects.filter(
                    producto=producto,
                    compra_id=compra.id,
                    cantidad_disponible__gt=0,
                ).order_by('-pk').first()
                CostoPendiente.objects.create(
                    producto=producto,
                    lote=lote,
                    cantidad_compra=cantidad,
                    unidad_compra='unidades',
                    costo_propuesto=nuevo,
                    motivo=f'Costo actualizado al modificar la compra #{compra.id}',
                    creado_por=request.user,
                    pendiente_desde=timezone.now(),
                )
        return redirect('listar_compras')
    return render(request, 'modificar_compra.html', {'compra': compra})

@login_required
@permission_required('Compras.add_compra', raise_exception=True)
def api_proveedores(request):
    proveedores = Proveedores.objects.all().order_by('nombre')
    query = request.GET.get('q', '').strip()
    if query:
        proveedores = proveedores.filter(Q(nombre__icontains=query) | Q(cedula__icontains=query))
    return JsonResponse([
        {
            'ruc_nit': proveedor.cedula,
            'nombre': proveedor.nombre,
            'email': proveedor.email,
            'telefono': proveedor.telefono,
            'direccion': proveedor.direccion,
        }
        for proveedor in proveedores
    ], safe=False)


@login_required
@permission_required('Compras.add_compra', raise_exception=True)
def api_articulos(request):
    productos = Productos.objects.all().order_by('Descripcion')
    query = request.GET.get('q', '').strip()
    if query:
        productos = productos.filter(Q(Codigo__icontains=query) | Q(Descripcion__icontains=query))
    return JsonResponse([
        {
            'codigo': producto.Codigo,
            'descripcion': producto.Descripcion,
            'precio': str(producto.Precio or 0),
            'costo': str(producto.Costo or 0),
            'stock': producto.Cantidad,
            'iva': str(producto.iva or 0),
            'promocion': bool(producto.promocion),
        }
        for producto in productos
    ], safe=False)


@login_required
@permission_required('Compras.add_compra', raise_exception=True)
@require_POST
def guardar_compra(request):
    try:
        data = json.loads(request.body or '{}')
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'ok': False, 'msg': 'La solicitud no contiene JSON válido.'}, status=400)

    try:
        cedula = ''.join(char for char in str(data.get('ruc_nit', '')).upper() if char.isalnum())
        proveedor = Proveedores.objects.filter(cedula__iexact=cedula).first()
        if not proveedor:
            nombre_proveedor = str(data.get('proveedor', '')).strip()
            if not nombre_proveedor or not cedula:
                return JsonResponse({'ok': False, 'msg': 'Selecciona un proveedor con nombre y cédula/RIF.'}, status=400)
            proveedor = Proveedores(
                cedula=cedula,
                nombre=nombre_proveedor[:60],
                email=f'pendiente+{cedula}@example.invalid',
                telefono='0000000000',
                direccion='Por completar',
            )
            try:
                proveedor.save()
            except Exception:
                return JsonResponse({'ok': False, 'msg': 'No se pudo crear el proveedor. Verifica su cédula/RIF.'}, status=400)

        fecha_emision = datetime.strptime(
            data.get('fecha_compra') or timezone.localdate().isoformat(),
            '%Y-%m-%d',
        ).date()
        control_fiscal = str(data.get('control_fiscal', '')).strip()
        politica_costo = str(data.get('politica_costo', 'pendiente'))
        if politica_costo not in {'pendiente', 'vigente'}:
            return JsonResponse({'ok': False, 'msg': 'La política de costo seleccionada no es válida.'}, status=400)
        articulos = data.get('articulos')
        if not control_fiscal:
            return JsonResponse({'ok': False, 'msg': 'El número de control fiscal es obligatorio.'}, status=400)
        if not isinstance(articulos, list) or not articulos:
            return JsonResponse({'ok': False, 'msg': 'Agrega al menos un artículo a la compra.'}, status=400)

        articulos_validados = []
        codigos = set()
        for articulo in articulos:
            codigo = str(articulo.get('codigo', '')).strip()
            if not codigo or codigo in codigos:
                return JsonResponse({'ok': False, 'msg': 'Hay códigos vacíos o repetidos en los artículos.'}, status=400)
            codigos.add(codigo)
            try:
                cantidad = int(articulo.get('cantidad', 0))
                precio = Decimal(str(articulo.get('precio', 0)))
            except (TypeError, ValueError, InvalidOperation):
                return JsonResponse({'ok': False, 'msg': f'Cantidad o precio inválido para {codigo}.'}, status=400)
            if cantidad <= 0 or not precio.is_finite() or precio < 0:
                return JsonResponse({'ok': False, 'msg': f'Cantidad o precio inválido para {codigo}.'}, status=400)
            producto = Productos.objects.filter(Codigo=codigo).first()
            if not producto:
                return JsonResponse({'ok': False, 'msg': f'El artículo {codigo} no existe.'}, status=400)
            articulos_validados.append((producto, cantidad, precio))
    except (TypeError, ValueError, InvalidOperation):
        return JsonResponse({'ok': False, 'msg': 'Verifica la fecha y los datos de la compra.'}, status=400)

    with transaction.atomic():
        compra = Compra.objects.create(
            proveedor=proveedor,
            fecha_emision=fecha_emision,
            control_fiscal=control_fiscal,
        )
        for producto, cantidad, precio in articulos_validados:
            producto = Productos.objects.select_for_update().get(pk=producto.pk)
            DetalleCompra.objects.create(
                compra=compra,
                producto=producto,
                precio=precio,
                cantidad=cantidad,
                subtotal=precio * cantidad,
            )
            _registrar_lote_compra(
                producto, cantidad, precio, compra, request.user, politica_costo,
            )
    return JsonResponse({'ok': True, 'compra_id': compra.id})


@login_required
@permission_required('Compras.change_compra', raise_exception=True)
@require_POST
@transaction.atomic
def reactivar_compra(request, compra_id):
    compra = get_object_or_404(Compra.objects.select_for_update(), id=compra_id)
    if compra.estado == 'ANULADA':
        for detalle in compra.detallecompra_set.select_related('producto').order_by('producto_id'):
            producto = Productos.objects.select_for_update().get(pk=detalle.producto_id)
            lote_anulado = CostoLote.objects.select_for_update().filter(
                producto=producto, compra_id=compra.id, cantidad_anulada__gt=0,
            ).order_by('-pk').first()
            tiene_lote_compra = CostoLote.objects.filter(producto=producto, compra_id=compra.id).exists()
            cantidad_reponer = (
                lote_anulado.cantidad_anulada if lote_anulado
                else 0 if tiene_lote_compra
                else detalle.cantidad
            )
            if cantidad_reponer <= 0:
                continue
            if lote_anulado:
                lote_anulado.cantidad_anulada = 0
                lote_anulado.save(update_fields=['cantidad_anulada'])
            _registrar_lote_compra(producto, cantidad_reponer, detalle.precio, compra, request.user)
        compra.estado = 'ACTIVA'
        compra.save()
    return redirect('listar_compras')

@login_required
@permission_required('Compras.view_compra', raise_exception=True)
def compras_list(request):
    compras = Compra.objects.all().order_by('-fecha_emision')
    total_compras = sum(c.total() for c in compras)

    hoy = timezone.now()
    compras_mes = compras.filter(fecha_emision__year=hoy.year, fecha_emision__month=hoy.month)
    total_compras_mes = sum(c.total() for c in compras_mes)

    context = {
        'compras': compras,
        'total_compras': total_compras,
        'total_compras_mes': total_compras_mes,
    }
    return render(request, 'compras.html', context)