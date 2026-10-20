from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User
from django.db.models import Q
from .models import Cliente, Customer, Envio, Pago
from django.core.validators import RegexValidator, MinLengthValidator, MaxLengthValidator
import re
from django.contrib.auth.password_validation import validate_password

class ClienteAuthenticationForm(AuthenticationForm):
    username = forms.CharField(
        widget=forms.TextInput(attrs={'class': 'auth-input', 'placeholder': 'Correo o usuario'}),
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'auth-input', 'placeholder': 'Contraseña'}),
    )

    def clean(self):
        username = self.cleaned_data.get('username')
        password = self.cleaned_data.get('password')
        if username and password:
            username = username.strip()
            self.user_cache = authenticate(
                self.request,
                username=username,
                password=password,
                customer_only=True,
            )
            if self.user_cache is None:
                self.user_cache = authenticate(
                    self.request,
                    username=username,
                    password=password,
                )
            if self.user_cache is None:
                customer = Customer.objects.filter(Q(email__iexact=username) | Q(nombre__iexact=username)).first()
                if customer:
                    if not customer.email_verified:
                        raise forms.ValidationError(
                            'Confirma tu correo antes de iniciar sesión. Puedes reenviar el enlace desde el registro.'
                        )
                    raise forms.ValidationError('Contraseña incorrecta. Usa la contraseña correcta o restablece tu cuenta.')
                raise forms.ValidationError('Credenciales inválidas o acceso no permitido.')
            if getattr(self.user_cache, 'is_staff', False) or getattr(self.user_cache, 'is_superuser', False):
                raise forms.ValidationError('Los administradores no pueden iniciar sesión desde el frontend.')
            self.confirm_login_allowed(self.user_cache)
        return self.cleaned_data

class ClienteForm(forms.ModelForm):
    cedula = forms.CharField(
        max_length=12,
        validators=[
            RegexValidator(r'^\d+$', 'Solo se permiten números.'),
            MinLengthValidator(6),
            MaxLengthValidator(12)
        ]
    )
    email = forms.EmailField(max_length=80)
    telefono = forms.CharField(
        max_length=15,
        validators=[
            RegexValidator(r'^\d+$', 'Solo se permiten números.'),
            MinLengthValidator(10),
            MaxLengthValidator(15)
        ]
    )

    class Meta:
        model = Cliente
        fields = ['cedula', 'nombre', 'email', 'telefono']

    def clean_nombre(self):
        nombre = self.cleaned_data['nombre'].strip()
        if not nombre.replace(' ', '').isalpha():
            raise forms.ValidationError("El nombre solo debe contener letras y espacios.")
        return nombre

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if Cliente.objects.filter(email=email).exists():
            raise forms.ValidationError("Este correo ya está registrado.")
        return email

    def clean_telefono(self):
        telefono = self.cleaned_data['telefono'].strip()
        if not telefono.isdigit():
            raise forms.ValidationError("El teléfono solo debe contener números.")
        return telefono

    def clean(self):
        cleaned_data = super().clean()
        # Puedes agregar validaciones cruzadas aquí
        return cleaned_data

class ClienteRegistroForm(forms.ModelForm):
    tipo_documento = forms.ChoiceField(
        choices=[
            ('V', 'V · Cédula'),
            ('J', 'J · Empresa'),
            ('G', 'G · Organismo'),
            ('P', 'P · Pasaporte'),
        ],
        required=False,
        initial='V',
        widget=forms.Select(attrs={'class': 'auth-document-select', 'aria-label': 'Tipo de identificación'}),
    )
    numero_documento = forms.CharField(
        required=False,
        max_length=20,
        widget=forms.TextInput(attrs={
            'class': 'auth-document-number',
            'placeholder': 'Número de cédula, RIF o pasaporte',
            'autocomplete': 'off',
            'aria-label': 'Número de cédula, RIF o pasaporte',
        }),
    )
    password1 = forms.CharField(
        label='Contraseña',
        widget=forms.PasswordInput(attrs={
            'class': 'w-full rounded-xl border border-gray-800 bg-gray-900/50 py-3 pl-10 pr-3 text-white placeholder:text-gray-400 shadow-inner shadow-slate-950/30 outline-none transition-all duration-300 focus:border-blue-500 focus:bg-gray-800 focus:ring-2 focus:ring-blue-600/50',
            'autocomplete': 'new-password',
            'placeholder': 'Contraseña',
        }),
        min_length=8,
        help_text='Mínimo 8 caracteres.',
    )
    password2 = forms.CharField(
        label='Repetir contraseña',
        widget=forms.PasswordInput(attrs={
            'class': 'w-full rounded-xl border border-gray-800 bg-gray-900/50 py-3 pl-10 pr-3 text-white placeholder:text-gray-400 shadow-inner shadow-slate-950/30 outline-none transition-all duration-300 focus:border-blue-500 focus:bg-gray-800 focus:ring-2 focus:ring-blue-600/50',
            'autocomplete': 'new-password',
            'placeholder': 'Repite la contraseña',
        }),
        min_length=8,
    )

    cedula = forms.CharField(
        label='Cédula o RIF',
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'w-full rounded-xl border border-gray-800 bg-gray-900/50 py-3 pl-10 pr-3 text-white placeholder:text-gray-400 shadow-inner shadow-slate-950/30 outline-none transition-all duration-300 focus:border-blue-500 focus:bg-gray-800 focus:ring-2 focus:ring-blue-600/50',
            'placeholder': 'V-12345678',
            'autocomplete': 'off',
        }),
    )

    telefono = forms.CharField(
        required=True,
        max_length=20,
        widget=forms.TextInput(attrs={
            'class': 'w-full rounded-xl border border-gray-800 bg-gray-900/50 py-3 pl-10 pr-3 text-white placeholder:text-gray-400 shadow-inner shadow-slate-950/30 outline-none transition-all duration-300 focus:border-blue-500 focus:bg-gray-800 focus:ring-2 focus:ring-blue-600/50',
            'placeholder': '+58 424 000 0000',
            'autocomplete': 'tel',
        }),
    )

    direccion = forms.CharField(
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'w-full rounded-xl border border-gray-800 bg-gray-900/50 py-3 pl-10 pr-3 text-white placeholder:text-gray-400 shadow-inner shadow-slate-950/30 outline-none transition-all duration-300 focus:border-blue-500 focus:bg-gray-800 focus:ring-2 focus:ring-blue-600/50',
            'placeholder': 'Ciudad, sector y dirección de entrega',
            'autocomplete': 'street-address',
        }),
        max_length=255,
    )

    class Meta:
        model = Customer
        fields = ['nombre', 'email', 'cedula', 'telefono', 'direccion']
        widgets = {
            'nombre': forms.TextInput(attrs={
                'class': 'w-full rounded-xl border border-gray-800 bg-gray-900/50 py-3 pl-10 pr-3 text-white placeholder:text-gray-400 shadow-inner shadow-slate-950/30 outline-none transition-all duration-300 focus:border-blue-500 focus:bg-gray-800 focus:ring-2 focus:ring-blue-600/50',
                'placeholder': 'Nombre completo',
            }),
            'email': forms.EmailInput(attrs={
                'class': 'w-full rounded-xl border border-gray-800 bg-gray-900/50 py-3 pl-10 pr-3 text-white placeholder:text-gray-400 shadow-inner shadow-slate-950/30 outline-none transition-all duration-300 focus:border-blue-500 focus:bg-gray-800 focus:ring-2 focus:ring-blue-600/50',
                'placeholder': 'correo@ejemplo.com',
            }),
        }

    def clean_nombre(self):
        nombre = self.cleaned_data.get('nombre', '').strip()
        if not nombre:
            raise forms.ValidationError("El nombre es obligatorio.")
        if not nombre.replace(' ', '').isalpha():
            raise forms.ValidationError("El nombre solo debe contener letras y espacios.")
        return nombre

    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip().lower()
        if not email:
            raise forms.ValidationError("El correo es obligatorio.")
        if not re.match(r'^[\w\.-]+@[\w\.-]+\.\w+$', email):
            raise forms.ValidationError("Ingrese un correo electrónico válido.")
        existing_customer = Customer.objects.filter(email__iexact=email).first()
        if existing_customer and existing_customer.email_verified:
            raise forms.ValidationError('No se pudo validar este correo. Revisa los datos e intenta nuevamente.')
        if User.objects.filter(email__iexact=email, is_staff=True).exists():
            raise forms.ValidationError('No se pudo validar este correo. Revisa los datos e intenta nuevamente.')
        return email

    def clean_cedula(self):
        document_type = (self.data.get('tipo_documento') or '').strip().upper()
        document_number = (self.data.get('numero_documento') or '').strip().upper()
        cedula = (self.cleaned_data.get('cedula') or '').strip()
        if document_number:
            if document_type in {'V', 'J', 'G'} and re.fullmatch(r'\d{5,10}', document_number):
                cedula = f'{document_type}-{document_number}'
            elif document_type == 'P' and re.fullmatch(r'[A-Z0-9.-]{5,20}', document_number):
                cedula = document_number
            else:
                raise forms.ValidationError('Selecciona un tipo e ingresa una identificación válida.')
        if not cedula:
            raise forms.ValidationError('La cédula o RIF es obligatorio.')
        cedula = cedula.upper()
        if len(cedula) < 5 or not re.fullmatch(r'^[A-Z0-9-]+$', cedula):
            raise forms.ValidationError('Ingresa una cédula o RIF válido, sin espacios.')
        if Customer.objects.filter(cedula__iexact=cedula).exists():
            raise forms.ValidationError('No se pudo validar esta identificación. Revisa los datos e intenta nuevamente.')
        if Cliente.objects.filter(cedula__iexact=cedula).exists():
            raise forms.ValidationError('No se pudo validar esta identificación. Revisa los datos e intenta nuevamente.')
        return cedula

    def clean_password2(self):
        password1 = self.cleaned_data.get('password1')
        password2 = self.cleaned_data.get('password2')
        if password1 and password2 and password1 != password2:
            raise forms.ValidationError("Las contraseñas no coinciden.")
        # Validar fuerza de la contraseña usando los validadores configurados en settings
        if password1:
            try:
                validate_password(password1)
            except forms.ValidationError as e:
                raise forms.ValidationError(e.messages)
        return password2

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get('password1')
        password2 = cleaned_data.get('password2')
        if password1 and password2 and password1 != password2:
            raise forms.ValidationError("Las contraseñas no coinciden.")
        return cleaned_data

    def clean_telefono(self):
        telefono = self.cleaned_data.get('telefono', '').strip()
        if not telefono:
            raise forms.ValidationError('El teléfono es obligatorio.')
        telefono_limpio = re.sub(r'\D', '', telefono)
        if len(telefono_limpio) < 7 or len(telefono_limpio) > 15:
            raise forms.ValidationError("El teléfono debe tener entre 7 y 15 dígitos.")
        return f"+{telefono_limpio}"

    def clean_direccion(self):
        direccion = self.cleaned_data.get('direccion', '').strip()
        if len(direccion) < 5:
            raise forms.ValidationError('La dirección debe tener al menos 5 caracteres.')
        return direccion

class PagoManualForm(forms.ModelForm):
    metodo = forms.ChoiceField(
        choices=[
            ('', 'Seleccione un método'),
            ('TRANSFERENCIA', 'Transferencia bancaria'),
        ],
        required=True,
        label='Método de pago',
    )
    referencia = forms.CharField(
        max_length=200,
        required=True,
        label='Número de referencia',
        help_text='Ingrese la referencia del pago móvil, transferencia o zelle.',
    )
    comprobante = forms.ImageField(
        required=True,
        label='Comprobante',
        help_text='Suba una imagen clara del comprobante.',
    )

    class Meta:
        model = Pago
        fields = ['metodo', 'referencia', 'comprobante']

    def clean_referencia(self):
        referencia = self.cleaned_data.get('referencia', '').strip()
        if not referencia:
            raise forms.ValidationError('La referencia es obligatoria.')
        return referencia

    def clean_comprobante(self):
        comprobante = self.cleaned_data.get('comprobante')
        if comprobante and getattr(comprobante, 'size', 0) > 5 * 1024 * 1024:
            raise forms.ValidationError('El comprobante no puede superar 5 MB.')
        return comprobante


class EnvioAdminForm(forms.ModelForm):
    class Meta:
        model = Envio
        fields = [
            'estado', 'nombre_destinatario', 'telefono', 'direccion',
            'transportista', 'numero_guia', 'url_seguimiento', 'observaciones',
        ]
        widgets = {
            'direccion': forms.Textarea(attrs={'rows': 2}),
            'observaciones': forms.Textarea(attrs={'rows': 2}),
        }

    def clean(self):
        cleaned_data = super().clean()
        estado = cleaned_data.get('estado')
        if self.instance.requiere_revision:
            for field in ('nombre_destinatario', 'telefono', 'direccion'):
                if not cleaned_data.get(field, '').strip():
                    self.add_error(field, 'Completa este dato para resolver la revisión del envío.')

        if estado in {'despachado', 'en_transito', 'entregado'}:
            if not cleaned_data.get('transportista', '').strip():
                self.add_error('transportista', 'Indica el transportista para este estado.')
            if not cleaned_data.get('numero_guia', '').strip():
                self.add_error('numero_guia', 'Indica el número de guía para este estado.')

        if estado in {'incidencia', 'devuelto'} and not cleaned_data.get('observaciones', '').strip():
            self.add_error('observaciones', 'Describe la incidencia o devolución.')
        return cleaned_data


class PagoMovilCheckoutForm(forms.Form):
    BANCOS = (
        ('Banesco', 'Banesco'),
        ('Mercantil', 'Mercantil'),
        ('BBVA Provincial', 'BBVA Provincial'),
        ('Bancamiga', 'Bancamiga'),
        ('Banco de Venezuela', 'Banco de Venezuela'),
        ('BNC', 'BNC'),
        ('Banco del Tesoro', 'Banco del Tesoro'),
        ('100% Banco', '100% Banco'),
        ('Otro banco', 'Otro banco'),
    )

    banco = forms.ChoiceField(choices=BANCOS, required=True)
    cedula_tipo = forms.ChoiceField(
        choices=(('V', 'V'), ('E', 'E'), ('J', 'J'), ('G', 'G'), ('P', 'P')),
        required=False,
        initial='V',
    )
    cedula_pagador = forms.CharField(
        max_length=30,
        required=True,
        widget=forms.TextInput(attrs={'inputmode': 'numeric', 'autocomplete': 'off'}),
    )
    referencia = forms.CharField(max_length=50, min_length=4, required=True)
    capture = forms.ImageField(
        required=True,
        error_messages={'invalid_image': 'El capture de pago debe ser una imagen válida.'},
    )

    def clean_cedula_pagador(self):
        value = self.cleaned_data['cedula_pagador'].strip().upper()
        match = re.fullmatch(r'([VEJPG])\s*-?\s*(\d{5,10})', value)
        if match:
            prefix, number = match.groups()
        else:
            prefix = self.cleaned_data.get('cedula_tipo') or 'V'
            number_match = re.fullmatch(r'\d{5,10}', value)
            if not number_match:
                raise forms.ValidationError('Ingrese entre 5 y 10 dígitos para la cédula o identificación.')
            number = value
        return f'{prefix}-{number}'

    def clean_referencia(self):
        value = self.cleaned_data['referencia'].strip()
        if not re.fullmatch(r'[A-Za-z0-9-]{4,50}', value):
            raise forms.ValidationError('La referencia debe tener entre 4 y 50 letras, números o guiones.')
        return value

    def clean_capture(self):
        capture = self.cleaned_data['capture']
        if capture.size > 5 * 1024 * 1024:
            raise forms.ValidationError('El comprobante no puede superar 5 MB.')
        return capture


class RegistroForm(forms.Form):
    email = forms.EmailField()
    password = forms.CharField(widget=forms.PasswordInput)

    def clean_email(self):
        email = self.cleaned_data['email']
        if "ferreelectri" not in email:
            raise forms.ValidationError("El correo debe ser corporativo.")
        return email
