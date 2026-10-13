from django.urls import path
from . import views

urlpatterns = [
    path('clientes/pdf/', views.reporte_clientes_pdf, name='reporte_clientes_pdf'),
    path('clientes/excel/', views.reporte_clientes_excel, name='reporte_clientes_excel'),
    path('proveedores/pdf/', views.reporte_proveedores_pdf, name='reporte_proveedores_pdf'),
    path('proveedores/excel/', views.reporte_proveedores_excel, name='reporte_proveedores_excel'),
    path('productos/pdf/', views.reporte_productos_pdf, name='reporte_productos_pdf'),
    path('productos/excel/', views.reporte_productos_excel, name='reporte_productos_excel'),
    path('facturas/pdf/', views.reporte_facturas_pdf, name='reporte_facturas_pdf'),
    path('facturas/excel/', views.reporte_facturas_excel, name='reporte_facturas_excel'),
    path('factura/pdf/<int:numero>/', views.reporte_factura_pdf, name='reporte_factura_pdf'),
]