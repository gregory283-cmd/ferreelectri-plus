from django import forms
from .models import Proveedores
from django.core.validators import RegexValidator, MinLengthValidator, MaxLengthValidator

class ProveedorForm(forms.ModelForm):
    Cedula = forms.CharField(
        max_length=12,
        widget=forms.TextInput(attrs={
            'pattern': '^[0-9]{6,12}$',
            'maxlength': '12',
            'minlength': '6',
            'title': 'Solo números, mínimo 6 dígitos',
            'required': True,
            'id': 'cedula'
        }),
        validators=[
            RegexValidator(r'^\d+$', 'Solo se permiten números.'),
            MinLengthValidator(6),
            MaxLengthValidator(12)
        ]
    )
    Email = forms.EmailField(
        max_length=80,
        widget=forms.EmailInput(attrs={
            'maxlength': '80',
            'title': 'Debe ser un correo válido',
            'required': True,
            'id': 'email'
        })
    )
    Telefono = forms.CharField(
        max_length=15,
        widget=forms.TextInput(attrs={
            'pattern': '^[0-9]{10,15}$',
            'maxlength': '15',
            'minlength': '10',
            'title': 'Solo números, mínimo 10 dígitos',
            'required': True,
            'id': 'telefono'
        }),
        validators=[
            RegexValidator(r'^\d+$', 'Solo se permiten números.'),
            MinLengthValidator(10),
            MaxLengthValidator(15)
        ]
    )

    def clean_nombre(self):
        nombre = self.cleaned_data['nombre'].strip()
        if not nombre.replace(' ', '').isalpha():
            raise forms.ValidationError("El nombre solo debe contener letras y espacios.")
        return nombre

    def clean_Email(self):
        email = self.cleaned_data['Email'].strip().lower()
        if Proveedores.objects.filter(Email=email).exists():
            raise forms.ValidationError("Este correo ya está registrado.")
        return email

    def clean_Telefono(self):
        telefono = self.cleaned_data['Telefono'].strip()
        if not telefono.isdigit():
            raise forms.ValidationError("El teléfono solo debe contener números.")
        return telefono

    class Meta:
        model = Proveedores
        fields = ['Cedula', 'nombre', 'Email', 'Telefono', 'direccion']