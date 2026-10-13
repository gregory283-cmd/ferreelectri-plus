import os
import sys
import traceback

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)
os.environ['DJANGO_SETTINGS_MODULE'] = 'FERREELECTRI_PLUS.settings'
import django

django.setup()

from django.core.mail import send_mail
from django.conf import settings

print('EMAIL_HOST', settings.EMAIL_HOST, settings.EMAIL_PORT, settings.EMAIL_USE_TLS, settings.EMAIL_USE_SSL, settings.EMAIL_HOST_USER, settings.DEFAULT_FROM_EMAIL)
try:
    res = send_mail(
        'Prueba SMTP',
        'Mensaje de prueba',
        settings.EMAIL_HOST_USER,
        [settings.EMAIL_HOST_USER],
        fail_silently=False,
    )
    print('send_mail returned', res)
except Exception:
    traceback.print_exc()
