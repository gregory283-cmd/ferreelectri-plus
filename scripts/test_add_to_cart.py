import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'FERREELECTRI_PLUS.settings')
import django
django.setup()
from django.test import Client

client = Client()
response = client.post('/producto/A0001/agregar/', {'cantidad': 1}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
print('STATUS', response.status_code)
print('CONTENT', response.content.decode('utf-8'))
