"""Tareas asíncronas de negocio para FerreElectri PLUS."""

import json
import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.contrib.sites.shortcuts import get_current_site
from django.template.loader import render_to_string
from django.urls import reverse

from Ventas.models import Factura

from .models import AdminPushSubscription, Pedido


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=5,
)
def send_order_confirmation_email(self, pedido_id):
    """Envía la confirmación fuera del request HTTP con dos consultas ORM."""
    # select_related resuelve el FK cliente en la consulta principal y evita N+1.
    pedido = (
        Pedido.objects
        .select_related('cliente')
        .prefetch_related('items__producto')
        .get(pk=pedido_id)
    )

    # Construye el detalle en memoria usando la relación ya precargada.
    lines = []
    for item in pedido.items.all():
        product_name = item.producto.Descripcion if item.producto else 'Producto eliminado'
        lines.append(f'- {product_name} x{item.cantidad}: Bs. {item.subtotal():.2f}')

    # Evita intentar entregar mensajes si el pedido no tiene un destinatario válido.
    recipient = (pedido.cliente.email or '').strip()
    if not recipient:
        return {'sent': False, 'reason': 'missing_recipient', 'pedido_id': pedido_id}

    # Usa la configuración SMTP centralizada sin bloquear el hilo de Django.
    message = EmailMultiAlternatives(
        subject=f'Confirmación de pedido #{pedido.pk}',
        body=(
            f'Hola {pedido.cliente.get_full_name() or pedido.cliente.username},\n\n'
            f'Tu pedido #{pedido.pk} fue creado correctamente.\n'
            + '\n'.join(lines)
            + f'\n\nTotal de referencia: USD {pedido.total:.2f}'
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[recipient],
    )
    message.send(fail_silently=False)
    return {'sent': True, 'pedido_id': pedido_id}


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=5,
)
def send_paid_order_note_email(self, factura_id):
    factura = (
        Factura.objects
        .select_related('cliente', 'pedido__cliente')
        .prefetch_related('detalles__producto', 'pedido__pagos')
        .get(pk=factura_id)
    )
    pedido = factura.pedido
    if not pedido or pedido.estado != 'pagado':
        return {'sent': False, 'reason': 'order_not_paid', 'factura_id': factura_id}

    pago = pedido.pagos.filter(verificado=True).order_by('-creado', '-id').first()
    if not pago:
        return {'sent': False, 'reason': 'payment_not_verified', 'factura_id': factura_id}
    if pago.monto != factura.total:
        return {'sent': False, 'reason': 'payment_total_mismatch', 'factura_id': factura_id}

    recipient = (pedido.cliente.email or '').strip()
    if not recipient:
        return {'sent': False, 'reason': 'missing_recipient', 'factura_id': factura_id}

    from .views import _contexto_factura_pdf

    pdf_context = _contexto_factura_pdf(factura)
    if pdf_context['total_no_concilia']:
        return {'sent': False, 'reason': 'document_total_mismatch', 'factura_id': factura_id}
    html = render_to_string('factura_cliente_pdf.html', pdf_context)
    from weasyprint import HTML

    pdf = HTML(string=html, base_url=str(settings.BASE_DIR)).write_pdf()
    customer_name = pedido.cliente.get_full_name() or pedido.cliente.username
    try:
        payment_snapshot = json.loads(pago.gateway_payload or '{}')
    except (TypeError, ValueError):
        payment_snapshot = {}
    amount_bs = payment_snapshot.get('amount_bs')
    bcv_rate = payment_snapshot.get('bcv_rate')
    message = EmailMultiAlternatives(
        subject=f'Nota de entrega del pedido #{pedido.pk}',
        body=(
            f'Hola {customer_name},\n\n'
            f'Confirmamos la recepción de tu pago para el pedido #{pedido.pk}. '
            'Adjuntamos la nota de entrega y el detalle de tu compra.\n\n'
            f'Total pagado: {factura.moneda} {pago.monto:.2f}\n'
            + (f'Equivalente recibido: Bs. {amount_bs} a tasa BCV {bcv_rate}\n' if amount_bs and bcv_rate else '')
            + f'Método: {pago.get_metodo_display()}\n'
            f'Referencia: {pago.numero_referencia or pago.referencia or "No informada"}\n\n'
            'Descarga la nota en tu panel de cliente, en Mis pedidos:\n'
            f"https://{get_current_site(None).domain}{reverse('cliente_panel')}\n\n"
            'Este documento es interno y no fiscal.'
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[recipient],
    )
    message.attach(f'nota_entrega_pedido_{pedido.pk}.pdf', pdf, 'application/pdf')
    message.send(fail_silently=False)
    return {'sent': True, 'pedido_id': pedido.pk, 'factura_id': factura_id}


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=5,
)
def notify_admin_order_created(self, pedido_id):
    if not settings.ADMIN_WEBPUSH_VAPID_PUBLIC_KEY or not settings.ADMIN_WEBPUSH_VAPID_PRIVATE_KEY:
        return {'sent': 0, 'reason': 'push_not_configured', 'pedido_id': pedido_id}

    pedido = Pedido.objects.only('pk').get(pk=pedido_id)
    subscriptions = AdminPushSubscription.objects.filter(
        user__is_active=True,
        user__is_staff=True,
    )
    if not subscriptions.exists():
        return {'sent': 0, 'reason': 'no_subscriptions', 'pedido_id': pedido_id}

    from pywebpush import WebPushException, webpush

    payload = json.dumps({
        'title': f'Nuevo pedido #{pedido.pk}',
        'body': 'Revisa el pago y los datos de entrega en el panel.',
        'url': reverse('detalle_pedido_admin', args=[pedido.pk]),
        'tag': f'order-{pedido.pk}',
    })
    sent = 0
    for subscription in subscriptions.iterator():
        try:
            webpush(
                subscription_info=subscription.subscription,
                data=payload,
                vapid_private_key=settings.ADMIN_WEBPUSH_VAPID_PRIVATE_KEY,
                vapid_claims={'sub': settings.ADMIN_WEBPUSH_VAPID_CONTACT},
            )
            sent += 1
        except WebPushException as error:
            status_code = getattr(getattr(error, 'response', None), 'status_code', None)
            if status_code in {404, 410}:
                subscription.delete()
            else:
                logging.getLogger(__name__).warning(
                    'No se pudo enviar push al usuario administrativo %s.', subscription.user_id,
                )
    return {'sent': sent, 'pedido_id': pedido_id}
