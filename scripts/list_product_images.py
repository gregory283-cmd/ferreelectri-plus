import os
import sys
from pathlib import Path
import django

# Ensure project root is in sys.path so Django settings module can be imported
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'FERREELECTRI_PLUS.settings')
django.setup()

from Inventario.models import Productos

print('Codigo | Imagen name | Exists on disk')
for p in Productos.objects.all():
    name = p.Imagen.name if p.Imagen else None
    path = os.path.join(os.getcwd(), 'media', name) if name else None
    exists = os.path.exists(path) if path else False
    print(f"{p.Codigo} | {name} | {exists}")
