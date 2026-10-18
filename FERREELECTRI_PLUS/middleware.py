import threading
import logging
import ipaddress
from django.shortcuts import redirect, render
from django.conf import settings
from django.urls import resolve
from django.utils.deprecation import MiddlewareMixin
import threading
from urllib.parse import urlencode
from django.conf import settings

logger = logging.getLogger(__name__)


def get_client_ip(request):
    if getattr(settings, 'RENDER_EXTERNAL_HOSTNAME', ''):
        forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR', '')
        if forwarded_for:
            candidate = forwarded_for.split(',')[0].strip()
            try:
                return str(ipaddress.ip_address(candidate))
            except ValueError:
                pass
    candidate = request.META.get('REMOTE_ADDR', '')
    try:
        return str(ipaddress.ip_address(candidate)) if candidate else None
    except ValueError:
        return None

_thread_locals = threading.local()

def get_current_user():
    return getattr(_thread_locals, 'user', None)

class CurrentUserMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        _thread_locals.user = user if getattr(user, 'is_authenticated', False) else None
        response = self.get_response(request)
        return response

class CustomerSessionMiddleware:
    """Carga `request.customer` usando la cookie/token de cliente independiente."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.customer = None
        try:
            user = getattr(request, 'user', None)
            if getattr(user, 'is_authenticated', False) and (getattr(user, 'is_staff', False) or getattr(user, 'is_superuser', False)):
                return self.get_response(request)
            from dashboard.customer_auth import get_customer_from_request
            request.customer = get_customer_from_request(request)
        except Exception:
            request.customer = None
        return self.get_response(request)


class AdminPanelIsolationMiddleware:
    """Impide que una identidad cliente alcance cualquier endpoint administrativo."""
    PUBLIC_PATHS = {
        '/admin-panel/login/',
        '/admin-panel/staff/login/',
        '/admin-panel/desbloquear/',
        '/admin-panel/recuperar/',
        '/admin-panel/solicitar-recuperacion/',
        '/admin-panel/recuperar-codigo/',
        '/admin-panel/passkeys/login/options/',
        '/admin-panel/passkeys/login/verify/',
        '/admin-panel/passkeys/recovery/options/',
        '/admin-panel/passkeys/recovery/verify/',
        '/admin-panel/app-session/lock/',
        '/admin-panel/app-launch/',
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        public_session_status = request.path.startswith('/admin-panel/session-approval/status/')
        if request.path.startswith('/admin-panel/') and request.path not in self.PUBLIC_PATHS and not public_session_status:
            user = getattr(request, 'user', None)
            if not getattr(user, 'is_authenticated', False) or not getattr(user, 'is_staff', False):
                query = urlencode({'next': request.get_full_path()})
                return redirect('/admin-panel/login/?' + query)
        return self.get_response(request)


class AdminDeviceSessionMiddleware:
    """Keeps a short-lived record of each authenticated administrative session."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        user = getattr(request, 'user', None)
        if (
            request.path.startswith('/admin-panel/')
            and getattr(user, 'is_authenticated', False)
            and getattr(user, 'is_staff', False)
            and request.session.session_key
        ):
            from django.utils import timezone
            from dashboard.models import AdminDeviceSession

            session_key = request.session.session_key
            last_refresh = timezone.now() - timezone.timedelta(seconds=30)
            defaults = {
                'user': user,
                'passkey_id': request.session.get('admin_current_passkey_id'),
                'ip_address': get_client_ip(request),
                'user_agent': request.META.get('HTTP_USER_AGENT', '')[:1000],
                'last_seen_at': timezone.now(),
                'is_active': True,
            }
            device_session = AdminDeviceSession.objects.filter(session_key=session_key).first()
            if device_session is None:
                AdminDeviceSession.objects.create(session_key=session_key, **defaults)
            elif (
                device_session.last_seen_at < last_refresh
                or not device_session.is_active
                or device_session.passkey_id != defaults['passkey_id']
            ):
                AdminDeviceSession.objects.filter(pk=device_session.pk).update(**defaults)
        return response

class LoginRequiredMiddleware:
    """
    Middleware que redirige a los usuarios no autenticados al login.
    """
    EXEMPT_URLS = [
        '/login/',
        '/staff/login/',
        '/admin-panel/login/',
        '/admin-panel/staff/login/',
        '/registro/',
        '/recuperar/',
        '/solicitar-recuperacion/',
        '/recuperar-codigo/',
        '/admin-panel/recuperar/',
        '/admin-panel/solicitar-recuperacion/',
        '/cliente/recuperar/',
        '/cliente/solicitar-recuperacion/',
        '/cliente/recuperar-codigo/',
        '/static/',
        '/media/',
        '/admin/login/',
        '/portal-acceso-ferre-99x/',
        '/cliente/login/',
        '/cliente/registro/',
        '/oauth/',
        '/manifest.webmanifest',
        '/service-worker.js',
        '/admin-panel/app-session/lock/',
        '/admin-panel/session-approval/status/',
        '/admin-panel/app-launch/',
        '/pwa/icons/',
    ]
    
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Proteger rutas de /admin/ para que solo staff pueda acceder (excepto login)
        try:
            if request.path.startswith('/admin/') and not request.path.startswith('/admin/login/'):
                if not (hasattr(request, 'user') and request.user.is_authenticated and request.user.is_staff):
                    return redirect(settings.LOGIN_URL)
        except Exception:
            pass

        if not request.user.is_authenticated:
            if not any(request.path == path or request.path.startswith(path) for path in self.EXEMPT_URLS):
                return redirect(settings.LOGIN_URL)
        return self.get_response(request)

class NoCacheMiddleware(MiddlewareMixin):
    def process_response(self, request, response):
        response['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response['Pragma'] = 'no-cache'
        response['Expires'] = '0'
        return response

class CustomExceptionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            response = self.get_response(request)
        except Exception as e:
            logger.exception("Error no controlado: %s", e)
            if settings.DEBUG:
                raise
            return render(request, "error_500.html", status=500)
        return response


