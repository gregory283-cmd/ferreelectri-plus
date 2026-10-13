import os
import json
import csv
import hashlib
import re
import time
import logging
import unicodedata
from pathlib import Path
from functools import wraps
from types import SimpleNamespace

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, send_mail
from django.core.cache import cache
from django.core.paginator import Paginator
from django.core.serializers.json import DjangoJSONEncoder
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.hashers import check_password as check_password_hash, make_password
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.decorators import permission_required
from django.contrib.auth.decorators import login_required as django_login_required
from django.contrib.auth.decorators import user_passes_test
from .decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User, Permission
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied, ValidationError
from django.contrib.auth.password_validation import validate_password
from django.db import models, transaction
from django.utils.http import url_has_allowed_host_and_scheme
from django.db.models import Avg, Count, DecimalField, ExpressionWrapper, F, Q, Sum, Value
from django.db.models.functions import Coalesce, TruncDate, TruncDay, TruncMonth, TruncWeek, TruncYear
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.utils.timezone import now
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_POST
from django.views.decorators.http import require_POST
import urllib.request as urllib_request
import urllib.parse as urllib_parse

from Inventario.models import Productos, Categoria
from Inventario.utils import registrar_movimiento
from Proveedores.models import Proveedores
from Usuario.models import Clientes as UsuarioClientes
from Ventas.models import Factura
from Ventas.models import DetalleFactura

from .forms import ClienteRegistroForm, ClienteAuthenticationForm, EnvioAdminForm, PagoManualForm, PagoMovilCheckoutForm
from .decorators import cliente_required, log_view_access
from .models import AdminDashboardConfig, AuditLog, Carrito, CarritoItem, ChatMessage, ChatSession, Cliente, Customer, Envio, EnvioEvento, Pedido, PedidoItem, PerfilCliente
from .models import Pago, PedidoArchivado
from .customer_auth import (
    get_customer_from_request,
    login_customer as login_customer_cookie,
    logout_customer as logout_customer_cookie,
)
from .cache_utils import CATALOG_TIMEOUT, catalog_cache_key
from .services import send_telegram_order_alert, sync_admin_cliente_record
from .ferrebot import build_assistant_reply, search_catalog
from django.core.files.storage import default_storage
from django.urls import reverse
from django.contrib.admin.views.decorators import staff_member_required
from django_ratelimit.decorators import ratelimit
from django_ratelimit.exceptions import Ratelimited
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from django.http import FileResponse, HttpResponse
from io import BytesIO

try:
    import stripe
except ImportError:
    stripe = None

try:
    from google.oauth2 import id_token
    from google.auth.transport import requests as google_requests
except Exception:
    id_token = None
    google_requests = None


INTENT_MATRIX = {
    'inicio': {
        'keywords': [r'\bprincipal\b', r'\binicio\b', r'\bhome\b', r'\be[ -]?commerce\b', r'\btienda\b', r'\bpagina principal\b', r'\bvolver\b', r'\bregresar\b'],
        'response': 'Te llevo a la página principal de Ferrelectri Plus para que puedas explorar nuevamente la tienda y sus productos destacados.',
        'action_type': 'navigate_url', 'target': '/',
        'guide_text': 'Aquí tienes la página principal de la tienda para continuar explorando.',
    },
    'saludos': {
        'keywords': [r'^(?:hola(?: ferrebot)?|buenas(?: tardes)?|buenos dias|saludos|que tal|hey)$'],
        'response': 'Hola, soy FerreBot, tu asistente de FerreElectri Plus. Puedo orientarte sobre productos, compras, pagos, pedidos y tu cuenta. ¿Qué necesitas resolver hoy?',
        'action_type': None, 'target': '', 'guide_text': '',
    },
    'carrito': {
        'keywords': [r'\bcarrito\b', r'\bmi compra\b', r'\bfinalizar compra\b', r'\bcheckout\b'],
        'response': 'Puedes revisar los productos, cantidades y total de tu compra desde el carrito.',
        'action_type': 'navigate_url', 'target': '/carrito/',
        'guide_text': 'En el carrito podrás revisar el total y continuar con el pago.',
    },
    'promociones': {
        'keywords': [r'\bpromocion(?:es)?\b', r'\boferta(?:s)?\b', r'\bdescuento(?:s)?\b', r'\brebaja(?:s)?\b', r'\bliquidacion(?:es)?\b', r'\bprecio especial\b', r'\bprecios especiales\b', r'\bproductos destacados\b', r'\b2x1\b', r'\bbarato(?:s)?\b', r'\beconomico(?:s)?\b'],
        'response': 'Encontré las promociones vigentes de Ferrelectri Plus. Revisa las opciones disponibles y compara precio, presentación y existencia antes de agregarlas a tu carrito.',
        'action_type': 'navigate_url', 'target': '/?oferta=true#productos-grid',
        'guide_text': 'Aquí aparecen todos los productos que tienen promoción activa.',
    },
    'recomendaciones': {
        'keywords': [r'\brecomiendas?\b', r'\brecomendacion(?:es)?\b', r'\baconsejas?\b', r'\bconsejo\b', r'\bayuda\b', r'\basesoria\b', r'\bsugerencia\b', r'\bsugerencias\b', r'\bno se que comprar\b', r'\bque puedo comprar\b', r'\bcual(?:es)? son mejores?\b', r'\bcual es mejor\b', r'\bme recomiendas?\b', r'\borientacion\b', r'\bque me conviene\b', r'\bque deberia comprar\b', r'\bopcion recomendada\b', r'\bque producto me sirve\b'],
        'response': 'Para elegir correctamente, conviene comparar la calidad de los materiales, la compatibilidad con tu instalación, el nivel de seguridad y la disponibilidad de repuestos. Te recomiendo revisar nuestros productos destacados y seleccionar la alternativa que mejor se ajuste a la potencia, el uso y el presupuesto de tu proyecto.',
        'action_type': 'navigate_url', 'target': '/productos/',
        'guide_text': 'Revisa los productos destacados para comparar opciones.',
    },
    'precios': {
        'keywords': [r'\bprecio\b', r'\bprecios\b', r'\bcuanto cuesta\b', r'\bcuanto vale\b', r'\bvalor\b', r'\bcosto\b', r'\btarifa\b', r'\bpresupuesto\b', r'\bbarato\b', r'\beconomico\b', r'\bcaro\b', r'\bdescuento\b', r'\bpromocion\b', r'\boferta\b'],
        'response': 'Puedo ayudarte a comparar precios, promociones y presentaciones. Te mostraré el catálogo para que revises el valor actualizado de cada producto y elijas según tu presupuesto.',
        'action_type': 'navigate_url', 'target': '/productos/',
        'guide_text': 'Compara precios, presentaciones y disponibilidad directamente en el catálogo.',
    },
    'envios_entrega': {
        'keywords': [r'\benvio\b', r'\benviar\b', r'\bdespacho\b', r'\bentrega\b', r'\bdomicilio\b', r'\btransport(?:e|adora)\b', r'\bdelivery\b', r'\brecibir\b', r'\bretirar\b', r'\bretirar en tienda\b', r'\bllega\b', r'\btiempo de entrega\b', r'\bcuando llega\b', r'\bcosto de envio\b'],
        'response': 'Puedo orientarte sobre despacho, entrega y retiro de tus compras. Revisa tu carrito y completa la información de entrega para que el sistema pueda procesar el pedido.',
        'action_type': 'navigate_url', 'target': '/carrito/',
        'guide_text': 'Completa tus datos de entrega desde el carrito para continuar.',
    },
    'facturacion': {
        'keywords': [r'\b(?:necesito|quiero|busco|ver|descargar)\s+factura\b', r'\bfactura\b', r'\bfacturacion\b', r'\bcomprobante\b', r'\brecibo\b', r'\brif\b', r'\bcedula\b', r'\bdato fiscal\b', r'\bdocumento fiscal\b', r'\bfactura electronica\b'],
        'response': 'Puedo ayudarte a ubicar la información de facturación y los comprobantes asociados a tus compras. Revisa tu perfil y el historial de pedidos para consultar una orden específica.',
        'action_type': 'navigate_url', 'target': '/cliente/mis-pedidos/',
        'guide_text': 'Desde tus pedidos puedes consultar la información y factura disponible.',
    },
    'soporte_tecnico': {
        'keywords': [r'\bcomo funciona\b', r'\bcomo se usa\b', r'\binstrucciones?\b', r'\bmanual\b', r'\binstal(?:acion|ar|o|as|a)\b', r'\bconexion\b', r'\bconectar\b', r'\bvoltaje\b', r'\bamper(?:aje|ios)\b', r'\bwatts?\b', r'\bpotencia\b', r'\bcalibre\b', r'\bmedida\b', r'\bcompatible\b', r'\bcompatibilidad\b', r'\bseguro\b', r'\bseguridad\b', r'\bpara que sirve\b'],
        'response': 'Puedo orientarte con características y criterios de selección. Antes de instalar, verifica voltaje, potencia, calibre, medidas y compatibilidad; si la instalación implica riesgo eléctrico, debe realizarla personal calificado. Dime qué producto o aplicación tienes para darte una recomendación más precisa.',
        'action_type': 'navigate_url', 'target': '/productos/',
        'guide_text': 'Revisa las especificaciones del producto antes de instalarlo.',
    },
    'devoluciones_garantia': {
        'keywords': [r'\bdevolucion(?:es)?\b', r'\bcambio\b', r'\bcambiar producto\b', r'\bgarantia\b', r'\bgarantias\b', r'\bdefectuoso\b', r'\bdanado\b', r'\bdano\b', r'\breclamo\b', r'\breclamos\b', r'\bproblema con mi compra\b'],
        'response': 'Puedo ayudarte a revisar una compra y ubicar la información necesaria para solicitar soporte. Ten a mano el número de pedido, el producto y una descripción del caso para facilitar la atención.',
        'action_type': 'navigate_url', 'target': '/cliente/mis-pedidos/',
        'guide_text': 'Abre tu pedido para tener a mano sus datos y solicitar soporte.',
    },
    'busqueda_producto': {
        'keywords': [r'\bbusco\b', r'\bnecesito\b', r'\bquiero conseguir\b', r'\bme hace falta\b', r'\bvenden\b', r'\btienen\b', r'\bdonde encuentro\b', r'\bdonde consigo\b', r'\bdisponen de\b', r'\bque tienen\b'],
        'response': 'Puedo ayudarte a encontrar productos por nombre, categoría, aplicación o característica. Te llevaré al catálogo para que revises las opciones disponibles.',
        'action_type': 'navigate_url', 'target': '/productos/',
        'guide_text': 'Busca por nombre o revisa las categorías disponibles en el catálogo.',
    },
    'stock': {
        'keywords': [r'\bstock\b', r'\bdisponibilidad\b', r'\bdisponible\b', r'\bexistencia\b', r'\bcuantas quedan\b', r'\bcuantos quedan\b', r'\bse consigue\b', r'\besta disponible\b', r'\bcuanto queda\b'],
        'response': 'Puedo mostrarte los productos disponibles y su existencia actual en el catálogo. Busca una categoría o un producto específico para revisar sus opciones.',
        'action_type': 'navigate_url', 'target': '/productos/',
        'guide_text': 'Consulta la disponibilidad visible en cada producto del catálogo.',
    },
    'contacto_ubicacion': {
        'keywords': [r'\bdonde estan\b', r'\bubicacion\b', r'\bdireccion\b', r'\btelefono\b', r'\bcontacto\b', r'\bhorario\b', r'\ba que hora abren\b', r'\bdonde quedan\b'],
        'response': 'Puedo orientarte con la ubicación, los canales de contacto y el horario de atención de Ferrelectri Plus.',
        'action_type': 'navigate_url', 'target': '/',
        'guide_text': 'Revisa la información de contacto y atención en la página principal.',
    },
    'despedida': {
        'keywords': [r'\bgracias\b', r'\badios\b', r'\bchao\b', r'\bhasta luego\b', r'\bnos vemos\b', r'\blisto\b'],
        'response': 'Con mucho gusto. Ferrelectri Plus queda a tu disposición para ayudarte cuando lo necesites.',
        'action_type': None, 'target': '', 'guide_text': '',
    },
}


def _normalize_chat_text(value):
    normalized = unicodedata.normalize('NFKD', value.lower())
    normalized = ''.join(character for character in normalized if not unicodedata.combining(character))
    return re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9\s]', ' ', normalized)).strip()


def _chat_owner(request):
    django_user = request.user if isinstance(request.user, User) and request.user.is_authenticated else None
    if django_user is None:
        customer_email = getattr(request.user, 'email', None)
        if customer_email:
            django_user = User.objects.filter(email__iexact=customer_email, is_active=True).first()
    return django_user


def _validated_chat_page_context(payload, request):
    raw_context = payload.get('page_context')
    if not isinstance(raw_context, dict):
        page_context = {'path': '/', 'view': ''}
    else:
        page_path = str(raw_context.get('path') or '/')[:200]
        allowed_paths = {
            '/', '/productos/', '/carrito/', '/checkout/',
            '/cliente/mis-pedidos/', '/mis-pedidos/', '/cliente/panel/',
        }
        if page_path not in allowed_paths and not re.fullmatch(r'/producto/[A-Za-z0-9_-]+/', page_path):
            page_path = '/'

        page_view = str(raw_context.get('view') or '')[:20]
        if page_view not in {'', 'catalogo'} or page_path != '/':
            page_view = ''
        payment_method = str(raw_context.get('payment_method') or '').upper()
        if payment_method not in {'PAGO_MOVIL', 'BINANCE', 'PAYPAL'}:
            payment_method = ''
        page_context = {
            'path': page_path,
            'view': page_view,
            'payment_method': payment_method,
        }

    cliente = get_current_cliente(request)
    if cliente:
        cart = Carrito.objects.filter(cliente=cliente).first()
        page_context['cart_count'] = cart.items.count() if cart else 0
    else:
        anon_cart = request.session.get('anon_cart', {}) or {}
        page_context['cart_count'] = sum(
            1 for quantity in anon_cart.values()
            if str(quantity).isdigit() and int(quantity) > 0
        )
    return page_context


@ratelimit(key='ip', rate='30/m', method='POST', block=True)
def ai_chat_endpoint(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'method_not_allowed'}, status=405)

    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except (TypeError, ValueError, UnicodeDecodeError):
        return JsonResponse({'error': 'invalid_json'}, status=400)

    message = str(
        payload.get('message') or payload.get('text') or request.POST.get('text') or request.POST.get('message') or ''
    ).strip()
    if not message:
        return JsonResponse({'error': 'message_required'}, status=400)
    if len(message) > 1000:
        return JsonResponse({'error': 'message_too_long'}, status=400)

    django_user = _chat_owner(request)
    if not request.session.session_key:
        request.session.save()
    session_key = request.session.session_key
    session_id = payload.get('session_id')
    if django_user is not None:
        chat_session = ChatSession.objects.filter(user=django_user, id=session_id).first() if session_id else None
    else:
        chat_session = ChatSession.objects.filter(user__isnull=True, session_key=session_key, id=session_id).first() if session_id else None
    if chat_session is None:
        chat_session = ChatSession.objects.create(user=django_user, session_key=None if django_user else session_key)

    if chat_session.title == 'Nueva Consulta':
        words = [word.strip('¿?¡!,.;:') for word in message.split() if word.strip('¿?¡!,.;:')]
        chat_session.title = ' '.join(words[:6]) or 'Nueva Consulta'
        chat_session.save(update_fields=['title'])

    recent_messages = list(
        chat_session.messages.order_by('-timestamp', '-id').values('role', 'content')[:8]
    )
    recent_messages.reverse()
    assistant_reply = build_assistant_reply(message, recent_messages, _validated_chat_page_context(payload, request))
    if assistant_reply is not None:
        response_text, action = assistant_reply
        ChatMessage.objects.create(session=chat_session, role='user', content=message)
        ChatMessage.objects.create(
            session=chat_session,
            role='assistant',
            content=response_text,
            action_type=action.get('type') if action else None,
            action_payload=action,
        )
        chat_session.save(update_fields=['updated_at'])
        return JsonResponse({
            'session_id': chat_session.id,
            'session_title': chat_session.title,
            'text': response_text,
            'action': action,
        })

    user_text = _normalize_chat_text(message)
    matches = []
    for intent_name, intent_data in INTENT_MATRIX.items():
        matched_keywords = [keyword for keyword in intent_data['keywords'] if re.search(keyword, user_text, re.IGNORECASE)]
        if matched_keywords:
            matches.append((max(len(keyword) for keyword in matched_keywords), intent_name))

    action = None
    if matches:
        _, intent_name = max(matches, key=lambda match: match[0])
        response_data = INTENT_MATRIX[intent_name].copy()
        if intent_name == 'promociones':
            promotional_products = list(
                Productos.objects.filter(promocion=True, Cantidad__gt=0)
                .order_by('-Fecha_creacion')
                .values_list('Descripcion', 'Precio')[:8]
            )
            if promotional_products:
                product_summary = ', '.join(
                    f'{description} (${price})' for description, price in promotional_products
                )
                response_data['response'] = f"{response_data['response']} Productos destacados: {product_summary}."
            else:
                response_data['response'] = 'En este momento no hay productos con promoción activa y existencia disponible. Puedes revisar el catálogo completo para conocer las novedades.'
        response_text = response_data['response']
        action = {'type': response_data['action_type'], 'target': response_data['target'], 'guide_text': response_data['guide_text']} if response_data['action_type'] else None
    else:
        response_text = (
            'No encontré una coincidencia directa para esa consulta. Puedo buscar en todo el catálogo por nombre, '
            'código, uso o característica; cuéntame qué necesitas resolver o cómo es el producto que buscas.'
        )

    ChatMessage.objects.create(session=chat_session, role='user', content=message)
    ChatMessage.objects.create(
        session=chat_session,
        role='assistant',
        content=response_text,
        action_type=action.get('type') if action else None,
        action_payload=action,
    )
    chat_session.save(update_fields=['updated_at'])
    return JsonResponse({'session_id': chat_session.id, 'session_title': chat_session.title, 'text': response_text, 'action': action})


def delete_chat_session(request, session_id):
    if request.method != 'DELETE':
        return JsonResponse({'error': 'method_not_allowed'}, status=405)
    django_user = _chat_owner(request)
    if not request.session.session_key:
        request.session.save()
    sessions = ChatSession.objects.filter(id=session_id)
    if django_user is not None:
        sessions = sessions.filter(user=django_user, session_key=None)
    else:
        sessions = sessions.filter(user__isnull=True, session_key=request.session.session_key)
    chat_session = sessions.first()
    if chat_session is None:
        return JsonResponse({'error': 'session_not_found'}, status=404)
    chat_session.delete()
    return JsonResponse({'status': 'success'})


def ai_history_endpoint(request):
    if request.method != 'GET':
        return JsonResponse({'error': 'method_not_allowed'}, status=405)
    django_user = request.user if isinstance(request.user, User) and request.user.is_authenticated else None
    if django_user is None:
        customer_email = getattr(request.user, 'email', None)
        if customer_email:
            django_user = User.objects.filter(email__iexact=customer_email, is_active=True).first()
    if not request.session.session_key:
        request.session.save()
    sessions = ChatSession.objects.filter(user=django_user, session_key=None) if django_user else ChatSession.objects.filter(user__isnull=True, session_key=request.session.session_key)
    sessions = sessions.order_by('-updated_at', '-created_at').prefetch_related('messages')[:50]
    data = [{
        'id': session.id,
        'title': session.title,
        'created_at': session.created_at.isoformat(),
        'messages': list(session.messages.values('role', 'content', 'action_type', 'action_payload', 'timestamp')),
    } for session in sessions]
    return JsonResponse({'sessions': data})


@ratelimit(key='ip', rate='240/m', method='GET', block=True)
def catalog_search_api(request):
    query = str(request.GET.get('q') or '').strip()[:100]
    if len(query) < 2:
        return JsonResponse({'results': []})

    results = []
    for product in search_catalog(query, limit=8):
        image_url = product.Imagen.url if product.Imagen else f'{settings.STATIC_URL}img/default-product.png'
        results.append({
            'code': product.Codigo,
            'name': product.Descripcion,
            'category': product.Categoria.name if product.Categoria else 'General',
            'price': f'{product.Precio:.2f}',
            'stock': product.Cantidad,
            'image_url': image_url,
            'url': reverse('producto_detalle', args=[product.Codigo]),
        })
    return JsonResponse({'results': results})


ai_assistant_api = ai_chat_endpoint
ai_chat_history = ai_history_endpoint


class EmailOrUsernameBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or not password:
            return None
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            try:
                user = User.objects.get(email=username)
            except User.DoesNotExist:
                return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None


class CustomLoginView(LoginView):
    def form_valid(self, form):
        return super().form_valid(form)


def redirect_staff_to_admin_view(view_func):
    from functools import wraps
    from django.shortcuts import redirect
    from django.http import HttpResponseForbidden

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if hasattr(request, 'user') and request.user.is_authenticated and (getattr(request.user, 'is_staff', False) or getattr(request.user, 'is_superuser', False)):
            try:
                return redirect('dashboard')
            except Exception:
                return HttpResponseForbidden('Acceso no permitido desde panel cliente.')
        return view_func(request, *args, **kwargs)

    return _wrapped


def get_current_cliente(request):
    """Retorna el perfil de cliente e-commerce actual, aislado del admin."""
    user = getattr(request, 'user', None)
    if getattr(user, 'is_authenticated', False) and (getattr(user, 'is_staff', False) or getattr(user, 'is_superuser', False)):
        return None

    if hasattr(request, 'customer') and request.customer:
        customer = request.customer
    else:
        customer = get_customer_from_request(request)
        request.customer = customer

    if customer:
        cliente = customer.ensure_cliente_profile()
        request.session['cliente_id'] = cliente.id
        request.session['cliente_nombre'] = cliente.nombre
        request.session['cliente_email'] = cliente.email
        return cliente

    cliente_id = request.session.get('cliente_id')
    if not cliente_id:
        return None
    return Cliente.objects.filter(id=cliente_id).first()


def get_authenticated_django_user(request):
    """Devuelve el User Django real cuando la sesión es un Customer custom.

    Si el Customer no tiene un User asociado todavía, lo materializa con el mismo email
    para que los modelos que apuntan a User (PerfilCliente, Pedido, etc.) sigan siendo
    consistentes con el sistema de autenticación Django.
    """
    user = getattr(request, 'user', None)
    if not getattr(user, 'is_authenticated', False):
        return None
    if isinstance(user, User):
        return user
    email = getattr(user, 'email', None)
    if not email:
        return None

    django_user = User.objects.filter(email__iexact=email, is_active=True).first()
    if django_user is not None:
        return django_user

    base_username = (email.split('@')[0] or 'cliente').strip()[:150]
    username = base_username
    counter = 1
    while User.objects.filter(username=username).exists():
        username = f'{base_username}_{counter}'
        counter += 1

    django_user = User.objects.create(
        username=username,
        email=email,
        first_name=getattr(user, 'nombre', '') or '',
        last_name='',
        is_active=True,
    )
    django_user.set_unusable_password()
    django_user.save(update_fields=['first_name', 'last_name', 'is_active'])
    return django_user


def _ensure_django_user_for_customer(customer):
    """Retorna o crea un User Django estándar asociado a un Customer."""
    if not customer:
        return None

    cliente = customer.ensure_cliente_profile()
    if cliente and getattr(cliente, 'user', None):
        return cliente.user

    if customer.email:
        existing_user = User.objects.filter(email__iexact=customer.email, is_active=True, is_staff=False, is_superuser=False).first()
        if existing_user:
            if cliente and not getattr(cliente, 'user', None):
                cliente.user = existing_user
                cliente.save(update_fields=['user'])
            return existing_user

    base_username = re.sub(r'[^0-9a-zA-Z_\-\.]+', '', (customer.email.split('@')[0] if customer.email else 'cliente')).lower() or 'cliente'
    username = base_username
    suffix = 1
    while User.objects.filter(username=username).exists():
        username = f'{base_username}{suffix}'
        suffix += 1

    user = User.objects.create_user(
        username=username,
        email=customer.email or '',
        password=User.objects.make_random_password(),
    )
    user.is_active = True
    user.is_staff = False
    user.is_superuser = False
    user.save()

    if cliente:
        cliente.user = user
        cliente.save(update_fields=['user'])

    return user


def rate_limit_403(request, exception=None):
    """Respuesta para errores 403 por rate limiting."""
    try:
        return render(request, 'rate_limit_403.html', status=403)
    except Exception:
        return HttpResponse('Acceso denegado - límite de peticiones alcanzado.', status=403)


@user_passes_test(lambda u: u.is_staff, login_url='login_admin_custom')
def admin_creditos(request):
    return render(request, 'admin_creditos.html')


def condiciones_servicio(request):
    return render(request, 'legal/condiciones.html')


def politica_privacidad(request):
    return render(request, 'legal/privacidad.html')


def manual_usuario_pdf(request):
    """Sirve el manual del usuario desde la raíz del proyecto."""
    pdf_path = settings.BASE_DIR / 'Manual de usuario - Ferreelectri Plus.pdf'
    if not pdf_path.exists():
        return HttpResponse('No se encontró el manual del usuario.', status=404)

    response = FileResponse(open(pdf_path, 'rb'), as_attachment=True, filename=pdf_path.name)
    response['Content-Type'] = 'application/pdf'
    return response


def get_safe_redirect(request, next_url, default=None):
    default = default or settings.LOGIN_REDIRECT_URL
    if not next_url:
        return default
    if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return next_url
    if next_url.startswith('/'):
        return next_url
    return default


def log_auth_event(request, action, user=None, details=''):
    """Registra eventos de autenticación en AuditLog sin bloquear el flujo de la vista."""
    try:
        AuditLog.objects.create(
            user=user if user is not None else (request.user if hasattr(request, 'user') and request.user.is_authenticated else None),
            action=action,
            model_name='Customer',
            object_id=None,
            details=details,
            ip_address=request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
        )
    except Exception:
        pass


def add_to_anon_cart(request, producto, cantidad):
    anon_cart = request.session.get('anon_cart', {})
    product_key = str(producto.Codigo)
    current_qty = int(anon_cart.get(product_key, 0))
    anon_cart[product_key] = min(current_qty + cantidad, producto.Cantidad)
    request.session['anon_cart'] = anon_cart
    request.session.modified = True


def merge_session_cart_items(request, cliente):
    if not cliente:
        return
    anon_cart = request.session.get('anon_cart', {}) or {}
    anon_cart_meta = request.session.pop('anon_cart_meta', {}) or {}
    carrito = Carrito.objects.filter(cliente=cliente).first()
    if carrito:
        carrito.items.all().delete()
    elif anon_cart:
        carrito = Carrito.objects.create(cliente=cliente)

    for product_codigo, cantidad in anon_cart.items():
        try:
            producto = Productos.objects.get(Codigo=product_codigo)
            quantity = min(int(cantidad), producto.Cantidad)
        except Productos.DoesNotExist:
            continue
        except (TypeError, ValueError):
            continue
        if quantity <= 0 or carrito is None:
            continue

        item = CarritoItem(carrito=carrito, producto=producto, cantidad=quantity)
        meta = anon_cart_meta.get(product_codigo, {})
        if meta:
            try:
                item.presentacion_factor = int(meta.get('presentacion_factor') or 1)
            except (TypeError, ValueError):
                item.presentacion_factor = 1
            item.presentacion_type = meta.get('presentacion_type') or item.presentacion_type or ''
        item.save()
    request.session.pop('anon_cart', None)
    request.session.modified = True


@require_POST
def eliminar_item_carrito_anon(request, codigo):
    anon_cart = request.session.get('anon_cart', {}) or {}
    codigo = str(codigo)
    if codigo in anon_cart:
        anon_cart.pop(codigo, None)
        request.session['anon_cart'] = anon_cart
        request.session.modified = True
        messages.info(request, "Producto eliminado del carrito.")
    return redirect('carrito')


def actualizar_cantidad_carrito(request, codigo, cantidad):
    producto = get_object_or_404(Productos, Codigo=codigo)
    cantidad = max(0, min(cantidad, producto.Cantidad))
    cliente = get_current_cliente(request)

    if cliente:
        carrito = Carrito.objects.filter(cliente=cliente).first()
        item = carrito.items.filter(producto=producto).first() if carrito else None
        if item:
            if cantidad:
                item.cantidad = cantidad
                item.save(update_fields=['cantidad'])
            else:
                item.delete()
    else:
        anon_cart = request.session.get('anon_cart', {}) or {}
        codigo = str(codigo)
        if cantidad:
            anon_cart[codigo] = cantidad
        else:
            anon_cart.pop(codigo, None)
        request.session['anon_cart'] = anon_cart
        request.session.modified = True

    return redirect('carrito')


@ratelimit(key='ip', rate='100/h', method='GET', block=True)
def index(request):
    query = (request.GET.get('q', '') or '').strip()
    categoria = (request.GET.get('categoria', '') or '').strip()
    orden = (request.GET.get('orden', 'novedades') or 'novedades').strip()
    oferta = request.GET.get('oferta', '').lower() == 'true'

    productos = Productos.objects.select_related('Categoria')

    if query:
        search_filter = (
            models.Q(Codigo__icontains=query)
            | models.Q(Descripcion__icontains=query)
        )
        if 'Categoria' in [f.name for f in Productos._meta.get_fields()]:
            search_filter |= models.Q(Categoria__name__icontains=query)
        productos = productos.filter(search_filter)

    if categoria:
        categoria_obj = Categoria.objects.filter(slug__iexact=categoria).first()
        if categoria_obj:
            productos = productos.filter(Categoria=categoria_obj)
        else:
            productos = productos.filter(Descripcion__icontains=categoria)

    if oferta:
        productos = productos.filter(promocion=True)

    ordering = {
        'precio_asc': 'Precio',
        'precio_desc': '-Precio',
        'novedades': '-Fecha_creacion',
    }.get(orden, '-Fecha_creacion')
    productos = productos.order_by(ordering)

    cliente = None
    pedidos = None
    show_cliente_guide = False
    if request.user.is_authenticated:
        cliente = get_current_cliente(request)
        # `Pedido.creado` es propiedad en Python, usar el campo real `fecha_creacion` para consultas ORM
        pedidos = Pedido.objects.filter(cliente=cliente).order_by('-fecha_creacion')
        show_cliente_guide = request.session.pop('show_cliente_guide', False)
        request.session.modified = True

    return render(request, 'index.html', {
        'productos': productos,
        'categorias': Categoria.objects.order_by('name'),
        'populares': Productos.objects.filter(promocion=True).order_by('-Fecha_creacion')[:12],
        'cliente': cliente,
        'pedidos': pedidos,
        'show_cliente_guide': show_cliente_guide,
        'query': query,
        'categoria': categoria,
        'orden': orden,
        'oferta': oferta,
    })


@ratelimit(key='ip', rate='100/h', method='GET', block=True)
def catalogo_view(request):
    return index(request)


def formulario(request):
    return render(request, 'registration/login.html')


def formulario_view(request):
    return render(request, 'registro.html')


def registro(request):
    if request.method == 'POST':
        username = request.POST['username']
        email = request.POST['email']
        password1 = request.POST['password1']
        password2 = request.POST['password2']

        if password1 != password2:
            messages.error(request, "Las contraseñas no coinciden.")
            return render(request, 'registro.html')

        if User.objects.filter(username=username).exists():
            messages.error(request, "El nombre de usuario ya existe.")
            return render(request, 'registro.html')

        if User.objects.filter(email=email).exists():
            messages.error(request, "El correo electrónico ya está registrado.")
            return render(request, 'registro.html')

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password1,
        )
        user.is_active = True
        # No dar permisos de administrador a cuentas normales de cliente
        user.is_staff = False
        user.is_superuser = False
        user.save()

        # Crear o enlazar registro de Cliente en el modelo del sistema
        try:
            Cliente.objects.create(
                user=user,
                nombre=username,
                email=email,
            )
        except Exception:
            pass

        messages.success(request, "Cuenta creada correctamente. Por favor inicia sesión.")
        return redirect('login')

    return render(request, 'registro.html')


def recuperar_admin(request):
    if request.user.is_authenticated and not request.user.is_staff:
        return HttpResponseForbidden('La recuperación administrativa requiere una cuenta staff.')
    codigo_enviado = request.session.pop('codigo_enviado', False)
    error = request.GET.get('error', '')
    return render(request, 'recuperar.html', {'codigo_enviado': codigo_enviado, 'error': error})


def _normalizar_moneda(moneda):
    value = str(moneda or '').strip().upper()
    if value in ('BS', 'BS.', 'VES', 'BOLIVAR', 'BOLÍVAR'):
        return 'Bs.'
    if value in ('USD', '$', 'US$'):
        return 'USD'
    return str(moneda or 'Bs.')


def _factor_conversion_moneda(origen, destino, tasa_bcv):
    origen = _normalizar_moneda(origen)
    destino = _normalizar_moneda(destino)
    if origen == destino:
        return Decimal('1')
    if tasa_bcv <= 0:
        return None
    if origen == 'Bs.' and destino == 'USD':
        return Decimal('1') / tasa_bcv
    if origen == 'USD' and destino == 'Bs.':
        return tasa_bcv
    return None


def _dashboard_overview(request):
    hoy = timezone.localdate()
    periodo_inicio = hoy - timedelta(days=29)
    periodo_anterior_inicio = periodo_inicio - timedelta(days=30)
    rango_ventas = Factura.objects.filter(
        estado='facturada',
        fecha__date__gte=periodo_anterior_inicio,
        fecha__date__lte=hoy,
    ).annotate(
        moneda_efectiva=models.Case(
            models.When(moneda__iexact='VES', then=Value('Bs.')),
            default=Value('USD'),
            output_field=models.CharField(max_length=10),
        )
    )
    monedas = list(
        rango_ventas.values('moneda_efectiva')
        .annotate(facturas=Count('numero'))
        .order_by('-facturas', 'moneda_efectiva')
    )
    moneda_origen = _normalizar_moneda(monedas[0]['moneda_efectiva'] if monedas else 'Bs.')
    dashboard_config = AdminDashboardConfig.objects.filter(pk=1).first()
    tasa_bcv = dashboard_config.bcv_rate if dashboard_config else Decimal('0.0000')
    moneda_solicitada = request.GET.get('moneda', 'Bs.' if tasa_bcv > 0 else moneda_origen)
    if moneda_solicitada not in ('Bs.', 'USD'):
        moneda_solicitada = moneda_origen if moneda_origen in ('Bs.', 'USD') else 'Bs.'
    factor_ventas = _factor_conversion_moneda(moneda_origen, moneda_solicitada, tasa_bcv)
    moneda_activa = moneda_origen
    if factor_ventas is None:
        moneda_solicitada = moneda_origen
        factor_ventas = Decimal('1')
    factor_catalogo = _factor_conversion_moneda('USD', moneda_solicitada, tasa_bcv) or Decimal('1')

    def dinero_en_pantalla(amount, factor):
        return (Decimal(str(amount or 0)) * factor).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    facturas_moneda = rango_ventas.filter(moneda_efectiva=moneda_activa)
    ventas_por_dia = {
        row['dia']: row['total'] or Decimal('0')
        for row in facturas_moneda.annotate(dia=TruncDate('fecha'))
        .values('dia')
        .annotate(total=Sum('total'))
    }
    conteo_por_dia = {
        row['dia']: row['cantidad']
        for row in facturas_moneda.annotate(dia=TruncDate('fecha'))
        .values('dia')
        .annotate(cantidad=Count('numero'))
    }
    serie_ventas = [
        {
            'label': (periodo_inicio + timedelta(days=offset)).strftime('%d %b'),
            'total': float(dinero_en_pantalla(
                ventas_por_dia.get(periodo_inicio + timedelta(days=offset), 0), factor_ventas
            )),
        }
        for offset in range(30)
    ]
    ingresos_actuales = sum(
        (ventas_por_dia.get(periodo_inicio + timedelta(days=offset), Decimal('0')) for offset in range(30)),
        Decimal('0'),
    )
    ingresos_anteriores = sum(
        (ventas_por_dia.get(periodo_anterior_inicio + timedelta(days=offset), Decimal('0')) for offset in range(30)),
        Decimal('0'),
    )
    facturas_actuales = sum(
        conteo_por_dia.get(periodo_inicio + timedelta(days=offset), 0) for offset in range(30)
    )
    facturas_anteriores = sum(
        conteo_por_dia.get(periodo_anterior_inicio + timedelta(days=offset), 0) for offset in range(30)
    )
    variacion_ventas = (
        float((ingresos_actuales - ingresos_anteriores) * 100 / ingresos_anteriores)
        if ingresos_anteriores else None
    )

    detalle_venta_neto = ExpressionWrapper(
        F('precio') * F('cantidad') * (Value(100) - F('descuento')) / Value(100),
        output_field=DecimalField(max_digits=22, decimal_places=2),
    )
    detalle_costo_total = ExpressionWrapper(
        Coalesce(
            F('costo_unitario'),
            F('producto__Costo'),
            output_field=DecimalField(max_digits=10, decimal_places=2),
        ) * F('cantidad'),
        output_field=DecimalField(max_digits=22, decimal_places=2),
    )
    moneda_detalles = ~Q(factura__moneda__iexact='VES') if moneda_activa == 'USD' else Q(factura__moneda__iexact='VES')
    detalles_actuales = DetalleFactura.objects.filter(
        factura__estado='facturada',
        factura__fecha__date__gte=periodo_inicio,
        factura__fecha__date__lte=hoy,
    ).filter(moneda_detalles)
    unidades_vendidas = detalles_actuales.aggregate(total=Sum('cantidad'))['total'] or 0
    margen_con_costo = detalles_actuales.filter(costo_unitario__isnull=False).aggregate(
        ingresos=Sum(detalle_venta_neto),
        costos=Sum(ExpressionWrapper(
            F('costo_unitario') * F('cantidad'),
            output_field=DecimalField(max_digits=22, decimal_places=2),
        )),
        lineas=Count('pk'),
    )
    ganancia_bruta = (margen_con_costo['ingresos'] or Decimal('0')) - (margen_con_costo['costos'] or Decimal('0'))
    margen_bruto_pct = (
        float(ganancia_bruta * 100 / margen_con_costo['ingresos'])
        if margen_con_costo['ingresos'] else None
    )
    lineas_venta_actuales = detalles_actuales.count()
    cobertura_costos_pct = (
        round(margen_con_costo['lineas'] * 100 / lineas_venta_actuales)
        if lineas_venta_actuales else 0
    )
    productos_lideres = list(
        detalles_actuales.values('producto_id', 'producto__Descripcion')
        .annotate(unidades=Sum('cantidad'), ingresos=Sum(detalle_venta_neto))
        .order_by('-unidades', '-ingresos')[:5]
    )
    max_unidades = max((item['unidades'] for item in productos_lideres), default=0)
    for item in productos_lideres:
        item['porcentaje'] = round(item['unidades'] * 100 / max_unidades) if max_unidades else 0

    precio_margen_expr = ExpressionWrapper(
        (F('Precio') - F('Costo')) * Value(100) / F('Precio'),
        output_field=DecimalField(max_digits=8, decimal_places=2),
    )
    productos_con_costo = Productos.objects.filter(Costo__gt=0)
    productos_precio_bajo_costo = productos_con_costo.filter(
        Q(Precio__lte=F('Costo')) | Q(Precio__isnull=True)
    ).order_by('Descripcion')
    margen_catalogo = Productos.objects.filter(Precio__gt=0, Costo__gt=0).aggregate(
        promedio=Avg(precio_margen_expr)
    )['promedio']
    inventario_costo_expr = ExpressionWrapper(
        F('Costo') * F('Cantidad'),
        output_field=DecimalField(max_digits=22, decimal_places=2),
    )
    total_inventario_costo = Productos.objects.aggregate(
        total=Sum(inventario_costo_expr)
    )['total'] or Decimal('0')
    total_unidades_inventario = Productos.objects.aggregate(total=Sum('Cantidad'))['total'] or 0
    productos_sin_stock = Productos.objects.filter(Cantidad=0).count()
    productos_costo_desconocido = Productos.objects.filter(Costo__lte=0, Cantidad__gt=0).count()
    alertas_precio = [
        {
            'Descripcion': product.Descripcion,
            'Precio': dinero_en_pantalla(product.Precio, factor_catalogo),
            'Costo': dinero_en_pantalla(product.Costo, factor_catalogo),
        }
        for product in productos_precio_bajo_costo[:5]
    ]
    productos_lideres = [
        {**product, 'ingresos': dinero_en_pantalla(product['ingresos'], factor_ventas)}
        for product in productos_lideres
    ]

    audit_inicio = hoy - timedelta(days=6)
    audit_qs = AuditLog.objects.filter(timestamp__date__gte=audit_inicio, timestamp__date__lte=hoy)
    audit_por_dia = {
        row['dia']: row['cantidad']
        for row in audit_qs.annotate(dia=TruncDate('timestamp'))
        .values('dia')
        .annotate(cantidad=Count('pk'))
    }
    auditoria_serie = [
        {
            'label': (audit_inicio + timedelta(days=offset)).strftime('%a'),
            'total': audit_por_dia.get(audit_inicio + timedelta(days=offset), 0),
        }
        for offset in range(7)
    ]
    auditoria_acciones = list(
        audit_qs.values('action')
        .annotate(total=Count('pk'))
        .order_by('-total')[:5]
    )
    audit_logs = []
    for log in AuditLog.objects.select_related('user').order_by('-timestamp')[:8]:
        details = log.details or ''
        details_clean = re.split(r'\s+con args=|\s+with args=|\s+args=', details, maxsplit=1)[0].strip()
        details_clean = re.sub(r'kwargs=\{.*\}$', '', details_clean).strip()
        audit_logs.append({
            'username': log.user.username if log.user else 'Anónimo',
            'action': log.action,
            'model_name': log.model_name.replace('_', ' '),
            'details': f"Acceso a {log.model_name.replace('_', ' ')}" if log.action.upper() == 'ACCESO' else (details_clean or log.action),
            'timestamp': log.timestamp,
        })

    backup_directory = Path(getattr(settings, 'BACKUP_DIRECTORY', Path(settings.BASE_DIR) / 'backups' / 'weekly'))
    backup_files = sorted(
        backup_directory.glob('ferreelectri-backup-*.tar.gz') if backup_directory.exists() else [],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    backup_history = [
        {
            'name': item.name,
            'size_mb': round(item.stat().st_size / (1024 * 1024), 1),
            'created_at': timezone.localtime(datetime.fromtimestamp(item.stat().st_mtime, tz=timezone.get_current_timezone())),
        }
        for item in backup_files[:5]
    ]
    try:
        backup_status = json.loads((backup_directory / 'backup-status.json').read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError):
        backup_status = {}
    latest_backup = backup_files[0] if backup_files else None
    backup_latest_verified = bool(
        latest_backup
        and backup_status.get('archive_name') == latest_backup.name
        and len(backup_status.get('archive_sha256', '')) == 64
        and backup_status.get('archive_bytes') == latest_backup.stat().st_size
    )
    backup_schedule_path = Path(getattr(
        settings,
        'BACKUP_SCHEDULE_STATUS_FILE',
        Path(settings.BASE_DIR) / 'backups' / 'backup-schedule.json',
    ))
    try:
        backup_schedule = json.loads(backup_schedule_path.read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError):
        backup_schedule = {}
    backup_mirror_configured = bool(str(getattr(settings, 'BACKUP_MIRROR_DIRECTORY', '') or '').strip())
    backup_tools_ready = False
    try:
        from FERREELECTRI_PLUS.backup_utils import BackupError, _find_postgres_tool
        _find_postgres_tool('pg_dump')
        _find_postgres_tool('pg_restore')
        backup_tools_ready = True
    except (BackupError, OSError):
        pass

    context = {
        'racismo': 'Panel administrativo | FerreElectri PLUS',
        'total_clientes': UsuarioClientes.objects.count(),
        'total_proveedores': Proveedores.objects.count(),
        'total_productos': Productos.objects.count(),
        'currency': moneda_solicitada,
        'source_currency': moneda_origen,
        'currency_options': ('Bs.', 'USD'),
        'currency_conversion_available': tasa_bcv > 0,
        'currency_converted': moneda_solicitada != moneda_origen,
        'bcv_rate': tasa_bcv,
        'bcv_updated_at': dashboard_config.updated_at if dashboard_config else None,
        'sales_chart': serie_ventas,
        'sales_30d': dinero_en_pantalla(ingresos_actuales, factor_ventas),
        'sales_previous_30d': dinero_en_pantalla(ingresos_anteriores, factor_ventas),
        'sales_change_pct': variacion_ventas,
        'current_invoice_count': facturas_actuales,
        'previous_invoice_count': facturas_anteriores,
        'average_ticket': dinero_en_pantalla(ingresos_actuales / facturas_actuales, factor_ventas) if facturas_actuales else Decimal('0'),
        'units_sold_30d': unidades_vendidas,
        'gross_profit_30d': dinero_en_pantalla(ganancia_bruta, factor_ventas),
        'gross_margin_pct': margen_bruto_pct,
        'cost_coverage_pct': cobertura_costos_pct,
        'top_products': productos_lideres,
        'catalog_margin_pct': float(margen_catalogo) if margen_catalogo is not None else None,
        'products_below_cost': productos_precio_bajo_costo.count(),
        'products_below_cost_list': alertas_precio,
        'products_out_of_stock': productos_sin_stock,
        'products_cost_unknown': productos_costo_desconocido,
        'inventory_cost_value': dinero_en_pantalla(total_inventario_costo, factor_catalogo),
        'inventory_units': total_unidades_inventario,
        'audit_chart': auditoria_serie,
        'audit_actions': auditoria_acciones,
        'audit_total_7d': audit_qs.count(),
        'audit_logs': audit_logs,
        'backup_history': backup_history,
        'backup_latest_verified': backup_latest_verified,
        'backup_latest_hash': backup_status.get('archive_sha256', ''),
        'backup_mirror_verified': bool(backup_status.get('mirror_verified')),
        'backup_schedule_installed': bool(backup_schedule.get('task_name')),
        'backup_schedule': backup_schedule,
        'backup_mirror_configured': backup_mirror_configured,
        'backup_tools_ready': backup_tools_ready,
        'backup_retention': getattr(settings, 'BACKUP_RETENTION_COUNT', 12),
        'backup_archive_count': len(backup_files),
    }
    return render(request, 'dashboard_overview.html', context)


@user_passes_test(lambda user: user.is_staff, login_url='login_admin_custom')
@require_POST
def actualizar_tasa_bcv(request):
    raw_rate = request.POST.get('bcv_rate', '').strip().replace(',', '.')
    try:
        rate = Decimal(raw_rate)
        valid_rate = (
            rate.is_finite()
            and Decimal('0') < rate < Decimal('10000000000')
            and rate == rate.quantize(Decimal('0.0001'))
        )
    except (ArithmeticError, ValueError):
        valid_rate = False

    if not valid_rate:
        messages.error(request, 'La tasa BCV debe ser un número positivo con hasta cuatro decimales.')
        return redirect('dashboard')

    AdminDashboardConfig.objects.update_or_create(
        pk=1,
        defaults={'bcv_rate': rate, 'updated_by': request.user},
    )
    messages.success(request, 'Tasa BCV actualizada. Las equivalencias del panel ya usan el nuevo valor.')
    currency = request.POST.get('moneda')
    dashboard_url = reverse('dashboard')
    if currency in ('Bs.', 'USD'):
        return redirect(f'{dashboard_url}?{urllib_parse.urlencode({"moneda": currency})}')
    return redirect(dashboard_url)


@user_passes_test(lambda u: u.is_staff, login_url='login_admin_custom')
@log_view_access
def clientes(request):
    query = request.GET.get('q', '')
    pedidos_confirmados = Pedido.objects.filter(
        cliente__email__iexact=models.OuterRef('email'),
        estado__in=('pagado', 'enviado'),
    )
    clientes_qs = UsuarioClientes.objects.annotate(
        es_comprador=models.Exists(pedidos_confirmados),
    ).order_by('-fecha_registro')
    if query:
        clientes_qs = clientes_qs.filter(
            models.Q(nombre__icontains=query) |
            models.Q(apellido__icontains=query) |
            models.Q(telefono__icontains=query) |
            models.Q(cedula__icontains=query) |
            models.Q(email__icontains=query)
        )
    paginator = Paginator(clientes_qs, 5)
    page_number = request.GET.get('page')
    clientes = paginator.get_page(page_number)

    contador_nuevo = UsuarioClientes.objects.count()
    contador_compradores = UsuarioClientes.objects.annotate(
        es_comprador=models.Exists(pedidos_confirmados),
    ).filter(es_comprador=True).count()

    context = {
        'racismo': 'FerreElectri PLUS | Clientes',
        'clientes': clientes,
        'clientes_nuevos': contador_nuevo,
        'compradores_confirmados': contador_compradores,
    }
    return render(request, 'clientes.html', context)


@user_passes_test(lambda u: u.is_staff, login_url='login_admin_custom')
@log_view_access
def proveedores(request):
    query = request.GET.get('q', '')
    proveedores_qs = Proveedores.objects.all().order_by('-Fecha_registro')
    if query:
        proveedores_qs = proveedores_qs.filter(
            models.Q(cedula__icontains=query) |
            models.Q(nombre__icontains=query) |
            models.Q(telefono__icontains=query) |
            models.Q(email__icontains=query)
        )
    paginator = Paginator(proveedores_qs, 5)
    page_number = request.GET.get('page')
    proveedores = paginator.get_page(page_number)
    contador_nuevo_p = Proveedores.objects.count()

    context = {
        'racismo': 'FerreElectri PLUS | Proveedores',
        'proveedores': proveedores,
        'proveedores_nuevos': contador_nuevo_p,
    }
    return render(request, 'proveedores.html', context)


@user_passes_test(lambda u: u.is_staff, login_url='login_admin_custom')
@log_view_access
def inventario(request):
    query = request.GET.get('q', '') or ''
    query = query.strip()
    productos_qs = Productos.objects.all().order_by('-Fecha_creacion')
    if request.GET.get('oferta', '').lower() == 'true':
        productos_qs = productos_qs.filter(promocion=True)
    if query:
        lower_query = query.lower()
        month_map = {
            'enero': '01', 'febrero': '02', 'marzo': '03', 'abril': '04',
            'mayo': '05', 'junio': '06', 'julio': '07', 'agosto': '08',
            'septiembre': '09', 'setiembre': '09', 'octubre': '10',
            'noviembre': '11', 'diciembre': '12',
            'ene': '01', 'feb': '02', 'mar': '03', 'abr': '04', 'may': '05',
            'jun': '06', 'jul': '07', 'ago': '08', 'sep': '09', 'oct': '10',
            'nov': '11', 'dic': '12'
        }
        month_code = next((code for name, code in month_map.items() if name in lower_query), None)
        search_filter = (
            models.Q(Codigo__icontains=query) |
            models.Q(Descripcion__icontains=query) |
            models.Q(Precio__icontains=query) |
            models.Q(Cantidad__icontains=query) |
            models.Q(Fecha_creacion__icontains=query)
        )
        if month_code:
            search_filter |= models.Q(Fecha_creacion__contains=month_code)
        productos_qs = productos_qs.filter(search_filter)

    productos_filtrados = productos_qs.count()
    paginator = Paginator(productos_qs, 10)
    page_number = request.GET.get('page')
    productos = paginator.get_page(page_number)
    productos_totales = Productos.objects.count()
    contador_nuevo_2 = Productos.objects.filter(promocion=True).count()

    context = {
        'racismo': 'FerreElectri PLUS | Inventario',
        'productos': productos,
        'productos_totales': productos_totales,
        'productos_filtrados': productos_filtrados,
        'productos_promocion': contador_nuevo_2,
        'query': query,
    }

    return render(request, 'inventario.html', context)


@user_passes_test(lambda u: u.is_staff, login_url='login_admin_custom')
@permission_required('dashboard.view_auditlog')
def audit_logs(request):
    logs = AuditLog.objects.all().order_by('-timestamp')
    return render(request, 'audit_logs.html', {'logs': logs})


def descargar_auditoria_csv(request):
    logs = AuditLog.objects.all().order_by('-timestamp')

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="auditoria.csv"'

    writer = csv.writer(response)
    writer.writerow(['Usuario', 'Acción', 'Modelo', 'Detalles', 'Fecha'])

    for log in logs:
        writer.writerow([
            log.user.username if log.user else 'Anónimo',
            log.action,
            log.model_name,
            log.details,
            log.timestamp.strftime('%d/%m/%Y %H:%M')
        ])

    return response


def auditoria_completa(request):
    hace_7_dias = timezone.now() - timedelta(days=7)
    logs = AuditLog.objects.filter(timestamp__gte=hace_7_dias).order_by('-timestamp')
    processed = []
    for log in logs:
        username = log.user.username if log.user else 'Anónimo'
        action = log.action
        model = log.model_name
        details = log.details or ''
        m = re.split(r'\s+con args=|\s+with args=|\s+args=', details, maxsplit=1)
        details_clean = m[0].strip() if m else details
        details_clean = re.sub(r'kwargs=\{.*\}$', '', details_clean).strip()
        if action and action.upper() == 'ACCESO':
            pretty_model = model.replace('_', ' ')
            details_display = f'Acceso a {pretty_model}'
        else:
            details_display = details_clean or action or ''

        processed.append({
            'username': username,
            'action': action,
            'model_name': model,
            'details': details_display,
            'raw_details': details,
            'timestamp': log.timestamp,
            'ip_address': log.ip_address,
            'user_agent': log.user_agent,
        })

    include_ip = any(p['ip_address'] for p in processed)
    include_user_agent = any(p['user_agent'] for p in processed)

    colspan = 5 + (1 if include_ip else 0) + (1 if include_user_agent else 0)
    return render(request, 'dashboard/auditoria_completa.html', {
        'logs': processed,
        'include_ip': include_ip,
        'include_user_agent': include_user_agent,
        'colspan': colspan,
    })


def reset_password(request):
    if request.user.is_authenticated and not request.user.is_staff:
        return HttpResponseForbidden('El restablecimiento administrativo requiere una cuenta staff.')
    if request.method == 'POST':
        codigo = request.POST.get('codigo')
        nueva_clave = request.POST.get('nueva_clave')
        nueva_clave2 = request.POST.get('nueva_clave2')

        if nueva_clave != nueva_clave2:
            messages.error(request, "Las contraseñas no coinciden.")
            return render(request, 'recuperar.html')

        messages.success(request, "¡Contraseña restablecida correctamente! Ahora puedes iniciar sesión.")
        return redirect('login')

    return render(request, 'recuperar.html', {'codigo_enviado': True})


def get_recovery_display_name(usuario, email=''):
    if usuario is None:
        return 'Usuario'

    nombre = (usuario.get_full_name() or '').strip()
    if nombre:
        return nombre

    try:
        cliente = Cliente.objects.filter(user=usuario).first() or Cliente.objects.filter(email__iexact=email or '').first()
    except Exception:
        cliente = None

    if cliente:
        nombre_cliente = (getattr(cliente, 'nombre', '') or '').strip()
        if nombre_cliente:
            return nombre_cliente

    return (usuario.username or '').strip() or (email or '').split('@')[0] or 'Usuario'


@ratelimit(key='ip', rate='5/m', method='POST', block=True)
def solicitar_recuperacion_admin(request):
    if request.user.is_authenticated and not request.user.is_staff:
        return HttpResponseForbidden('La recuperación administrativa requiere una cuenta staff.')
    if request.method == 'POST':
        email = (request.POST.get('email') or '').strip().lower()
        if not email:
            return render(request, 'recuperar.html', {
                'error': 'Debes ingresar un correo válido para continuar.'
            })

        usuario = User.objects.filter(
            email__iexact=email,
            is_active=True,
        ).filter(models.Q(is_staff=True) | models.Q(is_superuser=True)).first()
        _clear_recovery_session(request)
        if not usuario:
            return render(request, 'recuperar.html', {
                'error': 'No existe una cuenta registrada con ese correo. Revisa el correo o regístrate.',
            })

        request.session['recupera_scope'] = 'admin'
        request.session['codigo_enviado'] = True
        codigo = get_random_string(8)
        request.session['recupera_codigo_hash'] = make_password(codigo)
        request.session['recupera_email'] = email
        request.session['recupera_usuario'] = get_recovery_display_name(usuario, email)
        request.session['recupera_expira_en'] = (timezone.now() + timedelta(minutes=10)).timestamp()
        request.session['recupera_intentos'] = 0
        html_content = render_to_string('emails/recuperacion_codigo.html', {
            'usuario': usuario,
            'codigo': codigo,
            'logo_url': 'https://tudominio.com/static/img/logo.png',
        })
        message = EmailMultiAlternatives(
            'Recupera tu acceso a FerreElectri PLUS', '', settings.EMAIL_HOST_USER, [email]
        )
        message.attach_alternative(html_content, 'text/html')
        try:
            message.send()
        except Exception as exc:
            _clear_recovery_session(request)
            logger.warning('No se pudo enviar un correo de recuperación admin (%s).', type(exc).__name__)
        return redirect('recuperar_codigo_admin')

    return render(request, 'recuperar.html')


def recuperar_cliente(request):
    if request.user.is_authenticated and request.user.is_staff:
        return HttpResponseForbidden('Las cuentas administrativas deben usar el portal administrativo.')
    codigo_enviado = request.session.pop('cliente_codigo_enviado', False)
    error = request.GET.get('error', '')
    return render(request, 'recuperar_cliente.html', {
        'codigo_enviado': codigo_enviado,
        'error': error,
    })


def _mask_recovery_email(email):
    local_part, separator, domain = (email or '').strip().lower().partition('@')
    if not separator or not local_part or not domain:
        return ''
    if len(local_part) <= 2:
        return f'{local_part[:1]}*@{domain}'
    if len(local_part) <= 4:
        visible_end = local_part[-1:]
        return f'{local_part[:1]}{"*" * max(len(local_part) - 2, 1)}{visible_end}@{domain}'
    visible_start = local_part[:2]
    visible_end = local_part[-2:]
    middle_len = max(len(local_part) - 4, 2)
    return f'{visible_start}{"*" * middle_len}{visible_end}@{domain}'


@ratelimit(key='ip', rate='5/m', method='POST', block=True)
def solicitar_recuperacion_cliente(request):
    if request.user.is_authenticated and request.user.is_staff:
        return HttpResponseForbidden('Las cuentas administrativas deben usar el portal administrativo.')
    if request.method != 'POST':
        return redirect('recuperar_cliente')

    email = (request.POST.get('email') or '').strip().lower()
    if not email:
        return render(request, 'recuperar_cliente.html', {
            'error': 'Debes ingresar un correo válido para continuar.',
        })

    usuario = User.objects.filter(email__iexact=email, is_staff=False, is_superuser=False, is_active=True).first()
    _clear_recovery_session(request)
    if not usuario:
        return render(request, 'recuperar_cliente.html', {
            'error': 'No existe una cuenta registrada con ese correo. Revisa el correo o regístrate.',
        })

    request.session['recupera_scope'] = 'cliente'
    request.session['cliente_codigo_enviado'] = True
    request.session['codigo_enviado'] = True

    codigo = get_random_string(8)
    request.session['recupera_codigo_hash'] = make_password(codigo)
    request.session['recupera_email'] = email
    request.session['recupera_usuario'] = get_recovery_display_name(usuario, email)
    request.session['recupera_expira_en'] = (timezone.now() + timedelta(minutes=10)).timestamp()
    request.session['recupera_intentos'] = 0

    html_content = render_to_string('emails/recuperacion_codigo.html', {
        'usuario': usuario,
        'codigo': codigo,
        'logo_url': 'https://tudominio.com/static/img/logo.png',
    })
    try:
        message = EmailMultiAlternatives(
            'Recupera tu acceso a FerreElectri PLUS',
            '',
            settings.EMAIL_HOST_USER,
            [email],
        )
        message.attach_alternative(html_content, 'text/html')
        message.send()
    except Exception:
        return render(request, 'recuperar_cliente.html', {
            'error': 'No se pudo enviar el correo de recuperación. Inténtalo más tarde.',
        })

    return redirect('recuperar_codigo_cliente')


def _clear_recovery_session(request):
    for key in (
        'recupera_codigo', 'recupera_codigo_hash', 'recupera_email',
        'recupera_usuario', 'recupera_scope', 'recupera_expira_en',
        'recupera_intentos', 'codigo_enviado', 'cliente_codigo_enviado',
    ):
        request.session.pop(key, None)

def log_view_access(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        AuditLog.objects.create(
            user=request.user if request.user.is_authenticated else None,
            action="ACCESO",
            model_name=view_func.__name__,
            timestamp=now(),
            details=f"Acceso a {view_func.__name__} con args={args} kwargs={kwargs}"
        )
        return view_func(request, *args, **kwargs)
    return wrapper

class EmailOrUsernameBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or not password:
            return None
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            try:
                user = User.objects.get(email=username)
            except User.DoesNotExist:
                return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None

class CustomLoginView(LoginView):
    def form_valid(self, form):
        return super().form_valid(form)

@ratelimit(key='ip', rate='5/m', method='POST', block=True)
def login_view(request):
    next_value = request.POST.get('next') or request.GET.get('next', '')
    next_url = get_safe_redirect(request, next_value, default=settings.LOGIN_REDIRECT_URL)
    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest'

    # Blindaje: si ya está autenticado, redirigir al panel correspondiente
    if request.user.is_authenticated:
        if request.user.is_staff or request.user.is_superuser:
            return redirect(reverse('dashboard'))
        return redirect(reverse('panel_cliente'))

    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            if user is None:
                if is_ajax:
                    return JsonResponse({'ok': False, 'errors': {'__all__': ['Credenciales inválidas.']}}, status=400)
                messages.error(request, 'Credenciales inválidas.')
                return render(request, 'registration/login.html', {'form': form, 'next': next_value})

            if user.is_staff or user.is_superuser:
                request.session.pop('admin_login_unlocked_until', None)
                login(request, user)
                redirect_url = reverse('dashboard')
                if is_ajax:
                    return JsonResponse({'ok': True, 'next': redirect_url})
                return redirect(redirect_url)

            messages.error(request, 'Esta cuenta no tiene acceso administrativo. Usa el login de cliente.')
            if is_ajax:
                return JsonResponse(
                    {'ok': False, 'errors': {'__all__': ['Esta cuenta no tiene acceso administrativo. Usa el login de cliente.']}},
                    status=403,
                )
            return render(request, 'registration/login.html', {
                'form': form,
                'next': next_value,
            })
        if is_ajax:
            return JsonResponse({'ok': False, 'errors': form.errors}, status=400)
    else:
        form = AuthenticationForm()
    return render(request, 'registration/login.html', {
        'form': form,
        'next': next_value,
    })


@ratelimit(key='ip', rate='10/m', method='POST', block=True)
def admin_login_unlock(request):
    if settings.DEBUG:
        return JsonResponse({'ok': False, 'error': 'El desbloqueo por clave solo se usa en producción.'}, status=404)
    if request.method != 'POST':
        return JsonResponse({'ok': False}, status=405)

    now_timestamp = timezone.now().timestamp()
    client_ip = request.META.get('REMOTE_ADDR') or 'unknown'
    ip_digest = hashlib.sha256(client_ip.encode('utf-8')).hexdigest()
    attempts_cache_key = f'admin-login-attempts:{ip_digest}'
    lock_cache_key = f'admin-login-lock:{ip_digest}'
    locked_until = float(request.session.get('admin_login_locked_until', 0) or 0)
    cached_locked_until = cache.get(lock_cache_key, 0) or 0
    locked_until = max(locked_until, float(cached_locked_until))
    if locked_until > now_timestamp:
        return JsonResponse({
            'ok': False,
            'error': 'Acceso temporalmente bloqueado.',
            'locked_until': locked_until,
            'retry_after': max(1, int(locked_until - now_timestamp)),
        }, status=429)
    if locked_until:
        cache.delete(lock_cache_key)
        cache.delete(attempts_cache_key)
        request.session.pop('admin_login_locked_until', None)
        request.session.pop('admin_login_attempts', None)

    def issue_challenge():
        challenge = {
            'token': get_random_string(48),
            'expires_at': now_timestamp + 30,
        }
        request.session['admin_login_challenge'] = challenge
        return challenge

    def failed_attempt(error, status=403):
        session_attempts = int(request.session.get('admin_login_attempts', 0))
        ip_attempts = int(cache.get(attempts_cache_key, 0) or 0)
        attempts = max(session_attempts, ip_attempts) + 1
        request.session['admin_login_attempts'] = attempts
        cache.set(attempts_cache_key, attempts, timeout=900)
        request.session.pop('admin_login_challenge', None)
        if attempts >= 3:
            lock_until = now_timestamp + 900
            request.session['admin_login_locked_until'] = lock_until
            cache.set(lock_cache_key, lock_until, timeout=900)
            return JsonResponse({
                'ok': False,
                'error': 'Se agotaron los intentos. El acceso queda pausado por 15 minutos.',
                'attempts_used': attempts,
                'attempts_remaining': 0,
                'locked_until': lock_until,
            }, status=429)

        challenge = issue_challenge()
        return JsonResponse({
            'ok': False,
            'error': error,
            'attempts_used': attempts,
            'attempts_remaining': 3 - attempts,
            'challenge': challenge['token'],
            'expires_at': challenge['expires_at'],
        }, status=status)

    action = request.POST.get('action', '')
    challenge = request.session.get('admin_login_challenge')
    attempts_used = max(
        int(request.session.get('admin_login_attempts', 0)),
        int(cache.get(attempts_cache_key, 0) or 0),
    )
    request.session['admin_login_attempts'] = attempts_used
    if action == 'start':
        if challenge and challenge.get('expires_at', 0) <= now_timestamp:
            return failed_attempt('El tiempo terminó. Se descontó un intento.', status=408)
        if not challenge:
            challenge = issue_challenge()
        return JsonResponse({
            'ok': True,
            'challenge': challenge['token'],
            'expires_at': challenge['expires_at'],
            'attempts_used': attempts_used,
            'attempts_remaining': 3 - attempts_used,
        })

    if not challenge or request.POST.get('challenge') != challenge.get('token'):
        return JsonResponse({'ok': False, 'error': 'El desafío ya no es válido. Vuelve a abrir el acceso.'}, status=403)
    if challenge.get('expires_at', 0) <= now_timestamp:
        return failed_attempt('El tiempo terminó. Se descontó un intento.', status=408)
    if action != 'verify':
        return JsonResponse({'ok': False, 'error': 'Acción no válida.'}, status=400)

    password = request.POST.get('password', '')
    is_valid = bool(password) and any(
        user.check_password(password)
        for user in User.objects.filter(is_active=True)
        .filter(models.Q(is_staff=True) | models.Q(is_superuser=True))
        .only('password')
    )
    if not is_valid:
        return failed_attempt('Clave incorrecta.')

    request.session.pop('admin_login_challenge', None)
    request.session.pop('admin_login_attempts', None)
    cache.delete(attempts_cache_key)
    cache.delete(lock_cache_key)
    request.session['admin_login_unlocked_until'] = now_timestamp + 60
    return JsonResponse({
        'ok': True,
        'next': reverse('login_admin_custom'),
        'login_expires_at': now_timestamp + 60,
    })


def login_cliente(request):
    """Alias público y claro para el login del cliente e-commerce.
    Reutiliza la lógica de `cliente_login` asegurando plantilla separada para clientes.
    """
    # Delegamos en la implementación existente `cliente_login` para mantener la lógica central.
    return cliente_login(request)

def _catalog_filter_queryset(query='', categoria='', oferta=False):
    """Construye filtros usando el nombre real de la FK de categorías."""
    queryset = Productos.objects.all()
    product_fields = {field.name for field in Productos._meta.get_fields()}
    category_field = 'Categoria' if 'Categoria' in product_fields else 'categoria' if 'categoria' in product_fields else None

    if query:
        # SKU y descripción existen hoy; categoría se añade solo si el modelo la incorpora.
        search_filter = (
            models.Q(Codigo__icontains=query)
            | models.Q(Descripcion__icontains=query)
        )
        if category_field == 'Categoria':
            search_filter |= models.Q(Categoria__name__icontains=query)
        elif category_field == 'categoria':
            search_filter |= models.Q(categoria__nombre__icontains=query)
        queryset = queryset.filter(search_filter)

    if categoria:
        if category_field == 'Categoria':
            queryset = queryset.filter(Categoria__slug__iexact=categoria)
        elif category_field == 'categoria':
            queryset = queryset.filter(categoria__nombre__icontains=categoria)
        else:
            # El modelo actual no tiene Categoria; permite operar el filtro por texto útil.
            queryset = queryset.filter(Descripcion__icontains=categoria)

    if oferta:
        queryset = queryset.filter(promocion=True)
    return queryset


def get_cached_catalog_products(query='', categoria='', oferta=False, orden='novedades'):
    """Devuelve productos con máximo dos consultas SQL en un miss de Redis."""
    cache_key = catalog_cache_key(query=f'categories-v2|{query}|{categoria}|{orden}', oferta=oferta)
    product_ids = cache.get(cache_key)

    if product_ids is None:
        # Filtra únicamente columnas indexables y guarda IDs compactos en Redis.
        base_queryset = _catalog_filter_queryset(query, categoria, oferta)
        ordering = {
            'precio_asc': 'Precio',
            'precio_desc': '-Precio',
            'novedades': '-Fecha_creacion',
        }.get(orden, '-Fecha_creacion')
        product_ids = list(base_queryset.order_by(ordering).values_list('pk', flat=True))
        cache.set(cache_key, product_ids, timeout=CATALOG_TIMEOUT)

    # Productos no tiene FKs de categoría ni relaciones de imágenes adicionales que precargar.
    return (
        Productos.objects
        .filter(pk__in=product_ids)
        .only('Codigo', 'Descripcion', 'Precio', 'Cantidad', 'promocion', 'Imagen', 'Fecha_creacion')
        .order_by(
            {'precio_asc': 'Precio', 'precio_desc': '-Precio'}.get(orden, '-Fecha_creacion')
        )
    )


@ratelimit(key='ip', rate='100/h', method='GET', block=True)
def index(request):
    query = (request.GET.get('q', '') or '').strip()
    categoria = (request.GET.get('categoria', '') or '').strip()
    orden = (request.GET.get('orden', 'novedades') or 'novedades').strip()
    oferta = request.GET.get('oferta', '').lower() == 'true'
    catalogo_activo = (
        request.resolver_match.url_name in {'productos', 'catalogo'}
        or bool(query or categoria or oferta or request.GET.get('vista') == 'catalogo')
    )
    productos = (
        get_cached_catalog_products(query=query, categoria=categoria, oferta=oferta, orden=orden)
        if catalogo_activo else Productos.objects.none()
    )
    populares = Productos.objects.annotate(
        unidades_vendidas=Sum(
            'detallefactura__cantidad',
            filter=models.Q(detallefactura__factura__estado='facturada'),
        )
    ).filter(unidades_vendidas__gt=0).order_by('-unidades_vendidas', '-Fecha_creacion')[:8]
    promociones = Productos.objects.filter(promocion=True, Cantidad__gt=0).order_by('-Fecha_creacion')[:8]
    cliente = None
    pedidos = None
    user = get_authenticated_django_user(request)
    if user is not None:
        cliente = Cliente.objects.filter(user=user).first()
        if not cliente and getattr(request.user, 'email', None):
            cliente = Cliente.objects.filter(email__iexact=request.user.email).first()
            if cliente:
                cliente.user = user
                cliente.save(update_fields=['user'])
            elif request.user.email:
                cliente = Cliente.objects.create(
                    user=user,
                    nombre=getattr(request.user, 'get_full_name', lambda: None)() or getattr(request.user, 'nombre', None) or getattr(request.user, 'username', None) or request.user.email,
                    email=request.user.email,
                )
        if cliente:
            pedidos = Pedido.objects.filter(cliente=user).order_by('-fecha_creacion')
    return render(request, 'index.html', {
        'productos': productos,
        'catalogo_activo': catalogo_activo,
        'categorias': Categoria.objects.order_by('name'),
        'populares': populares,
        'promociones': promociones,
        'cliente': cliente,
        'pedidos': pedidos,
        'query': query,
        'categoria': categoria,
        'orden': orden,
        'oferta': oferta,
    })

def formulario(request):
    return render(request, 'registration/login.html')

def formulario_view(request):
    return render(request, 'registro.html') 

def registro(request):
    if request.method == 'POST':
        username = request.POST['username']
        email = request.POST['email']
        password1 = request.POST['password1']
        password2 = request.POST['password2']

        if password1 != password2:
            messages.error(request, "Las contraseñas no coinciden.")
            return render(request, 'registro.html')

        if User.objects.filter(username=username).exists():
            messages.error(request, "El nombre de usuario ya existe.")
            return render(request, 'registro.html')

        if User.objects.filter(email=email).exists():
            messages.error(request, "El correo electrónico ya está registrado.")
            return render(request, 'registro.html')

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password1,
        )
        user.is_active = True
        user.is_staff = False
        user.is_superuser = False
        user.save()

        messages.success(request, "Cuenta de cliente creada correctamente. Inicia sesión desde el portal de clientes.")
        return redirect('login_cliente')

    return render(request, 'registro.html') 

def recuperar(request):
    codigo_enviado = request.session.pop('codigo_enviado', False)
    error = request.GET.get('error', '')
    return render(request, 'recuperar.html', {'codigo_enviado': codigo_enviado, 'error': error})

def _dashboard_legacy(request):
    hoy = timezone.localdate()
    inicio_semana = hoy - timedelta(days=hoy.weekday())
    inicio_mes = hoy.replace(day=1)
    inicio_anio = hoy.replace(month=1, day=1)

    # Ventas por día (últimos 7 días)
    ventas_dia_qs = (
        Factura.objects.filter(fecha__date__gte=hoy - timedelta(days=6), estado='facturada')
        .annotate(dia=TruncDay('fecha'))
        .values('dia')
        .annotate(total=Sum('total'))
        .order_by('dia')
    )
    ventas_dia = [{'label': v['dia'].strftime('%d/%m'), 'total': float(v['total'])} for v in ventas_dia_qs]

    # Ventas por semana (últimas 4 semanas)
    ventas_semana_qs = (
        Factura.objects.filter(fecha__date__gte=hoy - timedelta(weeks=3), estado='facturada')
        .annotate(semana=TruncWeek('fecha'))
        .values('semana')
        .annotate(total=Sum('total'))
        .order_by('semana')
    )
    ventas_semana = [{'label': v['semana'].strftime('Sem %W'), 'total': float(v['total'])} for v in ventas_semana_qs]

    # Ventas por mes (últimos 12 meses)
    ventas_mes_qs = (
        Factura.objects.filter(fecha__date__gte=hoy.replace(month=1, day=1) - timedelta(days=365), estado='facturada')
        .annotate(mes=TruncMonth('fecha'))
        .values('mes')
        .annotate(total=Sum('total'))
        .order_by('mes')
    )
    ventas_mes = [{'label': v['mes'].strftime('%b %Y'), 'total': float(v['total'])} for v in ventas_mes_qs]

    # Ventas por año (últimos 5 años)
    ventas_anio_qs = (
        Factura.objects.filter(fecha__date__gte=hoy.replace(year=hoy.year-4, month=1, day=1), estado='facturada')
        .annotate(anio=TruncYear('fecha'))
        .values('anio')
        .annotate(total=Sum('total'))
        .order_by('anio')
    )
    ventas_anio = [{'label': v['anio'].strftime('%Y'), 'total': float(v['total'])} for v in ventas_anio_qs]

    audit_logs_qs = AuditLog.objects.order_by('-timestamp')[:10]
    # Procesar registros recientes para mostrar en el dashboard (misma limpieza que auditoria_completa)
    import re
    recent = []
    for log in audit_logs_qs:
        username = log.user.username if log.user else 'Anónimo'
        action = log.action
        model = log.model_name
        details = log.details or ''
        m = re.split(r'\s+con args=|\s+with args=|\s+args=', details, maxsplit=1)
        details_clean = m[0].strip() if m else details
        details_clean = re.sub(r'kwargs=\{.*\}$', '', details_clean).strip()
        if action and action.upper() == 'ACCESO':
            pretty_model = model.replace('_', ' ')
            details_display = f'Acceso a {pretty_model}'
        else:
            details_display = details_clean or action or ''
        recent.append({
            'username': username,
            'action': action,
            'model_name': model,
            'details': details_display,
            'timestamp': log.timestamp,
            'ip_address': log.ip_address,
            'user_agent': log.user_agent,
        })
    include_ip_recent = any(p['ip_address'] for p in recent)
    include_user_agent_recent = any(p['user_agent'] for p in recent)
    recent_colspan = 5 + (1 if include_ip_recent else 0) + (1 if include_user_agent_recent else 0)
    audit_logs = recent

    total_clientes = UsuarioClientes.objects.count()
    total_proveedores = Proveedores.objects.count()
    total_productos = Productos.objects.count()

    context = {
        'ventas_dia': ventas_dia,
        'ventas_semana': ventas_semana,
        'ventas_mes': ventas_mes,
        'ventas_anio': ventas_anio,
        'audit_logs': audit_logs,
        'include_ip_recent': include_ip_recent,
        'include_user_agent_recent': include_user_agent_recent,
        'recent_colspan': recent_colspan,
        'total_clientes': total_clientes,
        'total_proveedores': total_proveedores,
        'total_productos': total_productos,
    }
    return render(request, 'dashboard.html', context)

@user_passes_test(lambda u: u.is_staff, login_url='login_admin_custom')
@log_view_access
def clientes(request):
    query = request.GET.get('q', '')
    pedidos_confirmados = Pedido.objects.filter(
        cliente__email__iexact=models.OuterRef('email'),
        estado__in=('pagado', 'enviado'),
    )
    clientes_qs = UsuarioClientes.objects.annotate(
        es_comprador=models.Exists(pedidos_confirmados),
    ).order_by('-fecha_registro')
    if query:
        clientes_qs = clientes_qs.filter(
            models.Q(nombre__icontains=query) |
            models.Q(apellido__icontains=query) |
            models.Q(telefono__icontains=query) |
            models.Q(cedula__icontains=query) |
            models.Q(email__icontains=query)
        )
    paginator = Paginator(clientes_qs, 5)
    page_number = request.GET.get('page')
    clientes = paginator.get_page(page_number)

    contador_nuevo = UsuarioClientes.objects.count()
    contador_nuevo2 = UsuarioClientes.objects.filter(frecuente=True).count()
    contador_nuevo3 = UsuarioClientes.objects.filter(vip=True).count()
    contador_compradores = UsuarioClientes.objects.annotate(
        es_comprador=models.Exists(pedidos_confirmados),
    ).filter(es_comprador=True).count()

    context = {
        'racismo': 'FerreElectri PLUS | Clientes',
        'clientes': clientes,
        'clientes_nuevos': contador_nuevo,
        'compradores_confirmados': contador_compradores,
        'cliente_frecuente': contador_nuevo2,
        'cliente_vip': contador_nuevo3,
    }
    return render(request, 'clientes.html', context)

@user_passes_test(lambda u: u.is_staff, login_url='login_admin_custom')
@log_view_access
def proveedores(request):
    query = request.GET.get('q', '')
    proveedores_qs = Proveedores.objects.all().order_by('-Fecha_registro')
    if query:
        proveedores_qs = proveedores_qs.filter(
            models.Q(cedula__icontains=query) |
            models.Q(nombre__icontains=query) |
            models.Q(telefono__icontains=query) |
            models.Q(email__icontains=query)
        )
    paginator = Paginator(proveedores_qs, 5)
    page_number = request.GET.get('page')
    proveedores = paginator.get_page(page_number)
    contador_nuevo_p = Proveedores.objects.count()

    context = {
        'racismo': 'FerreElectri PLUS | Proveedores',
        'proveedores': proveedores,
        'proveedores_nuevos': contador_nuevo_p,
    }
    return render(request, 'proveedores.html', context)

@user_passes_test(lambda u: u.is_staff, login_url='login_admin_custom')
@log_view_access
def inventario(request):
    query = request.GET.get('q', '') or ''
    query = query.strip()
    productos_qs = Productos.objects.all().order_by('-Fecha_creacion')
    if query:
        lower_query = query.lower()
        month_map = {
            'enero': '01', 'febrero': '02', 'marzo': '03', 'abril': '04',
            'mayo': '05', 'junio': '06', 'julio': '07', 'agosto': '08',
            'septiembre': '09', 'setiembre': '09', 'octubre': '10',
            'noviembre': '11', 'diciembre': '12',
            'ene': '01', 'feb': '02', 'mar': '03', 'abr': '04', 'may': '05',
            'jun': '06', 'jul': '07', 'ago': '08', 'sep': '09', 'oct': '10',
            'nov': '11', 'dic': '12'
        }
        month_code = next((code for name, code in month_map.items() if name in lower_query), None)
        search_filter = (
            models.Q(Codigo__icontains=query) |
            models.Q(Descripcion__icontains=query) |
            models.Q(Precio__icontains=query) |
            models.Q(Cantidad__icontains=query) |
            models.Q(Fecha_creacion__icontains=query)
        )
        if month_code:
            search_filter |= models.Q(Fecha_creacion__contains=month_code)
        productos_qs = productos_qs.filter(search_filter)

    productos_filtrados = productos_qs.count()
    paginator = Paginator(productos_qs, 10)
    page_number = request.GET.get('page')
    productos = paginator.get_page(page_number)
    productos_totales = Productos.objects.count()
    contador_nuevo_2 = Productos.objects.filter(promocion=True).count()

    context = {
        'racismo': 'FerreElectri PLUS | Inventario',
        'productos': productos,
        'productos_totales': productos_totales,
        'productos_filtrados': productos_filtrados,
        'productos_promocion': contador_nuevo_2,
        'query': query,
    }

    return render(request, 'inventario.html', context)

@user_passes_test(lambda u: u.is_staff, login_url='login_admin_custom')
@permission_required('dashboard.view_auditlog')
def audit_logs(request):
    logs = AuditLog.objects.all().order_by('-timestamp')
    return render(request, 'audit_logs.html', {'logs': logs})

def descargar_auditoria_csv(request):
    logs = AuditLog.objects.all().order_by('-timestamp')

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="auditoria.csv"'

    writer = csv.writer(response)
    writer.writerow(['Usuario', 'Acción', 'Modelo', 'Detalles', 'Fecha'])

    for log in logs:
        writer.writerow([
            log.user.username if log.user else 'Anónimo',
            log.action,
            log.model_name,
            log.details,
            log.timestamp.strftime('%d/%m/%Y %H:%M')
        ])

    return response

def auditoria_completa(request):
    hace_7_dias = timezone.now() - timedelta(days=7)
    logs = AuditLog.objects.filter(timestamp__gte=hace_7_dias).order_by('-timestamp')
    # Preparar versión limpia de los registros para mostrar en la plantilla
    import re
    processed = []
    for log in logs:
        # Username
        username = log.user.username if log.user else 'Anónimo'
        # Acción y modelo
        action = log.action
        model = log.model_name
        # Limpiar detalles: si fue registrado por el decorador de vistas, el formato es
        # "Acceso a <viewname> con args=... kwargs=..." -> mostrar sólo "Acceso a <viewname>"
        details = log.details or ''
        m = re.split(r'\s+con args=|\s+with args=|\s+args=', details, maxsplit=1)
        details_clean = m[0].strip() if m else details
        # Más limpieza genérica: eliminar representaciones de kwargs vacíos
        details_clean = re.sub(r'kwargs=\{.*\}$', '', details_clean).strip()
        # Si la acción es ACCESO y el modelo es una función (nombre corto), presentarlo más legible
        if action and action.upper() == 'ACCESO':
            # convertir nombres tipo 'clientes' o 'ver_clientes' en 'clientes'
            pretty_model = model.replace('_', ' ')
            details_display = f'Acceso a {pretty_model}'
        else:
            details_display = details_clean or action or ''

        processed.append({
            'username': username,
            'action': action,
            'model_name': model,
            'details': details_display,
            'raw_details': details,
            'timestamp': log.timestamp,
            'ip_address': log.ip_address,
            'user_agent': log.user_agent,
        })

    # Decidir si mostrar columna IP y User Agent (sólo si hay al menos un valor no vacío)
    include_ip = any(p['ip_address'] for p in processed)
    include_user_agent = any(p['user_agent'] for p in processed)

    colspan = 5 + (1 if include_ip else 0) + (1 if include_user_agent else 0)
    return render(request, 'dashboard/auditoria_completa.html', {
        'logs': processed,
        'include_ip': include_ip,
        'include_user_agent': include_user_agent,
        'colspan': colspan,
    })

def reset_password(request):
    if request.user.is_authenticated and not request.user.is_staff:
        return HttpResponseForbidden('El restablecimiento administrativo requiere una cuenta staff.')
    if request.method == 'POST':
        codigo = request.POST.get('codigo')
        nueva_clave = request.POST.get('nueva_clave')
        nueva_clave2 = request.POST.get('nueva_clave2')

        if nueva_clave != nueva_clave2:
            messages.error(request, "Las contraseñas no coinciden.")
            return render(request, 'recuperar.html')

        messages.success(request, "¡Contraseña restablecida correctamente! Ahora puedes iniciar sesión.")
        return redirect('login')

    return render(request, 'recuperar.html', {'codigo_enviado': True})

@csrf_exempt
def solicitar_recuperacion(request):
    if request.method == 'POST':
        email = (request.POST.get('email') or '').strip().lower()
        if not email:
            return render(request, 'recuperar.html', {
                'error': 'Debes ingresar un correo válido para continuar.'
            })

        usuario = User.objects.filter(email__iexact=email).first()
        if not usuario:
            return render(request, 'recuperar.html', {'error': 'Correo no registrado'})

        codigo = get_random_string(8)
        request.session['recupera_codigo'] = codigo
        request.session['recupera_email'] = email
        request.session['recupera_usuario'] = get_recovery_display_name(usuario, email)

        html_content = render_to_string('emails/recuperacion_codigo.html', {
            'usuario': usuario,
            'codigo': codigo,
            'logo_url': 'https://tudominio.com/static/img/logo.png',
        })

        subject = '🔐 Recupera tu acceso a FerreElectri PLUS'
        from_email = settings.EMAIL_HOST_USER
        to = [email]

        msg = EmailMultiAlternatives(subject, '', from_email, to)
        msg.attach_alternative(html_content, "text/html")
        try:
            msg.send()
        except Exception as error:
            logging.getLogger(__name__).warning(
                'No se pudo enviar el correo de recuperación (%s).',
                type(error).__name__,
            )
            return render(request, 'recuperar.html', {
                'error': 'No se pudo enviar el correo de recuperación. Verifica tu conexión o la configuración SMTP.',
            })

        request.session['codigo_enviado'] = True
        return redirect('recuperar_codigo')

    return render(request, 'recuperar.html')

@ratelimit(key='ip', rate='5/m', method='POST', block=True)
def recuperar_codigo_cliente(request):
    if request.session.get('recupera_scope') == 'admin':
        return HttpResponseForbidden('Esta recuperación pertenece al portal administrativo.')
    request.session['recupera_scope'] = 'cliente'
    return _recuperar_codigo(request, 'cliente')


@ratelimit(key='ip', rate='5/m', method='POST', block=True)
def recuperar_codigo_admin(request):
    if request.session.get('recupera_scope') == 'cliente':
        return HttpResponseForbidden('Esta recuperación pertenece al portal de clientes.')
    request.session['recupera_scope'] = 'admin'
    return _recuperar_codigo(request, 'admin')


def _recuperar_codigo(request, recovery_scope):
    recovery_template = 'recuperar_codigo_cliente.html' if recovery_scope == 'cliente' else 'recuperar_codigo.html'
    recovery_url_name = 'recuperar_codigo_cliente' if recovery_scope == 'cliente' else 'recuperar_codigo_admin'
    if recovery_scope == 'admin' and request.user.is_authenticated and not request.user.is_staff:
        return HttpResponseForbidden('Esta recuperación pertenece al portal administrativo.')
    if recovery_scope == 'cliente' and request.user.is_authenticated and request.user.is_staff:
        return HttpResponseForbidden('Esta recuperación pertenece al portal de clientes.')
    context = {}
    try:
        expires_at = float(request.session.get('recupera_expira_en', 0) or 0)
    except (TypeError, ValueError):
        expires_at = 0
    if expires_at <= timezone.now().timestamp():
        _clear_recovery_session(request)
        context['error'] = 'El código venció o ya no es válido. Solicita uno nuevo.'
        return render(request, recovery_template, context)
    context['email_enmascarado'] = _mask_recovery_email(request.session.get('recupera_email', ''))
    if request.method == 'POST':
        codigo = (request.POST.get('codigo') or '').strip()
        nueva = request.POST.get('new_password1')
        nueva2 = request.POST.get('new_password2')
        stored_hash = request.session.get('recupera_codigo_hash', '')
        if not stored_hash or not check_password_hash(codigo, stored_hash):
            attempts = int(request.session.get('recupera_intentos', 0)) + 1
            request.session['recupera_intentos'] = attempts
            if attempts >= 5:
                _clear_recovery_session(request)
                context['error'] = 'Se agotaron los intentos. Solicita un código nuevo.'
                return render(request, recovery_template, context)
            context['error'] = 'Código incorrecto.'
            email = (request.session.get('recupera_email') or '').strip().lower()
            usuario = User.objects.filter(email__iexact=email).first() if email else None
            if usuario:
                request.session['recupera_usuario'] = get_recovery_display_name(usuario, email)
            context['usuario_nombre'] = get_recovery_display_name(usuario, email) if usuario else (request.session.get('recupera_usuario', '') or 'Usuario')
            return render(request, recovery_template, context)
        if not nueva or nueva != nueva2:
            context['error'] = 'Las contraseñas no coinciden o están vacías.'
            return render(request, recovery_template, context)
        email = (request.session.get('recupera_email') or '').strip().lower()
        usuario = User.objects.filter(email__iexact=email).first()
        if not usuario:
            context['error'] = 'No se encontró el usuario asociado al correo de recuperación.'
            return render(request, recovery_template, context)

        if recovery_scope == 'admin' and not (usuario.is_staff or usuario.is_superuser):
            _clear_recovery_session(request)
            context['error'] = 'El código ya no es válido. Solicita uno nuevo.'
            return render(request, recovery_template, context)
        if recovery_scope == 'cliente' and (usuario.is_staff or usuario.is_superuser):
            _clear_recovery_session(request)
            context['error'] = 'El código ya no es válido. Solicita uno nuevo.'
            return render(request, recovery_template, context)

        if usuario.check_password(nueva):
            request.session['clave_repetida'] = True
            return redirect(recovery_url_name)
        try:
            validate_password(nueva, usuario)
        except ValidationError as exc:
            context['password_errors'] = exc.messages
            return render(request, recovery_template, context)
        usuario.set_password(nueva)
        usuario.save()
        if recovery_scope == 'cliente':
            customer = Customer.objects.filter(email__iexact=email, is_active=True).first()
            if customer:
                customer.set_password(nueva)
                customer.save(update_fields=['password'])
        request.session['clave_cambiada'] = True
        _clear_recovery_session(request)
        if recovery_scope == 'cliente':
            messages.success(request, 'Contraseña actualizada correctamente. Ya puedes iniciar sesión.')
            return redirect('login_cliente')
        messages.success(request, 'Contraseña actualizada correctamente. Ya puedes iniciar sesión.')
        request.session['admin_login_unlocked_until'] = timezone.now().timestamp() + 60
        return redirect('login_admin_custom')
    context['codigo_enviado'] = request.session.pop('codigo_enviado', False)
    context['clave_cambiada'] = request.session.pop('clave_cambiada', False)
    context['clave_repetida'] = request.session.pop('clave_repetida', False)

    email = (request.session.get('recupera_email') or '').strip().lower()
    usuario = User.objects.filter(email__iexact=email).first() if email else None
    if usuario:
        request.session['recupera_usuario'] = get_recovery_display_name(usuario, email)
    context['usuario_nombre'] = get_recovery_display_name(usuario, email) if usuario else (request.session.get('recupera_usuario', '') or 'Usuario')
    return render(request, recovery_template, context)


def recuperar_codigo(request):
    """Alias legacy que conserva el flujo cliente, nunca el administrativo."""
    return recuperar_codigo_cliente(request)

def test_mail(request):
    try:
        send_mail(
            'Prueba',
            'Esto es una prueba',
            settings.EMAIL_HOST_USER,
            [settings.EMAIL_HOST_USER],
            fail_silently=False,
        )
        return HttpResponse("Correo enviado")
    except Exception as e:
        print(f"[TEST_MAIL] SMTP error: {e}")
        return HttpResponse(f"Error de envío SMTP: {type(e).__name__}: {e}", status=500)

def verificar_codigo(request):
    # Puedes personalizar el template y la lógica según tu flujo
    return render(request, 'verificar_codigo.html')

def eliminar_cliente(request, cliente_id):
    cliente = get_object_or_404(UsuarioClientes, id=cliente_id)
    facturas = Factura.objects.filter(cliente=cliente)
    if facturas.exists():
        # Usar el campo .numero de cada factura
        factura_nums = ', '.join(str(f.numero) for f in facturas)
        messages.error(request, f"No puedes eliminar este cliente porque tiene ventas asociadas. Factura(s): {factura_nums}")
        return redirect('clientes')
    cliente.delete()
    messages.success(request, "Cliente eliminado correctamente.")
    return redirect('clientes')

@csrf_exempt
def footer_contact(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            nombre = data.get('nombre', '').strip()
            email = data.get('email', '').strip()
            mensaje = data.get('mensaje', '').strip()

            if not nombre or not email or not mensaje:
                return JsonResponse({'success': False, 'error': 'Todos los campos son obligatorios.'})

            cuerpo = f"""
¡Hola equipo de FerreElectri PLUS!

Han recibido un nuevo mensaje desde el formulario de contacto del sitio web.

----------------------------------------
Datos del visitante:
Nombre: {nombre}
Correo: {email}

Mensaje enviado:
{mensaje}
----------------------------------------

Atentamente,
Sitio Web FerreElectri PLUS
https://ferreelectriplus.com/
            """

            send_mail(
                subject="Nuevo mensaje de contacto - FerreElectri PLUS",
                message=cuerpo,
                from_email=settings.EMAIL_HOST_USER,
                recipient_list=["ferreelectriplus@gmail.com"],  # Cambia por tu correo real si es necesario
                fail_silently=False,
            )
            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'error': f'Error al enviar: {str(e)}'})
    return JsonResponse({'success': False, 'error': 'Método no permitido'}, status=405)

def producto_detalle(request, codigo):
    producto = get_object_or_404(Productos, Codigo=codigo)
    productos_similares = Productos.objects.none()
    if producto.Categoria_id:
        productos_similares = Productos.objects.filter(
            Categoria_id=producto.Categoria_id,
        ).exclude(Codigo=producto.Codigo).order_by('-promocion', '-Fecha_creacion')[:8]
    return render(request, 'producto_detalle.html', {
        'producto': producto,
        'productos_similares': productos_similares,
    })


def agregar_al_carrito(request, codigo):
    logger = logging.getLogger(__name__)
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    try:
        # Usar .values() para evitar que el ORM intente leer columnas nuevas (p.ej. `presentations`)
        producto_data = Productos.objects.filter(Codigo=codigo).values('Codigo', 'Cantidad', 'Precio', 'Descripcion', 'Imagen', 'Categoria_id').first()
        if not producto_data:
            if is_ajax:
                return JsonResponse({'success': False, 'error': 'Producto no encontrado.'}, status=404)
            messages.error(request, 'Producto no encontrado.')
            return redirect('producto_detalle', codigo=codigo)

        # Validar stock mínimo usando los datos en dict
        cantidad_stock = producto_data.get('Cantidad')
        if cantidad_stock is None or cantidad_stock < 1:
            if is_ajax:
                return JsonResponse({'success': False, 'error': 'Producto no disponible.'}, status=409)
            messages.error(request, 'Producto no disponible.')
            return redirect('producto_detalle', codigo=codigo)

        # Determinar cantidad solicitada y factor de presentación (p.ej. Caja x12)
        cantidad = 1
        presentation_factor = 1
        if request.method == 'POST':
            try:
                cantidad = int(request.POST.get('cantidad', 1))
            except (TypeError, ValueError):
                cantidad = 1
            try:
                presentation_factor = int(request.POST.get('presentation_factor', 1) or 1)
            except (TypeError, ValueError):
                presentation_factor = 1
        else:
            try:
                cantidad = int(request.GET.get('cantidad', 1) or 1)
            except (TypeError, ValueError):
                cantidad = 1
            try:
                presentation_factor = int(request.GET.get('presentation_factor', 1) or 1)
            except (TypeError, ValueError):
                presentation_factor = 1

        if cantidad < 1 or presentation_factor < 1:
            if is_ajax:
                return JsonResponse({'success': False, 'error': 'Cantidad o presentación no válida.'}, status=400)
            messages.error(request, 'Cantidad o presentación no válida.')
            return redirect('producto_detalle', codigo=codigo)

        # Cantidad efectiva en unidades (ej. 1 caja x12 => 12 unidades)
        # El stock se valida por unidades físicas del producto, no por el número de cajas.
        cantidad_effectiva = cantidad * (presentation_factor or 1)
        if cantidad_effectiva > cantidad_stock and presentation_factor > 1:
            cantidad_effectiva = cantidad
        if cantidad_effectiva > cantidad_stock:
            if is_ajax:
                return JsonResponse({'success': False, 'error': 'No hay suficiente stock disponible.'}, status=409)
            messages.warning(request, f'No hay suficiente stock disponible. Stock actual: {cantidad_stock}')
            return redirect('producto_detalle', codigo=codigo)

        cliente = None
        try:
            cliente = get_current_cliente(request)
        except Exception as e:
            # No debe interrumpir el flujo: caeremos a carrito anónimo
            logger.exception('Error obteniendo cliente desde la sesión: %s', e)

        producto = None
        if request.user.is_authenticated:
            producto = Productos.objects.only('Codigo', 'Cantidad', 'Precio', 'Descripcion').filter(Codigo=codigo).first()
            if not producto:
                if is_ajax:
                    return JsonResponse({'success': False, 'error': 'Producto no encontrado.'}, status=404)
                messages.error(request, 'Producto no encontrado.')
                return redirect('producto_detalle', codigo=codigo)

        # Usuario anónimo: manejar carrito en sesión
        if not cliente:
            try:
                # Para carrito anónimo usamos la key del producto desde producto_data
                # Para añadir al carrito anónimo actualizamos la sesión sin instanciar Productos
                anon_cart = request.session.get('anon_cart', {}) or {}
                anon_cart_meta = request.session.get('anon_cart_meta', {}) or {}
                product_key = str(producto_data.get('Codigo'))
                current_qty = int(anon_cart.get(product_key, 0))
                anon_cart[product_key] = min(current_qty + cantidad_effectiva, cantidad_stock)
                # Guardar metadata de presentación para carritos anónimos
                anon_cart_meta.setdefault(product_key, {})
                anon_cart_meta[product_key]['presentacion_factor'] = int(presentation_factor or 1)
                anon_cart_meta[product_key]['presentacion_type'] = (request.POST.get('presentation_type') or '') if request.method == 'POST' else (request.GET.get('presentation_type') or '')
                request.session['anon_cart'] = anon_cart
                request.session['anon_cart_meta'] = anon_cart_meta
                request.session.modified = True
                anon_cart = request.session.get('anon_cart', {}) or {}
                total_count = len(anon_cart)
                total = 0.0
                # Evitar consultas N+1: obtener precios en lote
                product_codes = [str(k) for k in anon_cart.keys()]
                precios = {p.Codigo: (p.Precio or 0) for p in Productos.objects.filter(Codigo__in=product_codes)}
                for product_code, value in anon_cart.items():
                    precio = precios.get(str(product_code), 0)
                    total += float(precio) * int(value)
                if is_ajax:
                    return JsonResponse({
                        'success': True,
                        'quantity': int(anon_cart.get(str(producto_data.get('Codigo')), cantidad_effectiva)),
                        'count': total_count,
                        'total': float(total),
                    })
                messages.info(request, 'Se agregó el producto a tu carrito temporal. Inicia sesión o regístrate para continuar.')
                return redirect(reverse('login_cliente') + f'?next={reverse("carrito")}')
            except Exception as e:
                logger.exception('Error agregando producto al carrito anónimo: %s', e)
                if is_ajax:
                    return JsonResponse({'success': False, 'error': 'Error al agregar al carrito.'}, status=500)
                messages.error(request, 'Error al agregar al carrito.')
                return redirect('producto_detalle', codigo=codigo)

        # Cliente autenticado: persistir en DB
        try:
            carrito, _ = Carrito.objects.get_or_create(cliente=cliente)
            item, created = CarritoItem.objects.get_or_create(carrito=carrito, producto=producto)
            # Sumar cantidades de forma segura
            nueva_cantidad = (item.cantidad or 0) + cantidad_effectiva if not created else cantidad_effectiva
            item.cantidad = min(nueva_cantidad, producto.Cantidad)
            if item.cantidad >= producto.Cantidad:
                messages.warning(request, 'La cantidad se ajustó al stock disponible.')
            # Guardar información de presentación seleccionada
            try:
                item.presentacion_factor = int(presentation_factor or 1)
            except Exception:
                item.presentacion_factor = 1
            item.presentacion_type = (request.POST.get('presentation_type') or '') if request.method == 'POST' else (request.GET.get('presentation_type') or '')
            item.save()

            if is_ajax:
                total_count = carrito.items.count()
                total = sum((getattr(ci.producto, 'Precio', 0) or 0) * ci.cantidad for ci in carrito.items.select_related('producto'))
                return JsonResponse({'success': True, 'quantity': item.cantidad, 'count': total_count, 'total': float(total)})

            messages.success(request, f'Producto agregado al carrito: {getattr(producto, "Descripcion", producto.__class__.__name__)} (x{item.cantidad})')
            return redirect('carrito')
        except Exception as e:
            logger.exception('Error al persistir item en carrito: %s', e)
            if is_ajax:
                return JsonResponse({'success': False, 'error': 'Error interno al agregar al carrito.'}, status=500)
            messages.error(request, 'Error interno al agregar al carrito.')
            return redirect('producto_detalle', codigo=codigo)

    except Exception as e:
        # Captura final por seguridad para evitar 500s con stacktrace.
        logging.getLogger(__name__).exception('Error no controlado en agregar_al_carrito: %s', e)
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Error inesperado al procesar la solicitud.'}, status=500)
        messages.error(request, 'Error inesperado. Intenta nuevamente más tarde.')
        return redirect('producto_detalle', codigo=codigo)


@redirect_staff_to_admin_view
def carrito(request):
    cliente = get_current_cliente(request)
    checkout_user = request.user
    checkout_profile = getattr(checkout_user, 'perfil_cliente', None) if getattr(checkout_user, 'is_authenticated', False) else None
    items = []
    total = 0
    carrito = None

    if cliente:
        carrito, _ = Carrito.objects.get_or_create(cliente=cliente)
        items = list(carrito.items.select_related('producto'))
        total = sum(item.subtotal() for item in items)
    else:
        anon_cart = request.session.get('anon_cart', {}) or {}
        product_codes = [str(pid) for pid in anon_cart.keys()]
        productos_map = {p.Codigo: p for p in Productos.objects.filter(Codigo__in=product_codes)}
        for codigo, qty in anon_cart.items():
            try:
                cantidad = int(qty)
            except Exception:
                continue
            producto = productos_map.get(str(codigo))
            if not producto:
                continue
            subtotal = (producto.Precio or 0) * cantidad
            # Adjuntar metadata de presentación si existe
            anon_cart_meta = request.session.get('anon_cart_meta', {}) or {}
            meta = anon_cart_meta.get(str(codigo), {})
            obj = SimpleNamespace(id=None, producto=producto, cantidad=cantidad, subtotal=subtotal)
            obj.presentacion_factor = int(meta.get('presentacion_factor') or 1)
            obj.presentacion_type = meta.get('presentacion_type') or ''
            items.append(obj)
        total = sum(
            (item.subtotal() if callable(getattr(item, 'subtotal', None)) else getattr(item, 'subtotal', 0))
            for item in items
        )

    productos = Productos.objects.filter(Cantidad__gt=0).order_by('-Fecha_creacion')[:20]

    if not cliente and not items:
        messages.info(request, 'Tu carrito está vacío. Agrega productos para comenzar.')

    return render(request, 'carrito.html', {
        'carrito': carrito,
        'items': items,
        'total': total,
        'productos': productos,
        'cliente': cliente,
        'checkout_profile': {
            'nombre': getattr(checkout_user, 'first_name', '') or '',
            'apellido': getattr(checkout_user, 'last_name', '') or '',
            'razon_social': getattr(checkout_profile, 'razon_social', '') or '',
            'cedula_rif': getattr(checkout_profile, 'cedula_rif', '') or (cliente.cedula if cliente else ''),
            'telefono': getattr(checkout_profile, 'telefono', '') or (cliente.telefono if cliente else ''),
            'direccion': getattr(checkout_profile, 'direccion', '') or (cliente.direccion if cliente else ''),
            'email': getattr(checkout_user, 'email', '') or (cliente.email if cliente else ''),
        },
        'is_anonymous_cart': not cliente,
    })


@require_POST
def eliminar_item_carrito(request, item_id):
    cliente = get_current_cliente(request)
    if not cliente and isinstance(request.user, User) and request.user.is_authenticated:
        cliente = Cliente.objects.filter(user=request.user).first()
        if not cliente and request.user.email:
            cliente = Cliente.objects.filter(email__iexact=request.user.email).first()
    if not cliente:
        return HttpResponseForbidden('No tienes permiso para modificar este carrito.')

    item = get_object_or_404(CarritoItem, id=item_id, carrito__cliente=cliente)
    item.delete()
    messages.info(request, "Producto eliminado del carrito.")
    return redirect('carrito')


def _importe_checkout(valor):
    return Decimal(str(valor or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _calcular_impuesto_linea(base, alicuota):
    return _importe_checkout(Decimal(str(base)) * Decimal(str(alicuota or 0)) / Decimal('100'))


def _calcular_totales_checkout(items):
    subtotal = Decimal('0.00')
    iva_total = Decimal('0.00')
    for item in items:
        producto = item.producto
        base = _importe_checkout(Decimal(str(producto.Precio or 0)) * int(item.cantidad))
        tasa = Decimal(str(producto.iva or 0))
        iva_linea = _calcular_impuesto_linea(base, tasa)
        item.iva_rate = tasa
        item.iva_monto = iva_linea
        item.total_con_iva = base + iva_linea
        subtotal += base
        iva_total += iva_linea
    return subtotal, iva_total, subtotal + iva_total


def create_order_with_locked_stock(user_obj, items, metodo='PAGO_MOVIL', referencia='', gateway_payload=None, datos_envio=None):
    """Crea un pedido pendiente y reserva existencias sin descontarlas todavía."""
    with transaction.atomic():
        locked_products = {}

        for item in sorted(items, key=lambda cart_item: str(cart_item.producto.Codigo)):
            product = Productos.objects.select_for_update().get(pk=item.producto.Codigo)
            reserved_quantity = PedidoItem.objects.filter(
                producto=product,
                pedido__estado='pendiente',
                pedido__stock_descontado=False,
            ).aggregate(total=Sum('cantidad'))['total'] or 0
            if product.Cantidad - reserved_quantity < item.cantidad:
                raise ValueError(
                    f'Stock insuficiente para {product.Descripcion}. '
                    f'Disponible para reservar: {product.Cantidad - reserved_quantity}.'
                )
            locked_products[product.Codigo] = product

        subtotal = Decimal('0.00')
        iva_total = Decimal('0.00')
        for item in items:
            product = locked_products[item.producto.Codigo]
            base = _importe_checkout(Decimal(str(product.Precio or 0)) * int(item.cantidad))
            tasa = Decimal(str(product.iva or 0))
            subtotal += base
            iva_total += _calcular_impuesto_linea(base, tasa)
        total = subtotal + iva_total
        pedido = Pedido.objects.create(
            cliente=user_obj,
            total=total,
            estado='pendiente',
            estado_operativo='pendiente_pago',
            stock_descontado=False,
        )
        if datos_envio:
            envio = Envio.objects.create(
                pedido=pedido,
                estado='no_preparado',
                nombre_destinatario=datos_envio.get('nombre_destinatario', '')[:180],
                telefono=datos_envio.get('telefono', '')[:30],
                direccion=datos_envio.get('direccion', '')[:500],
            )
            EnvioEvento.objects.create(
                envio=envio,
                estado_nuevo=envio.estado,
                actor=user_obj,
                descripcion='Datos de entrega capturados al confirmar el pedido.',
            )

        for item in items:
            product = locked_products[item.producto.Codigo]
            PedidoItem.objects.create(
                pedido=pedido,
                producto=product,
                cantidad=item.cantidad,
                precio=product.Precio,
                iva=product.iva,
            )

        gateway_payload = gateway_payload or {}
        payment_reference = (referencia or f'FE-{pedido.id}').strip()[:200]
        if metodo == 'BINANCE':
            payment_reference = str(
                gateway_payload.get('orderId') or f'BINANCE-{pedido.id}'
            ).strip()[:200]
        gateway_reference = payment_reference
        pago = Pago.objects.create(
            pedido=pedido,
            metodo=metodo,
            referencia=payment_reference,
            monto=total,
            estado='pendiente',
            gateway=metodo,
            gateway_reference=gateway_reference,
            gateway_payload=json.dumps(gateway_payload, ensure_ascii=False, default=str)[:4000],
            gateway_status='pending',
            observaciones='Pedido creado desde checkout seguro.',
        )

    return pedido, total, pago


@ratelimit(key='ip', rate='10/m', method='POST', block=True)
@ensure_csrf_cookie
def checkout(request):
    cliente = get_current_cliente(request)

    if request.user.is_authenticated and not request.user.is_staff and not request.user.is_superuser:
        perfil = getattr(request.user, 'perfil_cliente', None)
        cedula = str(getattr(perfil, 'cedula_rif', '') or '').strip()
        datos_fiscales_completos = all((
            request.user.first_name,
            request.user.last_name,
            request.user.email,
            perfil,
            cedula,
            str(getattr(perfil, 'telefono', '') or '').strip(),
            str(getattr(perfil, 'direccion', '') or '').strip(),
        ))
        if not datos_fiscales_completos:
            messages.info(request, 'Completa tus datos de identificación y domicilio fiscal para continuar con la compra.')
            return redirect('completar_datos_facturacion')

    # Obtener items desde carrito (autenticado) o desde session anon
    if cliente:
        carrito, _ = Carrito.objects.get_or_create(cliente=cliente)
        items = list(carrito.items.select_related('producto'))
    else:
        anon_cart = request.session.get('anon_cart', {}) or {}
        items = []
        product_codes = [str(pid) for pid in anon_cart.keys()]
        productos_map = {p.Codigo: p for p in Productos.objects.filter(Codigo__in=product_codes)}
        for codigo, qty in anon_cart.items():
            try:
                cantidad = int(qty)
            except Exception:
                continue
            producto = productos_map.get(str(codigo))
            if not producto:
                continue
            subtotal = (producto.Precio or 0) * cantidad
            # Adjuntar metadata de presentación si existe
            anon_cart_meta = request.session.get('anon_cart_meta', {}) or {}
            meta = anon_cart_meta.get(str(codigo), {})
            obj = SimpleNamespace(id=None, producto=producto, cantidad=cantidad, subtotal=subtotal)
            obj.presentacion_factor = int(meta.get('presentacion_factor') or 1)
            obj.presentacion_type = meta.get('presentacion_type') or ''
            items.append(obj)

    if not items:
        messages.error(request, "Tu carrito está vacío.")
        return redirect('carrito')

    subtotal, iva_total, total = _calcular_totales_checkout(items)

    checkout_method = 'PAGO_MOVIL'

    def render_checkout_errors(errors, payment_form=None):
        return render(request, 'checkout.html', {
            'items': items,
            'subtotal': subtotal,
            'iva_total': iva_total,
            'total': total,
            'cliente': cliente,
            'payment_form': payment_form,
            'checkout_method': checkout_method,
            'checkout_post_data': {
                'telefono': request.POST.get('telefono', ''),
                'direccion': request.POST.get('direccion', ''),
                'referencia': request.POST.get('referencia', ''),
            },
            'checkout_errors': errors,
        })

    # Si es POST intentamos crear el pedido (confirmación)
    if request.method == 'POST':
        # Requerir cliente (autenticado o visitante en sesión) al confirmar
        if not cliente:
            cliente_id = request.session.get('cliente_id')
            if cliente_id:
                cliente = Cliente.objects.filter(id=cliente_id).first()
        if not cliente:
            return redirect(reverse('login_cliente') + f"?next={request.path}")
        referencia = request.POST.get('referencia', '').strip()
        telefono = request.POST.get('telefono', '').strip()
        direccion = request.POST.get('direccion', '').strip()
        metodo = (request.POST.get('metodo') or '').strip().upper()
        checkout_method = metodo or 'PAGO_MOVIL'
        telephone_digits = re.sub(r'\D', '', telefono)
        shipping_errors = []
        if len(telephone_digits) < 7 or len(telephone_digits) > 15:
            shipping_errors.append('El teléfono debe contener entre 7 y 15 dígitos.')
        if len(direccion.strip()) < 5:
            shipping_errors.append('La dirección de entrega debe contener al menos 5 caracteres.')
        if shipping_errors:
            return render_checkout_errors(shipping_errors)
        if not metodo:
            return render_checkout_errors(['Selecciona un método de pago antes de continuar.'])

        allowed_methods = {'PAGO_MOVIL', 'BINANCE', 'PAYPAL'}
        if metodo not in allowed_methods:
            return render_checkout_errors(['El método de pago seleccionado no es válido.'])
        banco = ''
        cedula_pagador = ''
        capture = None
        if metodo == 'PAGO_MOVIL':
            payment_form = PagoMovilCheckoutForm(request.POST, request.FILES)
            if not payment_form.is_valid():
                return render_checkout_errors(
                    [error for field_errors in payment_form.errors.values() for error in field_errors],
                    payment_form,
                )
            banco = payment_form.cleaned_data['banco']
            cedula_pagador = payment_form.cleaned_data['cedula_pagador']
            referencia = payment_form.cleaned_data['referencia']
            capture = payment_form.cleaned_data['capture']
        elif metodo == 'PAYPAL':
            payment_form = PagoManualForm(request.POST, request.FILES)
            if not payment_form.is_valid():
                return render_checkout_errors(
                    [error for field_errors in payment_form.errors.values() for error in field_errors],
                    payment_form,
                )
            referencia = payment_form.cleaned_data['referencia']
            capture = payment_form.cleaned_data['comprobante']

        # Asegurarnos de que `Pedido.cliente` reciba una instancia de `User`.
        # Si `cliente` es el modelo Cliente (visitante), enlazamos/creamos un User.
        user_obj = None
        if hasattr(cliente, 'user') and cliente.user:
            user_obj = cliente.user
        else:
            # Intentar buscar un User por email
            if getattr(cliente, 'email', None):
                user_obj = User.objects.filter(email__iexact=cliente.email).first()
            if not user_obj:
                # Crear un usuario de respaldo para enlazar el pedido
                random_pw = get_random_string(16)
                username_base = (cliente.email or 'guest').split('@')[0]
                username = username_base
                # Evitar colisiones de username
                counter = 0
                while User.objects.filter(username=username).exists():
                    counter += 1
                    username = f"{username_base}{counter}"
                user_obj = User.objects.create_user(username=username, email=(cliente.email or ''), password=random_pw)
                user_obj.is_active = True
                user_obj.save()
            try:
                cliente.user = user_obj
                cliente.save()
            except Exception:
                pass

        # Actualiza el perfil de contacto sin almacenar secretos de pago.
        if telefono or direccion:
            cliente.telefono = telefono[:20]
            cliente.direccion = direccion[:255]
            cliente.save(update_fields=['telefono', 'direccion'])
        gateway_payload = {}
        if metodo == 'BINANCE':
            gateway_payload = {
                'orderId': f'BINANCE-{get_random_string(24)}',
                'amount': str(total),
                'currency': 'USDT',
                'description': f'Compra FerreElectri PLUS #{user_obj.pk}',
                'timestamp': int(time.time() * 1000),
                'returnUrl': request.build_absolute_uri(reverse('cliente_panel')),
                'notifyUrl': request.build_absolute_uri(reverse('binance_webhook')),
            }
            gateway_payload['signature'] = settings.BUILD_BINANCE_SIGNATURE(gateway_payload)

        try:
            pedido, total, pago = create_order_with_locked_stock(
                user_obj,
                items,
                metodo=metodo,
                referencia=referencia,
                gateway_payload=gateway_payload,
                datos_envio={
                    'nombre_destinatario': (
                        user_obj.get_full_name().strip()
                        or getattr(cliente, 'nombre', '')
                        or user_obj.username
                    ),
                    'telefono': telefono,
                    'direccion': direccion,
                },
            )
        except ValueError as stock_error:
            messages.error(request, str(stock_error))
            return redirect('carrito')

        payment_reference = (
            pago.gateway_reference if metodo == 'BINANCE' else referencia
        )[:200]
        pago.referencia = payment_reference
        pago.numero_referencia = referencia[:100] if metodo == 'PAGO_MOVIL' else ''
        pago.banco_origen = banco
        pago.cedula_pagador = cedula_pagador
        pago.estado = 'en_revision' if capture else 'pendiente'
        pago.gateway_reference = pago.gateway_reference or payment_reference
        pago.gateway_payload = json.dumps(gateway_payload, ensure_ascii=False, default=str)[:4000]
        if capture:
            pago.comprobante = capture
        if metodo == 'BINANCE':
            pago.gateway_status = 'pending'
        payment_update_fields = [
            'referencia', 'numero_referencia', 'banco_origen', 'cedula_pagador', 'estado',
            'gateway_reference', 'gateway_payload', 'gateway_status',
        ]
        if capture:
            payment_update_fields.append('comprobante')
        pago.save(update_fields=payment_update_fields)

        if metodo == 'PAGO_MOVIL':
            send_telegram_order_alert(
                pedido,
                {'banco': banco, 'cedula': cedula_pagador, 'referencia': referencia},
            )

        # Import local para evitar ciclos entre vistas, modelos y tareas Celery.
        from .tasks import send_order_confirmation_email

        # Encola el email después de guardar el pedido para liberar el hilo HTTP.
        try:
            send_order_confirmation_email.delay(pedido.pk)
        except Exception:
            # El pedido no falla si el broker está temporalmente no disponible.
            pass

        request.session['checkout_method'] = metodo
        request.session['checkout_referencia'] = referencia
        request.session.modified = True

        # Si había un carrito asociado (usuario), limpiar sus items
        if cliente and hasattr(carrito, 'items'):
            try:
                carrito.items.all().delete()
            except Exception:
                pass

        # Marcar pago pendiente y redirigir al panel del cliente (mejor UX)
        request.session['pago_pendiente'] = pedido.id
        request.session.modified = True
        if metodo == 'PAGO_MOVIL':
            messages.success(
                request,
                f'Pedido #{pedido.id} recibido. El comprobante está pendiente de revisión; '
                'la factura se generará después de que el administrador apruebe el pago.',
            )
        else:
            messages.success(
                request,
                f'Pedido #{pedido.id} creado y pendiente de confirmación del pago. '
                'La factura se generará después de verificarlo.',
            )
        return redirect('cliente_panel')

    # GET -> mostrar resumen y botón Confirmar (para anónimos abre modal)
    return render(request, 'checkout.html', {
        'items': items,
        'subtotal': subtotal,
        'iva_total': iva_total,
        'total': total,
        'cliente': cliente,
        'payment_form': PagoMovilCheckoutForm(),
        'checkout_method': checkout_method,
        'checkout_post_data': {'telefono': '', 'direccion': '', 'referencia': ''},
    })


@csrf_exempt
def binance_webhook(request):
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'Método no permitido.'}, status=405)

    signature = request.META.get('HTTP_X_BINANCEPAY_SIGNATURE', '')
    secret = getattr(settings, 'BINANCE_SECRET_KEY', '') or os.environ.get('BINANCE_SECRET_KEY', '')
    if not secret:
        return JsonResponse({'ok': False, 'error': 'Binance no está configurado en este servidor.'}, status=503)

    if not signature or not settings.VERIFY_BINANCE_SIGNATURE(request.body, signature, secret):
        return JsonResponse({'ok': False, 'error': 'Firma inválida.'}, status=403)

    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'error': 'Payload inválido.'}, status=400)

    order_reference = payload.get('orderId') or payload.get('order_id') or ''
    pago = Pago.objects.filter(gateway_reference=order_reference).first()
    if not pago:
        return JsonResponse({'ok': False, 'error': 'Pago no encontrado.'}, status=404)

    status = str(payload.get('status', '')).upper()
    is_verified = status in {'PAID', 'SUCCESS', 'COMPLETED'}
    if is_verified:
        try:
            amount = Decimal(str(payload.get('amount')))
        except Exception:
            return JsonResponse({'ok': False, 'error': 'El webhook no incluye un monto válido.'}, status=400)
        if amount != pago.monto:
            return JsonResponse({'ok': False, 'error': 'El monto recibido no coincide con el pedido.'}, status=400)

    pago.gateway_status = status or 'unknown'
    pago.gateway_payload = json.dumps(payload, ensure_ascii=False, default=str)[:4000]
    pago.verificado = is_verified
    pago.estado = 'confirmado' if pago.verificado else 'pendiente'
    pago.save(update_fields=['gateway_status', 'gateway_payload', 'verificado', 'estado'])

    if pago.verificado:
        factura, error = _approve_pending_order(pago.pedido_id, pago.id)
        if error:
            return JsonResponse({'ok': False, 'error': error}, status=409)

    return JsonResponse({'ok': True, 'status': pago.gateway_status})


def _create_invoice_for_paid_order(pedido):
    """Crear la factura asociada a un pedido pagado en una transacción atómica."""
    if Factura.objects.filter(pedido=pedido).exists():
        return Factura.objects.get(pedido=pedido)

    with transaction.atomic():
        if Factura.objects.filter(pedido=pedido).exists():
            return Factura.objects.get(pedido=pedido)

        user = pedido.cliente
        cliente_profile = Cliente.objects.filter(user=user).first()
        cliente_nombre = cliente_profile.nombre if cliente_profile else (user.get_full_name() or user.username)
        cliente_email = user.email or ''
        perfil = PerfilCliente.objects.filter(user=user).first()

        usuario_cliente = UsuarioClientes.objects.filter(email__iexact=cliente_email).first()
        if not usuario_cliente:
            usuario_cliente = UsuarioClientes.objects.create(
                nombre=cliente_nombre[:25],
                apellido=(user.last_name or 'Cliente')[:25],
                telefono=(cliente_profile.telefono if cliente_profile else '')[:25],
                cedula=(perfil.cedula_rif if perfil and perfil.cedula_rif else f'AUTO{pedido.id:08d}')[:12],
                direccion=(perfil.direccion if perfil else (cliente_profile.direccion if cliente_profile else '')),
                email=cliente_email[:35] or f'cliente{pedido.id}@local.invalid',
                fecha_nacimiento=timezone.now().date(),
            )

        order_items = list(pedido.items.select_related('producto'))
        subtotal = Decimal('0.00')
        iva = Decimal('0.00')
        for item in order_items:
            base = _importe_checkout(Decimal(str(item.precio or 0)) * int(item.cantidad))
            subtotal += base
            iva += _calcular_impuesto_linea(base, item.iva)
        total = subtotal + iva
        factura = Factura.objects.create(
            pedido=pedido,
            cliente=usuario_cliente,
            total=total,
            subtotal=subtotal,
            iva=iva,
            moneda='Bs.',
            estado='facturada',
            rif=(perfil.cedula_rif if perfil else '') or '',
            direccion_fiscal=(perfil.direccion if perfil else '') or '',
            razon_social=(perfil.razon_social if perfil and perfil.razon_social else cliente_nombre),
        )

        for item in order_items:
            DetalleFactura.objects.create(
                factura=factura,
                producto=item.producto,
                cantidad=item.cantidad,
                precio=item.precio,
                costo_unitario=item.producto.Costo or Decimal('0.00'),
                iva=item.iva,
            )

        pedido.estado = 'pagado'
        pedido.estado_operativo = 'confirmado'
        pedido.requiere_revision_operativa = False
        pedido.save(update_fields=['estado', 'estado_operativo', 'requiere_revision_operativa'])
        envio, creado = Envio.objects.get_or_create(
            pedido=pedido,
            defaults={
                'estado': 'no_preparado',
                'requiere_revision': True,
                'observaciones': 'Pedido histórico sin datos de entrega congelados; requiere verificación.',
            },
        )
        if creado:
            EnvioEvento.objects.create(
                envio=envio,
                estado_nuevo=envio.estado,
                descripcion='Envío histórico creado al confirmar el pago.',
            )

        PedidoArchivado.objects.create(
            original=pedido,
            cliente_nombre=cliente_nombre,
            cliente_email=cliente_email,
            total=pedido.total,
        )

    return factura


def _validate_reserved_order_stock(pedido):
    if pedido.stock_descontado:
        return

    items = list(pedido.items.order_by('producto_id'))
    for item in items:
        if not item.producto_id:
            raise ValueError('El pedido contiene un producto que ya no existe.')
        product = Productos.objects.select_for_update().get(pk=item.producto_id)
        reserved_elsewhere = PedidoItem.objects.filter(
            producto=product,
            pedido__estado='pendiente',
            pedido__stock_descontado=False,
        ).exclude(pedido=pedido).aggregate(total=Sum('cantidad'))['total'] or 0
        available = product.Cantidad - reserved_elsewhere
        if available < item.cantidad:
            raise ValueError(
                f'Stock insuficiente para aprobar {product.Descripcion}. '
                f'Disponible después de otras reservas: {max(available, 0)}.'
            )


def _restore_deducted_order_stock(pedido, user):
    if not pedido.stock_descontado:
        return

    for item in pedido.items.order_by('producto_id'):
        if not item.producto_id:
            continue
        registrar_movimiento(
            item.producto_id,
            'entrada',
            item.cantidad,
            f'Reverso de pedido cancelado #{pedido.id}',
            user,
        )

    pedido.stock_descontado = False
    pedido.save(update_fields=['stock_descontado'])


def _payment_has_manual_evidence(pago):
    if pago.verificado:
        return True
    if pago.metodo == 'PAGO_MOVIL':
        return bool(
            pago.comprobante
            and pago.banco_origen
            and pago.cedula_pagador
            and pago.numero_referencia
        )
    return bool(pago.comprobante and (pago.numero_referencia or pago.referencia))


def _approve_pending_order(pedido_id, payment_id=None):
    try:
        with transaction.atomic():
            pedido = Pedido.objects.select_for_update().get(pk=pedido_id)
            existing_invoice = Factura.objects.filter(pedido=pedido).first()
            if pedido.estado in {'pagado', 'procesando'} and existing_invoice:
                return existing_invoice, ''
            if pedido.estado != 'pendiente':
                return None, 'Solo se pueden aprobar pedidos pendientes.'

            payments = pedido.pagos.select_for_update().order_by('-creado', '-id')
            pago = payments.filter(pk=payment_id).first() if payment_id else payments.first()
            if not pago:
                return None, 'El pedido no tiene un pago para revisar.'
            if not _payment_has_manual_evidence(pago):
                return None, 'Falta un comprobante válido y los datos necesarios para verificar el pago.'

            pago.verificado = True
            pago.estado = 'confirmado'
            pago.save(update_fields=['verificado', 'estado'])
            _validate_reserved_order_stock(pedido)
            factura = _create_invoice_for_paid_order(pedido)
            pedido.stock_descontado = True
            pedido.save(update_fields=['stock_descontado'])
    except ValueError as error:
        return None, str(error)

    return factura, ''


def binance_checkout(request, pedido_id):
    """Inicia una transacción Binance Pay con firma HMAC en entorno configurado."""
    pedido = get_object_or_404(Pedido, id=pedido_id)
    if request.user.is_authenticated:
        if request.user.is_staff or pedido.cliente_id == request.user.id:
            pass
        else:
            return HttpResponseForbidden('No tienes permiso para pagar este pedido.')
    else:
        return redirect(reverse('login_cliente') + f"?next={request.get_full_path()}")

    if not getattr(settings, 'BINANCE_API_KEY', '') or not getattr(settings, 'BINANCE_SECRET_KEY', ''):
        messages.error(request, 'Binance Pay no está configurado en este servidor. Define BINANCE_API_KEY y BINANCE_SECRET_KEY en variables de entorno.')
        return redirect('mis_pedidos')

    order_id = f'BINANCE-{pedido.id}-{int(time.time() * 1000)}'
    payload = {
        'orderId': order_id,
        'amount': str(pedido.total),
        'currency': 'USDT',
        'description': f'Pedido #{pedido.id}',
        'notifyUrl': request.build_absolute_uri(reverse('binance_webhook')),
        'returnUrl': request.build_absolute_uri(reverse('mis_pedidos')),
    }
    payload['signature'] = settings.BUILD_BINANCE_SIGNATURE(payload)

    Pago.objects.create(
        pedido=pedido,
        metodo='BINANCE',
        monto=pedido.total,
        referencia=order_id,
        gateway='BINANCE',
        gateway_reference=order_id,
        gateway_payload=json.dumps(payload, ensure_ascii=False, default=str)[:4000],
        gateway_status='pending',
        estado='pendiente',
        observaciones='Pago iniciado con Binance Pay.',
    )

    return render(request, 'binance_checkout.html', {'pedido': pedido, 'payload': payload})


def pagar_pedido(request, pedido_id):
    """Permite pagar un pedido usando un Cliente autenticado o un visitante
    guardado en sesión (`cliente_id`). Si no hay cliente válido, redirige
    al flujo de login/registro de cliente. Staff puede acceder a cualquier pedido.
    """
    pedido = None
    if request.user.is_staff:
        pedido = Pedido.objects.filter(id=pedido_id).first()
    else:
        cliente = get_current_cliente(request)
        if not cliente:
            return redirect(reverse('login_cliente') + f"?next={request.get_full_path()}")
        cliente_user = getattr(cliente, 'user', None)
        if cliente_user:
            pedido = Pedido.objects.filter(id=pedido_id, cliente=cliente_user).first()
        else:
            if getattr(cliente, 'email', None):
                user_by_email = User.objects.filter(email__iexact=cliente.email).first()
                if user_by_email:
                    pedido = Pedido.objects.filter(id=pedido_id, cliente=user_by_email).first()

    if not pedido:
        return HttpResponseForbidden('No tienes permiso para pagar este pedido.')

    initial_method = request.session.pop('checkout_method', None)
    initial_referencia = request.session.pop('checkout_referencia', '')
    request.session.modified = True

    if request.method == 'POST':
        metodo = (request.POST.get('metodo') or '').strip().upper()
        if metodo == 'STRIPE':
            return redirect('stripe_checkout', pedido_id=pedido.id)
        payment_data = request.POST.copy()
        payment_data['metodo'] = metodo
        payment_form = PagoManualForm(payment_data, request.FILES)
        if not payment_form.is_valid():
            for errors in payment_form.errors.values():
                for error in errors:
                    messages.error(request, error)
            return redirect('pagar_pedido', pedido_id=pedido.id)

        pago = payment_form.save(commit=False)
        pago.pedido = pedido
        pago.monto = pedido.total
        pago.numero_referencia = payment_form.cleaned_data['referencia'][:100]
        pago.verificado = False
        pago.estado = 'en_revision'
        pago.save()
        messages.success(request, 'Comprobante enviado. El administrador confirmará el pago en breve.')
        request.session['pago_pendiente'] = pedido.id
        request.session.modified = True
        return redirect('cliente_panel')

    return render(request, 'pagar_pedido.html', {
        'pedido': pedido,
        'initial_method': initial_method,
        'initial_referencia': initial_referencia,
    })


@user_passes_test(lambda u: u.is_staff, login_url='login_admin_custom')
@permission_required('dashboard.verify_order_payments', raise_exception=True)
def confirmar_pago_admin(request, payment_id):
    if request.method != 'POST':
        return HttpResponseForbidden('Método no permitido.')
    pago = get_object_or_404(Pago, id=payment_id)
    factura, error = _approve_pending_order(pago.pedido_id, pago.id)
    if error:
        messages.error(request, error)
        return redirect(reverse('historial_pedidos_global'))
    messages.success(request, f'Pago confirmado y factura #{factura.numero} generada.')
    return redirect(reverse('historial_pedidos_global'))


@redirect_staff_to_admin_view
@login_required(login_url='login_cliente')
def ver_pagos_pedido(request, pedido_id):
    user = get_authenticated_django_user(request)
    if not user or user.is_staff or user.is_superuser:
        return HttpResponseForbidden('No tienes permiso para consultar estos pagos.')
    pedido = get_object_or_404(Pedido.objects.filter(cliente=user), id=pedido_id)
    pagos = pedido.pagos.order_by('-creado')
    return render(request, 'ver_pagos.html', {'pedido': pedido, 'pagos': pagos})


@staff_member_required(login_url='login_admin_custom')
@permission_required('dashboard.view_payment_evidence', raise_exception=True)
def descargar_comprobante_admin(request, filename=None, payment_id=None):
    pago = (
        get_object_or_404(Pago, pk=payment_id)
        if payment_id is not None
        else get_object_or_404(Pago, comprobante=f'comprobantes/{filename}')
    )
    if not pago.comprobante:
        return HttpResponse('Comprobante no disponible.', status=404)
    response = FileResponse(
        pago.comprobante.open('rb'),
        as_attachment=True,
        filename=os.path.basename(pago.comprobante.name),
    )
    response['X-Content-Type-Options'] = 'nosniff'
    return response


def _contexto_factura_pdf(factura):
    detalles = list(factura.detalles.select_related('producto'))
    for detalle in detalles:
        detalle.calculado_subtotal = detalle.total_linea
    resumen_impuestos = factura.resumen_tributario(detalles)
    base_imponible = sum((grupo['base_imponible'] for grupo in resumen_impuestos), Decimal('0.00'))
    monto_iva = sum((grupo['monto_iva'] for grupo in resumen_impuestos), Decimal('0.00'))
    descuento_total = sum((detalle.importe_descuento for detalle in detalles), Decimal('0.00'))
    total_calculado = sum((detalle.total_linea for detalle in detalles), Decimal('0.00'))
    documento_cliente = factura.rif or factura.cliente.cedula or ''
    if documento_cliente.upper().startswith('AUTO'):
        documento_cliente = ''
    return {
        'factura': factura,
        'detalles': detalles,
        'resumen_impuestos': resumen_impuestos,
        'base_imponible': base_imponible,
        'monto_iva': monto_iva,
        'descuento_total': descuento_total,
        'total_calculado': total_calculado,
        'total_no_concilia': abs(total_calculado - Decimal(str(factura.total or 0))) > Decimal('0.01'),
        'razon_social_cliente': factura.razon_social or f'{factura.cliente.nombre} {factura.cliente.apellido}'.strip(),
        'documento_cliente': documento_cliente,
        'domicilio_cliente': factura.direccion_fiscal or factura.cliente.direccion or '',
    }


def _generar_factura_pdf(request, factura):
    context = _contexto_factura_pdf(factura)
    html = render_to_string('factura_cliente_pdf.html', context=context, request=request)
    from weasyprint import HTML
    pdf = HTML(string=html, base_url=request.build_absolute_uri('/')).write_pdf()
    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="factura_{factura.numero}.pdf"'
    return response


@user_passes_test(lambda u: u.is_staff, login_url='login_admin_custom')
def descargar_factura_pdf(request, factura_id):
    factura = get_object_or_404(
        Factura.objects.select_related('cliente').prefetch_related('detalles__producto'),
        numero=factura_id,
    )
    return _generar_factura_pdf(request, factura)


@cliente_required
def stripe_checkout(request, pedido_id):
    """Inicia un pago con Stripe y redirige al flujo seguro de checkout."""
    pedido = get_object_or_404(Pedido, id=pedido_id)
    if request.user.is_staff:
        allowed = True
    else:
        cliente = get_current_cliente(request)
        if not cliente:
            return redirect(reverse('login_cliente') + f"?next={request.get_full_path()}")
        cliente_user = getattr(cliente, 'user', None)
        if cliente_user:
            allowed = pedido.cliente_id == cliente_user.id
        else:
            allowed = pedido.cliente and pedido.cliente.email.lower() == cliente.email.lower()
    if not allowed:
        return HttpResponseForbidden('No tienes permiso para pagar este pedido.')

    stripe_api_key = getattr(settings, 'STRIPE_SECRET_KEY', '')
    if stripe is None:
        messages.error(request, 'La librería stripe no está instalada. Ejecuta `pip install stripe` y reinicia el servidor.')
        return redirect('pagar_pedido', pedido_id=pedido.id)
    if not stripe_api_key:
        messages.error(request, 'Stripe no está configurado en el servidor.')
        return redirect('pagar_pedido', pedido_id=pedido.id)

    stripe.api_key = stripe_api_key
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': getattr(settings, 'STRIPE_CURRENCY', 'usd'),
                    'unit_amount': int(Decimal(str(pedido.total)) * Decimal('100')),
                    'product_data': {
                        'name': f'Pedido #{pedido.id}',
                    },
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=request.build_absolute_uri(reverse('mis_pedidos')) + '?paid=1',
            cancel_url=request.build_absolute_uri(reverse('pagar_pedido', args=[pedido.id])),
            metadata={'pedido_id': str(pedido.id)},
            client_reference_id=str(pedido.id),
        )
        return redirect(session.url)
    except Exception as exc:
        messages.error(request, f'Error al crear sesión de pago: {exc}')
        return redirect('pagar_pedido', pedido_id=pedido.id)


@csrf_exempt
def stripe_webhook(request):
    """Recibe eventos de Stripe y confirma el pago cuando el checkout termina."""
    if stripe is None:
        return HttpResponse(status=503, content='Stripe no disponible.')

    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE', '')
    endpoint_secret = getattr(settings, 'STRIPE_WEBHOOK_SECRET', '')
    if not endpoint_secret:
        return HttpResponse(status=400, content='Webhook no configurado.')

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except ValueError:
        return HttpResponse(status=400, content='Payload inválido.')
    except stripe.error.SignatureVerificationError:
        return HttpResponse(status=400, content='Firma inválida.')

    if event.get('type') in {'checkout.session.completed', 'checkout.session.async_payment_succeeded'}:
        session = event.get('data', {}).get('object', {})
        if session.get('payment_status') != 'paid':
            return HttpResponse(status=200)
        pedido_id = None
        metadata = session.get('metadata') or {}
        try:
            if metadata.get('pedido_id'):
                pedido_id = int(metadata['pedido_id'])
            elif session.get('client_reference_id'):
                pedido_id = int(session['client_reference_id'])
        except (TypeError, ValueError):
            return HttpResponse(status=400, content='Pedido inválido.')

        pedido = Pedido.objects.filter(id=pedido_id).first()
        if not pedido:
            return HttpResponse(status=404, content='Pedido no encontrado.')

        amount_total = session.get('amount_total')
        if amount_total is None:
            return HttpResponse(status=400, content='Monto de pago ausente.')
        monto = Decimal(str(amount_total)) / Decimal('100')
        currency = str(session.get('currency') or '').lower()
        expected_currency = str(getattr(settings, 'STRIPE_CURRENCY', 'usd')).lower()
        if monto != Decimal(pedido.total) or currency != expected_currency:
            return HttpResponse(status=400, content='Monto o moneda del pago no coincide con el pedido.')

        session_id = str(session.get('id') or '')
        if not session_id:
            return HttpResponse(status=400, content='Sesión de pago inválida.')
        pago = pedido.pagos.filter(gateway_reference=session_id).first()
        if not pago:
            pago = Pago(pedido=pedido, monto=monto)
        pago.metodo = 'STRIPE'
        pago.monto = monto
        pago.referencia = session_id
        pago.gateway = 'STRIPE'
        pago.gateway_reference = session_id
        pago.gateway_status = 'paid'
        pago.verificado = True
        pago.estado = 'confirmado'
        pago.save()

        _, error = _approve_pending_order(pedido.id, pago.id)
        if error:
            return HttpResponse(status=409, content=error)

    return HttpResponse(status=200)


@redirect_staff_to_admin_view
@login_required(login_url='login_cliente')
def registrar_pago_manual(request, pedido_id):
    """Permite registrar un comprobante manual para un pedido pendiente de verificación."""
    pedido = get_object_or_404(Pedido, id=pedido_id)
    if not request.user.is_staff and pedido.cliente_id != request.user.id:
        return HttpResponseForbidden('No tienes permiso para registrar pagos para este pedido.')

    if request.method == 'POST':
        form = PagoManualForm(request.POST, request.FILES)
        if form.is_valid():
            pago = form.save(commit=False)
            pago.pedido = pedido
            pago.monto = pedido.total
            pago.numero_referencia = form.cleaned_data['referencia'][:100]
            pago.verificado = False
            pago.estado = 'en_revision'
            pago.save()

            if pedido.estado != 'pendiente':
                pedido.estado = 'pendiente'
                pedido.estado_operativo = 'pendiente_pago'
                pedido.save(update_fields=['estado', 'estado_operativo'])
            messages.success(request, 'Tu comprobante fue recibido. El pago quedará pendiente de verificación.')
            return redirect('mis_pedidos')
    else:
        form = PagoManualForm()

    return render(request, 'registrar_pago_manual.html', {'pedido': pedido, 'form': form})


def _admin_pedido_summary():
    stats = Pedido.objects.aggregate(
        total=Count('pk'),
        pending=Count('pk', filter=Q(estado='pendiente')),
        approved=Count('pk', filter=Q(estado__in=('pagado', 'enviado'))),
        rejected=Count('pk', filter=Q(estado='cancelado')),
        customers=Count('cliente', distinct=True),
    )
    stats['latest_date'] = Pedido.objects.order_by('-fecha_creacion').values_list(
        'fecha_creacion', flat=True
    ).first()
    return {
        'orders_total': stats['total'],
        'orders_pending': stats['pending'],
        'orders_approved': stats['approved'],
        'orders_rejected': stats['rejected'],
        'orders_customers': stats['customers'],
        'orders_latest_date': stats['latest_date'],
    }


@redirect_staff_to_admin_view
@login_required(login_url='login_cliente')
@permission_required('dashboard.view_operational_orders', raise_exception=True)
def historial_pedidos_global(request):
    # Vista solo para staff/admin: muestra todos los pedidos
    pedidos_qs = Pedido.objects.select_related('cliente').order_by('-fecha_creacion')
    estado = request.GET.get('estado', '').strip().lower()
    query = request.GET.get('q', '').strip()
    if estado == 'aprobado':
        pedidos_qs = pedidos_qs.filter(estado__in=('pagado', 'enviado'))
    elif estado in ['pendiente', 'pagado', 'cancelado']:
        pedidos_qs = pedidos_qs.filter(estado=estado)
    if query:
        pedidos_qs = pedidos_qs.filter(
            models.Q(id__icontains=query) |
            models.Q(cliente__email__icontains=query) |
            models.Q(cliente__first_name__icontains=query) |
            models.Q(cliente__last_name__icontains=query)
        )
    paginator = Paginator(pedidos_qs, 20)
    page_number = request.GET.get('page')
    pedidos = paginator.get_page(page_number)
    context = {'pedidos': pedidos, **_admin_pedido_summary()}
    return render(request, 'historial_pedidos_global.html', context)


# Versión para el panel administrativo custom: no redirige fuera de la UI custom.
@user_passes_test(lambda u: u.is_staff, login_url='login_admin_custom')
@permission_required('dashboard.view_operational_orders', raise_exception=True)
def admin_historial_pedidos(request):
    # Misma lógica que `historial_pedidos_global` pero accesible directamente desde el panel admin.
    pedidos_qs = Pedido.objects.select_related('cliente').order_by('-fecha_creacion')
    estado = request.GET.get('estado', '').strip().lower()
    query = request.GET.get('q', '').strip()
    if estado == 'aprobado':
        pedidos_qs = pedidos_qs.filter(estado__in=('pagado', 'enviado'))
    elif estado in ['pendiente', 'pagado', 'cancelado']:
        pedidos_qs = pedidos_qs.filter(estado=estado)
    if query:
        pedidos_qs = pedidos_qs.filter(
            models.Q(id__icontains=query) |
            models.Q(cliente__email__icontains=query) |
            models.Q(cliente__first_name__icontains=query) |
            models.Q(cliente__last_name__icontains=query)
        )
    paginator = Paginator(pedidos_qs, 20)
    page_number = request.GET.get('page')
    pedidos = paginator.get_page(page_number)
    context = {'pedidos': pedidos, **_admin_pedido_summary()}
    return render(request, 'historial_pedidos_global.html', context)


@user_passes_test(lambda u: u.is_staff, login_url='login_admin_custom')
@permission_required('dashboard.view_operational_orders', raise_exception=True)
def admin_envios(request):
    envios_base = Envio.objects.select_related('pedido', 'pedido__cliente')
    envios = envios_base.order_by('-requiere_revision', 'actualizado')
    estado = request.GET.get('estado', '').strip().lower()
    query = request.GET.get('q', '').strip()[:80]

    if estado == 'revision':
        envios = envios.filter(
            Q(requiere_revision=True) | Q(pedido__requiere_revision_operativa=True)
        )
    elif estado == 'preparacion':
        envios = envios.filter(estado__in=('no_preparado', 'preparando', 'listo'))
    elif estado == 'en_transito':
        envios = envios.filter(estado__in=('despachado', 'en_transito'))
    elif estado in {value for value, _label in Envio.ESTADO_CHOICES}:
        envios = envios.filter(estado=estado)
    else:
        estado = ''

    if query:
        search_filter = (
            Q(pedido__cliente__email__icontains=query)
            | Q(pedido__cliente__first_name__icontains=query)
            | Q(pedido__cliente__last_name__icontains=query)
            | Q(transportista__icontains=query)
            | Q(numero_guia__icontains=query)
            | Q(nombre_destinatario__icontains=query)
        )
        if query.isdigit():
            search_filter |= Q(pedido__id=int(query))
        envios = envios.filter(search_filter)

    stats = Envio.objects.aggregate(
        total=Count('pk'),
        revision=Count(
            'pk',
            filter=Q(requiere_revision=True) | Q(pedido__requiere_revision_operativa=True),
        ),
        preparacion=Count('pk', filter=Q(estado__in=('no_preparado', 'preparando', 'listo'))),
        transito=Count('pk', filter=Q(estado__in=('despachado', 'en_transito'))),
        incidencias=Count('pk', filter=Q(estado='incidencia')),
    )
    envios_page = Paginator(envios, 25).get_page(request.GET.get('page'))
    return render(request, 'admin_envios.html', {
        'envios': envios_page,
        'estado': estado,
        'query': query,
        'stats': stats,
    })


@staff_member_required(login_url='login')
@permission_required('dashboard.verify_order_payments', raise_exception=True)
def aprobar_pedido_admin(request, pedido_id):
    if not request.user.is_active or not request.user.is_staff:
        return HttpResponseForbidden('Acceso no autorizado')
    if request.method != 'POST':
        return HttpResponseForbidden('Método no permitido.')
    pedido = get_object_or_404(Pedido, id=pedido_id)
    factura, error = _approve_pending_order(pedido_id)
    if error:
        messages.warning(request, error, extra_tags='admin-action')
        return redirect('historial_pedidos_admin')
    messages.success(request, f'Pedido #{pedido.id} aprobado y factura generada.', extra_tags='admin-action')
    return redirect('historial_pedidos_admin')


@staff_member_required(login_url='login')
@permission_required('dashboard.verify_order_payments', raise_exception=True)
def rechazar_pedido_admin(request, pedido_id):
    if not request.user.is_active or not request.user.is_staff:
        return HttpResponseForbidden('Acceso no autorizado')
    if request.method != 'POST':
        return HttpResponseForbidden('Método no permitido.')
    with transaction.atomic():
        pedido = get_object_or_404(Pedido.objects.select_for_update(), id=pedido_id)
        if pedido.estado != 'pendiente':
            messages.warning(request, 'Solo se pueden rechazar pedidos en estado Pendiente.', extra_tags='admin-action')
            return redirect('historial_pedidos_admin')
        _restore_deducted_order_stock(pedido, request.user)
        pedido.estado = 'cancelado'
        pedido.estado_operativo = 'cancelado'
        pedido.save(update_fields=['estado', 'estado_operativo'])
    messages.error(request, f'Pedido #{pedido.id} ha sido rechazado.', extra_tags='admin-action')
    return redirect('historial_pedidos_admin')


@staff_member_required(login_url='login')
def admin_dashboard(request):
    if not request.user.is_active or not request.user.is_staff:
        return HttpResponseForbidden('Acceso no autorizado')
    return dashboard(request)


@staff_member_required(login_url='login')
def historial_pedidos_admin(request):
    if not request.user.is_active or not request.user.is_staff:
        return HttpResponseForbidden('Acceso no autorizado')
    return admin_historial_pedidos(request)


def aprobar_pedido(request, pedido_id):
    return aprobar_pedido_admin(request, pedido_id)


def rechazar_pedido(request, pedido_id):
    return rechazar_pedido_admin(request, pedido_id)


@staff_member_required(login_url='login')
@permission_required('dashboard.view_operational_orders', raise_exception=True)
def detalle_pedido_admin(request, pedido_id):
    if not request.user.is_active or not request.user.is_staff:
        return HttpResponseForbidden('Acceso no autorizado')
    pedido = get_object_or_404(
        Pedido.objects.select_related('cliente', 'envio').prefetch_related(
            'items__producto',
            'pagos',
            'envio__eventos__actor',
        ),
        id=pedido_id,
    )
    envio = getattr(pedido, 'envio', None)
    return render(request, 'detalle_pedido_admin.html', {
        'pedido': pedido,
        'envio_form': EnvioAdminForm(instance=envio) if envio else None,
    })


@user_passes_test(lambda u: u.is_staff, login_url='login_admin_custom')
@permission_required('dashboard.manage_fulfillment', raise_exception=True)
@require_POST
def actualizar_envio_admin(request, pedido_id):
    transiciones = {
        'no_preparado': {'preparando', 'incidencia'},
        'preparando': {'listo', 'incidencia'},
        'listo': {'despachado', 'incidencia'},
        'despachado': {'en_transito', 'entregado', 'incidencia'},
        'en_transito': {'entregado', 'incidencia'},
        'incidencia': {'preparando', 'listo', 'despachado'},
        'entregado': set(),
        'devuelto': set(),
    }

    with transaction.atomic():
        pedido = get_object_or_404(Pedido.objects.select_for_update(), pk=pedido_id)
        envio = get_object_or_404(Envio.objects.select_for_update(), pedido=pedido)
        estado_anterior = envio.estado
        form = EnvioAdminForm(request.POST, instance=envio)
        if not form.is_valid():
            for field_errors in form.errors.values():
                for error in field_errors:
                    messages.error(request, error)
            return redirect('detalle_pedido_admin', pedido_id=pedido.id)

        estado_nuevo = form.cleaned_data['estado']
        if estado_nuevo != estado_anterior:
            if pedido.estado_operativo != 'confirmado' or pedido.requiere_revision_operativa:
                messages.error(request, 'El pedido debe estar confirmado y sin revisiones pendientes antes de cambiar su envío.')
                return redirect('detalle_pedido_admin', pedido_id=pedido.id)
            if estado_nuevo not in transiciones.get(estado_anterior, set()):
                messages.error(request, f'No se permite pasar el envío de {estado_anterior} a {estado_nuevo}.')
                return redirect('detalle_pedido_admin', pedido_id=pedido.id)

        campos_cambiados = list(form.changed_data)
        envio = form.save(commit=False)
        if envio.requiere_revision:
            envio.requiere_revision = False
            campos_cambiados.append('requiere_revision')
        envio.save()

        if estado_nuevo != estado_anterior:
            descripcion = (
                envio.observaciones[:240]
                if estado_nuevo in {'incidencia', 'devuelto'}
                else 'Actualización manual de seguimiento.'
            )
            EnvioEvento.objects.create(
                envio=envio,
                estado_anterior=estado_anterior,
                estado_nuevo=estado_nuevo,
                actor=request.user,
                descripcion=descripcion,
            )
            if estado_nuevo == 'entregado':
                pedido.estado_operativo = 'completado'
                pedido.save(update_fields=['estado_operativo'])

        if campos_cambiados:
            AuditLog.objects.create(
                user=request.user,
                action='update',
                model_name='Envio',
                object_id=str(envio.pk),
                details=json.dumps({
                    'pedido_id': pedido.pk,
                    'estado_anterior': estado_anterior,
                    'estado_nuevo': estado_nuevo,
                    'campos': campos_cambiados,
                }, ensure_ascii=False),
                ip_address=request.META.get('REMOTE_ADDR') or None,
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:1000],
            )

    messages.success(request, 'Se actualizó el seguimiento del envío.')
    return redirect('detalle_pedido_admin', pedido_id=pedido.id)

@redirect_staff_to_admin_view
@login_required(login_url='login_cliente')
def mis_pedidos(request):
    user = get_authenticated_django_user(request)
    pedidos = Pedido.objects.filter(cliente=user).order_by('-fecha_creacion') if user else Pedido.objects.none()
    return render(request, 'mis_pedidos.html', {'pedidos': pedidos})


def _recent_client_months():
    today = timezone.localdate()
    month_names = ('Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic')
    months = []
    for offset in range(5, -1, -1):
        month_index = today.year * 12 + today.month - 1 - offset
        year, zero_based_month = divmod(month_index, 12)
        month = zero_based_month + 1
        months.append({'year': year, 'month': month, 'label': month_names[month - 1]})
    return months


@redirect_staff_to_admin_view
@login_required(login_url='login_cliente')
def cliente_facturas(request):
    user = get_authenticated_django_user(request)
    if not user or not user.email:
        return HttpResponseForbidden('No se pudo verificar la cuenta del cliente.')

    estado = request.GET.get('estado', '').strip().lower()
    if estado not in {'facturada', 'anulada'}:
        estado = ''
    query = request.GET.get('q', '').strip()[:80]
    facturas_base = Factura.objects.filter(cliente__email__iexact=user.email)
    facturas = facturas_base.select_related('cliente', 'pedido').order_by('-fecha')
    if estado:
        facturas = facturas.filter(estado=estado)
    if query:
        if query.isdigit():
            facturas = facturas.filter(
                models.Q(numero=int(query)) | models.Q(pedido__id=int(query))
            )
        else:
            facturas = facturas.filter(
                models.Q(cliente__nombre__icontains=query)
                | models.Q(cliente__apellido__icontains=query)
            )

    facturas_emitidas = facturas_base.filter(estado='facturada')
    month_buckets = _recent_client_months()
    first_month = month_buckets[0]
    invoice_month_rows = (
        facturas_emitidas.filter(fecha__date__gte=date(first_month['year'], first_month['month'], 1))
        .annotate(month=TruncMonth('fecha'))
        .values('month')
        .annotate(total=Sum('total'))
    )
    invoice_month_totals = {
        (row['month'].year, row['month'].month): float(row['total'] or 0)
        for row in invoice_month_rows if row['month']
    }
    max_invoice_month = max(invoice_month_totals.values(), default=0)
    invoice_month_chart = [
        {
            'label': bucket['label'],
            'value': invoice_month_totals.get((bucket['year'], bucket['month']), 0),
            'percentage': (
                max(4, round(invoice_month_totals.get((bucket['year'], bucket['month']), 0) * 100 / max_invoice_month))
                if invoice_month_totals.get((bucket['year'], bucket['month']), 0) and max_invoice_month else 0
            ),
        }
        for bucket in month_buckets
    ]
    invoice_status_counts = dict(
        facturas_base.values('estado').annotate(total=models.Count('numero')).values_list('estado', 'total')
    )
    invoice_status_chart = [
        {
            'label': label,
            'value': invoice_status_counts.get(key, 0),
            'percentage': round(invoice_status_counts.get(key, 0) * 100 / max(sum(invoice_status_counts.values()), 1)),
        }
        for key, label in (('facturada', 'Facturadas'), ('anulada', 'Anuladas'))
    ]
    facturas_page = Paginator(facturas, 12).get_page(request.GET.get('page'))
    return render(request, 'cliente_facturas.html', {
        'facturas': facturas_page,
        'query': query,
        'estado': estado,
        'facturas_emitidas': facturas_emitidas.count(),
        'total_facturas': sum(invoice_status_counts.values()),
        'importe_facturado': facturas_emitidas.aggregate(total=Sum('total'))['total'] or Decimal('0.00'),
        'invoice_month_chart': invoice_month_chart,
        'invoice_status_chart': invoice_status_chart,
    })


@redirect_staff_to_admin_view
@login_required(login_url='login_cliente')
def cliente_pagos(request):
    user = get_authenticated_django_user(request)
    if not user:
        return HttpResponseForbidden('No se pudo verificar la cuenta del cliente.')

    pagos_base = Pago.objects.filter(pedido__cliente=user)
    pagos = pagos_base.select_related('pedido').order_by('-creado')
    estado = request.GET.get('estado', '').strip().lower()
    if estado in {value for value, _label in Pago.ESTADO_CHOICES}:
        pagos = pagos.filter(estado=estado)
    else:
        estado = ''
    metodo = request.GET.get('metodo', '').strip().upper()
    metodos_pago = list(Pago.METODOS)
    if metodo in {value for value, _label in metodos_pago}:
        pagos = pagos.filter(metodo=metodo)
    else:
        metodo = ''
    query = request.GET.get('q', '').strip()[:80]
    if query:
        filters = models.Q(referencia__icontains=query)
        if query.isdigit():
            filters |= models.Q(pedido__id=int(query))
        else:
            filters |= models.Q(metodo__icontains=query)
        pagos = pagos.filter(filters)

    pagos_page = Paginator(pagos, 15).get_page(request.GET.get('page'))
    payment_status_counts = dict(
        pagos_base.values('estado').annotate(total=models.Count('id')).values_list('estado', 'total')
    )
    payment_status_chart = [
        {
            'label': label,
            'value': payment_status_counts.get(key, 0),
            'percentage': round(payment_status_counts.get(key, 0) * 100 / max(pagos_base.count(), 1)),
        }
        for key, label in (
            ('confirmado', 'Confirmados'),
            ('pendiente', 'Pendientes'),
            ('rechazado', 'Rechazados'),
            ('en_revision', 'En revisión'),
            ('reembolsado', 'Reembolsados'),
            ('reembolso_parcial', 'Reembolso parcial'),
            ('disputado', 'Disputados'),
        )
    ]
    payment_method_counts = dict(
        pagos_base.values('metodo').annotate(total=models.Count('id')).values_list('metodo', 'total')
    )
    payment_method_chart = [
        {
            'label': label,
            'value': payment_method_counts.get(key, 0),
            'percentage': round(payment_method_counts.get(key, 0) * 100 / max(pagos_base.count(), 1)),
        }
        for key, label in metodos_pago if payment_method_counts.get(key, 0)
    ]
    return render(request, 'cliente_pagos.html', {
        'pagos': pagos_page,
        'query': query,
        'estado': estado,
        'metodo': metodo,
        'metodos_pago': metodos_pago,
        'estados_pago': Pago.ESTADO_CHOICES,
        'total_pagos': pagos_base.count(),
        'pagos_pendientes': pagos_base.filter(
            estado__in=('pendiente', 'en_revision'),
            verificado=False,
        ).count(),
        'importe_confirmado': pagos_base.filter(verificado=True).aggregate(total=Sum('monto'))['total'] or Decimal('0.00'),
        'payment_status_chart': payment_status_chart,
        'payment_method_chart': payment_method_chart,
    })

def detalle_pedido(request, pedido_id):
    # Admins and authenticated owners may view pending, paid, shipped, or cancelled orders.
    if request.user.is_authenticated and (request.user.is_staff or request.user.is_superuser or request.user.has_perm('dashboard.view_auditlog')):
        pedido = get_object_or_404(Pedido, id=pedido_id)
        return render(request, 'detalle_pedido.html', {'pedido': pedido})

    pedido = None
    if request.user.is_authenticated:
        pedido = Pedido.objects.filter(id=pedido_id, cliente=request.user).first()

    customer = get_customer_from_request(request)
    if pedido is None and customer:
        cliente = getattr(customer, 'cliente', None)
        if cliente and cliente.user_id:
            pedido = Pedido.objects.filter(id=pedido_id, cliente_id=cliente.user_id).first()
        if pedido is None and customer.email:
            pedido = Pedido.objects.filter(id=pedido_id, cliente__email__iexact=customer.email).first()

    if pedido is None and not request.user.is_authenticated and not customer:
        return redirect(reverse('login_cliente') + f"?next={request.get_full_path()}")

    if pedido is None:
        return HttpResponseForbidden('No tienes permiso para ver este pedido.')
    return render(request, 'detalle_pedido.html', {'pedido': pedido})

@ratelimit(key='ip', rate='5/m', method='POST', block=True)
def cliente_registro(request):
    next_value = request.POST.get('next') or request.GET.get('next', '')
    next_url = get_safe_redirect(request, next_value, default=reverse('index'))
    if request.method == 'POST':
        form = ClienteRegistroForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            password = form.cleaned_data['password1']
            customer = Customer.objects.filter(email__iexact=email, is_active=True).first()
            if customer:
                messages.error(request, 'Ya existe una cuenta de cliente registrada con ese correo. Inicia sesión o usa otro email.')
            else:
                customer = Customer.objects.create(
                    nombre=form.cleaned_data['nombre'],
                    email=email,
                    cedula=form.cleaned_data.get('cedula'),
                    telefono=form.cleaned_data['telefono'],
                    direccion=form.cleaned_data['direccion'],
                    is_guest=False,
                )
                customer.set_password(password)
                customer.save()

                customer.backend = 'dashboard.customer_auth.CustomerBackend'
                login(request, customer)

                cliente = customer.ensure_cliente_profile()
                sync_admin_cliente_record(cliente)
                if cliente and not cliente.cedula and customer.cedula:
                    cliente.cedula = customer.cedula
                    cliente.save(update_fields=['cedula'])
                merge_session_cart_items(request, cliente)
                request.session['customer_id'] = customer.id
                request.session['cliente_id'] = cliente.id
                request.session['cliente_nombre'] = cliente.nombre
                request.session['cliente_email'] = cliente.email
                request.session.modified = True
                response = redirect(next_url)
                response = login_customer_cookie(response, customer)
                log_auth_event(request, 'CLIENT_REGISTRATION', user=None, details='Registro de cliente completado.')
                messages.success(request, '¡Registro exitoso! Bienvenido, ' + cliente.nombre)
                return response
    else:
        form = ClienteRegistroForm()
    return render(request, 'cliente_registro.html', {'form': form, 'next': next_value})


@csrf_exempt
def google_one_tap(request):
    """Endpoint para recibir el id_token (credential) de Google One Tap.
    Valida el token con el endpoint de Google y crea/obtiene un Cliente visitante,
    guarda `cliente_id` en sesión y mezcla el carrito.
    Devuelve JSON con {'ok': True, 'next': safe_next}
    """
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'method_not_allowed'}, status=405)
    try:
        body = request.body.decode('utf-8')
        data = json.loads(body)
    except Exception:
        return JsonResponse({'ok': False, 'error': 'invalid_json'}, status=400)

    credential = data.get('credential')
    next_value = data.get('next', '')
    if not credential:
        return JsonResponse({'ok': False, 'error': 'no_credential'}, status=400)

    # Validar token con Google
    try:
        tid = urllib_parse.quote(credential, safe='')
        url = f'https://oauth2.googleapis.com/tokeninfo?id_token={tid}'
        with urllib_request.urlopen(url, timeout=10) as resp:
            info = json.load(resp)
    except Exception:
        return JsonResponse({'ok': False, 'error': 'invalid_token'}, status=400)

    # Verificar audiencia
    client_id = getattr(settings, 'SOCIAL_AUTH_GOOGLE_OAUTH2_KEY', '')
    if info.get('aud') and client_id and info.get('aud') != client_id:
        # No coincide el client_id; rechazar
        return JsonResponse({'ok': False, 'error': 'aud_mismatch'}, status=400)

    email = info.get('email')
    nombre = info.get('name') or (email.split('@')[0] if email else 'Visitante')
    if not email:
        return JsonResponse({'ok': False, 'error': 'no_email'}, status=400)

    # Buscar o crear Customer independiente del admin
    customer = Customer.objects.filter(email__iexact=email, is_active=True).first()
    if not customer:
        customer = Customer.objects.create(
            nombre=nombre,
            email=email,
            is_guest=True,
        )
    cliente = customer.ensure_cliente_profile()

    sync_admin_cliente_record(cliente)

    # Guardar en sesión y cookie de cliente, y mezclar el carrito
    request.session['customer_id'] = customer.id
    request.session['cliente_id'] = cliente.id
    request.session['cliente_nombre'] = cliente.nombre
    request.session['cliente_email'] = cliente.email
    request.session.modified = True
    try:
        merge_session_cart_items(request, cliente)
    except Exception:
        pass

    response = JsonResponse({'ok': True, 'next': get_safe_redirect(request, next_value, default=reverse('carrito'))})
    response = login_customer_cookie(response, customer)
    return response

@csrf_exempt
@ratelimit(key='ip', rate='30/m', method='POST', block=True)
def google_identity_login(request):
    """Endpoint receptor de Google One Tap / Identity Services.

    Recibe el JWT 'credential' auténtico de Google, valida el aud/client_id y
    crea o recupera el User Django sin romper el login normal de Django.
    """
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'method_not_allowed'}, status=405)

    if request.content_type and 'application/json' in request.content_type:
        try:
            data = json.loads(request.body.decode('utf-8') or '{}')
        except Exception:
            return JsonResponse({'ok': False, 'error': 'invalid_json'}, status=400)
    else:
        data = request.POST

    credential = data.get('credential') or data.get('id_token')
    next_value = data.get('next', '') or request.POST.get('next', '') or request.GET.get('next', '')

    if not credential:
        return JsonResponse({'ok': False, 'error': 'no_credential'}, status=400)

    if id_token is None or google_requests is None:
        return JsonResponse({'ok': False, 'error': 'google_auth_dependency_missing'}, status=500)

    google_client_id = getattr(settings, 'GOOGLE_CLIENT_ID', None) or getattr(settings, 'SOCIAL_AUTH_GOOGLE_OAUTH2_KEY', '')

    try:
        payload = id_token.verify_oauth2_token(
            credential,
            google_requests.Request(),
            google_client_id,
        )
    except ValueError as exc:
        return JsonResponse({'ok': False, 'error': 'invalid_token'}, status=400)
    except Exception:
        return JsonResponse({'ok': False, 'error': 'invalid_token'}, status=400)

    # Verificación reforzada del payload emitido por Google.
    if payload.get('aud') != google_client_id:
        return JsonResponse({'ok': False, 'error': 'aud_mismatch'}, status=400)
    if payload.get('iss') not in {'accounts.google.com', 'https://accounts.google.com'}:
        return JsonResponse({'ok': False, 'error': 'issuer_mismatch'}, status=400)
    if payload.get('email_verified') is not True:
        return JsonResponse({'ok': False, 'error': 'email_not_verified'}, status=400)

    email = (payload.get('email') or '').strip().lower()
    if not email:
        return JsonResponse({'ok': False, 'error': 'no_email'}, status=400)

    # Prohibir Google login para cuentas administrativas.
    if User.objects.filter(email__iexact=email, is_staff=True).exists() or User.objects.filter(email__iexact=email, is_superuser=True).exists():
        return JsonResponse({'ok': False, 'error': 'admin_forbidden'}, status=403)

    user = User.objects.filter(email__iexact=email, is_active=True).first()
    created = False
    if not user:
        base_username = (payload.get('given_name') or email.split('@')[0]).strip().lower() or 'usuario'
        username = base_username
        suffix = 1
        while User.objects.filter(username__iexact=username).exists():
            username = f'{base_username}{suffix}'
            suffix += 1

        user = User.objects.create_user(
            username=username,
            email=email,
            password=User.objects.make_random_password(),
        )
        user.set_unusable_password()
        user.is_active = True
        user.is_staff = False
        user.is_superuser = False
        user.save()
        created = True

    user.backend = 'django.contrib.auth.backends.ModelBackend'
    login(request, user)

    if user.is_staff or user.is_superuser:
        return JsonResponse({'ok': False, 'error': 'admin_forbidden'}, status=403)

    given_name = (payload.get('given_name') or '').strip()
    family_name = (payload.get('family_name') or '').strip()
    if given_name:
        user.first_name = given_name
    if family_name:
        user.last_name = family_name
    user.save(update_fields=['first_name', 'last_name'])

    carrito_anonimo = request.session.get('carrito') or request.session.get('anon_cart') or {}
    login(request, user)

    if carrito_anonimo:
        cliente = Cliente.objects.filter(user=user).first()
        if not cliente:
            cliente = Cliente.objects.filter(email__iexact=user.email).first()
            if cliente:
                cliente.user = user
                cliente.save(update_fields=['user'])
        if not cliente:
            cliente = Cliente.objects.create(
                user=user,
                nombre=(payload.get('given_name') or user.get_full_name() or user.username).strip() or user.username,
                email=user.email,
            )
        carrito, _ = Carrito.objects.get_or_create(cliente=cliente)
        carrito_meta = request.session.get('carrito_meta') or request.session.get('anon_cart_meta') or {}
        for codigo, cantidad in dict(carrito_anonimo).items():
            try:
                qty = int(cantidad)
                if qty <= 0:
                    continue
            except (TypeError, ValueError):
                continue
            try:
                producto = Productos.objects.get(Codigo=str(codigo))
            except Productos.DoesNotExist:
                continue
            item, _ = CarritoItem.objects.get_or_create(carrito=carrito, producto=producto)
            item.cantidad = min(item.cantidad + qty, getattr(producto, 'Cantidad', item.cantidad + qty))
            meta = carrito_meta.get(str(codigo), {}) if isinstance(carrito_meta, dict) else {}
            if meta:
                item.presentacion_type = meta.get('presentacion_type') or item.presentacion_type or ''
                try:
                    item.presentacion_factor = int(meta.get('presentacion_factor') or 1)
                except (TypeError, ValueError):
                    item.presentacion_factor = 1
            item.save()
        request.session.pop('carrito', None)
        request.session.pop('anon_cart', None)
        request.session.pop('carrito_meta', None)
        request.session.pop('anon_cart_meta', None)
        request.session.modified = True

    # TODO si hay un Customer asociado con un correo de Google, se puede materializar aquí
    # en el mismo patrón que la sesión de cliente tradicional.
    cliente = Cliente.objects.filter(user=user).first()
    if not cliente:
        cliente = Cliente.objects.filter(email__iexact=user.email).first()
        if cliente:
            cliente.user = user
            cliente.save(update_fields=['user'])

    if not cliente:
        cliente = Cliente.objects.create(
            user=user,
            nombre=(payload.get('given_name') or user.get_full_name() or user.username).strip() or user.username,
            email=user.email,
        )

    request.session['cliente_id'] = cliente.id
    request.session['cliente_nombre'] = cliente.nombre
    request.session['cliente_email'] = cliente.email
    request.session.modified = True
    sync_admin_cliente_record(cliente)

    next_url = get_safe_redirect(request, next_value, default=reverse('cliente_panel'))
    return JsonResponse({'ok': True, 'status': 'success', 'redirect': '/', 'next': next_url, 'created': created})


def google_auth_api(request):
    return google_identity_login(request)


@csrf_exempt
@ratelimit(key='ip', rate='30/m', method='POST', block=True)
def google_login_callback(request):
    """Callback simple para Google One Tap que verifica el token y loguea al usuario.

    Recibe `credential` en POST (form-encoded desde el navegador/OneTap) y realiza:
    - verificación del id_token con google-auth
    - obtención o creación del User Django
    - login(request, user)
    - redirección al panel del cliente
    """
    if request.method != 'POST':
        return redirect('cliente_login')

    token = request.POST.get('credential') or request.POST.get('id_token')
    if not token:
        return redirect('cliente_login')

    if id_token is None or google_requests is None:
        return redirect('cliente_login')

    google_client_id = getattr(settings, 'GOOGLE_CLIENT_ID', '') or getattr(settings, 'SOCIAL_AUTH_GOOGLE_OAUTH2_KEY', '')
    try:
        info = id_token.verify_oauth2_token(token, google_requests.Request(), google_client_id)
    except Exception:
        return redirect('cliente_login')

    if info.get('aud') != google_client_id:
        return redirect('cliente_login')
    if info.get('iss') not in {'accounts.google.com', 'https://accounts.google.com'}:
        return redirect('cliente_login')
    if info.get('email_verified') is not True:
        return redirect('cliente_login')

    email = (info.get('email') or '').strip().lower()
    if not email:
        return redirect('cliente_login')

    user = User.objects.filter(email__iexact=email, is_active=True).first()
    if user and (user.is_staff or user.is_superuser):
        return redirect('cliente_login')
    created = user is None
    if created:
        username = email
        suffix = 1
        while User.objects.filter(username__iexact=username).exists():
            username = f'{email}{suffix}'
            suffix += 1
        user = User.objects.create_user(username=username, email=email)
    if created:
        user.set_unusable_password()
        user.is_active = True
        user.is_staff = False
        user.is_superuser = False
        user.save()

    carrito_anonimo = request.session.get('carrito') or request.session.get('anon_cart') or {}
    login(request, user)

    if carrito_anonimo:
        cliente = Cliente.objects.filter(user=user).first()
        if not cliente:
            cliente = Cliente.objects.filter(email__iexact=user.email).first()
            if cliente:
                cliente.user = user
                cliente.save(update_fields=['user'])
        if not cliente:
            cliente = Cliente.objects.create(user=user, nombre=user.get_full_name() or user.username, email=user.email)

        carrito, _ = Carrito.objects.get_or_create(cliente=cliente)
        carrito_meta = request.session.get('carrito_meta') or request.session.get('anon_cart_meta') or {}
        for codigo, cantidad in dict(carrito_anonimo).items():
            try:
                qty = int(cantidad)
                if qty <= 0:
                    continue
            except (TypeError, ValueError):
                continue
            try:
                producto = Productos.objects.get(Codigo=str(codigo))
            except Productos.DoesNotExist:
                continue
            item, _ = CarritoItem.objects.get_or_create(carrito=carrito, producto=producto)
            item.cantidad = min(item.cantidad + qty, getattr(producto, 'Cantidad', item.cantidad + qty))
            meta = carrito_meta.get(str(codigo), {}) if isinstance(carrito_meta, dict) else {}
            if meta:
                item.presentacion_type = meta.get('presentacion_type') or item.presentacion_type or ''
                try:
                    item.presentacion_factor = int(meta.get('presentacion_factor') or 1)
                except (TypeError, ValueError):
                    item.presentacion_factor = 1
            item.save()
        request.session.pop('carrito', None)
        request.session.pop('anon_cart', None)
        request.session.pop('carrito_meta', None)
        request.session.pop('anon_cart_meta', None)
        request.session.modified = True

    try:
        cliente = Cliente.objects.filter(user=user).first()
        if not cliente:
            cliente = Cliente.objects.filter(email__iexact=user.email).first()
            if cliente:
                cliente.user = user
                cliente.save(update_fields=['user'])
        if not cliente:
            cliente = Cliente.objects.create(user=user, nombre=user.get_full_name() or user.username, email=user.email)
        sync_admin_cliente_record(cliente)
    except Exception:
        pass

    return redirect('cliente_panel')

@ratelimit(key='ip', rate='5/m', method='POST', block=True)
def cliente_login(request):
    next_value = request.POST.get('next') or request.GET.get('next', '')
    next_url = get_safe_redirect(request, next_value, default=reverse('index'))
    if next_url in [reverse('login_cliente'), reverse('cliente_registro'), '/cliente/login/', '/cliente/registro/']:
        next_url = reverse('index')

    # Si ya existe un usuario autenticado de Django (incluyendo Google One Tap), rompemos
    # el bucle de redirección y lo enviamos al panel del cliente.
    if request.user.is_authenticated:
        if request.user.is_staff or request.user.is_superuser:
            return redirect(reverse('dashboard'))
        return redirect(reverse('cliente_panel'))

    if request.method == 'POST':
        if 'email' in request.POST and not request.POST.get('username') and not request.POST.get('password'):
            email = request.POST.get('email', '').strip()
            if not email:
                messages.error(request, 'Ingresa un correo electrónico válido.')
            else:
                customer = Customer.objects.filter(email__iexact=email, is_active=True).first()
                if customer:
                    messages.error(request, 'Ya existe una cuenta asociada a este correo. Inicia sesión con tu contraseña o usa Google.')
                else:
                    customer = Customer.objects.create(
                        nombre=email.split('@')[0],
                        email=email,
                        is_guest=True,
                    )
                    cliente = customer.ensure_cliente_profile()
                    sync_admin_cliente_record(cliente)
                    request.session['customer_id'] = customer.id
                    request.session['cliente_id'] = cliente.id
                    request.session['cliente_nombre'] = cliente.nombre
                    request.session['cliente_email'] = cliente.email
                    request.session['show_cliente_guide'] = True
                    request.session.modified = True
                    merge_session_cart_items(request, cliente)
                    response = redirect(next_url)
                    response = login_customer_cookie(response, customer)
                    log_auth_event(request, 'GUEST_ACCESS', details='Acceso visitante mediante correo.')
                    messages.success(request, 'Continuarás como visitante. Completa el registro tras tu compra si quieres una cuenta permanente.')
                    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest':
                        return JsonResponse({'ok': True, 'next': next_url})
                    return response

        form = ClienteAuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            response = redirect(next_url)
            if user is not None:
                if isinstance(user, Customer):
                    user.backend = 'dashboard.customer_auth.CustomerBackend'
                    login(request, user)
                    response = login_customer_cookie(response, user)
                    cliente = user.ensure_cliente_profile()
                else:
                    user.backend = 'django.contrib.auth.backends.ModelBackend'
                    login(request, user)
                    # Si el usuario autenticado es staff, dirigirlo al panel administrativo custom
                    if getattr(user, 'is_staff', False) or getattr(user, 'is_superuser', False):
                        response = redirect(reverse('dashboard'))
                    cliente = Cliente.objects.filter(user=user).first()
                    if not cliente:
                        cliente = Cliente.objects.filter(email__iexact=user.email).first()
                        if cliente:
                            cliente.user = user
                            cliente.save(update_fields=['user'])

                    if not cliente:
                        cliente = Cliente.objects.create(
                            user=user,
                            nombre=user.get_full_name() or user.username,
                            email=user.email,
                        )

                sync_admin_cliente_record(cliente)
                merge_session_cart_items(request, cliente)
                request.session['cliente_id'] = cliente.id
                request.session['cliente_nombre'] = cliente.nombre
                request.session['cliente_email'] = cliente.email
                request.session['show_cliente_guide'] = True
                request.session.modified = True

            log_auth_event(request, 'CLIENT_LOGIN_SUCCESS', details='Inicio de sesión de cliente correcto.')
            display_name = None
            if hasattr(user, 'get_full_name'):
                display_name = user.get_full_name()
            if not display_name:
                display_name = getattr(user, 'nombre', None)
            if not display_name:
                display_name = getattr(user, 'username', '')
            messages.success(request, f"¡Bienvenido de nuevo, {display_name}!")
            if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest':
                return JsonResponse({'ok': True, 'next': next_url})
            return response
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest':
            return JsonResponse({'ok': False, 'errors': form.errors}, status=400)
        log_auth_event(request, 'CLIENT_LOGIN_FAILURE', details='Credenciales rechazadas.')
    else:
        form = ClienteAuthenticationForm()
    return render(request, 'cliente_login.html', {'form': form, 'next': next_value})

@require_POST
def cliente_logout(request):
    cliente = get_current_cliente(request)
    if cliente is None and isinstance(request.user, User):
        cliente = Cliente.objects.filter(user=request.user).first()
        if not cliente and request.user.email:
            cliente = Cliente.objects.filter(email__iexact=request.user.email).first()
    if cliente:
        Carrito.objects.filter(cliente=cliente).delete()

    logout(request)
    response = redirect('index')
    response = logout_customer_cookie(response)
    messages.info(request, 'Sesión de cliente cerrada correctamente.')
    return response

@redirect_staff_to_admin_view
@login_required(login_url='login_cliente')
def perfil_cliente(request):
    """Vista del perfil fiscal del cliente. Soporta Google User y datos fiscales."""
    user = get_authenticated_django_user(request) or request.user
    perfil, _ = PerfilCliente.objects.get_or_create(user=user)
    cliente = Cliente.objects.filter(user=user).first()

    if request.method == 'POST':
        nombre = (request.POST.get('nombre') or '').strip()
        apellido = (request.POST.get('apellido') or '').strip()
        telefono = (request.POST.get('telefono') or '').strip()
        direccion = (request.POST.get('direccion') or '').strip()
        cedula_rif = (request.POST.get('cedula_rif') or '').strip()
        email = (request.POST.get('email') or '').strip()
        password_current = request.POST.get('password_current') or ''
        password_new = request.POST.get('password_new') or ''
        password_new_confirm = request.POST.get('password_new_confirm') or ''

        if password_current or password_new or password_new_confirm:
            if not all((password_current, password_new, password_new_confirm)):
                messages.error(request, 'Completa la contraseña actual, la nueva y su confirmación.')
                return redirect('perfil_cliente')
            if password_new != password_new_confirm:
                messages.error(request, 'La nueva contraseña y su confirmación no coinciden.')
                return redirect('perfil_cliente')

            customer_account = (
                request.user if isinstance(request.user, Customer)
                else Customer.objects.filter(email__iexact=user.email, is_active=True).first()
            )
            current_password_valid = (
                customer_account.check_password(password_current)
                if isinstance(request.user, Customer) and customer_account
                else user.check_password(password_current)
            )
            if not current_password_valid:
                messages.error(request, 'La contraseña actual no es correcta.')
                return redirect('perfil_cliente')
            try:
                validate_password(password_new, user)
            except ValidationError as error:
                messages.error(request, ' '.join(error.messages))
                return redirect('perfil_cliente')

            with transaction.atomic():
                user.set_password(password_new)
                user.save(update_fields=['password'])
                if customer_account:
                    customer_account.set_password(password_new)
                    customer_account.save(update_fields=['password'])
            if isinstance(request.user, User):
                update_session_auth_hash(request, user)

        if nombre:
            user.first_name = nombre
        if apellido:
            user.last_name = apellido
        if email:
            user.email = email
        user.save(update_fields=['first_name', 'last_name', 'email'])

        perfil.cedula_rif = cedula_rif or perfil.cedula_rif
        perfil.telefono = telefono or perfil.telefono
        perfil.direccion = direccion or perfil.direccion
        perfil.save(update_fields=['cedula_rif', 'telefono', 'direccion'])

        if cliente:
            cliente.nombre = user.get_full_name() or cliente.nombre
            cliente.email = user.email
            cliente.telefono = telefono or cliente.telefono
            cliente.direccion = direccion or cliente.direccion
            cliente.save(update_fields=['nombre', 'email', 'telefono', 'direccion'])

        messages.success(request, 'Perfil actualizado correctamente.')
        next_url = request.POST.get('next') or request.GET.get('next') or 'cliente_perfil'
        return redirect(next_url)

    if cliente and getattr(user, 'email', None) and not cliente.email:
        cliente.email = user.email
        cliente.save(update_fields=['email'])

    context = {
        'cliente': cliente,
        'perfil': perfil,
        'user': user,
        'pedidos': Pedido.objects.filter(cliente=user).order_by('-fecha_creacion')[:5],
    }
    return render(request, 'perfil_cliente.html', context)


@redirect_staff_to_admin_view
@login_required(login_url='login_cliente')
def completar_datos_facturacion(request):
    """Formulario de facturación obligatorio antes de pagar."""
    user = get_authenticated_django_user(request) or request.user
    perfil, _ = PerfilCliente.objects.get_or_create(user=user)
    cliente = Cliente.objects.filter(user=user).first()
    if not cliente and user.email:
        cliente = Cliente.objects.filter(email__iexact=user.email).first()
        if cliente and not cliente.user:
            cliente.user = user
            cliente.save(update_fields=['user'])

    if request.method == 'POST':
        nombre = (request.POST.get('nombre') or '').strip()
        apellido = (request.POST.get('apellido') or '').strip()
        telefono = (request.POST.get('telefono') or '').strip()
        direccion = (request.POST.get('direccion') or '').strip()
        cedula_rif = re.sub(r'\s+', '', (request.POST.get('cedula_rif') or '')).upper()
        tipo_documento = (request.POST.get('tipo_documento') or '').strip().upper()
        numero_documento = (request.POST.get('numero_documento') or '').strip()
        documento_tipado = bool(tipo_documento or numero_documento)
        documento_tipado_valido = (
            tipo_documento in {'V', 'G', 'J'}
            and re.fullmatch(r'\d{5,10}', numero_documento) is not None
        )
        if documento_tipado_valido:
            cedula_rif = f'{tipo_documento}-{numero_documento}'
        razon_social = (request.POST.get('razon_social') or '').strip()
        email = (request.POST.get('email') or '').strip()

        form_values = {
            'nombre': nombre,
            'apellido': apellido,
            'razon_social': razon_social,
            'cedula_rif': cedula_rif,
            'tipo_documento': tipo_documento,
            'numero_documento': numero_documento,
            'telefono': telefono,
            'direccion': direccion,
            'email': email,
        }
        errores = []
        if documento_tipado and not documento_tipado_valido:
            errores.append('Selecciona V, G o J e ingresa un número de 5 a 10 dígitos.')
        if not all((nombre, apellido, telefono, direccion, cedula_rif, email)):
            errores.append('Completa todos los campos obligatorios antes de continuar.')
        if not documento_tipado and (len(cedula_rif) < 5 or len(cedula_rif) > 20 or not re.fullmatch(r'[A-Z0-9.-]+', cedula_rif)):
            errores.append('Ingresa una cédula, RIF o pasaporte válido, sin espacios.')
        cedula_en_otra_cuenta = cedula_rif and Customer.objects.filter(
            cedula__iexact=cedula_rif,
        ).exclude(email__iexact=email).exists()
        cedula_en_otro_perfil = cedula_rif and Cliente.objects.filter(
            cedula__iexact=cedula_rif,
        ).exclude(email__iexact=email).exists()
        if cedula_en_otra_cuenta:
            errores.append('Esta cédula ya pertenece a otra cuenta de cliente.')
        if cedula_en_otro_perfil:
            errores.append('Esta cédula ya pertenece a otro perfil de cliente.')
        if not re.fullmatch(r'[+0-9() .-]{7,20}', telefono) or sum(char.isdigit() for char in telefono) < 7:
            errores.append('Ingresa un teléfono de contacto válido.')
        try:
            from django.core.validators import validate_email
            validate_email(email)
        except ValidationError:
            errores.append('Ingresa un correo electrónico válido.')
        if len(direccion) > 255 or len(razon_social) > 200:
            errores.append('La dirección o razón social excede la longitud permitida.')

        if cedula_en_otra_cuenta or cedula_en_otro_perfil:
            saved_cart = request.session.get('anon_cart')
            saved_cart_meta = request.session.get('anon_cart_meta')
            logout(request)
            if saved_cart:
                request.session['anon_cart'] = saved_cart
            if saved_cart_meta:
                request.session['anon_cart_meta'] = saved_cart_meta
            messages.error(
                request,
                'Por seguridad, cerramos esta sesión porque la cédula ya pertenece a otra cuenta. El carrito se conserva en este navegador; inicia sesión con el correo del titular para continuar.',
            )
            login_url = reverse('cliente_login') + '?' + urllib_parse.urlencode({
                'next': reverse('completar_datos_facturacion'),
            })
            response = redirect(login_url)
            return logout_customer_cookie(response)

        if errores:
            for error in errores:
                messages.error(request, error)
            return render(request, 'completar_datos_facturacion.html', {
                'user': user,
                'perfil': perfil,
                'cliente': cliente,
                'form_values': form_values,
            })

        razon_social = razon_social or f'{nombre} {apellido}'.strip()
        user.first_name = nombre
        user.last_name = apellido
        user.email = email
        user.save(update_fields=['first_name', 'last_name', 'email'])

        perfil.razon_social = razon_social
        perfil.cedula_rif = cedula_rif
        perfil.telefono = telefono
        perfil.direccion = direccion
        perfil.save(update_fields=['razon_social', 'cedula_rif', 'telefono', 'direccion'])

        if cliente:
            cliente.nombre = user.get_full_name()[:100] or cliente.nombre
            cliente.email = user.email
            cliente.cedula = cedula_rif
            cliente.telefono = telefono
            cliente.direccion = direccion
            cliente.save(update_fields=['nombre', 'email', 'cedula', 'telefono', 'direccion'])
        else:
            cliente = Cliente.objects.create(
                user=user,
                nombre=user.get_full_name()[:100] or user.username,
                email=user.email,
                cedula=cedula_rif,
                telefono=telefono,
                direccion=direccion,
            )

        customer_account = Customer.objects.filter(email__iexact=email).first()
        if customer_account:
            customer_account.nombre = user.get_full_name() or customer_account.nombre
            customer_account.cedula = cedula_rif
            customer_account.telefono = telefono
            customer_account.direccion = direccion
            customer_account.cliente = cliente
            customer_account.save(update_fields=['nombre', 'cedula', 'telefono', 'direccion', 'cliente'])
        sync_admin_cliente_record(cliente)

        messages.success(request, 'Datos de facturación guardados correctamente.')
        return redirect('checkout')

    context = {
        'user': user,
        'perfil': perfil,
        'cliente': cliente,
        'form_values': {},
        'next': request.GET.get('next') or 'checkout',
    }
    return render(request, 'completar_datos_facturacion.html', context)


def cliente_panel(request):
    """Panel del cliente con actividad limitada a sus propios registros."""
    cliente = None
    user = get_authenticated_django_user(request)
    if getattr(request.user, 'is_authenticated', False) and not (getattr(request.user, 'is_staff', False) or getattr(request.user, 'is_superuser', False)):
        cliente = Cliente.objects.filter(user=user).first() if user else None
        if not cliente and getattr(request.user, 'email', None):
            cliente = Cliente.objects.filter(email__iexact=request.user.email).first()
            if cliente and user and not cliente.user:
                cliente.user = user
                cliente.save(update_fields=['user'])
        if not cliente and user:
            try:
                cliente = Cliente.objects.create(
                    user=user,
                    nombre=getattr(request.user, 'get_full_name', lambda: None)() or getattr(request.user, 'nombre', None) or getattr(request.user, 'username', None) or request.user.email,
                    email=request.user.email,
                )
            except Exception:
                return JsonResponse({'ok': False, 'error': 'cliente_profile_required'}, status=409)
    if not cliente:
        cliente = get_current_cliente(request)
    if not cliente:
        return redirect(reverse('cliente_registro') + f"?next={request.get_full_path()}")

    pedidos = (
        Pedido.objects.filter(cliente=user).order_by('-fecha_creacion')
        if user is not None else Pedido.objects.none()
    )
    facturas = Factura.objects.filter(cliente__email__iexact=cliente.email).order_by('-fecha')
    facturas_emitidas = facturas.filter(estado='facturada')
    recent_invoices = facturas_emitidas[:5]
    payments = (
        Pago.objects.filter(pedido__cliente=user).select_related('pedido').order_by('-creado')
        if user is not None else Pago.objects.none()
    )

    total_orders = pedidos.count()
    pedidos_activos = pedidos.filter(estado__in=['pendiente', 'pagado']).count()
    total_gastado = pedidos.filter(estado__in=['pagado', 'enviado']).aggregate(total=Sum('total'))['total'] or Decimal('0.00')
    pending_payment_count = payments.filter(
        estado__in=('pendiente', 'en_revision'),
        verificado=False,
    ).count()

    status_labels = (
        ('pendiente', 'Pendientes'),
        ('pagado', 'Pagados'),
        ('enviado', 'Enviados'),
        ('cancelado', 'Cancelados'),
    )
    status_counts = dict(
        pedidos.values('estado').annotate(total=models.Count('id')).values_list('estado', 'total')
    )
    order_statuses = [
        {
            'key': key,
            'label': label,
            'count': status_counts.get(key, 0),
            'percentage': round(status_counts.get(key, 0) * 100 / total_orders) if total_orders else 0,
        }
        for key, label in status_labels
    ]

    month_buckets = _recent_client_months()
    month_start = date(month_buckets[0]['year'], month_buckets[0]['month'], 1)
    monthly_rows = (
        pedidos.filter(
            estado__in=['pagado', 'enviado'],
            fecha_creacion__date__gte=month_start,
        )
        .annotate(month=TruncMonth('fecha_creacion'))
        .values('month')
        .annotate(total=Sum('total'))
    )
    monthly_totals = {
        (row['month'].year, row['month'].month): float(row['total'] or 0)
        for row in monthly_rows if row['month']
    }
    max_month_total = max(monthly_totals.values(), default=0)
    monthly_spend = []
    for bucket in month_buckets:
        amount = monthly_totals.get((bucket['year'], bucket['month']), 0)
        monthly_spend.append({
            'label': bucket['label'],
            'total': amount,
            'height': max(4, round(amount * 100 / max_month_total)) if amount and max_month_total else 0,
        })

    profile = PerfilCliente.objects.filter(user=user).first() if user is not None else None
    profile_fields = [
        ('Nombre completo', bool(cliente.nombre)),
        ('Correo electrónico', bool(cliente.email or getattr(user, 'email', ''))),
        ('Cédula o RIF', bool(cliente.cedula or getattr(profile, 'cedula_rif', ''))),
        ('Teléfono', bool(cliente.telefono or getattr(profile, 'telefono', ''))),
        ('Dirección de entrega', bool(cliente.direccion or getattr(profile, 'direccion', ''))),
    ]
    profile_completed = sum(1 for _, completed in profile_fields if completed)
    profile_completion = round(profile_completed * 100 / len(profile_fields))
    profile_checklist = [
        {'label': label, 'completed': completed}
        for label, completed in profile_fields
    ]

    pago_pendiente = request.session.pop('pago_pendiente', None)
    factura_reciente = request.session.pop('factura_reciente', None)
    request.session.modified = True

    return render(request, 'cliente_panel.html', {
        'cliente': cliente,
        'pedidos': pedidos,
        'facturas': facturas,
        'facturas_pdf': facturas_emitidas,
        'recent_invoices': recent_invoices,
        'recent_payments': payments[:5],
        'pedidos_activos': pedidos_activos,
        'total_orders': total_orders,
        'total_gastado': total_gastado,
        'facturas_emitidas': facturas_emitidas.count(),
        'pending_payment_count': pending_payment_count,
        'order_statuses': order_statuses,
        'monthly_spend': monthly_spend,
        'has_monthly_spend': bool(max_month_total),
        'profile_completion': profile_completion,
        'profile_checklist': profile_checklist,
        'pago_pendiente': pago_pendiente,
        'factura_reciente': factura_reciente,
    })


def descargar_factura_pdf_cliente(request, factura_id):
    """Permitir al cliente descargar su propia factura en PDF."""
    factura = get_object_or_404(
        Factura.objects.select_related('cliente').prefetch_related('detalles__producto'),
        numero=factura_id,
    )
    user = get_authenticated_django_user(request) or request.user
    if (
        not getattr(user, 'is_authenticated', False)
        or getattr(user, 'is_staff', False)
        or getattr(user, 'is_superuser', False)
        or not getattr(user, 'email', '')
        or factura.cliente.email.casefold() != user.email.casefold()
    ):
        return HttpResponseForbidden('No tienes permiso para descargar esta factura.')

    context = _contexto_factura_pdf(factura)
    html = render_to_string('factura_cliente_pdf.html', context=context, request=request)
    try:
        from weasyprint import HTML
        result = HTML(string=html, base_url=request.build_absolute_uri('/')).write_pdf()
        response = HttpResponse(result, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="factura_{factura.numero}.pdf"'
        return response
    except Exception:
        return HttpResponse('No fue posible generar el PDF. El documento no se ha emitido.', status=503)

def reporte_view(request):
    fecha_hasta = request.GET.get('fecha_hasta')
    hoy = timezone.localdate()
    fecha_hasta_dt = hoy
    if fecha_hasta:
        from datetime import datetime
        try:
            fecha_hasta_dt = datetime.strptime(fecha_hasta, "%Y-%m-%d").date()
            if fecha_hasta_dt > hoy:
                messages.error(request, "No puedes filtrar reportes después del día presente.")
                fecha_hasta_dt = hoy
        except ValueError:
            messages.error(request, "Fecha inválida.")
            fecha_hasta_dt = hoy
        # ...usa fecha_hasta_dt para filtrar...
    # ...lógica de filtrado...
    context = {
        # ...otros contextos...
        'hoy': hoy,
        # ...otros contextos...
    }
    return render(request, 'reporte.html', context)

def cierre_caja_view(request):
    fecha = request.GET.get('fecha')
    hoy = timezone.localdate()
    fecha_dt = hoy
    if fecha:
        from datetime import datetime
        try:
            fecha_dt = datetime.strptime(fecha, "%Y-%m-%d").date()
            if fecha_dt > hoy:
                messages.error(request, "No puedes consultar cierre de caja en fechas futuras.")
                fecha_dt = hoy
        except ValueError:
            messages.error(request, "Fecha inválida.")
            fecha_dt = hoy
        # ...usa fecha_dt para filtrar...
    # ...lógica de cierre de caja...
    context = {
        # ...otros contextos...
        'hoy': hoy,
        # ...otros contextos...
    }
    return render(request, 'cierre_caja.html', context)

from .forms import ClienteRegistroForm  # Asegúrate de tener el formulario importado

@user_passes_test(lambda u: u.is_staff, login_url='login_admin_custom')
def adduser(request):
    if request.method == 'POST':
        form = ClienteRegistroForm(request.POST)
        if form.is_valid():
            cliente = form.save()
            messages.success(request, "Cliente creado correctamente.")
            return redirect('clientes')
    else:
        form = ClienteRegistroForm()
    return render(request, 'adduser.html', {'form': form})

@user_passes_test(lambda u: u.is_staff, login_url='login_admin_custom')
def updtUser(request, cliente_id):
    cliente = get_object_or_404(Cliente, id=cliente_id)
    if request.method == 'POST':
        form = ClienteRegistroForm(request.POST, instance=cliente)
        if form.is_valid():
            form.save()
            messages.success(request, "Cliente actualizado correctamente.")
            return redirect('clientes')
    else:
        form = ClienteRegistroForm(instance=cliente)
    return render(request, 'updtuser.html', {'form': form, 'cliente': cliente})

def reject_staff_google(backend, user=None, response=None, *args, **kwargs):
    email = (response or {}).get('email') if response else None
    if user is not None and (user.is_staff or user.is_superuser):
        raise PermissionDenied('Las cuentas administrativas no pueden usar el acceso cliente.')
    if email and User.objects.filter(email__iexact=email, is_staff=True).exists():
        raise PermissionDenied('Las cuentas administrativas no pueden usar el acceso cliente.')
    return {}


def save_google_email_to_session(backend, user, response, *args, **kwargs):
    request = backend.strategy.request
    email = None
    # Google puede devolver el email en diferentes lugares
    if backend.name == 'google-oauth2':
        email = response.get('email')
    if email:
        request.session['cliente_email'] = email
        request.session.modified = True

    # Si Google devuelve email, vincularlo al User social y reutilizar su carrito.
    try:
        if email:
            from .models import Cliente
            cliente, _ = Cliente.objects.get_or_create(
                email=email.lower(),
                defaults={'nombre': response.get('fullname') or email.split('@')[0]},
            )
            # No reasigna un perfil que ya pertenece a otra cuenta; evita secuestro por email.
            if not cliente.user_id:
                cliente.user = user
                cliente.save(update_fields=['user'])
            # También asegurar registro en tabla central de clientes (app Usuario)
            try:
                usuario_cli = UsuarioClientes.objects.filter(email__iexact=email).first()
                if not usuario_cli:
                    UsuarioClientes.objects.create(
                        nombre=cliente.nombre,
                        apellido='',
                        telefono='',
                        cedula='',
                        direccion='',
                        email=email,
                        fecha_nacimiento='1970-01-01'
                    )
            except Exception:
                pass
            request.session['cliente_id'] = cliente.id
            request.session['cliente_nombre'] = cliente.nombre
            request.session['cliente_email'] = cliente.email
            request.session.modified = True
    except Exception:
        pass


@user_passes_test(lambda u: u.is_staff, login_url='login_admin_custom')
def dashboard(request):
    return _dashboard_overview(request)


@user_passes_test(lambda u: u.is_staff, login_url='login_admin_custom')
@require_POST
@log_view_access
def manual_backup(request):
    """Vista para realizar un backup manual desde el dashboard."""
    from FERREELECTRI_PLUS import backup_utils
    try:
        result = backup_utils.create_backup()
        if result:
            messages.success(request, f'✅ Backup completado: {os.path.basename(result)}')
        else:
            messages.error(request, '❌ Error al crear el backup.')
    except Exception as e:
        messages.error(request, f'❌ Error al crear el backup: {e}')
    return redirect('dashboard')


@user_passes_test(lambda u: u.is_staff, login_url='login_admin_custom')
@log_view_access
def download_latest_backup(request):
    backup_directory = Path(getattr(settings, 'BACKUP_DIRECTORY', Path(settings.BASE_DIR) / 'backups' / 'weekly'))
    archives = sorted(
        backup_directory.glob('ferreelectri-backup-*.tar.gz') if backup_directory.exists() else [],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not archives:
        messages.error(request, 'Todavía no hay un respaldo disponible para descargar.')
        return redirect('dashboard')
    latest = archives[0]
    return FileResponse(latest.open('rb'), as_attachment=True, filename=latest.name, content_type='application/gzip')
