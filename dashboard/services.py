import json
import logging
import urllib.parse
import urllib.request

from django.conf import settings
from Usuario.models import Clientes as UsuarioClientes


logger = logging.getLogger(__name__)


def sync_admin_cliente_record(cliente):
    email = (getattr(cliente, 'email', '') or '').strip().lower()
    if not email:
        return None

    nombre_completo = (getattr(cliente, 'nombre', '') or '').strip()
    partes_nombre = nombre_completo.split()
    nombre = (partes_nombre[0] if partes_nombre else email.split('@')[0])[:25]
    apellido = ' '.join(partes_nombre[1:])[:25]
    cedula = (getattr(cliente, 'cedula', '') or '').strip() or None
    registro = UsuarioClientes.objects.filter(email__iexact=email).first()
    if not registro:
        registro = UsuarioClientes(email=email, cedula=cedula, fecha_nacimiento=None)

    values = {
        'nombre': nombre,
        'apellido': apellido,
        'telefono': (getattr(cliente, 'telefono', '') or '')[:25],
        'direccion': getattr(cliente, 'direccion', '') or '',
    }
    if cedula and not UsuarioClientes.objects.filter(cedula=cedula).exclude(pk=registro.pk).exists():
        values['cedula'] = cedula
    for field, value in values.items():
        if value or not getattr(registro, field):
            setattr(registro, field, value)
    registro.save()
    return registro


def send_telegram_order_alert(order, transaction_data):
    """Notify the configured store chat without blocking order creation."""
    bot_token = getattr(settings, 'TELEGRAM_BOT_TOKEN', '')
    chat_id = getattr(settings, 'TELEGRAM_CHAT_ID', '')
    if not bot_token or not chat_id:
        return False

    customer = getattr(order, 'cliente', None)
    username = getattr(customer, 'username', None) or getattr(customer, 'email', 'Cliente')
    message = (
        '*NUEVO PAGO MOVIL POR VERIFICAR*\n\n'
        f'*Pedido:* #{order.id}\n'
        f'*Monto:* ${order.total}\n'
        f'*Banco:* {transaction_data.get("banco", "No indicado")}\n'
        f'*Cedula:* {transaction_data.get("cedula", "No indicada")}\n'
        f'*Referencia:* {transaction_data.get("referencia", "No indicada")}\n'
        f'*Cliente:* {username}\n\n'
        'Entra al panel admin para aprobarlo.'
    )
    url = f'https://api.telegram.org/bot{bot_token}/sendMessage'
    payload = json.dumps({'chat_id': chat_id, 'text': message, 'parse_mode': 'Markdown'}).encode('utf-8')
    request = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return 200 <= response.status < 300
    except Exception as exc:
        logger.warning('Telegram order alert failed: %s', exc)
        return False
