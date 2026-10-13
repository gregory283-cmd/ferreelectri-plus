from django.db import models
from django.db.models import Sum

class Compra(models.Model):
    proveedor = models.ForeignKey('Proveedores.Proveedores', on_delete=models.CASCADE)
    fecha_emision = models.DateField()
    control_fiscal = models.CharField(max_length=50, blank=True, default='')
    estado = models.CharField(max_length=20, default='ACTIVA')  

    def __str__(self):
        # Proveedor model usa campo 'nombre' en minúsculas
        return f"Compra #{self.id} - {self.proveedor.nombre}"

    def total(self):
        return self.detallecompra_set.aggregate(total=models.Sum('subtotal'))['total'] or 0

class DetalleCompra(models.Model):
    compra = models.ForeignKey(Compra, on_delete=models.CASCADE)
    producto = models.ForeignKey('Inventario.Productos', on_delete=models.CASCADE)
    precio = models.DecimalField(max_digits=10, decimal_places=2)
    cantidad = models.PositiveIntegerField()
    subtotal = models.DecimalField(max_digits=12, decimal_places=2)

    def save(self, *args, **kwargs):
        self.subtotal = self.precio * self.cantidad
        super().save(*args, **kwargs)
