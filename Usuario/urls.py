from django.urls import path, include
from . import views
from dashboard import views as dashboard_views

urlpatterns = [
    path('usuarios/', views.usuarios, name='usuarios'),
    path('addUser/', views.addUser, name='addUser'),
    path('updtUser/<int:id>/', views.updtUser, name='updtUser'),
    path('dltUser/<int:id>/', views.dltUser, name='dltUser'),
    path('clientes/ver/<int:pk>/', views.ver_cliente, name='ver_cliente'),
    path('clientes/pdf/<int:pk>/', views.cliente_pdf, name='cliente_pdf'),
]
