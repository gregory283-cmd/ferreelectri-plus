from django.shortcuts import render, redirect, get_object_or_404
from .models import *
from .forms import *
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from .models import Clientes
from django.core.paginator import Paginator
from django.db.models import Q
from django.views.decorators.http import require_POST
from django.templatetags.static import static
from django.http import HttpResponse
from django.template.loader import get_template
from xhtml2pdf import pisa
from weasyprint import HTML

# Create your views here.

@login_required
@permission_required('Usuario.view_cliente')
def usuarios(request):
    clientes_list = Clientes.objects.all().order_by('-id')
    search_query = request.GET.get('q', '').strip()
    if search_query:
        clientes_list = clientes_list.filter(
            Q(cedula__icontains=search_query)
            | Q(nombre__icontains=search_query)
            | Q(apellido__icontains=search_query)
            | Q(email__icontains=search_query)
            | Q(telefono__icontains=search_query)
        )
    paginator = Paginator(clientes_list, 5)  # 5 clientes por página

    page_number = request.GET.get('page')
    clientes = paginator.get_page(page_number)

    context = {
        'clientes': clientes,
        'racismo': 'Clientes',
        'search_query': search_query,
    }
    return render(request, 'usuarios.html', context)

@login_required
@permission_required('Usuario.add_cliente')
def addUser(request):
    if request.method == 'POST':
        tipo_cedula = request.POST.get('tipo_cedula')
        cedula_num = request.POST.get('cedula')
        cedula_completa = f"{tipo_cedula}{cedula_num}"
        email = request.POST.get('email')
        post_data = request.POST.copy()
        post_data['cedula'] = cedula_completa
        form = ClienteForm(post_data, files=request.FILES)
        if Clientes.objects.filter(cedula=cedula_completa).exists():
            messages.error(request, 'Ya existe un cliente con esa cédula, no se agregó.')
            return redirect('usuarios')
        if Clientes.objects.filter(email=email).exists():
            messages.error(request, 'Ya existe un cliente con ese correo, no se agregó.')
            return redirect('usuarios')
        if form.is_valid():
            form.save()
            messages.success(request, 'Cliente agregado exitosamente')
            return redirect('usuarios')
        # Si no es válido, sigue y muestra errores en el formulario
    else:
        form = ClienteForm()
    context = {'form': form}
    return render(request, 'addUser.html', context)
    
@login_required
@permission_required('Usuario.change_cliente')
def updtUser(request, id):
    cliente = get_object_or_404(Clientes, id=id)
    if request.method == 'POST':
        form = ClienteForm(request.POST, request.FILES, instance=cliente)
        if form.is_valid():
            form.save()
            messages.success(request, 'Cliente actualizado exitosamente')
            return redirect('usuarios')
        else:
            messages.error(request, 'Error al actualizar al cliente')
            context = {'form': form, 'cliente': cliente}
            return render(request, 'updtUser.html', context)
    else:
        form = ClienteForm(instance=cliente)
        context = {'form': form, 'cliente': cliente}
        return render(request, 'updtUser.html', context)
    
@login_required
@permission_required('Usuario.delete_cliente')
@require_POST
def dltUser(request, id):
    cliente = get_object_or_404(Clientes, id=id)
    cliente.delete()
    messages.success(request, 'Cliente eliminado exitosamente')
    return redirect('usuarios')

@login_required
@permission_required('Usuario.view_cliente', raise_exception=True)
def ver_cliente(request, pk):
    cliente = get_object_or_404(Clientes, pk=pk)
    return render(request, 'ver_cliente.html', {'cliente': cliente})

# Para PDF individual (usa WeasyPrint, xhtml2pdf, o similar)
@login_required
@permission_required('Usuario.view_cliente', raise_exception=True)
def cliente_pdf(request, pk):
    cliente = get_object_or_404(Clientes, pk=pk)
    template_path = 'cliente_pdf.html'
    context = {'cliente': cliente}
    template = get_template(template_path)
    html = template.render(context)
    try:
        pdf_file = HTML(string=html, base_url=request.build_absolute_uri('/')).write_pdf()
        response = HttpResponse(pdf_file, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="cliente_{cliente.cedula}.pdf"'
        return response
    except Exception:
        import traceback
        return HttpResponse(traceback.format_exc(), status=500, content_type='text/plain')

def clientes(request):
    clientes_list = Clientes.objects.all()  # <-- Cambia Cliente por Clientes
    paginator = Paginator(clientes_list, 10)  # 10 por página
    page_number = request.GET.get('page')
    clientes = paginator.get_page(page_number)
    return render(request, 'usuarios.html', {'clientes': clientes})
    page_number = request.GET.get('page')
    clientes = paginator.get_page(page_number)
    return render(request, 'usuarios.html', {'clientes': clientes})
