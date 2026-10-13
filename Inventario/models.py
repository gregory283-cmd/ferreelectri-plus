from django.db import models
from django.conf import settings
from django.utils import timezone
from django.utils.text import slugify
from django.core.validators import MinValueValidator
from django.core.exceptions import ValidationError
from decimal import Decimal

# Create your models here.

class Productos(models.Model):
    IVA_CHOICES = (
        (Decimal('0.00'), 'Exento (0%)'),
        (Decimal('16.00'), 'Gravado (16%)'),
    )

    Codigo = models.CharField(max_length=10, primary_key=True, unique=True, editable=False)
    Descripcion = models.CharField(max_length=100)
    Precio = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)])
    iva = models.DecimalField(max_digits=5, decimal_places=2, choices=IVA_CHOICES, default=Decimal('16.00'))
    Costo = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    Cantidad = models.PositiveIntegerField(default=0)
    promocion = models.BooleanField(default=False)
    orden_lista = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    Fecha_creacion = models.DateField(auto_now_add=True)
    Imagen = models.ImageField(upload_to='productos/', blank=True, null=True)
    presentations = models.JSONField(blank=True, default=list)
    Categoria = models.ForeignKey('Categoria', on_delete=models.SET_NULL, null=True, blank=True)

    def save(self, *args, **kwargs):
        # Validaciones básicas antes de guardar
        if self.Precio is None:
            # Si no hay precio definido, dejar 0.00 para evitar nulls en ventas
            self.Precio = 0
        if self.Costo is None:
            self.Costo = 0
        if self.Costo < 0 or self.Precio < 0:
            raise ValidationError('El costo y el precio no pueden ser negativos.')

        if not self.Codigo:
            last = Productos.objects.filter(Codigo__startswith='A').order_by('-Codigo').first()
            if last and isinstance(last.Codigo, str) and last.Codigo[1:].isdigit():
                next_num = int(last.Codigo[1:]) + 1
            else:
                next_num = 1
            self.Codigo = f"A{next_num:04d}"
        # Ejecutar validaciones de modelo
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.Descripcion


class PresentacionProducto(models.Model):
    producto = models.ForeignKey(Productos, on_delete=models.CASCADE, related_name='presentaciones')
    nombre = models.CharField(max_length=100)
    factor = models.DecimalField(max_digits=10, decimal_places=2)
    unidad_medida = models.CharField(max_length=50)

    def __str__(self):
        return f"{self.nombre} ({self.factor} {self.unidad_medida})"


class Categoria(models.Model):
    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(max_length=100, unique=True, blank=True)

    class Meta:
        verbose_name = 'Categoría'
        verbose_name_plural = 'Categorías'

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.name)[:90]
            slug = base_slug
            counter = 0
            while Categoria.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                counter += 1
                slug = f"{base_slug}-{counter}"
            self.slug = slug
        super().save(*args, **kwargs)

    @property
    def imagen_representativa_url(self):
        category_image = getattr(self, 'imagen', None)
        if category_image:
            return category_image.url

        first_product = (
            self.productos_set
            .filter(Imagen__isnull=False)
            .exclude(Imagen='')
            .order_by('pk')
            .first()
        )
        if first_product and first_product.Imagen:
            return first_product.Imagen.url

        return None

    def __str__(self):
        return self.name

class MovimientoInventario(models.Model):
    TIPO_CHOICES = (
        ('entrada', 'Entrada'),
        ('salida', 'Salida'),
    )
    producto = models.ForeignKey(Productos, on_delete=models.CASCADE)
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES)
    cantidad = models.PositiveIntegerField()
    fecha = models.DateTimeField(default=timezone.now)
    descripcion = models.CharField(max_length=255, blank=True)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )  # <--- AGREGADO

    def __str__(self):
        return f"{self.get_tipo_display()} - {self.producto.Descripcion} ({self.cantidad})"


class CostoCambio(models.Model):
    producto = models.ForeignKey(Productos, on_delete=models.CASCADE)
    anterior = models.DecimalField(max_digits=10, decimal_places=2)
    nuevo = models.DecimalField(max_digits=10, decimal_places=2)
    fecha = models.DateTimeField(default=timezone.now)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    motivo = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f"Cambio Costo {self.producto.Codigo}: {self.anterior} -> {self.nuevo}"


class CostoLote(models.Model):
    producto = models.ForeignKey(Productos, on_delete=models.CASCADE, related_name='lotes_costo')
    compra_id = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    costo_unitario = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    cantidad_recibida = models.PositiveIntegerField()
    cantidad_disponible = models.PositiveIntegerField()
    cantidad_anulada = models.PositiveIntegerField(default=0)
    recibido_en = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ['recibido_en', 'pk']
        indexes = [models.Index(fields=['producto', 'cantidad_disponible', 'recibido_en'], name='inv_cost_lot_fifo_idx')]

    def __str__(self):
        return f'{self.producto.Codigo}: {self.cantidad_disponible}/{self.cantidad_recibida} a {self.costo_unitario}'


class CostoPendiente(models.Model):
    UNIDADES_COMPRA = (
        ('unidades', 'Unidades'),
        ('cajas', 'Cajas'),
        ('paquetes', 'Paquetes'),
        ('lotes', 'Lotes'),
        ('rollos', 'Rollos'),
        ('kits', 'Kits'),
    )
    ESTADOS = (
        ('espera_stock', 'Esperando agotamiento del costo anterior'),
        ('pendiente', 'Pendiente'),
        ('aprobado', 'Aprobado'),
        ('rechazado', 'Denegado'),
    )

    producto = models.ForeignKey(Productos, on_delete=models.CASCADE, related_name='costos_pendientes')
    lote = models.ForeignKey(CostoLote, on_delete=models.SET_NULL, null=True, blank=True, related_name='propuestas_costo')
    cantidad_compra = models.PositiveIntegerField(null=True, blank=True)
    unidad_compra = models.CharField(max_length=20, choices=UNIDADES_COMPRA, default='unidades')
    costo_propuesto = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    motivo = models.CharField(max_length=255, blank=True)
    estado = models.CharField(max_length=12, choices=ESTADOS, default='pendiente', db_index=True)
    creado_en = models.DateTimeField(auto_now_add=True, db_index=True)
    pendiente_desde = models.DateTimeField(null=True, blank=True, db_index=True)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='costos_pendientes_creados',
    )
    revisado_en = models.DateTimeField(null=True, blank=True)
    revisado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='costos_pendientes_revisados',
    )
    costo_anterior = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    precio_anterior = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    precio_aprobado = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    revertido_en = models.DateTimeField(null=True, blank=True)
    revertido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='costos_pendientes_revertidos',
    )

    class Meta:
        ordering = ['-creado_en', '-pk']
        indexes = [models.Index(fields=['estado', '-creado_en'], name='inv_cost_state_created_idx')]
        verbose_name = 'Costo pendiente'
        verbose_name_plural = 'Costos pendientes'

    def __str__(self):
        return f'{self.producto.Codigo}: {self.costo_propuesto} ({self.get_estado_display()})'
