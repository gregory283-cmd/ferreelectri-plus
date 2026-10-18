from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from Inventario.models import Productos

User = get_user_model()


class VentasCSRFTest(TestCase):
	def setUp(self):
		self.user = User.objects.create_superuser(
			username='ventas-csrf-admin',
			email='ventas-csrf-admin@example.com',
			password='VentasTest123!',
		)

	def test_escrituras_financieras_rechazan_post_sin_csrf(self):
		client = Client(enforce_csrf_checks=True)
		client.force_login(self.user)
		requests = (
			('guardar_factura', '{}'),
			('actualizar_precio_venta', '{"codigo":"A0001","precio_venta":"1.00"}'),
			('guardar_orden_productos', '{"orden":[]}'),
			('gestionar_costo_pendiente', '{"accion":"crear"}'),
		)

		for route_name, payload in requests:
			response = client.post(
				reverse(route_name),
				data=payload,
				content_type='application/json',
			)
			self.assertEqual(response.status_code, 403, route_name)

	def test_alta_venta_requiere_permiso_y_renderiza_formulario(self):
		client = Client()
		url = reverse('agregar_factura')
		self.assertEqual(client.get(url).status_code, 302)

		client.force_login(self.user)
		response = client.get(url)
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Registrar venta')
		print_response = client.get(reverse('formato_facturacion'))
		self.assertEqual(print_response.status_code, 200)
		self.assertContains(print_response, 'id="tipo_documento"')
		self.assertContains(print_response, 'FACTURA DE VENTA')
		self.assertContains(print_response, 'Número de control')
		self.assertContains(print_response, 'id="pi-direccion"')
		self.assertContains(print_response, 'Impuestos por alícuota')
		self.assertContains(print_response, 'Precio ($)')
		self.assertContains(
			print_response,
			f'const guardarFacturaUrl = "{reverse("guardar_factura")}";',
		)
		self.assertContains(print_response, 'id="invoice-csrf-form"')
		self.assertNotContains(print_response, 'alert(')
		self.assertNotContains(print_response, 'no fiscal')
		self.assertContains(print_response, 'formato-facturacion.css')
		self.assertContains(print_response, 'onclick="imprimirDocumento()"')
		self.assertContains(print_response, 'id="btn-buscar-cliente"')
		self.assertContains(print_response, 'id="btn-buscar-producto"')

	def test_gestionar_precios_renderiza_precio_y_existencia(self):
		from decimal import Decimal

		Productos.objects.create(
			Codigo='A1000',
			Descripcion='Producto de prueba de precios',
			Precio=Decimal('12.00'),
			Costo=Decimal('8.00'),
			Cantidad=5,
		)
		client = Client()
		client.force_login(self.user)

		response = client.get(reverse('gestionar_precios'))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Producto de prueba de precios')
		self.assertContains(response, '$12,00')
		self.assertContains(response, '$8,00')
		self.assertContains(response, 'data-stock="5"')
		self.assertContains(response, 'Precio y rentabilidad')
		self.assertContains(response, 'Recargo sobre costo (%)')
		self.assertContains(response, 'Margen bruto estimado')
		self.assertContains(response, '.modal-card.cost-modal { width: 100%; height: calc(100dvh - 20px);')
		self.assertContains(response, 'grid-template-columns: minmax(0, 1fr);')

	def test_actualizar_precio_no_permite_saltar_aprobacion_de_costo(self):
		import json
		from decimal import Decimal
		from Inventario.models import CostoCambio, CostoPendiente

		producto = Productos.objects.create(
			Codigo='A1001', Descripcion='Producto con costo editable',
			Precio=Decimal('12.00'), Costo=Decimal('8.00'), Cantidad=4,
		)
		client = Client()
		client.force_login(self.user)
		url = reverse('actualizar_precio_venta')
		payload = {'codigo': producto.Codigo, 'costo': '10.00', 'precio_venta': '12.00', 'en_promocion': False}
		propuesta = client.post(url, data=json.dumps(payload), content_type='application/json')
		self.assertTrue(propuesta.json()['cost_pending'])
		producto.refresh_from_db()
		self.assertEqual(producto.Costo, Decimal('8.00'))
		self.assertEqual(producto.Precio, Decimal('12.00'))
		self.assertEqual(CostoPendiente.objects.get(producto=producto).estado, 'pendiente')

		payload = {'codigo': producto.Codigo, 'precio_venta': '7.00', 'en_promocion': False}
		warning = client.post(url, data=json.dumps(payload), content_type='application/json')
		self.assertTrue(warning.json()['warning'])
		payload['force'] = True
		response = client.post(url, data=json.dumps(payload), content_type='application/json')
		self.assertTrue(response.json()['success'])
		producto.refresh_from_db()
		self.assertEqual(producto.Costo, Decimal('8.00'))
		self.assertEqual(producto.Precio, Decimal('7.00'))
		self.assertFalse(CostoCambio.objects.filter(producto=producto).exists())


class FacturaStockLifecycleTest(TestCase):
	def test_editar_factura_usa_stock_neto_y_no_duplica_descuento(self):
		import json
		from datetime import date
		from django.contrib.auth import get_user_model
		from django.test import Client
		from Usuario.models import Clientes
		from .models import DetalleFactura, Factura

		user = get_user_model().objects.create_superuser(
			username='invoice-edit-stock-admin', email='invoice-edit-stock@example.com', password='Test12345!'
		)
		cliente = Clientes.objects.create(
			nombre='Cliente', apellido='Edición', telefono='04140000002',
			cedula='V12345670', direccion='Dirección de prueba',
			email='invoice-edit-stock-customer@example.com', fecha_nacimiento=date(1990, 1, 1),
		)
		producto = Productos.objects.create(Descripcion='Producto editar factura', Precio=20, Costo=10, Cantidad=10)
		factura = Factura.objects.create(cliente=cliente)
		DetalleFactura.objects.create(factura=factura, producto=producto, cantidad=2, precio=20, iva=16)
		client = Client()
		client.force_login(user)
		url = reverse('editar_factura', args=[factura.numero])
		page = client.get(url)
		self.assertEqual(page.status_code, 200)
		self.assertContains(page, 'id="btn-buscar-cliente"')
		self.assertContains(page, 'id="btn-buscar-producto"')
		self.assertContains(page, 'btn-buscar-producto-fila')
		payload = {'cliente': {'cedula': cliente.cedula}, 'productos': [{'codigo': producto.Codigo, 'cantidad': 20, 'precio': 20, 'descuento': 0}]}

		fallida = client.post(url, data=json.dumps(payload), content_type='application/json')
		self.assertEqual(fallida.status_code, 400)
		producto.refresh_from_db()
		self.assertEqual(producto.Cantidad, 8)
		self.assertEqual(factura.detalles.count(), 1)

		payload['productos'][0]['cantidad'] = 3
		correcta = client.post(url, data=json.dumps(payload), content_type='application/json')
		self.assertTrue(correcta.json()['success'])
		producto.refresh_from_db()
		self.assertEqual(producto.Cantidad, 7)
		self.assertEqual(factura.detalles.get().cantidad, 3)

	def test_anulacion_y_reactivacion_son_idempotentes_y_validan_stock(self):
		from datetime import date
		from decimal import Decimal
		from django.contrib.auth import get_user_model
		from django.test import Client
		from Inventario.models import MovimientoInventario
		from Usuario.models import Clientes
		from .models import DetalleFactura, Factura

		user = get_user_model().objects.create_superuser(
			username='stock-lifecycle-admin', email='stock-lifecycle@example.com', password='Test12345!'
		)
		cliente = Clientes.objects.create(
			nombre='Cliente', apellido='Inventario', telefono='04140000001',
			cedula='V12345679', direccion='Dirección de prueba',
			email='stock-lifecycle-customer@example.com', fecha_nacimiento=date(1990, 1, 1),
		)
		producto = Productos.objects.create(Descripcion='Producto control de stock', Precio=20, Costo=10, Cantidad=10)
		factura = Factura.objects.create(cliente=cliente)
		DetalleFactura.objects.create(factura=factura, producto=producto, cantidad=2, precio=20, iva=16)
		producto.refresh_from_db()
		self.assertEqual(producto.Cantidad, 8)

		client = Client()
		client.force_login(user)
		url_anular = reverse('anular_factura', args=[factura.numero])
		client.post(url_anular)
		client.post(url_anular)
		producto.refresh_from_db()
		factura.refresh_from_db()
		self.assertEqual(producto.Cantidad, 10)
		self.assertEqual(factura.estado, 'anulada')
		self.assertEqual(MovimientoInventario.objects.filter(descripcion__contains='Reintegro por anulación').count(), 1)

		producto.Cantidad = 1
		producto.save(update_fields=['Cantidad'])
		url_activar = reverse('activar_factura', args=[factura.numero])
		client.post(url_activar)
		factura.refresh_from_db()
		self.assertEqual(factura.estado, 'anulada')
		self.assertEqual(producto.Cantidad, 1)

		producto.Cantidad = 2
		producto.save(update_fields=['Cantidad'])
		client.post(url_activar)
		client.post(url_activar)
		producto.refresh_from_db()
		factura.refresh_from_db()
		self.assertEqual(producto.Cantidad, 0)
		self.assertEqual(factura.estado, 'facturada')
		self.assertEqual(MovimientoInventario.objects.filter(descripcion__contains='Reactivación de venta').count(), 1)


class ListaPreciosToolsTest(TestCase):
	def setUp(self):
		from decimal import Decimal
		from django.contrib.auth import get_user_model
		from Inventario.models import Productos

		self.user = get_user_model().objects.create_superuser(
			username='price-tools-admin', email='price-tools@example.com', password='Test12345!'
		)
		self.producto_gravado = Productos.objects.create(
			Codigo='A2001', Descripcion='Producto gravado prueba', Precio=Decimal('100.00'),
			Costo=Decimal('60.00'), iva=Decimal('16.00'), orden_lista=1,
		)
		self.producto_exento = Productos.objects.create(
			Codigo='A2002', Descripcion='Producto exento prueba', Precio=Decimal('50.00'),
			Costo=Decimal('25.00'), iva=Decimal('0.00'), orden_lista=2,
		)
		self.client = Client()
		self.client.force_login(self.user)

	def test_orden_guardado_se_refleja_en_tabla_y_lista_pdf(self):
		import json
		from unittest.mock import patch

		response = self.client.post(
			reverse('guardar_orden_productos'),
			data=json.dumps({'orden': [self.producto_exento.Codigo, self.producto_gravado.Codigo]}),
			content_type='application/json',
		)
		self.assertTrue(response.json()['success'])
		self.producto_exento.refresh_from_db()
		self.producto_gravado.refresh_from_db()
		self.assertEqual(self.producto_exento.orden_lista, 0)
		self.assertEqual(self.producto_gravado.orden_lista, 1)

		catalog_response = self.client.get(reverse('gestionar_precios'))
		self.assertLess(
			catalog_response.content.index(b'Producto exento prueba'),
			catalog_response.content.index(b'Producto gravado prueba'),
		)
		with patch('Ventas.views.HTML') as html:
			html.return_value.write_pdf.return_value = b'%PDF-test'
			pdf_response = self.client.get(reverse('lista_precios_pdf'))
		self.assertEqual(pdf_response.status_code, 200)
		pdf_html = html.call_args.kwargs['string']
		self.assertLess(pdf_html.index('Producto exento prueba'), pdf_html.index('Producto gravado prueba'))
		self.assertIn('page-break-inside:avoid !important', pdf_html)

	def test_lista_pdf_desglosa_iva_solo_para_productos_gravados(self):
		from unittest.mock import patch

		with patch('Ventas.views.HTML') as html:
			html.return_value.write_pdf.return_value = b'%PDF-test'
			response = self.client.get(reverse('lista_precios_pdf'))
		self.assertEqual(response.status_code, 200)
		pdf_html = html.call_args.kwargs['string']
		self.assertIn('+ IVA 16%', pdf_html)
		self.assertIn('$100,00', pdf_html)
		self.assertIn('$50,00', pdf_html)
		self.assertNotIn('$116,00', pdf_html)
		self.assertNotIn('IVA 0%', pdf_html)

	def test_catalogo_4x_generates_pdf_with_shared_print_theme(self):
		from unittest.mock import patch

		with patch('Ventas.views.HTML') as pdf_engine:
			pdf_engine.return_value.write_pdf.return_value = b'%PDF-test'
			response = self.client.get(reverse('catalogo_4x_pdf'))
			rendered_html = pdf_engine.call_args.kwargs['string']

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response['Content-Type'], 'application/pdf')
		self.assertIn('background-image: none', rendered_html)
		self.assertIn('Catálogo de Productos', rendered_html)


class CostoPendienteWorkflowTest(TestCase):
	def setUp(self):
		from decimal import Decimal
		from django.contrib.auth import get_user_model
		from Inventario.models import Productos

		self.user = get_user_model().objects.create_superuser(
			username='pending-cost-admin', email='pending-cost@example.com', password='Test12345!'
		)
		self.producto = Productos.objects.create(
			Codigo='A3001', Descripcion='Tornillo de prueba', Precio=Decimal('15.00'),
			Costo=Decimal('11.00'), Cantidad=20,
		)
		self.client = Client()
		self.client.force_login(self.user)
		self.url = reverse('gestionar_costo_pendiente')

	def post_json(self, payload):
		import json
		return self.client.post(self.url, data=json.dumps(payload), content_type='application/json')

	def crear_propuesta(self, costo, cantidad=12, unidad='unidades'):
		response = self.post_json({
			'accion': 'crear', 'codigo': self.producto.Codigo,
			'cantidad_compra': cantidad, 'unidad_compra': unidad,
			'costo_propuesto': str(costo), 'motivo': 'Nueva compra',
		})
		self.assertEqual(response.status_code, 200, response.content)
		return response.json()['id']

	def test_propuesta_solo_cambia_costo_al_aprobar_y_revertir(self):
		from decimal import Decimal
		from Inventario.models import CostoCambio, CostoPendiente

		propuesta_id = self.crear_propuesta('9.50')
		self.producto.refresh_from_db()
		self.assertEqual(self.producto.Costo, Decimal('11.00'))

		editada = self.post_json({
			'accion': 'editar', 'id': propuesta_id, 'cantidad_compra': 15,
			'costo_propuesto': '9.25', 'motivo': 'Factura corregida',
		})
		self.assertTrue(editada.json()['success'])
		self.assertEqual(CostoPendiente.objects.get(pk=propuesta_id).estado, 'espera_stock')
		from Inventario.utils import registrar_movimiento
		registrar_movimiento(self.producto, 'salida', 20, 'Agotamiento de costo caro')
		aprobada = self.post_json({'accion': 'aprobar', 'id': propuesta_id})
		self.assertTrue(aprobada.json()['success'])
		self.producto.refresh_from_db()
		propuesta = CostoPendiente.objects.get(pk=propuesta_id)
		self.assertEqual(self.producto.Costo, Decimal('9.25'))
		self.assertEqual(propuesta.costo_anterior, Decimal('11.00'))
		self.assertEqual(propuesta.cantidad_compra, 15)

		posterior_id = self.crear_propuesta('10.00', cantidad=2, unidad='cajas')
		self.assertTrue(self.post_json({'accion': 'aprobar', 'id': posterior_id}).json()['success'])
		conflicto = self.post_json({'accion': 'revertir', 'id': propuesta_id})
		self.assertEqual(conflicto.status_code, 409)
		self.producto.refresh_from_db()
		self.assertEqual(self.producto.Costo, Decimal('10.00'))

		reversion = self.post_json({'accion': 'revertir', 'id': posterior_id})
		self.assertTrue(reversion.json()['success'])
		self.producto.refresh_from_db()
		self.assertEqual(self.producto.Costo, Decimal('9.25'))
		self.assertIsNotNone(CostoPendiente.objects.get(pk=posterior_id).revertido_en)
		self.assertEqual(CostoCambio.objects.filter(producto=self.producto).count(), 3)

	def test_denegar_y_eliminar_propuesta_no_modifica_costo(self):
		from decimal import Decimal
		from Inventario.models import CostoPendiente

		propuesta_id = self.crear_propuesta('8.75')
		denegada = self.post_json({'accion': 'denegar', 'id': propuesta_id})
		self.assertTrue(denegada.json()['success'])
		self.producto.refresh_from_db()
		self.assertEqual(self.producto.Costo, Decimal('11.00'))
		propuesta = CostoPendiente.objects.get(pk=propuesta_id)
		self.assertEqual(propuesta.estado, 'rechazado')
		self.assertIsNotNone(propuesta.revisado_en)
		eliminada = self.post_json({'accion': 'eliminar', 'id': propuesta_id})
		self.assertTrue(eliminada.json()['success'])
		self.assertFalse(CostoPendiente.objects.filter(pk=propuesta_id).exists())

	def test_cantidad_y_costo_de_propuesta_se_validan(self):
		response = self.post_json({
			'accion': 'crear', 'codigo': self.producto.Codigo,
			'cantidad_compra': 0, 'costo_propuesto': '7.00',
		})
		self.assertEqual(response.status_code, 400)
		response = self.post_json({
			'accion': 'crear', 'codigo': self.producto.Codigo,
			'cantidad_compra': 2, 'costo_propuesto': '-1.00',
		})
		self.assertEqual(response.status_code, 400)


class DetalleFacturaFiscalTotalsTest(TestCase):
	def test_line_items_group_base_and_tax_by_rate(self):
		from decimal import Decimal
		from .models import DetalleFactura, Factura

		factura = Factura()
		detalle_gravado = DetalleFactura(
			precio=Decimal('100.00'), cantidad=2,
			descuento=Decimal('10.00'), iva=Decimal('16.00'),
		)
		detalle_reducido = DetalleFactura(
			precio=Decimal('50.00'), cantidad=1,
			descuento=Decimal('0.00'), iva=Decimal('8.00'),
		)

		resumen = factura.resumen_tributario([detalle_gravado, detalle_reducido])

		self.assertEqual(detalle_gravado.base_imponible, Decimal('180.00'))
		self.assertEqual(detalle_gravado.monto_iva, Decimal('28.80'))
		self.assertEqual(detalle_gravado.total_linea, Decimal('208.80'))
		self.assertEqual(
			resumen,
			[
				{'alicuota': Decimal('8.00'), 'base_imponible': Decimal('50.00'), 'monto_iva': Decimal('4.00')},
				{'alicuota': Decimal('16.00'), 'base_imponible': Decimal('180.00'), 'monto_iva': Decimal('28.80')},
			],
		)


class ProductTaxRateEnforcementTest(TestCase):
	def test_invoice_uses_product_tax_rate_and_recalculates_totals(self):
		import json
		from datetime import date
		from decimal import Decimal
		from django.contrib.auth import get_user_model
		from django.test import Client
		from django.urls import reverse
		from CxC.models import CuentaCobro
		from Inventario.models import Productos
		from Usuario.models import Clientes
		from .models import DetalleFactura, Factura

		user = get_user_model().objects.create_superuser(
			username='tax-admin', email='tax-admin@example.com', password='Test12345!'
		)
		cliente = Clientes.objects.create(
			nombre='Cliente', apellido='Prueba', telefono='04140000000',
			cedula='V12345678', direccion='Dirección de prueba',
			email='tax-customer@example.com', fecha_nacimiento=date(1990, 1, 1),
		)
		gravado = Productos.objects.create(
			Descripcion='Producto gravado', Precio=100, Costo=65,
			Cantidad=3, promocion=True,
		)
		exento = Productos.objects.create(Descripcion='Producto exento', Precio=50, Cantidad=3, iva=Decimal('0.00'))
		client = Client()
		client.force_login(user)
		catalog = client.get(reverse('api_productos')).json()
		customers = client.get(reverse('api_clientes')).json()
		self.assertEqual(customers[0]['cedula'], cliente.cedula)
		self.assertEqual(customers[0]['telefono'], cliente.telefono)
		self.assertEqual(customers[0]['direccion'], cliente.direccion)
		producto_catalogo = next(item for item in catalog if item['Codigo'] == gravado.Codigo)
		self.assertEqual(
			producto_catalogo['iva'],
			16.0,
		)
		self.assertEqual(producto_catalogo['costo'], 65.0)
		self.assertEqual(producto_catalogo['stock'], 3)
		self.assertTrue(producto_catalogo['promocion'])

		response = client.post(
			reverse('guardar_factura'),
			data=json.dumps({
				'cliente': {'cedula': cliente.cedula},
				'total': '999.00',
				'productos': [
					{'codigo': gravado.Codigo, 'cantidad': 1, 'precio': 100, 'iva': 0},
					{'codigo': exento.Codigo, 'cantidad': 1, 'precio': 50, 'iva': 16},
				],
			}),
			content_type='application/json',
		)

		self.assertEqual(response.status_code, 200)
		self.assertTrue(response.json()['success'])
		factura = Factura.objects.get()
		self.assertEqual(factura.subtotal, Decimal('150.00'))
		self.assertEqual(factura.iva, Decimal('16.00'))
		self.assertEqual(factura.total, Decimal('166.00'))
		self.assertEqual(
			set(DetalleFactura.objects.values_list('iva', flat=True)),
			{Decimal('0.00'), Decimal('16.00')},
		)
		cuenta = CuentaCobro.objects.get(factura=factura)
		self.assertEqual(cuenta.cliente, cliente)
		cxc_response = client.get(reverse('listar_cxc'))
		self.assertContains(cxc_response, f'#{factura.numero}')
		self.assertEqual(cxc_response.context['total_cxc_accounts'], 1)
		nota_entrega = client.get(reverse('ver_factura', args=[factura.numero]), {'tipo_documento': 'nota_entrega'})
		self.assertContains(nota_entrega, 'Nota de entrega')
		self.assertContains(nota_entrega, 'no fiscal')
		self.assertContains(nota_entrega, '@page { size:A4 landscape; margin:10mm; }')
		self.assertContains(nota_entrega, 'onclick="imprimirFactura()"')
		self.assertContains(nota_entrega, 'prepararFichaImpresion()')
