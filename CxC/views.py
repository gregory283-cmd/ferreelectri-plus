from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render

from Usuario.models import Clientes  # noqa: F401 (usado en futuras extensiones)
from Ventas.models import DetalleFactura, Factura
from Inventario.models import Productos
from Inventario.utils import registrar_movimiento

from .models import (
    CuentaCobro,
    PagoCxC,
    ReversionPagoCxC,
    saldo_factura_total,
    saldo_pagado,
    saldo_pendiente,
)


def _sincronizar_cuenta_con_factura(cuenta: CuentaCobro) -> None:
    """
    Reglas pedidas:
    - Si la factura está anulada en Ventas, la cuenta CxC queda anulada automáticamente.
    - Si la factura se reactiva en Ventas, la cuenta CxC vuelve a activa.
    """
    if cuenta.factura.estado == "anulada" and cuenta.estado != "anulada":
        cuenta.estado = "anulada"
        cuenta.save(update_fields=["estado"])
    elif cuenta.factura.estado == "facturada" and cuenta.estado == "anulada":
        cuenta.estado = "activa"
        cuenta.save(update_fields=["estado"])


@login_required
def listar_cxc(request: HttpRequest) -> HttpResponse:
    cuentas = (
        CuentaCobro.objects.select_related("cliente", "factura")
        .filter(factura__estado="facturada", estado="activa")
        .order_by("-created")
    )

    rows = []
    for c in cuentas:
        _sincronizar_cuenta_con_factura(c)

        total = saldo_factura_total(c)
        pagado = saldo_pagado(c)
        pendiente = saldo_pendiente(c)

        # CxC activa: nunca mostrar anuladas ni "sin saldo" (pendiente 0)
        if c.factura.estado == "anulada" or c.estado == "anulada":
            continue
        if pendiente <= 0:
            continue

        rows.append(
            {
                "cuenta": c,
                "numero": c.factura.numero,
                "cliente": str(c.cliente),
                "fecha": c.factura.fecha,
                "total": total,
                "pagado": pagado,
                "pendiente": pendiente,
                "estado": c.estado,
                "factura_estado": c.factura.estado,
            }
        )

    total_cxc_pending = sum((row['pendiente'] for row in rows), Decimal('0.00'))
    total_cxc_accounts = len(rows)
    search_query = request.GET.get('q', '').strip()
    if search_query:
        normalized_query = search_query.casefold()
        rows = [
            row for row in rows
            if normalized_query in str(row['numero']).casefold()
            or normalized_query in row['cliente'].casefold()
        ]

    page_number = request.GET.get('page', 1)
    paginator = Paginator(rows, 5)
    rows = paginator.get_page(page_number)

    return render(request, "cxc/listar_cxc.html", {
        "rows": rows,
        "search_query": search_query,
        "total_cxc_pending": total_cxc_pending,
        "total_cxc_accounts": total_cxc_accounts,
        "matching_cxc_accounts": paginator.count,
    })


@login_required
def listar_cxc_anuladas(request: HttpRequest) -> HttpResponse:
    # “Canceladas o anuladas” en CxC:
    # - Factura anulada (Factura.estado='anulada')
    # - o sin saldo (pendiente <= 0), aunque CuentaCobro.estado no sea 'cerrada'
    cuentas = (
        CuentaCobro.objects.select_related("cliente", "factura")
        .filter(factura__estado__in=["facturada", "anulada"])
        .order_by("-created")
    )

    rows = []
    for c in cuentas:
        _sincronizar_cuenta_con_factura(c)

        total = saldo_factura_total(c)
        pagado = saldo_pagado(c)
        pendiente = saldo_pendiente(c)

        # Solo entran las que cumplen:
        # - factura anulada
        # - o pendiente <= 0
        if c.factura.estado != "anulada" and pendiente > 0:
            continue

        rows.append(
            {
                "cuenta": c,
                "numero": c.factura.numero,
                "cliente": str(c.cliente),
                "fecha": c.factura.fecha,
                "total": total,
                "pagado": pagado,
                "pendiente": pendiente,
                "estado": c.estado,
                "factura_estado": c.factura.estado,
            }
        )

    page_number = request.GET.get('page', 1)
    paginator = Paginator(rows, 5)
    rows = paginator.get_page(page_number)

    return render(request, "cxc/listar_cxc_anuladas.html", {"rows": rows})


@login_required
def pagos_de_factura(request: HttpRequest, numero_factura: int) -> HttpResponse:
    cuenta = get_object_or_404(CuentaCobro, factura__numero=numero_factura)
    _sincronizar_cuenta_con_factura(cuenta)

    pagos = cuenta.pagos.all().order_by("-fecha_pago")

    total = saldo_factura_total(cuenta)
    pagado = saldo_pagado(cuenta)
    pendiente = saldo_pendiente(cuenta)

    return render(
        request,
        "cxc/pagos_factura.html",
        {
            "cuenta": cuenta,
            "pagos": pagos,
            "total": total,
            "pagado": pagado,
            "pendiente": pendiente,
        },
    )


@login_required
def registrar_pago_form(request: HttpRequest, numero_factura: int) -> HttpResponse:
    cuenta = get_object_or_404(CuentaCobro, factura__numero=numero_factura)
    _sincronizar_cuenta_con_factura(cuenta)

    if cuenta.estado != "activa":
        messages.error(request, "No se puede registrar un pago: la factura está anulada o la cuenta no está activa.")
        return redirect("pagos_factura", numero_factura=numero_factura)

    total = saldo_factura_total(cuenta)
    pagado = saldo_pagado(cuenta)
    pendiente = saldo_pendiente(cuenta)

    return render(
        request,
        "cxc/registrar_pago.html",
        {
            "cuenta": cuenta,
            "total": total,
            "pagado": pagado,
            "pendiente": pendiente,
        },
    )


@login_required
def registrar_pago(request: HttpRequest, numero_factura: int) -> HttpResponse:
    if request.method != "POST":
        return HttpResponseBadRequest("Método no permitido")

    cuenta = get_object_or_404(CuentaCobro, factura__numero=numero_factura)
    _sincronizar_cuenta_con_factura(cuenta)

    metodo = request.POST.get("metodo") or "efectivo"
    monto_raw = request.POST.get("monto") or "0"
    referencia = request.POST.get("referencia") or ""
    banco = request.POST.get("banco") or ""
    nota = request.POST.get("nota") or ""

    try:
        monto = Decimal(str(monto_raw).strip())
    except Exception:
        messages.error(request, "Monto inválido.")
        return redirect("listar_cxc")

    if monto <= 0:
        messages.error(request, "El monto debe ser mayor a 0.")
        return redirect("listar_cxc")

    if cuenta.estado != "activa":
        messages.error(request, "No se puede registrar un pago: cuenta anulada/cerrada.")
        return redirect("pagos_factura", numero_factura=numero_factura)

    pendiente = saldo_pendiente(cuenta)
    if monto > pendiente:
        messages.error(
            request,
            "No se puede registrar un pago mayor al saldo pendiente. Por favor ingresa un monto igual o menor a "
            f"{pendiente:.2f}.",
        )
        return redirect("registrar_pago_form", numero_factura=numero_factura)

    with transaction.atomic():
        PagoCxC.objects.create(
            cuenta=cuenta,
            metodo=metodo,
            monto=monto,
            referencia=referencia,
            banco=banco,
            nota=nota,
        )

    messages.success(request, "Pago registrado correctamente.")
    return redirect("pagos_factura", numero_factura=numero_factura)


@login_required
@transaction.atomic
def reactivar_factura_cxc(request: HttpRequest, numero_factura: int) -> HttpResponse:
    if request.method != "POST":
        return HttpResponseBadRequest("Método no permitido")

    cuenta = get_object_or_404(CuentaCobro, factura__numero=numero_factura)
    _sincronizar_cuenta_con_factura(cuenta)

    if cuenta.estado != "anulada":
        messages.info(request, "La factura ya está activa o no se encuentra en estado anulada.")
        return redirect("pagos_factura", numero_factura=numero_factura)

    factura = cuenta.factura
    if factura.estado != "anulada":
        cuenta.estado = "activa"
        cuenta.save(update_fields=["estado"])
        messages.success(request, "Cuenta CxC reactivada correctamente.")
        return redirect("pagos_factura", numero_factura=numero_factura)

    detalles = list(DetalleFactura.objects.filter(factura=factura).order_by('producto_id'))
    cantidades = {}
    for detalle in detalles:
        cantidades[detalle.producto_id] = cantidades.get(detalle.producto_id, 0) + detalle.cantidad
    productos = {
        producto.pk: producto
        for producto in Productos.objects.select_for_update().filter(pk__in=cantidades).order_by('pk')
    }
    for producto_id, cantidad in cantidades.items():
        producto = productos.get(producto_id)
        if producto is None or producto.Cantidad < cantidad:
            messages.error(
                request,
                f"No hay suficiente stock para {producto.Descripcion if producto else producto_id}. No se puede reactivar la venta.",
            )
            return redirect("listar_cxc_anuladas")

    for detalle in detalles:
        registrar_movimiento(
            detalle.producto_id,
            'salida',
            detalle.cantidad,
            f'Reactivación de venta (Factura #{factura.numero})',
            request.user,
        )

    factura.estado = "facturada"
    factura.save(update_fields=["estado"])
    cuenta.estado = "activa"
    cuenta.save(update_fields=["estado"])

    messages.success(request, "Venta reactivada correctamente.")
    return redirect("pagos_factura", numero_factura=numero_factura)


@login_required
@transaction.atomic
def anular_pago(request: HttpRequest, pago_id: int) -> HttpResponse:
    if request.method != "POST":
        return HttpResponseBadRequest("Método no permitido")

    pago = get_object_or_404(PagoCxC, id=pago_id)
    cuenta = pago.cuenta
    _sincronizar_cuenta_con_factura(cuenta)

    if cuenta.estado != "activa":
        messages.error(request, "No se puede anular un pago: la cuenta está anulada.")
        return redirect("pagos_factura", numero_factura=cuenta.factura.numero)

    if pago.estado != "registrado":
        messages.warning(request, "Este pago ya está anulado.")
        return redirect("pagos_factura", numero_factura=cuenta.factura.numero)

    motivo = (request.POST.get("motivo") or "Anulación en CxC")[:255]
    pago.estado = "anulado"
    pago.save(update_fields=["estado"])

    ReversionPagoCxC.objects.create(
        pago=pago,
        motivo=motivo,
        usuario=request.user,
    )

    messages.success(request, "Pago anulado correctamente.")
    return redirect("pagos_factura", numero_factura=cuenta.factura.numero)


@login_required
@transaction.atomic
def asegurar_cuentas_cxc(request: HttpRequest) -> HttpResponse:
    if not request.user.is_staff:
        return HttpResponseBadRequest("Solo staff")

    facturas = Factura.objects.filter(estado="facturada")
    for f in facturas:
        CuentaCobro.objects.get_or_create(factura=f, cliente=f.cliente)

    messages.success(request, f"Listo. Cuentas CxC aseguradas para {facturas.count()} facturas.")
    return redirect("listar_cxc")
