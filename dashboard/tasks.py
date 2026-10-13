"""Tareas asíncronas de negocio para FerreElectri PLUS."""

from celery import shared_task
from django.conf import settings
from django.core.mail import EmailMultiAlternatives

from .models import Pedido


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
            + f'\n\nTotal: Bs. {pedido.total:.2f}'
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[recipient],
    )
    message.send(fail_silently=False)
    return {'sent': True, 'pedido_id': pedido_id}
