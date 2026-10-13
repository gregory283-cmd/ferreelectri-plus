from django import forms
from .models import Ventas

class VentasForm(forms.ModelForm):
    def clean_codigo(self):
        codigo = self.cleaned_data.get('codigo', '').strip()
        if len(codigo) < 3:
            raise forms.ValidationError("El código debe tener al menos 3 caracteres.")
        return codigo

    def clean_articulo(self):
        articulo = self.cleaned_data.get('articulo', '').strip()
        if len(articulo) < 3:
            raise forms.ValidationError("El nombre del artículo debe tener al menos 3 caracteres.")
        return articulo

    def clean_cantidad(self):
        cantidad = self.cleaned_data.get('cantidad')
        if cantidad is not None and cantidad <= 0:
            raise forms.ValidationError("La cantidad debe ser mayor a cero.")
        return cantidad

    def clean_precio(self):
        precio = self.cleaned_data.get('precio')
        if precio is not None and precio < 0:
            raise forms.ValidationError("El precio no puede ser negativo.")
        return precio

    def clean(self):
        cleaned_data = super().clean()
        # Validación cruzada: descuento no mayor al precio
        precio = cleaned_data.get('precio')
        descuento = cleaned_data.get('descuento')
        if precio is not None and descuento is not None and descuento > precio:
            self.add_error('descuento', "El descuento no puede ser mayor al precio.")
        return cleaned_data

    class Meta:
        model = Ventas
        fields = '__all__'