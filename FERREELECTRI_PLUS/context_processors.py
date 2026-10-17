from django.conf import settings
from django.urls import reverse


def cart_summary(request):
    from dashboard.models import Carrito, Cliente
    from Inventario.models import Productos

    user = getattr(request, 'user', None)
    if getattr(user, 'is_authenticated', False):
        if getattr(user, 'is_staff', False) or getattr(user, 'is_superuser', False):
            return {'cantidad_carrito': 0}

        customer = getattr(request, 'customer', None)
        if not customer and hasattr(user, 'ensure_cliente_profile'):
            customer = user
        if customer:
            cliente = customer.ensure_cliente_profile()
        else:
            cliente = Cliente.objects.filter(user=user).first()
            if not cliente and getattr(user, 'email', None):
                cliente = Cliente.objects.filter(email__iexact=user.email).first()

        carrito = Carrito.objects.filter(cliente=cliente).first() if cliente else None
        if carrito:
            return {'cantidad_carrito': carrito.items.count()}

    anon_cart = request.session.get('anon_cart', {}) or {}
    product_codes = [
        str(code) for code, quantity in anon_cart.items()
        if str(quantity).isdigit() and int(quantity) > 0
    ]
    return {
        'cantidad_carrito': Productos.objects.filter(Codigo__in=product_codes).count()
        if product_codes else 0,
    }


def security_flags(request):
    return {'ADMIN_LOGIN_GATE_ENABLED': not settings.DEBUG}


def admin_pwa_settings(request):
    user = getattr(request, 'user', None)
    is_admin = bool(
        getattr(user, 'is_authenticated', False)
        and (getattr(user, 'is_staff', False) or getattr(user, 'is_superuser', False))
    )
    return {
        'ADMIN_WEBPUSH_PUBLIC_KEY': (
            settings.ADMIN_WEBPUSH_VAPID_PUBLIC_KEY if is_admin else ''
        ),
    }


def google_client_id(request):
    host = request.get_host().lower()
    normalized_host = host.replace('[::1]', 'localhost').replace('0.0.0.0', 'localhost')

    if normalized_host.startswith('localhost') or normalized_host.startswith('127.0.0.1') or normalized_host.startswith('::1'):
        login_uri = 'http://localhost:8000' + reverse('google_identity_login')
    else:
        scheme = 'https' if request.is_secure() else 'http'
        login_uri = f'{scheme}://{request.get_host()}{reverse("google_identity_login")}'

    return {
        'GOOGLE_CLIENT_ID': getattr(settings, 'SOCIAL_AUTH_GOOGLE_OAUTH2_KEY', ''),
        'GOOGLE_LOGIN_URI': login_uri,
    }


def user_avatar(request):
    avatar_url = ''
    fallback = 'neutral'
    initials = ''
    full_name = ''
    if request.user.is_authenticated:
        user = request.user
        if not hasattr(user, 'email') or not isinstance(user, type(request.user)):
            from dashboard.views import get_authenticated_django_user
            user = get_authenticated_django_user(request) or user

        if isinstance(user, type(request.user)) and not hasattr(user, 'get_full_name'):
            user = getattr(request.user, 'get_full_name', lambda: '') and request.user

        if hasattr(user, 'get_full_name'):
            full_name = user.get_full_name() or getattr(user, 'username', '')
            initials = ''.join([word[0].upper() for word in full_name.split() if word])[:2]

            # Buscar foto de Google en social auth extra_data.
            social_auth = getattr(user, 'social_auth', None)
            if social_auth is not None:
                google_account = social_auth.filter(provider__iexact='google-oauth2').first() or social_auth.filter(provider__icontains='google').first()
                if google_account:
                    extra_data = getattr(google_account, 'extra_data', {}) or {}
                    avatar_url = extra_data.get('picture') or extra_data.get('profile_pic') or ''

            # Soporte para django-allauth social accounts si está activo.
            social_account_set = getattr(user, 'socialaccount_set', None)
            if not avatar_url and social_account_set is not None:
                google_account = social_account_set.filter(provider__icontains='google').first()
                if google_account:
                    avatar_url = getattr(google_account, 'get_avatar_url', lambda: '')() or google_account.extra_data.get('picture') or ''

        # Personaliza imagen genérica según sexo del cliente si no hay foto externa.
        try:
            from dashboard.models import Cliente
            django_user = user if hasattr(user, 'email') else request.user
            cliente = Cliente.objects.filter(user=django_user).first() if hasattr(django_user, 'email') else None
            if not cliente and getattr(request.user, 'email', None):
                cliente = Cliente.objects.filter(email__iexact=request.user.email).first()
            if cliente and cliente.sexo:
                fallback = 'female' if cliente.sexo == 'f' else 'male' if cliente.sexo == 'm' else 'neutral'
        except Exception:
            fallback = 'neutral'

    return {
        'user_avatar_url': avatar_url,
        'user_avatar_fallback': fallback,
        'user_initials': initials,
        'user_full_name': full_name,
    }
