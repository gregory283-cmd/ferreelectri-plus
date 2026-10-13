from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import User
from django.db.models import Q


class EmailOrUsernameModelBackend(ModelBackend):
    """Autenticación por username o email.

    Permite admin/staff cuando el inicio de sesión se realiza desde la ruta de
    administrador real (/login/ o /staff/login/), pero bloquea esos usuarios en
    el frontend de cliente.
    """

    def authenticate(self, request=None, username=None, password=None, **kwargs):
        if username is None or password is None:
            return None

        username = str(username).strip()
        if not username:
            return None

        lookup = Q(username__iexact=username) | Q(email__iexact=username)

        allow_admin = False
        if request is not None:
            path = getattr(request, 'path', '') or ''
            allow_admin = (
                path.startswith('/login')
                or path.startswith('/staff/login')
                or path.startswith('/admin')
                or path.startswith('/portal-acceso-ferre-99x/')
                or path.startswith('/portal-acceso-ferre-99x/admin')
            )

        queryset = User.objects.filter(lookup)
        if not allow_admin and request is not None:
            queryset = queryset.exclude(is_staff=True, is_superuser=True)

        user = queryset.first()
        if user is None:
            return None

        if not self.user_can_authenticate(user):
            return None

        if user.check_password(password):
            return user

        return None
