import json
from decimal import Decimal, InvalidOperation

from django import forms
from .models import Productos, Categoria

PREMIUM_CONTROL_CLASSES = (
    'w-full px-4 py-3 bg-gray-50 dark:bg-slate-900/50 '
    'border border-gray-200 dark:border-slate-700 rounded-xl text-sm '
    'outline-none transition-all duration-200 shadow-sm '
    'focus:bg-white dark:focus:bg-slate-800 focus:ring-2 '
    'focus:ring-blue-600/50 focus:border-blue-600 focus:shadow-md'
)

class CategoriaForm(forms.ModelForm):
    class Meta:
        model = Categoria
        fields = ['name']
        labels = {
            'name': 'Nombre de la categoría',
        }
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ej. Herramientas eléctricas',
            }),
        }

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        if len(name) < 2:
            raise forms.ValidationError('El nombre debe tener al menos 2 caracteres.')
        return name

class ProductosForm(forms.ModelForm):
    class Meta:
        model = Productos
        fields = ['Descripcion', 'Precio', 'iva', 'Costo', 'Cantidad', 'Categoria', 'Imagen']
        labels = {
            'Descripcion': 'Descripcion',
            'Precio': 'Precio',
            'iva': 'Tratamiento de IVA',
            'Costo': 'Costo',
            'Cantidad': 'Cantidad',
            'Imagen': 'Imagen',
        }
        widgets = {
            'Descripcion': forms.TextInput(attrs={'class': PREMIUM_CONTROL_CLASSES}),
            'Precio': forms.NumberInput(attrs={'class': PREMIUM_CONTROL_CLASSES}),
            'iva': forms.Select(attrs={'class': PREMIUM_CONTROL_CLASSES}),
            'Costo': forms.NumberInput(attrs={'class': PREMIUM_CONTROL_CLASSES}),
            'Cantidad': forms.NumberInput(attrs={'class': PREMIUM_CONTROL_CLASSES}),
            'Categoria': forms.Select(attrs={'class': PREMIUM_CONTROL_CLASSES}),
            'Imagen': forms.ClearableFileInput(attrs={'class': PREMIUM_CONTROL_CLASSES}),
        }

    def clean_Costo(self):
        costo = self.cleaned_data['Costo']
        if costo < 0:
            raise forms.ValidationError("El costo no puede ser negativo.")
        return costo

    def clean_Cantidad(self):
        cantidad = self.cleaned_data['Cantidad']
        if cantidad < 0:
            raise forms.ValidationError("La cantidad no puede ser negativa.")
        return cantidad

    def clean(self):
        cleaned = super().clean()
        # Validate presentations_json if sent in POST
        data = self.data.get('presentations_json')
        if data:
            try:
                items = json.loads(data)
                if not isinstance(items, list):
                    raise forms.ValidationError('Formato inválido para presentaciones.')
                for i, it in enumerate(items):
                    if not isinstance(it, dict):
                        raise forms.ValidationError(f'Entrada #{i+1} inválida.')
                    if not all(key in it for key in ('type', 'factor', 'unit')):
                        raise forms.ValidationError(f'Entrada #{i+1} incompleta.')
                    if not str(it.get('type', '')).strip():
                        raise forms.ValidationError(f'El tipo de presentación en la entrada #{i+1} es obligatorio.')
                    if not str(it.get('unit', '')).strip():
                        raise forms.ValidationError(f'La unidad base en la entrada #{i+1} es obligatoria.')
                    try:
                        factor = Decimal(str(it.get('factor')))
                        factor_two_decimals = factor.quantize(Decimal('0.01'))
                    except (InvalidOperation, TypeError, ValueError):
                        raise forms.ValidationError(f'El factor en la entrada #{i+1} debe ser numérico.')
                    if not factor.is_finite() or factor != factor_two_decimals:
                        raise forms.ValidationError(f'El factor en la entrada #{i+1} admite hasta dos decimales.')
                    if factor <= 0:
                        raise forms.ValidationError(f'El factor en la entrada #{i+1} debe ser mayor que cero.')
            except forms.ValidationError:
                raise
            except Exception:
                raise forms.ValidationError('No se pudieron procesar las presentaciones.')
        return cleaned

    def clean_Descripcion(self):
        descripcion = self.cleaned_data['Descripcion'].strip()
        if len(descripcion) < 3:
            raise forms.ValidationError("La descripción debe tener al menos 3 caracteres.")
        return descripcion
        
class ActualizarPrecioForm(forms.ModelForm):
    class Meta:
        model = Productos
        fields = ['Precio']