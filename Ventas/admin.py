from django.contrib import admin
from .models import Ventas, Factura, DetalleFactura

admin.site.register(Ventas)
admin.site.register(Factura)
admin.site.register(DetalleFactura)
