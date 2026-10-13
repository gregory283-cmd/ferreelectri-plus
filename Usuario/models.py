from django.db import models

# Create your models here.

class Clientes(models.Model):
    nombre = models.CharField(max_length=25)
    apellido = models.CharField(max_length=25)
    telefono = models.CharField(max_length=25)
    cedula = models.CharField(max_length=20, unique=True, null=True, blank=True, default=None)
    direccion = models.TextField()
    email = models.CharField(max_length=254, unique=True)
    fecha_nacimiento = models.DateField(null=True, blank=True)
    fecha_registro = models.DateField(auto_now_add=True)
    frecuente = models.BooleanField(default=False)
    vip = models.BooleanField(default=False)
    
    def __str__(self):
        return self.nombre