from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import User

class EmailOrUsernameBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, customer_only=False, **kwargs):
        if username is None or password is None:
            return None

        username = username.strip()
        user = None

        if '@' in username:
            if customer_only:
                candidates = User.objects.filter(email__iexact=username, is_staff=False, is_superuser=False)
            else:
                candidates = User.objects.filter(email__iexact=username).order_by('-is_staff', '-is_superuser')
            user = candidates.first()
        else:
            try:
                user = User.objects.get(username=username)
            except User.DoesNotExist:
                candidates = User.objects.filter(email__iexact=username)
                if customer_only:
                    candidates = candidates.filter(is_staff=False, is_superuser=False)
                user = candidates.first()

        if user is None:
            return None

        if not self.user_can_authenticate(user):
            return None

        if user.check_password(password):
            return user
        return None