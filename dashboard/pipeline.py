from django.db import transaction

from .models import Cliente
from .services import sync_admin_cliente_record

def save_cliente_google(backend, user, response, *args, **kwargs):
    email = response.get('email')
    nombre = response.get('name')
    if not email:
        return

    # Reutiliza el perfil por correo y lo vincula al User social autenticado.
    with transaction.atomic():
        cliente, _ = Cliente.objects.get_or_create(
            email=email.lower(),
            defaults={'nombre': nombre or email.split('@')[0]},
        )
        if not cliente.user_id:
            cliente.user = user
            cliente.save(update_fields=['user'])
    # Guarda el cliente en sesión
    request = backend.strategy.request
    cliente = Cliente.objects.filter(email__iexact=email).first()
    if cliente:
        sync_admin_cliente_record(cliente)
        request.session['cliente_id'] = cliente.id
        request.session['cliente_nombre'] = cliente.nombre
        request.session['cliente_email'] = cliente.email