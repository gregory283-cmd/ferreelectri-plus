from django.urls import path
from . import views

urlpatterns = [
    path('', views.inventario, name='inventario'),
    path('productos/', views.listar_productos, name='listar_productos'),
    path('categorias/crear/', views.crear_categoria, name='crear_categoria'),
    path('categorias/<int:categoria_id>/editar/', views.editar_categoria, name='editar_categoria'),
    path('categorias/<int:categoria_id>/eliminar/', views.eliminar_categoria, name='eliminar_categoria'),
    path('addProducto/', views.addProducto, name='addProducto'),
    path('updtProducto/<str:id>/', views.updtProducto, name='updtProducto'),
    path('dltProducto/<str:id>/', views.dltProducto, name='dltProducto'),  # <--- CAMBIA int por str
    path('movimientos/', views.movimientos_inventario, name='movimientos_inventario'),
    path('movimientos/nuevo/', views.nuevo_movimiento_inventario, name='nuevo_movimiento_inventario'),  # <--- AGREGA ESTA LÍNEA
    path('registrar_salida/', views.registrar_salida, name='registrar_salida'),
    path('producto/<int:pk>/actualizar-precio/', views.actualizar_precio, name='actualizar_precio'),
    path('actualizar-precio-ajax/', views.actualizar_precio_ajax, name='actualizar_precio_ajax'),
]
