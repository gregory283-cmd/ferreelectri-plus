"""Configuración del worker Celery para FerreElectri PLUS."""

import os

from celery import Celery

# Permite que Celery cargue la configuración de Django antes de importar tareas.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'FERREELECTRI_PLUS.settings')

# Usa el nombre del proyecto para descubrir automáticamente las tareas de las apps.
app = Celery('FERREELECTRI_PLUS')

# Lee todas las variables CELERY_* declaradas en settings.py.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Busca tasks.py en cada aplicación instalada.
app.autodiscover_tasks()
