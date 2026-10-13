from django.conf import settings
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.contrib.auth.hashers import check_password
from django.db.models import Q

from .models import Customer


def get_customer_cookie_name():
    return getattr(settings, 'CUSTOMER_SESSION_COOKIE_NAME', 'fe_customer_sessionid')


def get_customer_signer():
    salt = getattr(settings, 'CUSTOMER_AUTH_SIGNING_SALT', 'dashboard.customer.auth')
    return TimestampSigner(salt=salt)


def make_customer_cookie_value(customer_id):
    return get_customer_signer().sign(str(customer_id))


def unsign_customer_cookie(value):
    return get_customer_signer().unsign(
        value,
        max_age=getattr(settings, 'CUSTOMER_SESSION_COOKIE_AGE', 60 * 60 * 24 * 7),
    )


def get_customer_from_request(request):
    cookie_value = request.COOKIES.get(get_customer_cookie_name())
    customer_id = None
    if cookie_value:
        try:
            customer_id = unsign_customer_cookie(cookie_value)
        except (BadSignature, SignatureExpired):
            customer_id = None

    if not customer_id:
        customer_id = request.session.get('customer_id')

    if not customer_id:
        return None

    return Customer.objects.filter(id=customer_id, is_active=True).first()


def login_customer(response, customer):
    response.set_cookie(
        get_customer_cookie_name(),
        make_customer_cookie_value(customer.id),
        max_age=getattr(settings, 'CUSTOMER_SESSION_COOKIE_AGE', 60 * 60 * 24 * 7),
        secure=getattr(settings, 'CUSTOMER_SESSION_COOKIE_SECURE', not settings.DEBUG),
        httponly=getattr(settings, 'CUSTOMER_SESSION_COOKIE_HTTPONLY', True),
        samesite=getattr(settings, 'CUSTOMER_SESSION_COOKIE_SAMESITE', 'Lax'),
        path='/',
    )
    return response


def logout_customer(response):
    response.delete_cookie(get_customer_cookie_name(), path='/')
    return response


class CustomerBackend:
    def authenticate(self, request, username=None, password=None, customer_only=False, **kwargs):
        if not username or not password or not customer_only:
            return None
        username = username.strip()
        lookup = Q(is_active=True) & (
            Q(email__iexact=username) |
            Q(nombre__iexact=username) |
            Q(email__istartswith=f"{username}@")
        )
        customer = Customer.objects.filter(lookup).first()
        if customer and check_password(password, customer.password):
            return customer
        return None

    def get_user(self, user_id):
        return self.get_customer(user_id)

    def get_customer(self, customer_id):
        return Customer.objects.filter(id=customer_id, is_active=True).first()
