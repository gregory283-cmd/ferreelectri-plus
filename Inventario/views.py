# Create your views here.
from mimetypes import guess_type
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_GET
from .models import Productos, PresentacionProducto, MovimientoInventario, Categoria
from .forms import ProductosForm, ActualizarPrecioForm, CategoriaForm
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required, permission_required
from dashboard.decorators import cliente_required
from django.db.models.deletion import ProtectedError
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from Inventario.utils import registrar_movimiento
from datetime import datetime, timedelta
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.http import JsonResponse
import json
from Ventas.models import DetalleFactura

from decimal import Decimal, InvalidOperation


@require_GET
def servir_imagen_producto(request, filename):
    product_media_root = (Path(settings.MEDIA_ROOT) / 'productos').resolve()
    image_path = (product_media_root / filename).resolve()
    try:
        image_path.relative_to(product_media_root)
    except ValueError:
        raise Http404
    if not image_path.is_file():
        raise Http404
    return FileResponse(
        image_path.open('rb'),
        content_type=guess_type(image_path.name)[0] or 'application/octet-stream',
    )


def parse_presentations_from_request(request):
    array_data = list(zip(
        request.POST.getlist('presentacion_nombre[]'),
        request.POST.getlist('presentacion_factor[]'),
        request.POST.getlist('presentacion_unidad[]'),
    ))
    if array_data:
        data = [
            {'type': nombre, 'factor': factor, 'unit': unidad}
            for nombre, factor, unidad in array_data
        ]
    else:
        presentations_json = request.POST.get('presentations_json')
        data = []

        if presentations_json:
            try:
                data = json.loads(presentations_json)
            except (TypeError, ValueError):
                data = []

        if not data:
            rows = {}
            for key, value in request.POST.items():
                if key.startswith('presentacion_'):
                    rows.setdefault(key.split('_', 1)[1], {})['type'] = value
                elif key.startswith('factor_'):
                    rows.setdefault(key.split('_', 1)[1], {})['factor'] = value
                elif key.startswith('unidad_'):
                    rows.setdefault(key.split('_', 1)[1], {})['unit'] = value
            if rows:
                data = [rows[index] for index in sorted(rows, key=lambda x: int(x) if x.isdigit() else x)]

    if not isinstance(data, list):
        return []

    cleaned = []
    for item in data:
        if not isinstance(item, dict):
            continue
        type_ = str(item.get('type') or item.get('nombre') or item.get('presentacion') or '').strip()
        unit = str(item.get('unit') or item.get('unidad_medida') or item.get('unidad') or '').strip()
        factor = item.get('factor')
        try:
            factor = Decimal(str(factor)).quantize(Decimal('0.01'))
        except (TypeError, ValueError, InvalidOperation):
            continue
        if not type_ or not unit or factor <= 0:
            continue
        cleaned.append({'type': type_, 'factor': factor, 'unit': unit})
    return cleaned


def save_product_presentations(producto, request):
    presentations = parse_presentations_from_request(request)
    with transaction.atomic():
        producto.presentaciones.all().delete()
        PresentacionProducto.objects.bulk_create([
            PresentacionProducto(
                producto=producto,
                nombre=item['type'],
                factor=item['factor'],
                unidad_medida=item['unit'],
            )
            for item in presentations
        ])
        producto.presentations = [
            {'type': item['type'], 'factor': float(item['factor']), 'unit': item['unit']}
            for item in presentations
        ]
        producto.save(update_fields=['presentations'])
    return presentations


def presentation_context(producto):
    related_presentations = producto.presentaciones.all()
    if related_presentations.exists():
        return [
            {'type': pres.nombre, 'factor': str(pres.factor), 'unit': pres.unidad_medida}
            for pres in related_presentations
        ]
    return [
        {'type': item.get('type', ''), 'factor': item.get('factor', ''), 'unit': item.get('unit', '')}
        for item in (producto.presentations or [])
        if isinstance(item, dict)
    ]


def limpiar_decimal(valor):
    if not valor:
        return Decimal('0')
    valor = valor.replace(',', '.')
    try:
        return Decimal(valor)
    except InvalidOperation:
        return Decimal('0')


@login_required
@permission_required('Inventario.add_categoria')
def crear_categoria(request):
    if request.method == 'POST':
        form = CategoriaForm(request.POST)
        if form.is_valid():
            categoria = form.save()
            messages.success(request, f'Categoría "{categoria.name}" creada exitosamente.')
            return redirect('listar_productos')
    else:
        form = CategoriaForm()

    categorias = Categoria.objects.annotate(num_productos=Count('productos')).order_by('-id')
    return render(request, 'crear_categoria.html', {'form': form, 'categorias': categorias})


@login_required
@permission_required('Inventario.change_categoria')
def editar_categoria(request, categoria_id):
    categoria = get_object_or_404(Categoria, id=categoria_id)
    if request.method == 'POST':
        form = CategoriaForm(request.POST, instance=categoria)
        if form.is_valid():
            form.save()
            messages.success(request, f'Categoría "{categoria.name}" actualizada exitosamente.')
            return redirect('crear_categoria')
    else:
        form = CategoriaForm(instance=categoria)
    categorias = Categoria.objects.annotate(num_productos=Count('productos')).order_by('-id')
    return render(request, 'crear_categoria.html', {'form': form, 'categorias': categorias, 'editando': categoria})


@login_required
@permission_required('Inventario.delete_categoria')
def eliminar_categoria(request, categoria_id):
    categoria = get_object_or_404(Categoria, id=categoria_id)
    if request.method == 'POST':
        nombre = categoria.name
        categoria.delete()
        messages.success(request, f'Categoría "{nombre}" eliminada exitosamente.')
    return redirect('crear_categoria')


@login_required
@permission_required('Inventario.view_productos')
def listar_productos(request):
    search_query = request.GET.get('q', '').strip()
    productos_list = Productos.objects.select_related('Categoria').all().order_by('Codigo')
    if search_query:
        productos_list = productos_list.filter(
            Q(Codigo__icontains=search_query)
            | Q(Descripcion__icontains=search_query)
            | Q(Categoria__name__icontains=search_query)
        )
    paginator = Paginator(productos_list, 5)  # 5 productos por página

    page_number = request.GET.get('page')  # Obtén el número de página de la URL
    productos = paginator.get_page(page_number)

    context = {
        'productos': productos,
        'racismo': 'Inventario',
        'search_query': search_query,
    }
    return render(request, 'Productos.html', context)

@login_required
@permission_required('Inventario.add_productos')
def addProducto(request):
    if request.method == 'POST':
        productos = ProductosForm(request.POST, request.FILES)
        if productos.is_valid():
            producto = productos.save(commit=False)
            producto.Cantidad = productos.cleaned_data.get('Cantidad') or 0
            producto.Costo = productos.cleaned_data.get('Costo') or 0
            producto.save()
            save_product_presentations(producto, request)
            messages.success(request, 'Producto agregado exitosamente')
            return redirect('listar_productos')
        else:
            messages.error(request, 'Error al agregar el producto')
    else:
        productos = ProductosForm()
    context = {'productos': productos}
    return render(request, 'addProducto.html', context)

@login_required
@permission_required('Inventario.change_productos')
def updtProducto(request, id):
    producto = get_object_or_404(Productos, Codigo=id)  # Cambia id=id por Codigo=id
    if request.method == 'POST':
        productos = ProductosForm(request.POST, request.FILES, instance=producto)
        if productos.is_valid():
            producto = productos.save(commit=False)
            producto.Cantidad = productos.cleaned_data.get('Cantidad') or 0
            producto.Costo = productos.cleaned_data.get('Costo') or producto.Costo
            producto.save()
            save_product_presentations(producto, request)
            messages.success(request, 'Producto actualizado exitosamente')
            return redirect('listar_productos')
        else:
            messages.error(request, 'Error al actualizar el producto')
    else:
        productos = ProductosForm(instance=producto)
    # Pasar JSON válido de presentaciones para inicializar Alpine.js en el template
    presentaciones = producto.presentaciones.all()
    try:
        presentations_json = json.dumps(presentation_context(producto), default=str)
    except Exception:
        presentations_json = '[]'
    context = {
        'producto': producto,
        'productos': productos,
        'presentaciones': presentaciones,
        'presentations_json': presentations_json,
    }
    return render(request, 'updtProducto.html', context)

@login_required
@permission_required('Inventario.delete_productos')
@require_POST
def dltProducto(request, id):
    producto = get_object_or_404(Productos, Codigo=id)
    try:
        producto.delete()
        messages.success(request, 'Producto eliminado exitosamente')
    except ProtectedError as e:
        # Obtener detalles que impiden la eliminación (DetalleFactura)
        try:
            detalles = DetalleFactura.objects.filter(producto=producto).select_related('factura')
            facturas = sorted({str(d.factura.numero) for d in detalles})
            if facturas:
                messages.error(request, f"No se puede eliminar el producto porque está referenciado en la(s) factura(s): {', '.join(facturas)}. Anule o elimine esas facturas primero.")
            else:
                messages.error(request, 'No se puede eliminar el producto porque existen referencias protegidas que impiden la eliminación.')
        except Exception:
            messages.error(request, 'No se puede eliminar el producto porque existen referencias protegidas que impiden la eliminación.')
    return redirect('listar_productos')

@login_required
@permission_required('Inventario.view_productos', raise_exception=True)
def inventario(request):
    productos = Paginator(
        Productos.objects.all().order_by('-Fecha_creacion'),
        5,
    ).get_page(request.GET.get('page'))
    total_unidades = Productos.objects.aggregate(total=Sum('Cantidad'))['total'] or 0
    context = {
        'productos': productos,
        'total_unidades': total_unidades,
        'racismo': 'Inventario',
    }
    return render(request, 'Inventario/inventario.html', context)

def movimientos_inventario(request):
    productos = Productos.objects.all()
    fecha_inicio = request.GET.get('fecha_inicio')
    fecha_fin = request.GET.get('fecha_fin')
    producto_id = request.GET.get('producto')

    movimientos = MovimientoInventario.objects.select_related('producto').order_by('-fecha')

    hay_filtro = fecha_inicio or fecha_fin or (producto_id and producto_id.isdigit())

    if fecha_inicio:
        movimientos = movimientos.filter(fecha__gte=fecha_inicio)
    if fecha_fin:
        try:
            from datetime import datetime, timedelta
            fecha_fin_dt = datetime.strptime(fecha_fin, "%Y-%m-%d") + timedelta(days=1)
            movimientos = movimientos.filter(fecha__lt=fecha_fin_dt)
        except Exception:
            pass
    if producto_id and producto_id.isdigit():
        movimientos = movimientos.filter(producto_id=int(producto_id))

    if not hay_filtro:
        movimientos = movimientos[:10]  # Solo los 10 últimos si no hay filtro

    return render(request, 'Inventario/movimientos_inventario.html', {
        'movimientos': movimientos,
        'productos': productos,
        'fecha_inicio': fecha_inicio or '',
        'fecha_fin': fecha_fin or '',
        'producto_id': int(producto_id) if producto_id and producto_id.isdigit() else '',
    })

def agregar_stock(request, id):
    producto = get_object_or_404(Productos, id=id)
    if request.method == 'POST':
        cantidad = request.POST.get('cantidad')
        try:
            cantidad = int(cantidad)
            registrar_movimiento(producto, 'entrada', cantidad, 'Compra registrada', request.user)
            messages.success(request, 'Stock actualizado exitosamente')
        except (TypeError, ValueError, ValidationError) as error:
            messages.error(request, str(error) or 'Cantidad inválida')
        return redirect('inventario')
    return render(request, 'agregar_stock.html', {'producto': producto})

def nuevo_movimiento_inventario(request):
    if request.method == 'POST':
        producto_id = request.POST.get('producto')
        tipo = request.POST.get('tipo')
        cantidad = request.POST.get('cantidad')
        descripcion = request.POST.get('descripcion')
        try:
            registrar_movimiento(producto_id, tipo, cantidad, descripcion or '', request.user)
            messages.success(request, 'Movimiento y existencias actualizados.')
        except (TypeError, ValueError, ValidationError, Productos.DoesNotExist) as error:
            messages.error(request, str(error) or 'No se pudo registrar el movimiento.')
        return redirect('movimientos_inventario')
    productos = Productos.objects.all()
    return render(request, 'Inventario/nuevo_movimiento.html', {'productos': productos})

@staff_member_required(login_url='login_admin_custom')
def registrar_salida(request):
    if request.method == 'POST':
        producto_id = request.POST.get('producto_id')
        try:
            cantidad = int(request.POST.get('cantidad', ''))
        except (TypeError, ValueError):
            messages.error(request, 'La cantidad debe ser un número entero positivo.')
            return redirect('inventario')
        if cantidad <= 0:
            messages.error(request, 'La cantidad debe ser un número entero positivo.')
            return redirect('inventario')
        try:
            producto = Productos.objects.get(pk=producto_id)
            registrar_movimiento(
                producto,
                'salida',
                cantidad,
                'Salida manual',
                request.user,
            )
            producto.refresh_from_db(fields=['Cantidad'])
            messages.success(request, f"Salida registrada. Nuevo stock de {getattr(producto, 'Descripcion', getattr(producto, 'Nombre', 'Producto'))}: {producto.Cantidad}")
        except Productos.DoesNotExist:
            messages.error(request, "Producto no encontrado.")
        except Exception as e:
            messages.error(request, f"Error al registrar salida: {str(e)}")
        return redirect('inventario')
    # Si no es POST, redirigimos al inventario (asegura que la vista siempre devuelve HttpResponse)
    return redirect('inventario')

def actualizar_precio(request, pk):
    producto = get_object_or_404(Productos, pk=pk)
    if request.method == 'POST':
        form = ActualizarPrecioForm(request.POST, instance=producto)
        if form.is_valid():
            form.save()
            messages.success(request, '¡Precio de venta actualizado correctamente!')
            return redirect('listar_productos')
    else:
        form = ActualizarPrecioForm(instance=producto)
    return render(request, 'inventario/actualizar_precio.html', {'form': form, 'producto': producto})

@login_required
@permission_required('Inventario.change_productos', raise_exception=True)
@require_POST
def actualizar_precio_ajax(request):
    try:
        data = json.loads(request.body)
        producto_id = data.get('producto_id')
        nuevo_precio = Decimal(str(data.get('nuevo_precio')))
        if not nuevo_precio.is_finite() or nuevo_precio < 0:
            raise InvalidOperation
    except (json.JSONDecodeError, TypeError, ValueError, InvalidOperation):
        return JsonResponse({'success': False, 'error': 'Datos de precio inválidos.'}, status=400)

    try:
        producto = Productos.objects.get(pk=producto_id)
    except (Productos.DoesNotExist, ValueError, TypeError):
        return JsonResponse({'success': False, 'error': 'Producto no encontrado.'}, status=404)

    producto.Precio = nuevo_precio
    producto.save(update_fields=['Precio'])
    return JsonResponse({'success': True})

@cliente_required
def carrito(request):
    productos = Productos.objects.all()
    context = {
        'productos': productos,
    }
    return render(request, 'carrito.html', context)
