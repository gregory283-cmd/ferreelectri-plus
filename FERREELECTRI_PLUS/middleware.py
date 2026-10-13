import threading
import logging
from django.shortcuts import redirect, render
from django.conf import settings
from django.urls import resolve
from django.utils.deprecation import MiddlewareMixin
import threading
from urllib.parse import urlencode
from django.conf import settings

logger = logging.getLogger(__name__)

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
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith('/admin-panel/') and request.path not in self.PUBLIC_PATHS:
            user = getattr(request, 'user', None)
            if not getattr(user, 'is_authenticated', False) or not getattr(user, 'is_staff', False):
                query = urlencode({'next': request.get_full_path()})
                return redirect('/admin-panel/login/?' + query)
        return self.get_response(request)

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


