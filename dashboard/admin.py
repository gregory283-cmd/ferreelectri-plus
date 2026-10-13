from .models import Producto, Cliente, Customer, PerfilCliente, Carrito, CarritoItem, Pedido, PedidoItem, ChatSession, ChatMessage, Pago
from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

class PedidoAdmin(admin.ModelAdmin):
	list_display = ('id', 'cliente', 'fecha_creacion', 'total', 'estado')
	list_filter = ('estado',)
	search_fields = ('cliente__email',)
	readonly_fields = ('estado', 'stock_descontado')
	actions = None

	class PagoInline(admin.TabularInline):
		model = Pago
		extra = 0
		can_delete = False
		fields = ('metodo', 'monto', 'banco_origen', 'cedula_pagador', 'numero_referencia', 'comprobante_descarga', 'estado', 'verificado')
		readonly_fields = fields

		@admin.display(description='Comprobante')
		def comprobante_descarga(self, obj):
			if not obj.comprobante:
				return 'No adjunto'
			return format_html('<a href="{}">Descargar comprobante</a>', reverse('admin_comprobante_pago', args=[obj.pk]))

	inlines = [PagoInline]


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
	list_display = ('nombre', 'email', 'cedula', 'telefono', 'direccion')
	search_fields = ('nombre', 'email', 'cedula', 'telefono')


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
	list_display = ('nombre', 'email', 'cedula', 'telefono', 'is_active', 'is_guest', 'fecha_registro')
	list_filter = ('is_active', 'is_guest', 'fecha_registro')
	search_fields = ('nombre', 'email', 'cedula', 'telefono', 'direccion')
	readonly_fields = ('fecha_registro', 'last_login')


@admin.register(PerfilCliente)
class PerfilClienteAdmin(admin.ModelAdmin):
	list_display = ('user', 'razon_social', 'cedula_rif', 'telefono', 'direccion', 'fecha_actualizacion')
	search_fields = ('user__username', 'user__email', 'razon_social', 'cedula_rif', 'telefono')
	readonly_fields = ('fecha_actualizacion',)


admin.site.register(Producto)
admin.site.register(Carrito)
admin.site.register(CarritoItem)
admin.site.register(Pedido, PedidoAdmin)
admin.site.register(PedidoItem)


@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
	list_display = ('title', 'user', 'session_key', 'created_at', 'updated_at')
	search_fields = ('title', 'user__username', 'user__email')
	list_filter = ('created_at', 'updated_at')


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
	list_display = ('session', 'role', 'action_type', 'timestamp')
	search_fields = ('content', 'session__title', 'session__user__username')
	list_filter = ('role', 'action_type', 'timestamp')
