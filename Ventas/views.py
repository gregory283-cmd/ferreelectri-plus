from django.shortcuts import render, redirect, get_object_or_404
from CxC.models import CuentaCobro
from .models import Ventas, Factura, DetalleFactura
from .forms import VentasForm
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from Inventario.models import Productos, MovimientoInventario, CostoCambio, CostoLote, CostoPendiente
from Inventario.utils import aplicar_costo_y_recalcular_precio, asegurar_lote_inicial
from Inventario.utils import registrar_movimiento
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.urls import reverse
from django.core.paginator import Paginator
from django.db.models import F, Prefetch, Sum
from django.template.loader import render_to_string
from weasyprint import HTML
from datetime import timedelta, datetime, date
from django.contrib.auth.decorators import login_required, permission_required
import json
from decimal import Decimal, InvalidOperation
from Usuario.models import Clientes
from django.db import transaction


def actualizar_totales_factura(factura):
    detalles = list(factura.detalles.all())
    factura.subtotal = sum((detalle.base_imponible for detalle in detalles), Decimal('0.00'))
    factura.iva = sum((detalle.monto_iva for detalle in detalles), Decimal('0.00'))
    factura.total = factura.subtotal + factura.iva
    factura.save(update_fields=['subtotal', 'iva', 'total'])


# --- FUNCIONES AUXILIARES ---
def ventas_to_dict(ventas_queryset):
    """Convierte un queryset de ventas a una lista de dicts simples para el template."""
    return [
        {
            'fecha': v.fecha,
            'cliente': str(v.cliente),
            'total': float(v.total)
        }
        for v in ventas_queryset
    ]

# Legacy report routes now use the same executive PDF and calculations.
def _reporte_ejecutivo_pdf_en_rango(request, inicio, fin):
    request.GET = request.GET.copy()
    request.GET['inicio'] = inicio.isoformat()
    request.GET['fin'] = fin.isoformat()
    return reporte_utilidad_pdf(request)


def reporte_caja_diario_pdf(request):
    hoy = timezone.localdate()
    return _reporte_ejecutivo_pdf_en_rango(request, hoy, hoy)


def reporte_caja_semanal_pdf(request):
    hoy = timezone.localdate()
    inicio_semana = hoy - timedelta(days=hoy.weekday())
    return _reporte_ejecutivo_pdf_en_rango(request, inicio_semana, hoy)


def reporte_caja_mensual_pdf(request):
    hoy = timezone.localdate()
    return _reporte_ejecutivo_pdf_en_rango(request, hoy.replace(day=1), hoy)


def reporte_caja_anual_pdf(request):
    hoy = timezone.localdate()
    return _reporte_ejecutivo_pdf_en_rango(request, hoy.replace(month=1, day=1), hoy)

@login_required
@permission_required('Ventas.view_factura', raise_exception=True)
def reporte_caja_personalizado_pdf(request):
    return reporte_utilidad_pdf(request)

def listar_facturas(request):
    """
    Tabla principal: SOLO facturadas (NO anuladas).
    Las anuladas se muestran en otra plantilla/página.
    """
    facturas_qs = Factura.objects.select_related('cliente').prefetch_related(
        Prefetch('detalles', queryset=DetalleFactura.objects.select_related('producto'))
    ).filter(estado='facturada').order_by('-fecha')

    paginator = Paginator(facturas_qs, 5)
    page_number = request.GET.get('page')
    facturas = paginator.get_page(page_number)

    total_facturadas = Factura.objects.filter(estado='facturada').count()
    total_anuladas = Factura.objects.filter(estado='anulada').count()

    return render(request, 'Facturacion.html', {
        'facturas': facturas,
        'total_facturadas': total_facturadas,
        'total_anuladas': total_anuladas,
    })


def listar_facturas_anuladas(request):
    """
    Pantalla dedicada: SOLO anuladas.
    """
    facturas_qs = Factura.objects.select_related('cliente').prefetch_related(
        Prefetch('detalles', queryset=DetalleFactura.objects.select_related('producto'))
    ).filter(estado='anulada').order_by('-fecha')

    paginator = Paginator(facturas_qs, 5)
    page_number = request.GET.get('page')
    facturas = paginator.get_page(page_number)

    total_facturadas = Factura.objects.filter(estado='facturada').count()
    total_anuladas = Factura.objects.filter(estado='anulada').count()

    return render(request, 'Facturacion_anuladas.html', {
        'facturas': facturas,
        'total_facturadas': total_facturadas,
        'total_anuladas': total_anuladas,
    })


def reporte_cobranza_por_cobrar_pdf(request):
    """
    Reporte descargable (PDF) con filtros:
    - cliente (por cédula)
    - rango fechas (from/to)
    - mayor a N días (desde fecha de la factura hasta hoy)
    - canceladas (anuladas)
    - sin cancelar (no anuladas / facturadas)
    """
    # Filtros base
    from_date = request.GET.get('from')  # YYYY-MM-DD
    to_date = request.GET.get('to')
    cliente_cedula = request.GET.get('cliente')
    dias_mas = request.GET.get('dias')  # número
    include_anuladas = request.GET.get('anuladas') == '1'
    include_facturadas = request.GET.get('facturadas') == '1'

    qs = Factura.objects.select_related('cliente').all()

    if from_date:
        qs = qs.filter(fecha__date__gte=from_date)
    if to_date:
        qs = qs.filter(fecha__date__lte=to_date)

    if cliente_cedula:
        qs = qs.filter(cliente__cedula=cliente_cedula)

    # Estado: anuladas y/o facturadas
    estados = []
    if include_anuladas:
        estados.append('anulada')
    if include_facturadas:
        estados.append('facturada')

    if estados:
        qs = qs.filter(estado__in=estados)

    # “Mayor a N días”: hoy - fecha
    hoy = timezone.localdate()
    if dias_mas:
        try:
            dias_mas_i = int(dias_mas)
            # fecha <= hoy - dias_mas
            qs = qs.filter(fecha__date__lte=hoy - timedelta(days=dias_mas_i))
        except ValueError:
            pass

    # Para “cobranza por cobrar” normalmente se usa pendiente.
    # En tu sistema, el total pendiente en Factura puede inferirse,
    # pero aquí usamos lo disponible: mostramos el total factura como “a cobrar”.
    # (Si ya existe un cálculo de pagos/pagado en modelo, lo reemplazamos luego.)
    facturas = qs.order_by('fecha')

    total_cobranza = sum(float(f.total) for f in facturas)

    context = {
        'titulo': 'Cobranza por cobrar',
        'from_date': from_date,
        'to_date': to_date,
        'cliente_cedula': cliente_cedula,
        'dias_mas': dias_mas,
        'include_anuladas': include_anuladas,
        'include_facturadas': include_facturadas,
        'facturas': facturas,
        'total_cobranza': total_cobranza,
        'now': timezone.now(),
    }

    html_string = render_to_string('reportes/reporte_cobranza_por_cobrar.html', context)
    pdf_file = HTML(string=html_string, base_url=request.build_absolute_uri('/')).write_pdf()
    response = HttpResponse(pdf_file, content_type='application/pdf')
    response['Content-Disposition'] = 'inline; filename="reporte_cobranza_por_cobrar.pdf"'
    return response

@login_required
@permission_required('Ventas.add_ventas', raise_exception=True)
def agregar_factura(request):
    if request.method == 'POST':
        form = VentasForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Factura registrada exitosamente')
            return redirect('listar_facturas')
        else:
            messages.error(request, 'Error al registrar la factura. Por favor revisa los datos.')
    else:
        form = VentasForm()
    return render(request, 'addFactura.html', {'form': form})

@login_required
@permission_required('Ventas.change_factura', raise_exception=True)
@require_POST
def anular_factura(request, numero):
    with transaction.atomic():
        factura = get_object_or_404(Factura.objects.select_for_update(), numero=numero)
        if factura.estado == 'anulada':
            messages.warning(request, 'La factura ya está anulada.')
            return redirect('listar_facturas')
        detalles = list(factura.detalles.select_related('producto').order_by('producto_id'))
        list(Productos.objects.select_for_update().filter(
            pk__in={detalle.producto_id for detalle in detalles}
        ).order_by('pk'))
        for detalle in detalles:
            registrar_movimiento(
                detalle.producto_id,
                'entrada',
                detalle.cantidad,
                f'Reintegro por anulación de factura #{factura.numero}',
                request.user,
            )
        factura.estado = 'anulada'
        factura.save(update_fields=['estado'])
    messages.success(request, 'Factura anulada y stock restablecido correctamente.')
    return redirect('listar_facturas')


@login_required
@permission_required('Ventas.change_factura', raise_exception=True)
@require_POST
def activar_factura(request, numero):
    with transaction.atomic():
        factura = get_object_or_404(Factura.objects.select_for_update(), numero=numero)
        if factura.estado != 'anulada':
            messages.info(request, 'La factura ya está activa.')
            return redirect('listar_facturas')
        detalles = list(factura.detalles.select_related('producto').order_by('producto_id'))
        cantidades = {}
        for detalle in detalles:
            cantidades[detalle.producto_id] = cantidades.get(detalle.producto_id, 0) + detalle.cantidad
        productos = {
            producto.pk: producto
            for producto in Productos.objects.select_for_update().filter(
                pk__in=cantidades
            ).order_by('pk')
        }
        for producto_id, cantidad in cantidades.items():
            producto = productos.get(producto_id)
            if producto is None or producto.Cantidad < cantidad:
                nombre = producto.Descripcion if producto else str(producto_id)
                messages.error(request, f'No hay stock suficiente para {nombre}. No se puede reactivar la factura.')
                return redirect('listar_facturas')
        for detalle in detalles:
            registrar_movimiento(
                detalle.producto_id,
                'salida',
                detalle.cantidad,
                f'Reactivación de venta (Factura #{factura.numero})',
                request.user,
            )
        factura.estado = 'facturada'
        factura.save(update_fields=['estado'])
    messages.success(request, 'Factura activada y stock descontado correctamente.')
    return redirect('listar_facturas')

def formato_facturacion(request):
    return render(request, 'formato_facturacion.html')

def buscar_producto(request):
    codigo = request.GET.get('codigo')
    try:
        producto = Productos.objects.get(Codigo=codigo)
        data = {
            'nombre': producto.Descripcion,
            'precio': float(producto.Precio or 0),
            'iva': float(producto.iva),
        }
        return JsonResponse(data)
    except Productos.DoesNotExist:
        return JsonResponse({'error': 'No encontrado'}, status=404)

@login_required
@permission_required('Ventas.add_factura', raise_exception=True)
@require_POST
def guardar_factura(request):
    if request.method == 'POST':
        try:
            with transaction.atomic():
                data = json.loads(request.body)
                cliente_data = data.get('cliente')
                productos_data = data.get('productos', [])
                force = bool(data.get('force', False))

                errores = []
                productos_vistos = set()
                productos_a_vender = []

                if not productos_data or not isinstance(productos_data, list):
                    return JsonResponse({'success': False, 'error': "Debes agregar al menos un producto a la factura."})

                cliente = None
                if cliente_data:
                    cliente = Clientes.objects.filter(cedula=cliente_data.get('cedula')).first()
                if not cliente:
                    return JsonResponse({'success': False, 'error': 'Cliente no encontrado.'})

                for prod in productos_data:
                    codigo = prod.get('codigo')
                    cantidad = int(prod.get('cantidad', 0))
                    precio = Decimal(str(prod.get('precio', '0')))
                    descuento = Decimal(str(prod.get('descuento', '0')))

                    if not codigo:
                        errores.append("Hay un producto sin código.")
                        continue
                    if codigo in productos_vistos:
                        errores.append(f"El producto '{codigo}' está repetido en la factura.")
                        continue
                    productos_vistos.add(codigo)
                    try:
                        producto = Productos.objects.select_for_update().get(Codigo=codigo)
                        iva = producto.iva
                        if cantidad <= 0:
                            errores.append(f"La cantidad para '{producto.Descripcion}' debe ser mayor a cero.")
                        elif cantidad > producto.Cantidad:
                            errores.append(
                                f"Stock insuficiente para '{producto.Descripcion}'. "
                                f"Solicitado: {cantidad}, disponible: {producto.Cantidad}."
                            )
                        if not precio.is_finite() or precio <= 0:
                            errores.append(f"El precio para '{producto.Descripcion}' debe ser mayor que cero.")
                        if not descuento.is_finite() or descuento < 0 or descuento > 100:
                            errores.append(f"El descuento para '{producto.Descripcion}' debe estar entre 0 y 100%.")
                        productos_a_vender.append((producto, cantidad, precio, descuento, iva))
                    except Productos.DoesNotExist:
                        errores.append(f"El producto con código '{codigo}' no existe.")

                if errores:
                    return JsonResponse({'success': False, 'error': "\n".join(errores)})

                # Verificar diferencias costo vs precio: si el precio es menor que el costo,
                # devolver una advertencia para que el frontend solicite confirmación al usuario.
                productos_en_perdida = []
                for producto, cantidad, precio, descuento, iva in productos_a_vender:
                    costo = Decimal(str(getattr(producto, 'Costo', 0) or 0))
                    if precio < costo:
                        perdida_unitaria = costo - precio
                        perdida_total = perdida_unitaria * int(cantidad)
                        productos_en_perdida.append({
                            'codigo': producto.Codigo,
                            'nombre': producto.Descripcion,
                            'precio': float(precio),
                            'costo': float(costo),
                            'cantidad': int(cantidad),
                            'perdida_unitaria': float(perdida_unitaria),
                            'perdida_total': float(perdida_total),
                        })

                if productos_en_perdida and not force:
                    return JsonResponse({
                        'success': False,
                        'warning': True,
                        'message': 'Hay productos cuyo precio de venta es menor que el costo.\n Si continúa, la venta generará pérdida.',
                        'productos_en_perdida': productos_en_perdida
                    })

                factura = Factura.objects.create(
                    cliente=cliente,
                    tipo_documento='nota_entrega',
                    total=Decimal('0.00'),
                    estado='facturada'
                )
                for producto, cantidad, precio, descuento, iva in productos_a_vender:
                    DetalleFactura.objects.create(
                        factura=factura,
                        producto=producto,
                        cantidad=cantidad,
                        precio=precio,
                        costo_unitario=producto.Costo or Decimal('0.00'),
                        descuento=descuento,
                        iva=iva
                    )

                actualizar_totales_factura(factura)
                CuentaCobro.objects.get_or_create(
                    factura=factura,
                    defaults={'cliente': cliente},
                )

                return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'error': f"Error inesperado: {str(e)}"})
    return JsonResponse({'success': False, 'error': 'Método no permitido'})

def lista_productos(request):
    productos = Productos.objects.all().values('Codigo', 'Descripcion')
    return JsonResponse(list(productos), safe=False)

def lista_clientes(request):
    clientes = Clientes.objects.all().values('cedula', 'nombre', 'apellido')
    return JsonResponse(list(clientes), safe=False)

def buscar_cliente(request):
    cedula = request.GET.get('cedula')
    try:
        cliente = Clientes.objects.get(cedula=cedula)
        data = {
            'nombre': cliente.nombre,
            'apellido': cliente.apellido,
            'email': cliente.email,
            'telefono': cliente.telefono,
        }
        return JsonResponse(data)
    except Clientes.DoesNotExist:
        return JsonResponse({'error': 'No encontrado'}, status=404)

from django.contrib import messages
from django.shortcuts import redirect, get_object_or_404

def eliminar_factura(request, numero):
    factura = get_object_or_404(Factura, numero=numero)
    if factura.estado == 'anulada':
        factura.delete()
        messages.success(request, 'Factura eliminada correctamente.')
    else:
        messages.error(request, 'Solo puedes eliminar facturas anuladas.')
    return redirect('listar_facturas')

def ver_factura(request, numero):
    factura = get_object_or_404(
        Factura.objects.select_related('cliente').prefetch_related('detalles__producto'),
        numero=numero,
    )
    detalles = list(factura.detalles.all())
    resumen_impuestos = factura.resumen_tributario(detalles)
    iva_total = sum((grupo['monto_iva'] for grupo in resumen_impuestos), Decimal('0.00'))
    base_imponible = sum((grupo['base_imponible'] for grupo in resumen_impuestos), Decimal('0.00'))
    descuento_total = sum((detalle.importe_descuento for detalle in detalles), Decimal('0.00'))
    total_calculado = sum((detalle.total_linea for detalle in detalles), Decimal('0.00'))
    documento_cliente = factura.rif or factura.cliente.cedula or ''
    if documento_cliente.upper().startswith('AUTO'):
        documento_cliente = ''
    pedido = factura.pedido if factura.pedido_id else None
    pago = pedido.pagos.filter(verificado=True).order_by('-creado', '-id').first() if pedido else None
    envio = getattr(pedido, 'envio', None) if pedido else None
    return render(request, 'ver_factura.html', {
        'factura': factura,
        'pedido': pedido,
        'pago': pago,
        'envio': envio,
        'detalles': detalles,
        'resumen_impuestos': resumen_impuestos,
        'base_imponible': base_imponible,
        'iva_total': iva_total,
        'descuento_total': descuento_total,
        'total_calculado': total_calculado,
        'total_no_concilia': abs(total_calculado - Decimal(str(factura.total or 0))) > Decimal('0.01'),
        'documento_cliente': documento_cliente,
        'razon_social_cliente': factura.razon_social or f'{factura.cliente.nombre} {factura.cliente.apellido}'.strip(),
        'domicilio_cliente': factura.direccion_fiscal or factura.cliente.direccion or '',
        'nota_entrega': factura.tipo_documento == 'nota_entrega',
    })

def ventas(request):
    facturas_list = Factura.objects.all()
    paginator = Paginator(facturas_list, 10)
    page_number = request.GET.get('page')
    facturas = paginator.get_page(page_number)
    return render(request, 'Facturacion.html', {'facturas': facturas})

def api_clientes(request):
    data = [
        {
            "cedula": c.cedula,
            "nombre": c.nombre,
            "apellido": c.apellido,
            "email": c.email,
            "telefono": c.telefono,
            "direccion": c.direccion,
        }
        for c in Clientes.objects.all()
    ]
    return JsonResponse(data, safe=False)

# Para productos:
# Productos ya importado al inicio; eliminar import duplicado

def api_productos(request):
    productos = Productos.objects.all()
    data = [
        {
            'Codigo': p.Codigo,
            'Nombre': getattr(p, 'Nombre', p.Descripcion if hasattr(p, 'Descripcion') else ''),
            'Descripcion': p.Descripcion,
            'precio': float(p.Precio or 0),
            'costo': float(p.Costo or 0),
            'iva': float(p.iva or 0),
            'stock': p.Cantidad,
            'promocion': bool(p.promocion),
        }
        for p in productos
    ]
    return JsonResponse(data, safe=False)

def _cierre_caja_context():
    from dashboard.models import AdminDashboardConfig

    hoy = timezone.localdate()
    inicio_semana = hoy - timedelta(days=hoy.weekday())
    inicio_mes = hoy.replace(day=1)
    inicio_anio = hoy.replace(month=1, day=1)
    config = AdminDashboardConfig.objects.filter(pk=1).first()
    tasa_bcv = config.bcv_rate if config else Decimal('0.0000')

    period_definitions = (
        ('Hoy', hoy),
        ('Semana', inicio_semana),
        ('Mes', inicio_mes),
        ('Año', inicio_anio),
    )
    currencies = set()
    year_invoices = Factura.objects.filter(
        fecha__date__gte=inicio_anio, fecha__date__lte=hoy, estado='facturada'
    )
    for raw_currency, order_id in year_invoices.values_list('moneda', 'pedido_id'):
        code = 'VES' if str(raw_currency or '').strip().upper() == 'VES' else 'USD'
        currencies.add('USD' if code in ('USD', '$', 'US$') else 'Bs.' if code in ('BS', 'BS.', 'VES') else str(raw_currency))

    if tasa_bcv > 0 and currencies <= {'Bs.', 'USD'}:
        report_currency = 'Bs.'
    elif not currencies or currencies == {'Bs.'}:
        report_currency = 'Bs.'
    elif currencies == {'USD'}:
        report_currency = 'USD'
    else:
        report_currency = None

    def report_amount(amounts):
        if report_currency == 'Bs.':
            return sum((amount * (tasa_bcv if currency == 'USD' else Decimal('1'))
                        for currency, amount in amounts.items()), Decimal('0.00'))
        if report_currency == 'USD':
            return sum((amount / tasa_bcv if currency == 'Bs.' else amount
                        for currency, amount in amounts.items()), Decimal('0.00'))
        return None

    def display_amount(amounts):
        if report_currency:
            amount = report_amount(amounts).quantize(Decimal('0.01'))
            formatted = f'{amount:,.2f}'.replace(',', '_').replace('.', ',').replace('_', '.')
            return f'{report_currency} {formatted}'
        parts = []
        for currency, amount in sorted(amounts.items()):
            formatted = f'{amount:,.2f}'.replace(',', '_').replace('.', ',').replace('_', '.')
            parts.append(f'{currency} {formatted}')
        return ' · '.join(parts) if parts else 'Bs. 0,00'

    invoice_queryset = Factura.objects.filter(estado='facturada').select_related(
        'cliente', 'pedido'
    ).prefetch_related(Prefetch(
        'detalles', queryset=DetalleFactura.objects.select_related('producto')
    ))
    cash_periods = []
    daily_invoices = []

    for label, start_date in period_definitions:
        invoices = list(invoice_queryset.filter(
            fecha__date__gte=start_date, fecha__date__lte=hoy
        ).order_by('-fecha', '-numero'))
        if label == 'Hoy':
            daily_invoices = invoices
        channel_data = {
            'ecommerce': {'revenue': {}, 'gross_profit': {}, 'invoice_count': 0, 'cost_lines': 0, 'all_lines': 0},
            'manual': {'revenue': {}, 'gross_profit': {}, 'invoice_count': 0, 'cost_lines': 0, 'all_lines': 0},
        }

        for invoice in invoices:
            channel = channel_data['ecommerce' if invoice.pedido_id else 'manual']
            currency = 'Bs.' if str(invoice.moneda or '').strip().upper() == 'VES' else 'USD'
            invoice.cash_total_display = display_amount({currency: invoice.total or Decimal('0.00')})
            channel['revenue'][currency] = channel['revenue'].get(currency, Decimal('0.00')) + (invoice.total or Decimal('0.00'))
            channel['invoice_count'] += 1

            for detail in invoice.detalles.all():
                quantity = Decimal(detail.cantidad or 0)
                net_sales = Decimal(str(detail.precio or 0)) * quantity * (
                    Decimal('1') - Decimal(str(detail.descuento or 0)) / Decimal('100')
                )
                cost_unit = detail.costo_unitario
                if cost_unit is None and detail.producto_id:
                    cost_unit = detail.producto.Costo
                channel['all_lines'] += 1
                if cost_unit is None:
                    continue
                gross_profit = net_sales - Decimal(str(cost_unit or 0)) * quantity
                channel['gross_profit'][currency] = channel['gross_profit'].get(currency, Decimal('0.00')) + gross_profit
                channel['cost_lines'] += 1

        for channel in channel_data.values():
            channel['revenue_display'] = display_amount(channel['revenue'])
            channel['gross_profit_display'] = display_amount(channel['gross_profit']) if channel['cost_lines'] else 'Sin costos comparables'
            channel['cost_coverage_pct'] = round(channel['cost_lines'] * 100 / channel['all_lines']) if channel['all_lines'] else 0
            channel['chart_revenue'] = report_amount(channel['revenue'])
            channel['chart_profit'] = report_amount(channel['gross_profit'])

        combined_revenue = {}
        combined_profit = {}
        for channel in channel_data.values():
            for currency, amount in channel['revenue'].items():
                combined_revenue[currency] = combined_revenue.get(currency, Decimal('0.00')) + amount
            for currency, amount in channel['gross_profit'].items():
                combined_profit[currency] = combined_profit.get(currency, Decimal('0.00')) + amount
        cash_periods.append({
            'label': label,
            'ecommerce': channel_data['ecommerce'],
            'manual': channel_data['manual'],
            'total_display': display_amount(combined_revenue),
            'gross_profit_display': display_amount(combined_profit) if any(item['cost_lines'] for item in channel_data.values()) else 'Sin costos comparables',
            'invoice_count': len(invoices),
            'chart_ecommerce': channel_data['ecommerce']['chart_revenue'],
            'chart_manual': channel_data['manual']['chart_revenue'],
        })

    cash_chart_data = {
        'labels': [period['label'] for period in cash_periods],
        'ecommerce': [float(period['chart_ecommerce'] or 0) for period in cash_periods],
        'manual': [float(period['chart_manual'] or 0) for period in cash_periods],
        'currency': report_currency or '',
    }
    return {
        'ventas_dia': daily_invoices,
        'ventas_semana': invoice_queryset.filter(fecha__date__gte=inicio_semana, fecha__date__lte=hoy),
        'ventas_mes': invoice_queryset.filter(fecha__date__gte=inicio_mes, fecha__date__lte=hoy),
        'ventas_anio': year_invoices,
        'cash_periods': cash_periods,
        'cash_chart_data': cash_chart_data,
        'cash_chart_available': report_currency is not None,
        'cash_currency': report_currency or 'Monedas separadas',
        'bcv_rate': tasa_bcv,
        'bcv_updated_at': config.updated_at if config else None,
        'today_ecommerce': cash_periods[0]['ecommerce'],
        'today_manual': cash_periods[0]['manual'],
        'hoy': hoy,
        'inicio_semana': inicio_semana,
        'inicio_mes': inicio_mes,
        'inicio_anio': inicio_anio,
    }


def cierre_caja(request):
    return render(request, 'cierre_caja.html', _cierre_caja_context())

@login_required
@permission_required('Ventas.add_factura', raise_exception=True)
def facturacion(request):
    """
    Vista para crear y listar facturas de venta.
    Valida stock antes de guardar y muestra mensajes claros al usuario.
    """
    if request.method == 'POST':
        productos_data = request.POST.getlist('productos')
        cantidades = request.POST.getlist('cantidades')
        errores = []
        productos_a_vender = []

        for codigo, cantidad in zip(productos_data, cantidades):
            try:
                producto = Productos.objects.get(pk=codigo)
                cantidad = int(cantidad)
                if cantidad <= 0:
                    errores.append(f"La cantidad para {producto.Descripcion} debe ser mayor a cero.")
                elif cantidad > producto.Cantidad:
                    errores.append(f"Stock insuficiente para {producto.Descripcion}. Disponible: {producto.Cantidad}")
                else:
                    productos_a_vender.append((producto, cantidad))
            except Productos.DoesNotExist:
                errores.append(f"Producto con código {codigo} no existe.")
            except Exception as e:
                errores.append(f"Error con el producto {codigo}: {str(e)}")

        if errores:
            for error in errores:
                messages.error(request, error)
            return redirect('facturacion')

        with transaction.atomic():
            for producto, cantidad in productos_a_vender:
                registrar_movimiento(
                    producto,
                    'salida',
                    cantidad,
                    'Venta registrada desde facturación',
                    request.user,
                )

        # ...lógica para guardar la factura...
        messages.success(request, "Factura creada correctamente y stock actualizado.")
        return redirect('facturacion')

    # ...código para GET...
    return render(request, 'Facturacion.html')

@login_required
@permission_required('Ventas.change_factura', raise_exception=True)
def editar_factura(request, numero):
    factura = get_object_or_404(Factura, numero=numero)
    if factura.estado == 'anulada':
        messages.error(request, "No puedes modificar una factura anulada.")
        return redirect('listar_facturas')
    detalles = DetalleFactura.objects.filter(factura=factura)
    detalles_json = json.dumps([
        {
            "codigo": d.producto.Codigo,
            "nombre": d.producto.Descripcion,
            "precio": float(d.precio),
            "cantidad": d.cantidad,
            "iva": float(d.iva),
            "descuento": float(d.descuento),
            "subtotal": float(d.subtotal())
        } for d in detalles
    ])

    if request.method == "POST":
        try:
            with transaction.atomic():
                data = json.loads(request.body)
                cliente_data = data.get('cliente')
                productos_data = data.get('productos', [])
                force = bool(data.get('force', False))
                factura = Factura.objects.select_for_update().get(pk=numero)
                if factura.estado == 'anulada':
                    return JsonResponse({'success': False, 'error': 'No se puede editar una factura anulada.'}, status=409)
                if not isinstance(productos_data, list) or not productos_data:
                    return JsonResponse({'success': False, 'error': 'La factura debe contener productos.'}, status=400)
                errores = []
                productos_vistos = set()
                productos_a_vender = []
                cliente = None
                if cliente_data:
                    cliente = Clientes.objects.filter(cedula=cliente_data.get('cedula')).first()
                if not cliente:
                    return JsonResponse({'success': False, 'error': 'Cliente no encontrado.'}, status=400)

                detalles_actuales = list(
                    factura.detalles.select_related('producto').order_by('producto_id')
                )
                stock_devolvible = {}
                for detalle in detalles_actuales:
                    stock_devolvible[detalle.producto_id] = stock_devolvible.get(detalle.producto_id, 0) + detalle.cantidad
                codigos_nuevos = {
                    prod.get('codigo') for prod in productos_data
                    if isinstance(prod, dict) and prod.get('codigo')
                }
                codigos_a_bloquear = codigos_nuevos | set(stock_devolvible)
                productos_bloqueados = {
                    producto.Codigo: producto
                    for producto in Productos.objects.select_for_update().filter(
                        Codigo__in=codigos_a_bloquear
                    ).order_by('Codigo')
                }
                for prod in productos_data:
                    if not isinstance(prod, dict):
                        errores.append('Hay un producto con formato inválido.')
                        continue
                    codigo = prod.get('codigo')
                    if not codigo:
                        errores.append("Hay un producto sin código.")
                        continue
                    if codigo in productos_vistos:
                        errores.append(f"El producto '{codigo}' está repetido en la factura.")
                        continue
                    productos_vistos.add(codigo)
                    producto = productos_bloqueados.get(codigo)
                    if producto is None:
                        errores.append(f"El producto con código '{codigo}' no existe.")
                        continue
                    try:
                        cantidad = int(prod.get('cantidad', 0))
                        precio = Decimal(str(prod.get('precio', '0')))
                        descuento = Decimal(str(prod.get('descuento', '0')))
                    except (TypeError, ValueError, InvalidOperation):
                        errores.append(f"Cantidad, precio o descuento inválido para '{producto.Descripcion}'.")
                        continue
                    if cantidad <= 0:
                        errores.append(f"La cantidad para '{producto.Descripcion}' debe ser mayor a cero.")
                    disponibles = producto.Cantidad + stock_devolvible.get(codigo, 0)
                    if cantidad > disponibles:
                        errores.append(f"Stock insuficiente para '{producto.Descripcion}'. Solicitado: {cantidad}, disponible: {disponibles}.")
                    if not precio.is_finite() or precio <= 0:
                        errores.append(f"El precio para '{producto.Descripcion}' debe ser mayor que cero.")
                    if not descuento.is_finite() or descuento < 0 or descuento > 100:
                        errores.append(f"El descuento para '{producto.Descripcion}' debe estar entre 0 y 100%.")
                    productos_a_vender.append((producto, cantidad, precio, descuento, producto.iva))

                if errores:
                    return JsonResponse({'success': False, 'error': "\n".join(errores)}, status=400)

                perdidas = [
                    (producto, cantidad, producto.Costo - precio)
                    for producto, cantidad, precio, descuento, iva in productos_a_vender
                    if precio < producto.Costo
                ]
                if perdidas and not force:
                    return JsonResponse({
                        'success': False,
                        'warning': True,
                        'productos_en_perdida': [
                            {'codigo': producto.Codigo, 'nombre': producto.Descripcion,
                             'perdida_unitaria': float(perdida), 'perdida_total': float(perdida * cantidad)}
                            for producto, cantidad, perdida in perdidas
                        ],
                    })

                for detalle in detalles_actuales:
                    registrar_movimiento(
                        detalle.producto_id, 'entrada', detalle.cantidad,
                        f'Reintegro temporal por edición de factura #{factura.numero}', request.user,
                    )
                factura.detalles.all().delete()
                for producto, cantidad, precio, descuento, iva in productos_a_vender:
                    DetalleFactura.objects.create(
                        factura=factura,
                        producto=producto,
                        cantidad=cantidad,
                        precio=precio,
                        costo_unitario=producto.Costo or Decimal('0.00'),
                        descuento=descuento,
                        iva=iva
                    )
                factura.cliente = cliente
                factura.save()
                actualizar_totales_factura(factura)

                return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'error': f"Error inesperado: {str(e)}"})

    return render(request, 'editar_factura.html', {
        'factura': factura,
        'detalles_json': detalles_json,
    })

def _reporte_utilidad_context(request):
    from dashboard.models import AdminDashboardConfig

    hoy = timezone.localdate()
    try:
        fecha_inicio = date.fromisoformat(request.GET.get('inicio', '') or hoy.replace(month=1, day=1).isoformat())
        fecha_fin = date.fromisoformat(request.GET.get('fin', '') or hoy.isoformat())
    except ValueError as error:
        raise ValueError('El rango debe usar fechas válidas.') from error
    if fecha_inicio > fecha_fin:
        raise ValueError('La fecha inicial debe ser anterior o igual a la fecha final.')
    if fecha_fin > hoy:
        raise ValueError('La fecha final no puede ser posterior al día de hoy.')

    facturas = Factura.objects.select_related('cliente', 'pedido').prefetch_related(
        Prefetch('detalles', queryset=DetalleFactura.objects.select_related('producto'))
    ).filter(
        fecha__date__gte=fecha_inicio,
        fecha__date__lte=fecha_fin,
        estado='facturada'
    ).order_by('fecha')
    config = AdminDashboardConfig.objects.filter(pk=1).first()
    tasa_bcv = config.bcv_rate if config else Decimal('0.0000')
    moneda_reporte = 'Bs.' if tasa_bcv > 0 else 'USD'
    factor_conversion = tasa_bcv if moneda_reporte == 'Bs.' else Decimal('1')

    def convertir(monto):
        return (Decimal(monto or 0) * factor_conversion).quantize(Decimal('0.01'))

    def nuevo_resumen_canal():
        return {
            'facturas': 0,
            'ventas_brutas': Decimal('0.00'),
            'descuentos': Decimal('0.00'),
            'ventas_netas': Decimal('0.00'),
            'iva': Decimal('0.00'),
            'costo': Decimal('0.00'),
            'utilidad': Decimal('0.00'),
            'unidades': 0,
            'lineas': 0,
            'lineas_con_costo': 0,
        }

    totales = nuevo_resumen_canal()
    canales = {'ecommerce': nuevo_resumen_canal(), 'manual': nuevo_resumen_canal()}
    iva_por_alicuota = {}
    productos = {}
    ventas_por_fecha = {}
    ventas = []
    productos_sin_costo = 0
    facturas_con_costo_estimado = 0

    for factura in facturas:
        canal = canales['ecommerce' if factura.pedido_id else 'manual']
        moneda_guardada = str(factura.moneda or '').strip().upper()
        # Checkout y facturación manual reciben precios en USD; Bs. era el default histórico, no una conversión.
        moneda_origen = 'VES' if moneda_guardada == 'VES' else 'USD'
        bruto_factura = Decimal('0.00')
        descuento_factura = Decimal('0.00')
        neto_factura = Decimal('0.00')
        iva_factura = Decimal('0.00')
        costo_factura = Decimal('0.00')
        utilidad_factura = Decimal('0.00')
        unidades_factura = 0
        lineas_factura = 0
        lineas_con_costo_factura = 0
        costo_estimado_factura = False

        for detalle in factura.detalles.all():
            unidades = int(detalle.cantidad or 0)
            bruto = detalle.importe_bruto
            descuento = detalle.importe_descuento
            neto = detalle.base_imponible
            iva = detalle.monto_iva
            alicuota = Decimal(str(detalle.iva or 0)).quantize(Decimal('0.01'))
            costo_unitario = detalle.costo_unitario
            costo_estimado = False
            if costo_unitario is None and detalle.producto_id:
                costo_unitario = detalle.producto.Costo
                costo_estimado = costo_unitario is not None

            costo = (
                Decimal(str(costo_unitario or 0)) * unidades
                if costo_unitario is not None else None
            )
            utilidad = neto - costo if costo is not None else Decimal('0.00')
            bruto_factura += bruto
            descuento_factura += descuento
            neto_factura += neto
            iva_factura += iva
            unidades_factura += unidades
            lineas_factura += 1
            if costo is not None:
                costo_factura += costo
                utilidad_factura += utilidad
                lineas_con_costo_factura += 1
            else:
                productos_sin_costo += 1
            costo_estimado_factura = costo_estimado_factura or costo_estimado

            tax_group = iva_por_alicuota.setdefault(alicuota, {
                'alicuota': alicuota,
                'base': Decimal('0.00'),
                'iva': Decimal('0.00'),
            })
            tax_group['base'] += neto
            tax_group['iva'] += iva

            product_key = detalle.producto_id or f'deleted-{detalle.pk}'
            product = productos.setdefault(product_key, {
                'nombre': detalle.producto.Descripcion if detalle.producto_id else 'Producto eliminado',
                'unidades': 0,
                'ventas_netas': Decimal('0.00'),
                'iva': Decimal('0.00'),
                'costo': Decimal('0.00'),
                'utilidad': Decimal('0.00'),
                'lineas': 0,
                'lineas_con_costo': 0,
            })
            product['unidades'] += unidades
            product['ventas_netas'] += neto
            product['iva'] += iva
            product['lineas'] += 1
            if costo is not None:
                product['costo'] += costo
                product['utilidad'] += utilidad
                product['lineas_con_costo'] += 1

        if not lineas_factura:
            neto_factura = Decimal(factura.subtotal or factura.total or 0)
            iva_factura = Decimal(factura.iva or 0)
            bruto_factura = neto_factura

        total_facturado = (
            neto_factura + iva_factura
            if lineas_factura else Decimal(factura.total or 0)
        )
        costo_estimado_factura = costo_estimado_factura or any(
            detalle.costo_unitario is None for detalle in factura.detalles.all()
        )
        if costo_estimado_factura:
            facturas_con_costo_estimado += 1

        row = {
            'numero': factura.numero,
            'fecha': factura.fecha,
            'cliente': str(factura.cliente),
            'canal': 'E-commerce' if factura.pedido_id else 'Facturación manual',
            'pedido_id': factura.pedido_id,
            'moneda_origen': moneda_origen,
            'total': convertir(total_facturado),
            'ventas_brutas': convertir(bruto_factura),
            'descuentos': convertir(descuento_factura),
            'venta_neta': convertir(neto_factura),
            'iva': convertir(iva_factura),
            'costo': convertir(costo_factura),
            'utilidad': convertir(utilidad_factura),
            'margen_porcentaje': utilidad_factura * 100 / neto_factura if neto_factura else Decimal('0.00'),
            'costo_estimado': costo_estimado_factura,
            'lineas_sin_costo': lineas_factura - lineas_con_costo_factura,
        }
        ventas.append(row)
        for target, values in ((totales, None), (canal, None)):
            target['facturas'] += 1
            target['ventas_brutas'] += bruto_factura
            target['descuentos'] += descuento_factura
            target['ventas_netas'] += neto_factura
            target['iva'] += iva_factura
            target['costo'] += costo_factura
            target['utilidad'] += utilidad_factura
            target['unidades'] += unidades_factura
            target['lineas'] += lineas_factura
            target['lineas_con_costo'] += lineas_con_costo_factura

        date_key = timezone.localtime(factura.fecha).date()
        day_totals = ventas_por_fecha.setdefault(date_key, {'ecommerce': Decimal('0.00'), 'manual': Decimal('0.00')})
        day_totals['ecommerce' if factura.pedido_id else 'manual'] += convertir(total_facturado)

    ventas_netas = convertir(totales['ventas_netas'])
    costo_total = convertir(totales['costo'])
    utilidad_total = convertir(totales['utilidad'])
    margen_porcentaje = utilidad_total * 100 / ventas_netas if ventas_netas else Decimal('0.00')
    iva_total = convertir(totales['iva'])
    ventas_brutas = convertir(totales['ventas_brutas'])
    descuentos_total = convertir(totales['descuentos'])
    coste_coverage = round(totales['lineas_con_costo'] * 100 / totales['lineas']) if totales['lineas'] else 0

    for channel in canales.values():
        channel['ventas_brutas'] = convertir(channel['ventas_brutas'])
        channel['descuentos'] = convertir(channel['descuentos'])
        channel['ventas_netas'] = convertir(channel['ventas_netas'])
        channel['iva'] = convertir(channel['iva'])
        channel['costo'] = convertir(channel['costo'])
        channel['utilidad'] = convertir(channel['utilidad'])
        channel['total'] = channel['ventas_netas'] + channel['iva']
        channel['margen_porcentaje'] = channel['utilidad'] * 100 / channel['ventas_netas'] if channel['ventas_netas'] else Decimal('0.00')
        channel['cobertura_costos'] = round(channel['lineas_con_costo'] * 100 / channel['lineas']) if channel['lineas'] else 0

    for product in productos.values():
        product['ventas_netas'] = convertir(product['ventas_netas'])
        product['iva'] = convertir(product['iva'])
        product['costo'] = convertir(product['costo'])
        product['utilidad'] = convertir(product['utilidad'])
        product['margen_porcentaje'] = product['utilidad'] * 100 / product['ventas_netas'] if product['ventas_netas'] else Decimal('0.00')
        product['cobertura_costos'] = round(product['lineas_con_costo'] * 100 / product['lineas']) if product['lineas'] else 0

    iva_resumen = [
        {**group, 'base': convertir(group['base']), 'iva': convertir(group['iva'])}
        for _, group in sorted(iva_por_alicuota.items())
    ]
    rango_dias = (fecha_fin - fecha_inicio).days
    if rango_dias <= 90:
        ventas_chart = [
            {
                'label': (fecha_inicio + timedelta(days=offset)).strftime('%d/%m'),
                'ecommerce': float(ventas_por_fecha.get(fecha_inicio + timedelta(days=offset), {}).get('ecommerce', 0)),
                'manual': float(ventas_por_fecha.get(fecha_inicio + timedelta(days=offset), {}).get('manual', 0)),
            }
            for offset in range(rango_dias + 1)
        ]
    else:
        monthly_totals = {}
        for sales_date, amounts in ventas_por_fecha.items():
            key = sales_date.replace(day=1)
            group = monthly_totals.setdefault(key, {'ecommerce': Decimal('0.00'), 'manual': Decimal('0.00')})
            group['ecommerce'] += amounts['ecommerce']
            group['manual'] += amounts['manual']
        ventas_chart = [
            {
                'label': month.strftime('%b %Y'),
                'ecommerce': float(amounts['ecommerce']),
                'manual': float(amounts['manual']),
            }
            for month, amounts in sorted(monthly_totals.items())
        ]

    ventas_chart_max = max(
        (point['ecommerce'] + point['manual'] for point in ventas_chart),
        default=0,
    )
    label_interval = max(1, (len(ventas_chart) + 9) // 10)
    for index, point in enumerate(ventas_chart):
        total_periodo = point['ecommerce'] + point['manual']
        point['total'] = total_periodo
        point['ecommerce_height'] = (
            point['ecommerce'] * 100 / ventas_chart_max if ventas_chart_max else 0
        )
        point['manual_height'] = (
            point['manual'] * 100 / ventas_chart_max if ventas_chart_max else 0
        )
        point['mostrar_etiqueta'] = index % label_interval == 0 or index == len(ventas_chart) - 1

    productos_top = sorted(productos.values(), key=lambda product: (-product['ventas_netas'], -product['unidades']))[:8]
    max_product_sales = max((product['ventas_netas'] for product in productos_top), default=Decimal('0.00'))
    for product in productos_top:
        product['participacion'] = round(product['ventas_netas'] * 100 / max_product_sales) if max_product_sales else 0

    productos_mas_vendidos = sorted(
        productos.values(),
        key=lambda product: (-product['unidades'], -product['ventas_netas']),
    )
    max_product_units = max(
        (product['unidades'] for product in productos_mas_vendidos),
        default=0,
    )
    for product in productos_mas_vendidos:
        product['participacion_unidades'] = (
            round(product['unidades'] * 100 / max_product_units)
            if max_product_units else 0
        )

    generacion = timezone.localtime(timezone.now())
    report_number = f"FE-RPT-{fecha_inicio.strftime('%Y%m%d')}-{fecha_fin.strftime('%Y%m%d')}"
    return {
        'fecha_inicio': fecha_inicio,
        'fecha_fin': fecha_fin,
        'fecha': f"{fecha_inicio.strftime('%d/%m/%Y')} - {fecha_fin.strftime('%d/%m/%Y')}",
        'ventas': ventas,
        'ventas_chart': ventas_chart,
        'canales': canales,
        'iva_resumen': iva_resumen,
        'productos_top': productos_top,
        'productos_mas_vendidos': productos_mas_vendidos,
        'producto_mas_vendido': productos_mas_vendidos[0] if productos_mas_vendidos else None,
        'moneda_reporte': moneda_reporte,
        'tasa_bcv': tasa_bcv,
        'tasa_bcv_actualizada': config.updated_at if config else None,
        'report_number': report_number,
        'generado': generacion,
        'productos_sin_costo': productos_sin_costo,
        'cobertura_costos': coste_coverage,
        'resumen': {
            'ventas': convertir(totales['ventas_netas'] + totales['iva']),
            'ventas_brutas': ventas_brutas,
            'descuentos': descuentos_total,
            'ventas_netas': ventas_netas,
            'iva': iva_total,
            'costo_ventas': costo_total,
            'utilidad': utilidad_total,
            'transacciones': totales['facturas'],
            'unidades': totales['unidades'],
            'margen_porcentaje': margen_porcentaje,
        },
        'costos_estimados': facturas_con_costo_estimado,
        'now': generacion,
    }


@login_required
@permission_required('Ventas.view_factura', raise_exception=True)
def reporte_utilidad(request):
    try:
        context = _reporte_utilidad_context(request)
    except ValueError as error:
        return HttpResponse(str(error), status=400, content_type='text/plain; charset=utf-8')
    return render(request, 'reporte_ejecutivo.html', context)


@login_required
@permission_required('Ventas.view_factura', raise_exception=True)
def reporte_utilidad_pdf(request):
    try:
        context = _reporte_utilidad_context(request)
    except ValueError as error:
        return HttpResponse(str(error), status=400, content_type='text/plain; charset=utf-8')
    html_string = render_to_string('reportes/reporte_ejecutivo_weasyprint.html', context)
    pdf_file = HTML(string=html_string, base_url=request.build_absolute_uri('/')).write_pdf()
    response = HttpResponse(pdf_file, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="{context["report_number"].lower()}.pdf"'
    return response


def lista_precios_pdf(request):
    productos_qs = Productos.objects.all().order_by(F('orden_lista').asc(nulls_last=True), 'Codigo')
    productos = []
    for p in productos_qs:
        # Obtener URL de imagen si existe (campo 'Imagen' en Inventario.Productos)
        imagen_url = ''
        try:
            if getattr(p, 'Imagen', None) and getattr(p, 'Imagen', None).name:
                imagen_url = p.Imagen.url
        except Exception:
            imagen_url = ''
        productos.append({
            'Codigo': getattr(p, 'Codigo', ''),
            'Descripcion': getattr(p, 'Descripcion', ''),
            'precio_venta': float(getattr(p, 'Precio', 0) or 0),
            'iva': float(getattr(p, 'iva', 0) or 0),
            'imagen_url': imagen_url,
            'promocion': bool(getattr(p, 'promocion', False) or getattr(p, 'en_promocion', False) or False),
        })
    context = {
        'productos': productos,
        'now': datetime.now(),
    }
    html = render_to_string('lista_precios.html', context)
    try:
        pdf_file = HTML(string=html, base_url=request.build_absolute_uri('/')).write_pdf()
        response = HttpResponse(pdf_file, content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename="lista_precios.pdf"'
        return response
    except Exception:
        import traceback
        return HttpResponse(traceback.format_exc(), status=500, content_type='text/plain')


def catalogo_4x_pdf(request):
    """Genera un PDF con 4 fichas por página (2x2) con imagen, descripción y precio."""
    productos_qs = Productos.objects.all().order_by(F('orden_lista').asc(nulls_last=True), 'Codigo')
    productos = []
    for p in productos_qs:
        imagen_url = ''
        try:
            if getattr(p, 'Imagen', None) and getattr(p, 'Imagen', None).name:
                imagen_url = p.Imagen.url
        except Exception:
            imagen_url = ''
        precio = Decimal(str(getattr(p, 'Precio', 0) or 0))
        alicuota = Decimal(str(getattr(p, 'iva', 0) or 0))
        monto_iva = (precio * alicuota / Decimal('100')).quantize(Decimal('0.01'))
        productos.append({
            'Codigo': getattr(p, 'Codigo', ''),
            'Descripcion': getattr(p, 'Descripcion', ''),
            'precio_venta': precio,
            'iva': float(getattr(p, 'iva', 0) or 0),
            'monto_iva': monto_iva,
            'precio_final': precio + monto_iva,
            'imagen_url': imagen_url,
            'promocion': bool(getattr(p, 'promocion', False) or getattr(p, 'en_promocion', False) or False),
        })
    context = {
        'productos': productos,
    }
    html = render_to_string('catalogo_4x.html', context)
    try:
        pdf_file = HTML(string=html, base_url=request.build_absolute_uri('/')).write_pdf()
        response = HttpResponse(pdf_file, content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename="catalogo_4x.pdf"'
        return response
    except Exception:
        import traceback
        return HttpResponse(traceback.format_exc(), status=500, content_type='text/plain')

def reporte_cierre_caja_pdf(request):
    return render(request, 'cierre_caja.html', _cierre_caja_context())

@login_required
@permission_required('Ventas.change_factura', raise_exception=True)
def gestionar_precios(request):
    # Obtener productos y exponer campos con los nombres que usa la plantilla
    productos_qs = Productos.objects.select_related('Categoria').order_by(F('orden_lista').asc(nulls_last=True), 'Codigo')
    productos = []
    for p in productos_qs:
        imagen_url = ''
        try:
            if getattr(p, 'Imagen', None) and getattr(p, 'Imagen', None).name:
                imagen_url = p.Imagen.url
        except Exception:
            imagen_url = ''
        productos.append({
            'id': getattr(p, 'Codigo', ''),
            'descripcion': getattr(p, 'Descripcion', ''),
            'precio_venta': float(getattr(p, 'Precio', 0) or 0),
            'costo': float(getattr(p, 'Costo', 0) or 0),
            'cantidad': int(getattr(p, 'Cantidad', 0) or 0),
            'iva': float(getattr(p, 'iva', 0) or 0),
            'categoria': str(getattr(getattr(p, 'Categoria', None), 'name', '') or ''),
            'margen': (
                ((float(getattr(p, 'Precio', 0) or 0) - float(getattr(p, 'Costo', 0) or 0)) /
                 float(getattr(p, 'Costo', 0))) * 100
                if float(getattr(p, 'Costo', 0) or 0) > 0 else 0
            ),
            'imagen_url': imagen_url,
            'promocion': bool(getattr(p, 'promocion', False) or False)
        })
    costos = CostoPendiente.objects.select_related(
        'producto', 'creado_por', 'revisado_por', 'revertido_por'
    ).order_by('-creado_en', '-pk')

    dias = ('lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo')
    meses = ('enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre')

    def agrupar_por_dia(propuestas, fecha_campo='creado_en'):
        grupos = {}
        for propuesta in propuestas:
            fecha_evento = (
                propuesta.pendiente_desde or propuesta.creado_en
                if fecha_campo == 'pendiente_o_creacion'
                else getattr(propuesta, fecha_campo) or propuesta.creado_en
            )
            propuesta.fecha_local = timezone.localtime(fecha_evento)
            if propuesta.estado == 'espera_stock':
                propuesta.stock_caro_restante = CostoLote.objects.filter(
                    producto_id=propuesta.producto_id,
                    cantidad_disponible__gt=0,
                    costo_unitario__gt=propuesta.costo_propuesto,
                ).aggregate(total=Sum('cantidad_disponible'))['total'] or 0
            fecha = propuesta.fecha_local.date()
            grupo = grupos.setdefault(fecha, {
                'fecha': f'{dias[fecha.weekday()].capitalize()} {fecha.day} de {meses[fecha.month - 1]} de {fecha.year}',
                'fecha_key': fecha.isoformat(),
                'items': [],
            })
            grupo['items'].append(propuesta)
        return list(grupos.values())

    propuestas_pendientes = agrupar_por_dia(
        costos.filter(estado__in=['pendiente', 'espera_stock']),
        'pendiente_o_creacion',
    )
    propuestas_aprobadas = agrupar_por_dia(costos.filter(estado='aprobado'), 'revisado_en')
    propuestas_denegadas = agrupar_por_dia(costos.filter(estado='rechazado'), 'revisado_en')
    return render(request, 'gestionar_precios.html', {
        'productos': productos,
        'propuestas_pendientes': propuestas_pendientes,
        'propuestas_aprobadas': propuestas_aprobadas,
        'propuestas_denegadas': propuestas_denegadas,
        'conteo_pendientes': costos.filter(estado='pendiente').count(),
        'conteo_espera_stock': costos.filter(estado='espera_stock').count(),
    })


@login_required
@permission_required('Ventas.change_factura', raise_exception=True)
@require_POST
def guardar_orden_productos(request):
    try:
        data = json.loads(request.body)
        codigos = data.get('orden')
        if not isinstance(codigos, list) or not all(isinstance(codigo, str) for codigo in codigos):
            return JsonResponse({'success': False, 'error': 'La lista de códigos no es válida.'}, status=400)
        if len(codigos) != len(set(codigos)):
            return JsonResponse({'success': False, 'error': 'La lista contiene códigos repetidos.'}, status=400)

        with transaction.atomic():
            productos = list(Productos.objects.select_for_update().values_list('Codigo', flat=True))
            if set(codigos) != set(productos):
                return JsonResponse({'success': False, 'error': 'El catálogo cambió. Recarga la página e inténtalo de nuevo.'}, status=409)
            for posicion, codigo in enumerate(codigos):
                Productos.objects.filter(Codigo=codigo).update(orden_lista=posicion)
        return JsonResponse({'success': True})
    except (TypeError, ValueError) as error:
        return JsonResponse({'success': False, 'error': f'Orden inválido: {error}'}, status=400)


@login_required
@permission_required('Ventas.change_factura', raise_exception=True)
@require_POST
def gestionar_costo_pendiente(request):
    try:
        data = json.loads(request.body)
        accion = data.get('accion')

        with transaction.atomic():
            if accion in {'crear', 'crear_manual'}:
                propuesta_manual = accion == 'crear_manual'
                codigo = data.get('codigo')
                cantidad = None if propuesta_manual else int(data.get('cantidad_compra', 0))
                unidad = data.get('unidad_compra', 'unidades')
                costo = Decimal(str(data.get('costo_propuesto', '')))
                if not propuesta_manual and cantidad <= 0:
                    return JsonResponse({'success': False, 'error': 'La cantidad comprada debe ser mayor que cero.'}, status=400)
                if unidad not in {'unidades', 'cajas', 'paquetes', 'lotes', 'rollos', 'kits'}:
                    return JsonResponse({'success': False, 'error': 'La unidad de compra no es válida.'}, status=400)
                if not costo.is_finite() or costo < 0 or costo.quantize(Decimal('0.01')) != costo:
                    return JsonResponse({'success': False, 'error': 'El costo unitario debe ser válido y tener máximo dos decimales.'}, status=400)
                producto = Productos.objects.select_for_update().get(Codigo=codigo)
                quedan_costos_mayores = CostoLote.objects.filter(
                    producto=producto,
                    cantidad_disponible__gt=0,
                    costo_unitario__gt=costo,
                ).exists()
                propuesta = CostoPendiente.objects.create(
                    producto=producto,
                    cantidad_compra=cantidad,
                    unidad_compra=unidad,
                    costo_propuesto=costo,
                    motivo=(data.get('motivo') or ('Propuesta manual desde Gestión de precios' if propuesta_manual else '')).strip()[:255],
                    creado_por=request.user,
                    estado='espera_stock' if quedan_costos_mayores else 'pendiente',
                    pendiente_desde=None if quedan_costos_mayores else timezone.now(),
                )
                propuesta.fecha_local = timezone.localtime(propuesta.creado_en)
                stock_caro = CostoLote.objects.filter(
                    producto=producto,
                    cantidad_disponible__gt=0,
                    costo_unitario__gt=costo,
                ).aggregate(total=Sum('cantidad_disponible'))['total'] or 0
                return JsonResponse({
                    'success': True,
                    'id': propuesta.pk,
                    'state': propuesta.estado,
                    'codigo': producto.Codigo,
                    'descripcion': producto.Descripcion,
                    'costo_actual': str(producto.Costo or 0),
                    'costo_propuesto': str(propuesta.costo_propuesto),
                    'cantidad_compra': propuesta.cantidad_compra,
                    'unidad': propuesta.get_unidad_compra_display() if propuesta.cantidad_compra else 'Propuesta manual',
                    'motivo': propuesta.motivo,
                    'creado_por': request.user.get_full_name() or request.user.get_username(),
                    'creado_en': propuesta.fecha_local.isoformat(),
                    'stock_caro': stock_caro,
                })

            propuesta = CostoPendiente.objects.select_for_update().get(pk=data.get('id'))
            if accion == 'editar':
                if propuesta.estado not in {'pendiente', 'espera_stock'}:
                    return JsonResponse({'success': False, 'error': 'Solo se pueden editar propuestas abiertas.'}, status=409)
                cantidad_dato = data.get('cantidad_compra')
                cantidad = int(cantidad_dato) if cantidad_dato not in (None, '') else None
                unidad = data.get('unidad_compra', propuesta.unidad_compra)
                costo = Decimal(str(data.get('costo_propuesto', '')))
                if propuesta.lote_id and (cantidad is None or cantidad <= 0):
                    return JsonResponse({'success': False, 'error': 'La cantidad comprada debe ser mayor que cero.'}, status=400)
                if unidad not in {'unidades', 'cajas', 'paquetes', 'lotes', 'rollos', 'kits'}:
                    return JsonResponse({'success': False, 'error': 'La unidad de compra no es válida.'}, status=400)
                if not costo.is_finite() or costo < 0 or costo.quantize(Decimal('0.01')) != costo:
                    return JsonResponse({'success': False, 'error': 'El costo unitario debe ser válido y tener máximo dos decimales.'}, status=400)
                propuesta.cantidad_compra = cantidad
                propuesta.unidad_compra = unidad
                propuesta.costo_propuesto = costo
                propuesta.motivo = (data.get('motivo') or '').strip()[:255]
                campos = ['cantidad_compra', 'unidad_compra', 'costo_propuesto', 'motivo']
                producto = Productos.objects.select_for_update().get(pk=propuesta.producto_id)
                asegurar_lote_inicial(producto)
                quedan_costos_mayores = CostoLote.objects.filter(
                    producto_id=propuesta.producto_id,
                    cantidad_disponible__gt=0,
                    costo_unitario__gt=costo,
                ).exists()
                propuesta.estado = 'espera_stock' if quedan_costos_mayores else 'pendiente'
                propuesta.pendiente_desde = None if quedan_costos_mayores else timezone.now()
                campos.extend(['estado', 'pendiente_desde'])
                propuesta.save(update_fields=campos)
                return JsonResponse({'success': True})

            if accion == 'eliminar':
                if propuesta.estado not in {'pendiente', 'espera_stock', 'rechazado'}:
                    return JsonResponse({'success': False, 'error': 'Una propuesta aprobada no se puede eliminar.'}, status=409)
                propuesta.delete()
                return JsonResponse({'success': True})

            if accion == 'aprobar':
                if propuesta.estado == 'espera_stock':
                    return JsonResponse({'success': False, 'error': 'La propuesta se habilitará cuando se agote el inventario comprado al costo anterior.'}, status=409)
                if propuesta.estado not in {'pendiente', 'espera_stock'}:
                    return JsonResponse({'success': False, 'error': 'La propuesta ya fue revisada.'}, status=409)
                producto = Productos.objects.select_for_update().get(pk=propuesta.producto_id)
                costo_anterior, precio_anterior, precio_aprobado = aplicar_costo_y_recalcular_precio(
                    producto,
                    propuesta.costo_propuesto,
                    usuario=request.user,
                    motivo=f'Aprobación de propuesta de costo #{propuesta.pk}',
                )
                propuesta.estado = 'aprobado'
                propuesta.costo_anterior = costo_anterior
                propuesta.precio_anterior = precio_anterior
                propuesta.precio_aprobado = precio_aprobado
                propuesta.revisado_en = timezone.now()
                propuesta.revisado_por = request.user
                propuesta.save(update_fields=['estado', 'costo_anterior', 'precio_anterior', 'precio_aprobado', 'revisado_en', 'revisado_por'])
                return JsonResponse({'success': True})

            if accion == 'denegar':
                if propuesta.estado not in {'pendiente', 'espera_stock'}:
                    return JsonResponse({'success': False, 'error': 'La propuesta ya fue revisada.'}, status=409)
                propuesta.estado = 'rechazado'
                propuesta.revisado_en = timezone.now()
                propuesta.revisado_por = request.user
                propuesta.save(update_fields=['estado', 'revisado_en', 'revisado_por'])
                return JsonResponse({'success': True})

            if accion == 'revertir':
                if propuesta.estado != 'aprobado' or propuesta.revertido_en:
                    return JsonResponse({'success': False, 'error': 'Esta aprobación ya no puede revertirse.'}, status=409)
                producto = Productos.objects.select_for_update().get(pk=propuesta.producto_id)
                if producto.Costo != propuesta.costo_propuesto or producto.Precio != propuesta.precio_aprobado:
                    return JsonResponse({'success': False, 'error': 'El costo o el precio cambiaron después de esta aprobación; no se puede revertir sin sobrescribir un cambio posterior.'}, status=409)
                CostoCambio.objects.create(
                    producto=producto,
                    anterior=producto.Costo,
                    nuevo=propuesta.costo_anterior,
                    usuario=request.user,
                    motivo=f'Reversión de propuesta de costo #{propuesta.pk}',
                )
                producto.Costo = propuesta.costo_anterior
                producto.Precio = propuesta.precio_anterior
                producto.save(update_fields=['Costo', 'Precio'])
                propuesta.revertido_en = timezone.now()
                propuesta.revertido_por = request.user
                propuesta.save(update_fields=['revertido_en', 'revertido_por'])
                return JsonResponse({'success': True})

        return JsonResponse({'success': False, 'error': 'Acción de costo no reconocida.'}, status=400)
    except (Productos.DoesNotExist, CostoPendiente.DoesNotExist):
        return JsonResponse({'success': False, 'error': 'El producto o la propuesta ya no existe.'}, status=404)
    except (TypeError, ValueError, InvalidOperation) as error:
        return JsonResponse({'success': False, 'error': f'Datos de costo inválidos: {error}'}, status=400)
    except Exception as error:
        return JsonResponse({'success': False, 'error': str(error)}, status=400)

@login_required
@permission_required('Ventas.change_factura', raise_exception=True)
@require_POST
def actualizar_precio_venta(request):
    try:
        data = json.loads(request.body)
        codigo = data.get('codigo')
        force = bool(data.get('force', False))
        with transaction.atomic():
            producto = Productos.objects.select_for_update().get(Codigo=codigo)
            precio = Decimal(str(data.get('precio_venta', '')))
            costo_actual = producto.Costo or Decimal('0.00')
            costo = Decimal(str(data.get('costo', costo_actual)))
            if not precio.is_finite() or precio <= 0:
                return JsonResponse({'success': False, 'error': 'El precio de venta debe ser mayor que cero.'}, status=400)
            if not costo.is_finite() or costo < 0:
                return JsonResponse({'success': False, 'error': 'El costo no puede ser negativo.'}, status=400)
            if costo != costo_actual:
                asegurar_lote_inicial(producto)
                propuesta = CostoPendiente.objects.filter(
                    producto=producto,
                    costo_propuesto=costo,
                    estado__in=['pendiente', 'espera_stock'],
                ).first()
                if propuesta is None:
                    espera_stock = CostoLote.objects.filter(
                        producto=producto,
                        cantidad_disponible__gt=0,
                        costo_unitario__gt=costo,
                    ).exists()
                    propuesta = CostoPendiente.objects.create(
                        producto=producto,
                        cantidad_compra=None,
                        costo_propuesto=costo,
                        motivo='Propuesta manual desde Gestión de precios',
                        creado_por=request.user,
                        estado='espera_stock' if espera_stock else 'pendiente',
                        pendiente_desde=None if espera_stock else timezone.now(),
                    )
                propuesta.fecha_local = timezone.localtime(propuesta.creado_en)
                stock_caro = CostoLote.objects.filter(
                    producto=producto,
                    cantidad_disponible__gt=0,
                    costo_unitario__gt=costo,
                ).aggregate(total=Sum('cantidad_disponible'))['total'] or 0
                return JsonResponse({
                    'success': True,
                    'cost_pending': True,
                    'state': propuesta.estado,
                    'id': propuesta.pk,
                    'codigo': producto.Codigo,
                    'descripcion': producto.Descripcion,
                    'costo_actual': str(producto.Costo or 0),
                    'costo_propuesto': str(propuesta.costo_propuesto),
                    'cantidad_compra': propuesta.cantidad_compra,
                    'unidad': propuesta.get_unidad_compra_display() if propuesta.cantidad_compra else 'Propuesta manual',
                    'motivo': propuesta.motivo,
                    'creado_por': request.user.get_full_name() or request.user.get_username(),
                    'creado_en': propuesta.fecha_local.isoformat(),
                    'stock_caro': stock_caro,
                })

            promocion = data.get('en_promocion', False)
            if not isinstance(promocion, bool):
                return JsonResponse({'success': False, 'error': 'El estado de promoción no es válido.'}, status=400)

            if precio < costo and not force:
                perdida_unitaria = costo - precio
                stock = int(producto.Cantidad or 0)
                return JsonResponse({
                    'success': False,
                    'warning': True,
                    'message': 'El precio de venta propuesto es menor que el costo del producto.',
                    'producto': {
                        'codigo': producto.Codigo,
                        'nombre': producto.Descripcion,
                        'precio_nuevo': float(precio),
                        'costo': float(costo),
                        'perdida_unitaria': float(perdida_unitaria),
                        'stock': stock,
                        'perdida_total': float(perdida_unitaria * stock),
                    }
                })

            producto.Precio = precio
            producto.promocion = promocion
            producto.save(update_fields=['Precio', 'promocion'])
        return JsonResponse({'success': True})
    except Productos.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Producto no encontrado.'}, status=404)
    except (ValueError, TypeError, InvalidOperation) as error:
        return JsonResponse({'success': False, 'error': f'Datos de precio inválidos: {error}'}, status=400)
    except Exception as error:
        return JsonResponse({'success': False, 'error': str(error)}, status=400)
