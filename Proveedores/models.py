from django.db import models
import re
from django.core.validators import RegexValidator, MinLengthValidator, MaxLengthValidator

# Create your models here.

class Proveedores(models.Model):
    cedula = models.CharField(
        max_length=12,
        unique=True,
        help_text='Cédula o RIF del proveedor. Puede incluir prefijo (V, E, J, G, P).'
    )
    nombre = models.CharField(max_length=60)
    email = models.EmailField(max_length=80)
    telefono = models.CharField(
        max_length=15,
        validators=[
            RegexValidator(r'^\d+$', 'Solo se permiten números.'),
            MinLengthValidator(10),
            MaxLengthValidator(15)
        ]
    )
    direccion = models.CharField(max_length=120)
    Fecha_registro = models.DateField(auto_now_add=True)
    
    def clean(self):
        # Normalizar y validar cédula/RIF: eliminar espacios, guiones, puntos y pasar a mayúsculas
        from django.core.exceptions import ValidationError
        if not self.cedula:
            raise ValidationError({'cedula': 'La cédula es obligatoria.'})

        ced = re.sub(r'[^A-Za-z0-9]', '', str(self.cedula)).upper()
        # Permitimos opcionalmente un prefijo V/E/J/G/P seguido de números
        if not re.match(r'^[VEJGP]?\d{6,11}$', ced):
            raise ValidationError({'cedula': 'Cédula/RIF inválida. Use formato como J304031880 o 304031880.'})
        # reasignar valor normalizado
        self.cedula = ced

        if not self.nombre:
            raise ValidationError({'nombre': 'El nombre del proveedor es obligatorio.'})

    def save(self, *args, **kwargs):
        # Ejecutar validaciones antes de guardar
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.nombre
