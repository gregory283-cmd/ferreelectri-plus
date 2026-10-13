from django.urls import path

from . import views

urlpatterns = [
    path("", views.listar_cxc, name="listar_cxc"),
    path("facturas/anuladas/", views.listar_cxc_anuladas, name="listar_cxc_anuladas"),
    path("facturas/<int:numero_factura>/pagos/", views.pagos_de_factura, name="pagos_factura"),
    path(
        "facturas/<int:numero_factura>/pago/registrar/",
        views.registrar_pago_form,
        name="registrar_pago_form",
    ),
    path("facturas/<int:numero_factura>/reactivar/", views.reactivar_factura_cxc, name="reactivar_factura_cxc"),
    path("pago/registrar/<int:numero_factura>/", views.registrar_pago, name="registrar_pago"),
    path("pago/anular/<int:pago_id>/", views.anular_pago, name="anular_pago"),
    path("mantenimiento/asegurar-cuentas/", views.asegurar_cuentas_cxc, name="asegurar_cuentas_cxc"),
]
