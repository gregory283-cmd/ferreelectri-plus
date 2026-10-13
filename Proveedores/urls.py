from django.urls import path, include
from . import views
from dashboard import views as dashboard_views

urlpatterns = [
    path('Proveedor/', views.Proveedor, name='Proveedor'),
    path('addProveedor/', views.addProveedor, name='addProveedor'),
    path('updtProveedor/<int:id>/', views.updtProveedor, name='updtProveedor'),
    path('dltProveedor/<int:id>/', views.dltProveedor, name='dltProveedor'),
    path('reporte/pdf/<int:pk>/', views.reporte_proveedor_pdf, name='reporte_proveedor_pdf'),
    path('ver/<int:pk>/', views.ver_proveedor, name='ver_proveedor'),
]
