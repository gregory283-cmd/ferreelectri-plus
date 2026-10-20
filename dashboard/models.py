from django.db import models
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import User
from django.utils.timezone import now
from .storage import PrivatePaymentStorage
from decimal import Decimal
import uuid

class AuditLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=50)
    model_name = models.CharField(max_length=100)
    object_id = models.CharField(max_length=255, null=True, blank=True)  # Cambiado a CharField
    timestamp = models.DateTimeField(default=now)
    details = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)

    def __str__(self):
        return f"{self.action} - {self.model_name} - {self.timestamp}"


class AdminDashboardConfig(models.Model):
    bcv_rate = models.DecimalField(max_digits=14, decimal_places=4, default=Decimal('0.0000'))
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = 'Configuración del panel administrativo'
        verbose_name_plural = 'Configuración del panel administrativo'

    def __str__(self):
        return f'Tasa BCV: {self.bcv_rate}'


class AdminPushSubscription(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='admin_push_subscriptions')
    endpoint_hash = models.CharField(max_length=64, unique=True)
    endpoint = models.TextField()
    subscription = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Suscripción de notificaciones administrativas'
        verbose_name_plural = 'Suscripciones de notificaciones administrativas'

    def __str__(self):
        return f'Notificaciones de {self.user.get_username()}'


class AdminPasskey(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='admin_passkeys')
    credential_id = models.CharField(max_length=1024, unique=True)
    public_key = models.BinaryField()
    sign_count = models.PositiveBigIntegerField(default=0)
    name = models.CharField(max_length=80, default='Llave de acceso')
    transports = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Llave de acceso administrativa'
        verbose_name_plural = 'Llaves de acceso administrativas'

    def __str__(self):
        return f'{self.name} · {self.user.get_username()}'


class AdminDevice(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='admin_devices')
    device_id = models.UUIDField(default=uuid.uuid4, editable=False)
    passkey = models.ForeignKey(
        AdminPasskey, null=True, blank=True, on_delete=models.SET_NULL, related_name='admin_devices',
    )
    name = models.CharField(max_length=80, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    first_seen_at = models.DateTimeField(default=now)
    last_seen_at = models.DateTimeField(default=now)
    is_active = models.BooleanField(default=True)
    is_primary = models.BooleanField(default=False)

    class Meta:
        verbose_name = 'Dispositivo administrativo'
        verbose_name_plural = 'Dispositivos administrativos'
        indexes = [models.Index(fields=['user', 'is_active', 'last_seen_at'])]
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'device_id'],
                name='dash_device_uuid_per_user',
            ),
            models.UniqueConstraint(
                fields=['user'],
                condition=models.Q(is_primary=True),
                name='dash_one_primary_device_user',
            ),
        ]

    def __str__(self):
        return f'{self.name or "Dispositivo sin nombre"} · {self.user.get_username()}'


class AdminDeviceSession(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='admin_device_sessions')
    device = models.ForeignKey(
        AdminDevice, null=True, blank=True, on_delete=models.SET_NULL, related_name='sessions',
    )
    passkey = models.ForeignKey(
        AdminPasskey, null=True, blank=True, on_delete=models.SET_NULL, related_name='device_sessions',
    )
    session_key = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=80, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    last_seen_at = models.DateTimeField(default=now)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Sesión administrativa por dispositivo'
        verbose_name_plural = 'Sesiones administrativas por dispositivo'
        indexes = [models.Index(fields=['user', 'is_active', 'last_seen_at'])]


class AdminSecurityConfig(models.Model):
    owner_user = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name='owned_admin_security_configs',
    )
    primary_passkey = models.ForeignKey(
        AdminPasskey, null=True, blank=True, on_delete=models.SET_NULL, related_name='primary_security_configs',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Propietario de seguridad administrativa'
        verbose_name_plural = 'Propietario de seguridad administrativa'

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)


class DevelopmentRequest(models.Model):
    class Priority(models.TextChoices):
        HIGH = 'high', 'Alta'
        MEDIUM = 'medium', 'Media'
        LOW = 'low', 'Baja'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pendiente'
        IN_PROGRESS = 'in_progress', 'En desarrollo'
        COMPLETED = 'completed', 'Completada'

    objective = models.CharField(max_length=240)
    priority = models.CharField(max_length=12, choices=Priority.choices, default=Priority.MEDIUM)
    acceptance_criteria = models.TextField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    requested_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='development_requests')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Solicitud de desarrollo'
        verbose_name_plural = 'Solicitudes de desarrollo'
        ordering = ['status', '-created_at']

    def __str__(self):
        return self.objective


class AdminLoginApproval(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pendiente'
        APPROVED = 'approved', 'Aprobada'
        DENIED = 'denied', 'Denegada'
        EXPIRED = 'expired', 'Vencida'
        COMPLETED = 'completed', 'Completada'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='admin_login_approvals')
    requester_session_key = models.CharField(max_length=40)
    active_session_key = models.CharField(max_length=40)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    responded_at = models.DateTimeField(null=True, blank=True)
    responded_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name='responded_admin_login_approvals',
    )

    class Meta:
        verbose_name = 'Aprobación de acceso administrativo'
        verbose_name_plural = 'Aprobaciones de acceso administrativo'
        indexes = [models.Index(fields=['user', 'active_session_key', 'status', 'expires_at'])]


class Customer(models.Model):
    nombre = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    cedula = models.CharField(max_length=20, unique=True, null=True, blank=True, default=None)
    password = models.CharField(max_length=128)
    telefono = models.CharField(max_length=20, blank=True)
    direccion = models.CharField(max_length=255, blank=True)
    cliente = models.OneToOneField(
        'Cliente', on_delete=models.SET_NULL, null=True, blank=True, related_name='customer_account'
    )
    is_active = models.BooleanField(default=True)
    email_verified = models.BooleanField(default=True)
    is_guest = models.BooleanField(default=False)
    fecha_registro = models.DateTimeField(auto_now_add=True)
    last_login = models.DateTimeField(null=True, blank=True)

    @property
    def is_authenticated(self):
        return True

    @property
    def is_anonymous(self):
        return False

    @property
    def is_staff(self):
        return False

    @property
    def is_superuser(self):
        return False

    @property
    def username(self):
        return self.email

    @property
    def first_name(self):
        if not self.nombre:
            return ''
        return self.nombre.split()[0]

    @property
    def last_name(self):
        if not self.nombre:
            return ''
        parts = self.nombre.split()
        if len(parts) <= 1:
            return ''
        return ' '.join(parts[1:])

    @property
    def perfil_cliente(self):
        if not self.email:
            return None
        user = User.objects.filter(email__iexact=self.email, is_active=True).first()
        if user is None:
            return None
        return getattr(user, 'perfil_cliente', None)

    def get_username(self):
        return self.email

    def get_full_name(self):
        return self.nombre or self.email

    def set_password(self, raw_password):
        self.password = make_password(raw_password)
        return self

    def check_password(self, raw_password):
        return check_password(raw_password, self.password)

    def ensure_cliente_profile(self):
        cliente = self.cliente or Cliente.objects.filter(email__iexact=self.email).first()
        if not cliente:
            cliente = Cliente.objects.create(
                user=None,
                nombre=self.nombre,
                email=self.email,
                cedula=self.cedula,
                telefono=self.telefono,
                direccion=self.direccion,
            )
        else:
            updated_fields = []
            for field in ('nombre', 'cedula', 'telefono', 'direccion'):
                value = getattr(self, field)
                if value and getattr(cliente, field) != value:
                    setattr(cliente, field, value)
                    updated_fields.append(field)
            if updated_fields:
                cliente.save(update_fields=updated_fields)
        self.cliente = cliente
        self.save(update_fields=['cliente'])
        return cliente

    def __str__(self):
        return self.email

    class Meta:
        verbose_name = 'Customer'
        verbose_name_plural = 'Customers'


class ChatSession(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name='ai_chat_sessions')
    session_key = models.CharField(max_length=40, null=True, blank=True)
    title = models.CharField(max_length=120, default='Nueva Consulta')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('-created_at',)
        verbose_name = 'Sesión de chat IA'
        verbose_name_plural = 'Sesiones de chat IA'

    def __str__(self):
        owner = self.user.get_username() if self.user else self.session_key or 'invitado'
        return f'{self.title} - {owner}'


class ChatMessage(models.Model):
    ROLE_CHOICES = (
        ('user', 'Usuario'),
        ('assistant', 'Asistente'),
        ('system', 'Sistema'),
    )

    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name='messages')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    content = models.TextField()
    action_type = models.CharField(max_length=50, null=True, blank=True)
    action_payload = models.JSONField(null=True, blank=True)
    timestamp = models.DateTimeField(default=now)

    class Meta:
        ordering = ('timestamp', 'id')
        verbose_name = 'Mensaje de chat IA'
        verbose_name_plural = 'Mensajes de chat IA'

    def __str__(self):
        return f'{self.role}: {self.content[:60]}'

class Producto(models.Model):
    nombre = models.CharField(max_length=100)
    descripcion = models.TextField(blank=True)
    precio = models.DecimalField(max_digits=10, decimal_places=2)
    imagen = models.ImageField(upload_to='productos/', blank=True, null=True)
    stock = models.PositiveIntegerField(default=0)
    disponible = models.BooleanField(default=True)

    def __str__(self):
        return self.nombre

class Cliente(models.Model):
    SEXO_CHOICES = [
        ('m', 'Masculino'),
        ('f', 'Femenino'),
        ('o', 'Otro'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, null=True, blank=True)
    nombre = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    cedula = models.CharField(max_length=20, unique=True, null=True, blank=True, default=None)
    telefono = models.CharField(max_length=20, blank=True)
    direccion = models.CharField(max_length=255, blank=True)
    sexo = models.CharField(max_length=1, choices=SEXO_CHOICES, blank=True, null=True)

    def __str__(self):
        return self.nombre

    def avatar_fallback(self):
        if self.sexo == 'f':
            return 'female'
        if self.sexo == 'm':
            return 'male'
        return 'neutral'


class PerfilCliente(models.Model):
    """Perfil fiscal y de contacto del cliente autenticado con Django User."""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='perfil_cliente')
    razon_social = models.CharField(max_length=200, blank=True, default='')
    cedula_rif = models.CharField(max_length=30, blank=True, default='')
    telefono = models.CharField(max_length=20, blank=True, default='')
    direccion = models.CharField(max_length=255, blank=True, default='')
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Perfil Cliente'
        verbose_name_plural = 'Perfiles Clientes'

    def __str__(self):
        return f'Perfil de {self.user.get_full_name() or self.user.username}'

class Carrito(models.Model):
    cliente = models.OneToOneField(Cliente, on_delete=models.CASCADE)
    creado = models.DateTimeField(auto_now_add=True)

class CarritoItem(models.Model):
    carrito = models.ForeignKey(Carrito, on_delete=models.CASCADE, related_name='items')
    producto = models.ForeignKey('Inventario.Productos', on_delete=models.CASCADE)
    cantidad = models.PositiveIntegerField(default=1)
    presentacion_type = models.CharField(max_length=120, blank=True, null=True)
    presentacion_factor = models.PositiveIntegerField(default=1)

    class Meta:
        unique_together = ('carrito', 'producto')

    def subtotal(self):
        return (self.producto.Precio or 0) * self.cantidad

class Pedido(models.Model):
    ESTADO_CHOICES = [
        ('pendiente', 'PENDIENTE'),
        ('pagado', 'PAGADO'),
        ('enviado', 'ENVIADO'),
        ('cancelado', 'CANCELADO'),
    ]
    ESTADO_OPERATIVO_CHOICES = [
        ('pendiente_pago', 'Pendiente de pago'),
        ('confirmado', 'Confirmado'),
        ('cancelado', 'Cancelado'),
        ('completado', 'Completado'),
    ]
    cliente = models.ForeignKey(User, on_delete=models.CASCADE)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    estado = models.CharField(max_length=30, choices=ESTADO_CHOICES, default='pendiente')
    estado_operativo = models.CharField(
        max_length=24,
        choices=ESTADO_OPERATIVO_CHOICES,
        default='pendiente_pago',
    )
    requiere_revision_operativa = models.BooleanField(default=False)
    stock_descontado = models.BooleanField(default=False)

    class Meta:
        permissions = [
            ('view_operational_orders', 'Puede consultar pedidos operativos'),
            ('verify_order_payments', 'Puede verificar pagos de pedidos'),
        ]

    def __str__(self):
        return f"Pedido #{self.id} - {self.cliente.email if self.cliente else 'Usuario'} - {self.estado}"

    def save(self, *args, **kwargs):
        if self.estado:
            self.estado = self.estado.lower()
        super().save(*args, **kwargs)

    @property
    def creado(self):
        return self.fecha_creacion

    @property
    def is_pagado(self):
        return self.estado == 'pagado'

    @property
    def is_enviado(self):
        return self.estado == 'enviado'

    def items_count(self):
        return self.items.aggregate(total=models.Sum('cantidad'))['total'] or 0

    def total_display(self):
        return f"{self.total:.2f}"

class PedidoItem(models.Model):
    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name='items')
    producto = models.ForeignKey('Inventario.Productos', on_delete=models.SET_NULL, null=True, blank=True)
    cantidad = models.PositiveIntegerField()
    precio = models.DecimalField(max_digits=10, decimal_places=2)
    iva = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('16.00'))

    def subtotal(self):
        return self.precio * self.cantidad


class Envio(models.Model):
    ESTADO_CHOICES = [
        ('no_preparado', 'No preparado'),
        ('preparando', 'Preparando'),
        ('listo', 'Listo para despacho'),
        ('despachado', 'Despachado'),
        ('en_transito', 'En tránsito'),
        ('entregado', 'Entregado'),
        ('incidencia', 'Incidencia'),
        ('devuelto', 'Devuelto'),
    ]

    pedido = models.OneToOneField(Pedido, on_delete=models.CASCADE, related_name='envio')
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='no_preparado')
    nombre_destinatario = models.CharField(max_length=180, blank=True, default='')
    telefono = models.CharField(max_length=30, blank=True, default='')
    direccion = models.CharField(max_length=500, blank=True, default='')
    transportista = models.CharField(max_length=100, blank=True, default='')
    numero_guia = models.CharField(max_length=100, blank=True, default='')
    url_seguimiento = models.URLField(max_length=500, blank=True, default='')
    requiere_revision = models.BooleanField(default=False)
    observaciones = models.TextField(blank=True, default='')
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        permissions = [
            ('manage_fulfillment', 'Puede gestionar preparación y envíos'),
        ]

    def __str__(self):
        return f'Envío del pedido #{self.pedido_id} - {self.estado}'


class EnvioEvento(models.Model):
    envio = models.ForeignKey(Envio, on_delete=models.CASCADE, related_name='eventos')
    estado_anterior = models.CharField(max_length=20, choices=Envio.ESTADO_CHOICES, blank=True, default='')
    estado_nuevo = models.CharField(max_length=20, choices=Envio.ESTADO_CHOICES)
    actor = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    descripcion = models.CharField(max_length=240, blank=True, default='')
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('creado', 'pk')


class Pago(models.Model):
    METODOS = (
        ('STRIPE', 'Stripe'),
        ('PAYPAL', 'PayPal'),
        ('PAGO_MOVIL', 'Pago Móvil'),
        ('TRANSFERENCIA', 'Transferencia bancaria'),
        ('COMPROBANTE', 'Comprobante manual'),
        ('ZELLE', 'Zelle'),
        ('BINANCE', 'Binance'),
    )
    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name='pagos')
    metodo = models.CharField(max_length=20, choices=METODOS)
    monto = models.DecimalField(max_digits=12, decimal_places=2)
    referencia = models.CharField(max_length=200, blank=True)
    banco_origen = models.CharField(max_length=100, blank=True, default='')
    cedula_pagador = models.CharField(max_length=30, blank=True, default='')
    numero_referencia = models.CharField(max_length=100, blank=True, default='')
    comprobante = models.ImageField(storage=PrivatePaymentStorage(), upload_to='comprobantes/', null=True, blank=True)
    verificado = models.BooleanField(default=False)
    ESTADO_CHOICES = (
        ('pendiente', 'Pendiente'),
        ('en_revision', 'En revisión'),
        ('confirmado', 'Confirmado'),
        ('rechazado', 'Rechazado'),
        ('reembolsado', 'Reembolsado'),
        ('reembolso_parcial', 'Reembolso parcial'),
        ('disputado', 'Disputado'),
    )
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='pendiente')
    gateway = models.CharField(max_length=20, blank=True, default='')
    gateway_reference = models.CharField(max_length=200, blank=True, default='')
    gateway_payload = models.TextField(blank=True, default='')
    gateway_status = models.CharField(max_length=30, blank=True, default='pending')
    gateway_signature = models.CharField(max_length=200, blank=True, default='')
    observaciones = models.TextField(blank=True, default='')
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        permissions = [
            ('view_payment_evidence', 'Puede consultar comprobantes de pago privados'),
        ]

    def save(self, *args, **kwargs):
        if self.metodo:
            self.metodo = self.metodo.upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Pago #{self.id} - {self.pedido.id} - {self.metodo} - {'Verificado' if self.verificado else 'No verificado'}"


class PedidoArchivado(models.Model):
    original = models.OneToOneField(Pedido, on_delete=models.SET_NULL, null=True, blank=True)
    cliente_nombre = models.CharField(max_length=200)
    cliente_email = models.CharField(max_length=200)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    fecha_archivo = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"PedidoArchivado #{self.id} - {self.cliente_nombre} - {self.total}"

