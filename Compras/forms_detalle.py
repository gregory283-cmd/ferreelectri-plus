from django import forms
from .models import DetalleCompra

class DetalleCompraForm(forms.ModelForm):
    def clean_producto(self):
        producto = self.cleaned_data.get('producto')
        if not producto:
            raise forms.ValidationError("Debe seleccionar un producto válido.")
        return producto

    def clean_precio(self):
        precio = self.cleaned_data.get('precio')
        if precio is not None and precio < 0:
            raise forms.ValidationError("El precio no puede ser negativo.")
        return precio

    def clean_cantidad(self):
        cantidad = self.cleaned_data.get('cantidad')
        if cantidad is not None and cantidad <= 0:
            raise forms.ValidationError("La cantidad debe ser mayor a cero.")
        return cantidad

    def clean(self):
        cleaned_data = super().clean()
        precio = cleaned_data.get('precio')
        cantidad = cleaned_data.get('cantidad')
        subtotal = cleaned_data.get('subtotal')
        if precio is not None and cantidad is not None:
            if subtotal is not None and subtotal != precio * cantidad:
                self.add_error('subtotal', "El subtotal debe ser igual a precio x cantidad.")
        return cleaned_data

    class Meta:
        model = DetalleCompra
        fields = '__all__'
