from django import forms
from .models import Clientes
import re

PREMIUM_CONTROL_CLASSES = (
    'w-full px-4 py-3 bg-gray-50 dark:bg-slate-900/50 '
    'border border-gray-200 dark:border-slate-700 rounded-xl text-sm '
    'outline-none transition-all duration-200 shadow-sm '
    'focus:bg-white focus:border-blue-600 focus:ring-2 '
    'focus:ring-blue-600/50 focus:shadow-md dark:focus:bg-slate-800'
)

class ClienteForm(forms.ModelForm):
    def clean_nombre(self):
        nombre = self.cleaned_data['nombre'].strip()
        if not nombre.replace(' ', '').isalpha():
            raise forms.ValidationError("El nombre solo debe contener letras y espacios.")
        return nombre

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        # Permitir el mismo email si es del mismo cliente (edición)
        qs = Clientes.objects.filter(email=email)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("Este correo ya está registrado.")
        return email

    def clean_telefono(self):
        telefono = self.cleaned_data['telefono'].strip()
        # Permite formato (0412) 1234567 o solo números
        solo_numeros = re.sub(r'\D', '', telefono)
        if len(solo_numeros) < 7:
            raise forms.ValidationError("El teléfono debe tener al menos 7 dígitos.")
        return solo_numeros

    def clean_cedula(self):
        cedula = self.cleaned_data['cedula'].strip()
        qs = Clientes.objects.filter(cedula=cedula)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("Esta cédula ya está registrada.")
        return cedula

    class Meta:
        model = Clientes
        fields = '__all__'
        widgets = {
            'cedula': forms.TextInput(attrs={'class': PREMIUM_CONTROL_CLASSES}),
            'nombre': forms.TextInput(attrs={'class': PREMIUM_CONTROL_CLASSES}),
            'apellido': forms.TextInput(attrs={'class': PREMIUM_CONTROL_CLASSES}),
            'telefono': forms.TextInput(attrs={'class': PREMIUM_CONTROL_CLASSES}),
            'email': forms.EmailInput(attrs={'class': PREMIUM_CONTROL_CLASSES}),
            'fecha_nacimiento': forms.TextInput(attrs={'class': PREMIUM_CONTROL_CLASSES}),
            'direccion': forms.Textarea(attrs={
                'rows': 3,
                'class': PREMIUM_CONTROL_CLASSES,
                'style': 'min-height: 70px; max-height: 90px; height: 74px; resize: none;'
            }),
        }