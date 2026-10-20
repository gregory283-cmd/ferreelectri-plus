from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse
from datetime import date
import json
from html.parser import HTMLParser

from Inventario.models import Productos, CostoCambio
from Proveedores.models import Proveedores
from .models import Compra, DetalleCompra

User = get_user_model()


class ComprasCostIntegrationTests(TestCase):
	def setUp(self):
		self.client = Client()
		self.user = User.objects.create_superuser(
			username='compras-test-admin',
			email='compras-test-admin@example.com',
			password='CompraTest123!',
		)
		self.client.force_login(self.user)

	def test_listar_compras_renderiza_busqueda_y_acciones(self):
		response = self.client.get(reverse('listar_compras'), {'q': 'CF'})

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'name="q"')
		self.assertContains(response, 'compras-search-submit')
		self.assertContains(response, 'compras-search-clear')
		self.assertContains(response, 'Compras a proveedores')
		class VisibleTextParser(HTMLParser):
			def __init__(self):
				super().__init__()
				self.hidden = 0
				self.visible_text = []

			def handle_starttag(self, tag, attrs):
				if tag in {'style', 'script'}:
					self.hidden += 1

			def handle_endtag(self, tag):
				if tag in {'style', 'script'} and self.hidden:
					self.hidden -= 1

			def handle_data(self, data):
				if not self.hidden:
					self.visible_text.append(data)

		parser = VisibleTextParser()
		parser.feed(response.content.decode())
		self.assertNotIn('.btn-accion {', ''.join(parser.visible_text))

	def test_guardar_compra_requiere_permiso_de_compra(self):
		user = User.objects.create_user(username='staff-sin-compras', is_staff=True)
		client = Client()
		client.force_login(user)

		response = client.post(
			reverse('guardar_compra'),
			data='{}',
			content_type='application/json',
		)

		self.assertEqual(response.status_code, 403)

	def test_guardar_compra_requiere_csrf_y_pantalla_expone_token(self):
		csrf_client = Client(enforce_csrf_checks=True)
		csrf_client.force_login(self.user)
		page = csrf_client.get(reverse('formato_compras'))
		self.assertEqual(page.status_code, 200)
		self.assertContains(page, 'X-CSRFToken')
		self.assertContains(page, 'name="csrfmiddlewaretoken"')
		self.assertContains(page, 'btn-buscar-proveedor')
		self.assertContains(page, 'btn-buscar-articulo')
		self.assertContains(page, 'cell.dataset.label = col.label')
		self.assertContains(page, '#modal-busqueda-tabla tbody td::before')
		self.assertContains(page, 'grid-template-columns:repeat(2,minmax(0,1fr))')
		self.assertContains(page, '.purchase-table-wrap { overflow:visible; }')
		self.assertContains(page, '.modal-busqueda-contenido { width:calc(100vw - 20px); min-width:0;')
		self.assertContains(page, 'No hay registros disponibles.')

		response = csrf_client.post(
			reverse('guardar_compra'),
			data='{}',
			content_type='application/json',
		)

		self.assertEqual(response.status_code, 403)

	def test_apis_de_busqueda_exponen_datos_de_proveedor_y_producto(self):
		proveedor = Proveedores.objects.create(
			cedula='J123456789',
			nombre='Proveedor de prueba',
			email='proveedor-modal@example.com',
			telefono='04121234567',
			direccion='Av. Principal',
		)
		producto = Productos.objects.create(
			Descripcion='Artículo de prueba', Precio=12.50, Costo=8.25,
			Cantidad=7, promocion=True,
		)

		proveedores = self.client.get(reverse('api_proveedores')).json()
		articulos = self.client.get(reverse('api_articulos')).json()
		proveedor_data = next(item for item in proveedores if item['ruc_nit'] == proveedor.cedula)
		producto_data = next(item for item in articulos if item['codigo'] == producto.Codigo)

		self.assertEqual(proveedor_data['telefono'], proveedor.telefono)
		self.assertEqual(proveedor_data['email'], proveedor.email)
		self.assertEqual(proveedor_data['direccion'], proveedor.direccion)
		self.assertEqual(producto_data['costo'], '8.25')
		self.assertEqual(producto_data['precio'], '12.50')
		self.assertEqual(producto_data['stock'], 7)
		self.assertEqual(producto_data['iva'], '16.00')
		self.assertTrue(producto_data['promocion'])

	def test_modificar_compra_requiere_permiso_de_cambio(self):
		user = User.objects.create_user(username='staff-sin-edicion-compra', is_staff=True)
		client = Client()
		client.force_login(user)
		proveedor = Proveedores.objects.create(
			cedula='V12345679',
			nombre='Proveedor permiso',
			email='proveedor-permiso@example.com',
			telefono='04121234568',
			direccion='Direccion de prueba',
		)
		compra = Compra.objects.create(proveedor=proveedor, fecha_emision=date.today())

		response = client.post(
			reverse('modificar_compra', kwargs={'compra_id': compra.id}),
			{'precio_0': '7.00', 'cantidad_0': '1'},
		)

		self.assertEqual(response.status_code, 403)

	def test_guardar_compra_updates_cost_and_logs(self):
		# crear producto
		p = Productos.objects.create(Codigo='T100', Descripcion='Producto Test', Precio=10.00, Costo=3.00, Cantidad=5)
		payload = {
			'proveedor': 'Proveedor X',
			'ruc_nit': 'V-00000000',
			'control_fiscal': 'CF-TEST-001',
			'politica_costo': 'vigente',
			'articulos': [
				{'codigo': p.Codigo, 'descripcion': p.Descripcion, 'precio': 5.00, 'cantidad': 2, 'subtotal': 10.00}
			]
		}
		resp = self.client.post(reverse('guardar_compra'), data=json.dumps(payload), content_type='application/json')
		self.assertEqual(resp.status_code, 200, resp.content.decode())
		data = resp.json()
		self.assertTrue(data.get('ok'))
		# reload product
		p.refresh_from_db()
		self.assertAlmostEqual(float(p.Costo), 5.00)
		# check CostoCambio log
		cambios = CostoCambio.objects.filter(producto=p)
		self.assertTrue(cambios.exists())

	def test_modificar_compra_updates_cost_and_logs(self):
		# crear producto y compra con detalle
		p = Productos.objects.create(Codigo='T200', Descripcion='Producto Mod', Precio=20.00, Costo=4.00, Cantidad=10)
		proveedor = Proveedores.objects.create(
			cedula='V12345678',
			nombre='Proveedor Test',
			email='proveedor-test@example.com',
			telefono='04121234567',
			direccion='Direccion de prueba',
		)
		compra = Compra.objects.create(proveedor=proveedor, fecha_emision=date.today())
		detalle = DetalleCompra.objects.create(compra=compra, producto=p, precio=4.00, cantidad=1, subtotal=4.00)
		page = self.client.get(reverse('modificar_compra', kwargs={'compra_id': compra.id}))
		self.assertEqual(page.status_code, 200)
		self.assertContains(page, 'btn-buscar-articulo')
		self.assertContains(page, 'buscar-producto-compra')
		# post modificación cambiando el precio (costo)
		post_data = {
			'precio_0': '7.00',
			'cantidad_0': '1'
		}
		resp = self.client.post(reverse('modificar_compra', kwargs={'compra_id': compra.id}), data=post_data)
		# should redirect
		self.assertIn(resp.status_code, (302, 301))
		p.refresh_from_db()
		self.assertAlmostEqual(float(p.Costo), 7.00)
		cambios = CostoCambio.objects.filter(producto=p)
		self.assertTrue(cambios.exists())

	def test_compra_mas_barata_espera_agotamiento_y_aprobacion_para_bajar_precio(self):
		from decimal import Decimal
		from Inventario.models import CostoPendiente
		from Inventario.utils import registrar_movimiento

		producto = Productos.objects.create(
			Codigo='T300', Descripcion='Tornillos FIFO', Precio=Decimal('22.00'),
			Costo=Decimal('11.00'), Cantidad=10,
		)
		payload = {
			'proveedor': 'Proveedor FIFO',
			'ruc_nit': 'J-123456789',
			'control_fiscal': 'CF-FIFO-001',
			'articulos': [{'codigo': producto.Codigo, 'precio': '9.00', 'cantidad': 12}],
		}
		response = self.client.post(
			reverse('guardar_compra'),
			data=json.dumps(payload),
			content_type='application/json',
		)
		self.assertEqual(response.status_code, 200, response.content.decode())
		compra_id = response.json()['compra_id']
		propuesta = CostoPendiente.objects.get(lote__compra_id=compra_id)
		self.assertEqual(propuesta.estado, 'espera_stock')
		panel_costos = self.client.get(reverse('gestionar_precios'))
		self.assertContains(panel_costos, 'Esperando agotar lote caro')
		self.assertContains(panel_costos, 'Stock caro restante')
		self.assertContains(panel_costos, '<strong>10</strong>')
		producto.refresh_from_db()
		self.assertEqual(producto.Costo, Decimal('11.00'))
		self.assertEqual(producto.Precio, Decimal('22.00'))

		registrar_movimiento(producto, 'salida', 10, 'Venta de inventario al costo anterior')
		propuesta.refresh_from_db()
		producto.refresh_from_db()
		self.assertEqual(propuesta.estado, 'pendiente')
		self.assertEqual(producto.Costo, Decimal('11.00'))
		self.assertEqual(producto.Precio, Decimal('22.00'))

		approved = self.client.post(
			reverse('gestionar_costo_pendiente'),
			data=json.dumps({'accion': 'aprobar', 'id': propuesta.pk}),
			content_type='application/json',
		)
		self.assertTrue(approved.json()['success'])
		producto.refresh_from_db()
		propuesta.refresh_from_db()
		self.assertEqual(producto.Costo, Decimal('9.00'))
		self.assertEqual(producto.Precio, Decimal('18.00'))
		self.assertEqual(propuesta.precio_anterior, Decimal('22.00'))
		self.assertEqual(propuesta.precio_aprobado, Decimal('18.00'))

	def test_anular_y_reactivar_compra_conserva_saldo_real_del_lote(self):
		from decimal import Decimal
		from Inventario.models import CostoLote, CostoPendiente
		from Inventario.utils import registrar_movimiento

		producto = Productos.objects.create(
			Codigo='T301', Descripcion='Tornillos lote anulable', Precio=22,
			Costo=11, Cantidad=10,
		)
		response = self.client.post(
			reverse('guardar_compra'),
			data=json.dumps({
				'proveedor': 'Proveedor lote', 'ruc_nit': 'J-223456789',
				'control_fiscal': 'CF-FIFO-002',
				'articulos': [{'codigo': producto.Codigo, 'precio': '9.00', 'cantidad': 12}],
			}),
			content_type='application/json',
		)
		compra_id = response.json()['compra_id']
		registrar_movimiento(producto, 'salida', 10, 'Consumo lote caro')
		producto.refresh_from_db()
		self.assertEqual(producto.Cantidad, 12)

		self.client.post(reverse('anular_compra', args=[compra_id]))
		producto.refresh_from_db()
		self.assertEqual(producto.Cantidad, 0)
		lote = CostoLote.objects.filter(compra_id=compra_id).order_by('-pk').first()
		self.assertEqual(lote.cantidad_anulada, 12)
		self.assertEqual(CostoPendiente.objects.filter(lote=lote, estado='rechazado').count(), 1)

		self.client.post(reverse('reactivar_compra', args=[compra_id]))
		producto.refresh_from_db()
		self.assertEqual(producto.Cantidad, 12)
		self.assertEqual(producto.Costo, Decimal('11.00'))
		self.assertEqual(producto.Precio, Decimal('22.00'))

	def test_politica_vigente_reemplaza_capas_y_recalcula_precio(self):
		from decimal import Decimal
		from Inventario.models import CostoLote, CostoPendiente

		producto = Productos.objects.create(
			Codigo='T302', Descripcion='Producto reemplazo de costo',
			Precio=Decimal('20.00'), Costo=Decimal('5.00'), Cantidad=3,
		)
		response = self.client.post(
			reverse('guardar_compra'),
			data=json.dumps({
				'proveedor': 'Proveedor reemplazo', 'ruc_nit': 'J-323456789',
				'control_fiscal': 'CF-COST-REPLACE', 'politica_costo': 'vigente',
				'articulos': [{'codigo': producto.Codigo, 'precio': '8.00', 'cantidad': 2}],
			}),
			content_type='application/json',
		)
		self.assertTrue(response.json()['ok'])
		producto.refresh_from_db()
		self.assertEqual(producto.Cantidad, 5)
		self.assertEqual(producto.Costo, Decimal('8.00'))
		self.assertEqual(producto.Precio, Decimal('32.00'))
		self.assertFalse(CostoPendiente.objects.filter(producto=producto, estado__in=['pendiente', 'espera_stock']).exists())
		self.assertFalse(CostoLote.objects.filter(producto=producto, cantidad_disponible__gt=0).exclude(costo_unitario=Decimal('8.00')).exists())

