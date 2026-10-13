from django import forms
from .models import Compra
from Proveedores.models import Proveedores
from django.utils import timezone

ESTADOS_VALIDOS = ["ACTIVA", "ANULADA"]

class ComprasForm(forms.ModelForm):
    def clean_proveedor(self):
        proveedor = self.cleaned_data.get('proveedor')
        if not proveedor or not Proveedores.objects.filter(pk=proveedor.pk).exists():
            raise forms.ValidationError("Debe seleccionar un proveedor válido.")
        return proveedor

    def clean_fecha_emision(self):
        fecha = self.cleaned_data.get('fecha_emision')
        if not fecha:
            raise forms.ValidationError("Debe ingresar una fecha de emisión.")
        if fecha > timezone.now().date():
            raise forms.ValidationError("La fecha de emisión no puede ser futura.")
        return fecha

    def clean_estado(self):
        estado = self.cleaned_data.get('estado', '').upper()
        if estado not in ESTADOS_VALIDOS:
            raise forms.ValidationError(f"El estado debe ser uno de: {', '.join(ESTADOS_VALIDOS)}.")
        return estado

    def clean_total(self):
        total = self.cleaned_data.get('total')
        if total is not None and total < 0:
            raise forms.ValidationError("El total no puede ser negativo.")
        return total

    def clean_descripcion(self):
        descripcion = self.cleaned_data.get('descripcion', '').strip()
        if len(descripcion) < 3:
            raise forms.ValidationError("La descripción debe tener al menos 3 caracteres.")
        return descripcion

    def clean(self):
        cleaned_data = super().clean()
        # Validación cruzada: no permitir guardar si el total es 0
        if self.instance and hasattr(self.instance, 'total'):
            total = self.instance.total()
            if total == 0:
                raise forms.ValidationError("No se puede guardar una compra con total igual a 0.")
        return cleaned_data

    class Meta:
        model = Compra
        fields = '__all__'
