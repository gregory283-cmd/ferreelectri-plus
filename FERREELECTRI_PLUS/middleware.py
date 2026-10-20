import threading
import logging
import ipaddress
import uuid
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
        user = getattr(request, 'user', None)
        device_session = None
        admin_device = None
        if (
            request.path.startswith('/admin-panel/')
            and getattr(user, 'is_authenticated', False)
            and getattr(user, 'is_staff', False)
            and request.session.session_key
        ):
            from django.contrib.auth import logout
            from django.contrib.sessions.models import Session
            from dashboard.models import AdminDevice, AdminDeviceSession, AdminSecurityConfig

            device_session = AdminDeviceSession.objects.filter(
                session_key=request.session.session_key,
                user=user,
            ).select_related('device').first()
            raw_device_id = request.session.get('admin_device_uuid') or request.COOKIES.get('ferreelectri_admin_device')
            if device_session and device_session.device_id:
                admin_device = device_session.device
                request.session['admin_device_uuid'] = str(admin_device.device_id)
                if not admin_device.name.strip():
                    request.session['admin_device_name_required'] = True
            elif raw_device_id:
                try:
                    admin_device = AdminDevice.objects.filter(
                        user=user,
                        device_id=uuid.UUID(str(raw_device_id)),
                    ).first()
                except (AttributeError, TypeError, ValueError):
                    admin_device = None
                if admin_device and not admin_device.name.strip():
                    request.session['admin_device_name_required'] = True
            if admin_device:
                request.session['admin_device_uuid'] = str(admin_device.device_id)

            security_config = AdminSecurityConfig.objects.filter(pk=1).only(
                'owner_user_id', 'primary_passkey_id',
            ).first()
            primary_session = bool(
                admin_device
                and admin_device.is_primary
                and security_config
                and security_config.owner_user_id == user.pk
                and security_config.primary_passkey_id
                and admin_device.passkey_id == security_config.primary_passkey_id
                and str(request.session.get('admin_device_uuid')) == str(admin_device.device_id)
            )
            if admin_device and not admin_device.is_active and primary_session:
                AdminDevice.objects.filter(pk=admin_device.pk).update(is_active=True)
                admin_device.is_active = True
            if admin_device and not admin_device.is_active:
                session_keys = list(
                    AdminDeviceSession.objects.filter(device=admin_device).values_list('session_key', flat=True)
                )
                Session.objects.filter(session_key__in=session_keys).delete()
                AdminDeviceSession.objects.filter(device=admin_device).update(is_active=False)
                logout(request)
                return redirect('login_admin_custom')
            if device_session and not device_session.is_active:
                if primary_session:
                    AdminDeviceSession.objects.filter(pk=device_session.pk).update(is_active=True)
                    device_session.is_active = True
                else:
                    Session.objects.filter(session_key=request.session.session_key).delete()
                    logout(request)
                    return redirect('login_admin_custom')

        if (
            request.path.startswith('/admin-panel/')
            and getattr(user, 'is_authenticated', False)
            and getattr(user, 'is_staff', False)
            and request.session.get('admin_device_name_required')
            and request.path not in {'/admin-panel/device/name/', '/admin-panel/app-session/lock/'}
        ):
            if device_session and device_session.is_active:
                return redirect('admin_device_name')

        response = self.get_response(request)
        user = getattr(request, 'user', None)
        if (
            request.path.startswith('/admin-panel/')
            and getattr(user, 'is_authenticated', False)
            and getattr(user, 'is_staff', False)
            and request.session.session_key
        ):
            from django.utils import timezone
            from dashboard.models import AdminDevice, AdminDeviceSession

            session_key = request.session.session_key
            last_refresh = timezone.now() - timezone.timedelta(seconds=30)
            if admin_device is None:
                raw_device_id = request.session.get('admin_device_uuid') or request.COOKIES.get('ferreelectri_admin_device')
                if raw_device_id:
                    try:
                        admin_device = AdminDevice.objects.filter(
                            user=user,
                            device_id=uuid.UUID(str(raw_device_id)),
                        ).first()
                    except (AttributeError, TypeError, ValueError):
                        admin_device = None
            defaults = {
                'user': user,
                'device': admin_device,
                'passkey_id': request.session.get('admin_current_passkey_id'),
                'name': admin_device.name if admin_device else '',
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
                or device_session.passkey_id != defaults['passkey_id']
            ):
                AdminDeviceSession.objects.filter(pk=device_session.pk).update(**defaults)
            if admin_device:
                if admin_device.last_seen_at < last_refresh:
                    AdminDevice.objects.filter(pk=admin_device.pk).update(
                        last_seen_at=timezone.now(),
                        ip_address=defaults['ip_address'],
                        user_agent=defaults['user_agent'],
                    )
                response.set_cookie(
                    'ferreelectri_admin_device',
                    str(admin_device.device_id),
                    max_age=60 * 60 * 24 * 365 * 3,
                    secure=request.is_secure(),
                    httponly=True,
                    samesite='Lax',
                )
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


