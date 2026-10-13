from django.contrib import admin
from django.urls import path, include
from django.views.generic.base import RedirectView
from dashboard import views as dashboard_views
from dashboard.views import login_view
from Usuario import views as usuario_views
from Proveedores import views as proveedores_views
from Inventario import views as inventario_views
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('media/comprobantes/<path:filename>', dashboard_views.descargar_comprobante_admin, name='private_payment_receipt'),
    # Redirige la ruta falsa del admin hacia el login real del sistema.
    path('admin/', RedirectView.as_view(url='/admin-panel/login/', permanent=False), name='admin_redirect'),
    # Ruta real no obvia para el panel administrativo protegido por staff.
    path('admin-panel/portal-acceso-ferre-99x/', admin.site.urls),
    path('', include('dashboard.urls'), name='dashboard'),
    path('accounts/login/', RedirectView.as_view(pattern_name='login_cliente', permanent=False), name='accounts_login_cliente'),
    path('accounts/', include('django.contrib.auth.urls')),
    path('accounts/', include('allauth.urls')),
    
    # Clientes
    path('admin-panel/usuarios/', include('Usuario.urls'), name='usuarios'),

    # Proveedores
    path('admin-panel/proveedores/', include('Proveedores.urls'), name='proveedores'),
    
    # Inventario
    path('admin-panel/inventario/', include('Inventario.urls'), name='inventario'),
    
    # Reportes
    path('admin-panel/reportes/', include('Reportes.urls')),
    
    # Authentication
    path('admin-panel/login/', login_view, name='login_admin_custom'),
    path('admin-panel/staff/login/', login_view, name='staff_login'),
    path('admin-panel/desbloquear/', dashboard_views.admin_login_unlock, name='admin_login_unlock'),
    path('login/', RedirectView.as_view(pattern_name='login_cliente', permanent=False), name='legacy_admin_login'),
    # Login exclusivo para clientes del e-commerce
    path('cliente/login/', dashboard_views.cliente_login, name='login_cliente'),
    path('logout/', dashboard_views.cliente_logout, name='logout'),
    path('auth/google-login/', dashboard_views.google_identity_login, name='google_identity_login'),

    # Formulario
    path('admin-panel/formulario/', dashboard_views.formulario_view, name='formulario'),
    
    # Ventas
    path('admin-panel/ventas/', include('Ventas.urls')),

    # Compras
    path('admin-panel/compras/', include('Compras.urls')),
    path('compras/', RedirectView.as_view(url='/admin-panel/compras/', permanent=False), name='legacy_compras'),

    # CxC
    path('admin-panel/cxc/', include('CxC.urls')),

    # Social Auth
    path('oauth/', include('social_django.urls', namespace='social')),
]

# Usa una respuesta controlada para los accesos prohibidos y los límites de tasa.
handler403 = 'dashboard.views.rate_limit_403'

# Servir MEDIA (y opcionalmente STATIC) solo en desarrollo para evitar exponer en producción.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    # En la mayoría de setups Django devserver ya sirve STATIC_URL, pero incluimos esto
    # por si se requiere exponer archivos estáticos adicionales desde STATIC_ROOT.
    try:
        urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    except Exception:
        pass
