from django.contrib import admin
from .models import Productos, MovimientoInventario
from .models import Categoria


@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
	list_display = ('name', 'slug')
	search_fields = ('name',)


@admin.register(Productos)
class ProductosAdmin(admin.ModelAdmin):
	list_display = ('Codigo', 'Descripcion', 'Categoria', 'Precio', 'iva', 'Cantidad', 'promocion')
	list_filter = ('Categoria', 'iva', 'promocion')
	search_fields = ('Codigo', 'Descripcion')


admin.site.register(MovimientoInventario)
