from django.urls import path
from . import views

urlpatterns = [
    path('', views.listar_compras, name='listar_compras'),
    path('compras/ver/<int:compra_id>/', views.ver_compra, name='ver_compra'),
    path('compras/modificar/<int:compra_id>/', views.modificar_compra, name='modificar_compra'),
    path('compras/anular/<int:compra_id>/', views.anular_compra, name='anular_compra'),
    path('compras/eliminar/<int:compra_id>/', views.eliminar_compra, name='eliminar_compra'),
    path('compras/reactivar/<int:compra_id>/', views.reactivar_compra, name='reactivar_compra'),
    path('formato-compras/', views.formato_compras, name='formato_compras'),
    path('reporte-compras/csv/', views.reporte_compras_csv, name='reporte_compras_csv'),
    path('api/proveedores/', views.api_proveedores, name='api_proveedores'),
    path('api/articulos/', views.api_articulos, name='api_articulos'),
    path('api/guardar_compra/', views.guardar_compra, name='guardar_compra'),
]