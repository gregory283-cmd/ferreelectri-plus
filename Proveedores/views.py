from django.shortcuts import render, redirect, get_object_or_404
from .models import Proveedores
from .forms import *
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.db import IntegrityError
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.utils import timezone
from django.template.loader import get_template
from django.views.decorators.http import require_POST
from xhtml2pdf import pisa
from weasyprint import HTML

# Create your views here.

@login_required
@permission_required('Proveedores.view_proveedores')
def Proveedor(request):
    proveedores_list = Proveedores.objects.all().order_by('-id')
    search_query = request.GET.get('q', '').strip()
    if search_query:
        proveedores_list = proveedores_list.filter(
            Q(cedula__icontains=search_query)
            | Q(nombre__icontains=search_query)
            | Q(telefono__icontains=search_query)
            | Q(email__icontains=search_query)
            | Q(direccion__icontains=search_query)
        )
    paginator = Paginator(proveedores_list, 5)  # 5 proveedores por página

    page_number = request.GET.get('page')  # Obtén el número de página de la URL
    proveedores = paginator.get_page(page_number)

    context = {
        'proveedores': proveedores,
        'racismo': 'Proveedores',
        'search_query': search_query,
    }
    return render(request, 'Proveedor.html', context)

@login_required
@permission_required('Proveedores.add_proveedores')
def addProveedor(request):
    cedulas_registradas = list(Proveedores.objects.values_list('cedula', flat=True))
    correos_registrados = list(Proveedores.objects.values_list('email', flat=True))

    if request.method == 'POST':
        nombre = request.POST.get('nombre')
        prefijo_cedula = request.POST.get('prefijo_cedula')
        cedula = request.POST.get('cedula')
        telefono = request.POST.get('telefono')
        correo = request.POST.get('correo')
        direccion = request.POST.get('direccion')  # <-- AGREGA ESTA LÍNEA

        # Une prefijo y cédula si tu modelo lo espera así, evitando duplicar el prefijo
        cedula_raw = (cedula or '').strip()
        pref = (prefijo_cedula or '').strip()
        if pref and cedula_raw.upper().startswith(pref.upper()):
            cedula_completa = cedula_raw
        else:
            cedula_completa = f"{pref}{cedula_raw}"

        # Guarda el proveedor
        try:
            Proveedores.objects.create(
                nombre=nombre,
                cedula=cedula_completa,
                telefono=telefono,
                email=correo,
                direccion=direccion
            )
        except (ValidationError, IntegrityError):
            messages.error(request, 'No se pudo guardar el proveedor. Verifica sus datos y que su cédula no esté registrada.')
            return redirect('Proveedor')
        messages.success(request, "¡Proveedor agregado exitosamente!")  # Mensaje de éxito
        return redirect('Proveedor')  # Cambia por el nombre correcto de tu url de listado

    return render(request, 'addProveedor.html', {
        'cedulas_registradas': cedulas_registradas,
        'correos_registrados': correos_registrados,
    })
    
@login_required
@permission_required('Proveedores.change_proveedores')
def updtProveedor(request, id):
    proveedor = get_object_or_404(Proveedores, id=id)
    if request.method == 'POST':
        # Construir la cédula completa igual que en addProveedor
        prefijo = (request.POST.get('prefijo_cedula') or '').strip()
        cedula_num = (request.POST.get('cedula') or '').strip()
        # Evitar duplicar prefijo si ya se incluyó en el campo cedula
        if prefijo and cedula_num.upper().startswith(prefijo.upper()):
            proveedor.cedula = cedula_num
        else:
            proveedor.cedula = f"{prefijo}{cedula_num}"
        proveedor.nombre = request.POST.get('nombre')
        proveedor.telefono = request.POST.get('telefono')
        proveedor.email = request.POST.get('correo')  # Usa 'correo' del formulario, pero guarda en 'email'
        proveedor.direccion = request.POST.get('direccion')
        try:
            proveedor.save()
        except (ValidationError, IntegrityError):
            messages.error(request, 'No se pudo actualizar el proveedor. Verifica sus datos y que su cédula no esté registrada.')
            return redirect('Proveedor')
        messages.success(request, '¡Proveedor modificado exitosamente!')
        return redirect('Proveedor')
    else:
        context = {'proveedor': proveedor}
        return render(request, 'updtProveedor.html', context)
    
@login_required
@permission_required('Proveedores.delete_proveedores')
@require_POST
def dltProveedor(request, id):
    proveedor = get_object_or_404(Proveedores, id=id)
    proveedor.delete()
    messages.success(request, '¡Proveedor eliminado exitosamente!')  # Mensaje de éxito
    return redirect('Proveedor')

@login_required
@permission_required('Proveedores.view_proveedores', raise_exception=True)
def reporte_proveedor_pdf(request, pk):
    proveedor = Proveedores.objects.get(pk=pk)
    context = {
        'proveedor': proveedor,
        'now': timezone.now(),
    }
    template = get_template('proveedor_pdf.html')
    html = template.render(context)
    try:
        pdf_file = HTML(string=html, base_url=request.build_absolute_uri('/')).write_pdf()
        response = HttpResponse(pdf_file, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="proveedor_{proveedor.cedula}.pdf"'
        return response
    except Exception:
        import traceback
        return HttpResponse(traceback.format_exc(), status=500, content_type='text/plain')

@login_required
@permission_required('Proveedores.view_proveedores', raise_exception=True)
def ver_proveedor(request, pk):
    proveedor = get_object_or_404(Proveedores, pk=pk)
    return render(request, 'ver_proveedor.html', {'proveedor': proveedor})

def proveedores(request):
    proveedores_list = Proveedores.objects.all()
    paginator = Paginator(proveedores_list, 10)
    page_number = request.GET.get('page')
    proveedores = paginator.get_page(page_number)
    return render(request, 'Proveedor.html', {'proveedores': proveedores})
