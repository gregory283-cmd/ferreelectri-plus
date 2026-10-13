from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from Inventario.models import Productos
from Proveedores.models import Proveedores
from Usuario.models import Clientes
from Ventas.models import DetalleFactura, Factura


class ReportesPdfPresentationTests(TestCase):
	def setUp(self):
		user_model = get_user_model()
		admin = user_model.objects.create_superuser(
			username='reportes-pdf-admin',
			email='reportes-pdf-admin@example.com',
			password='ReportesTest123!',
		)
		self.client.force_login(admin)
		self.cliente = Clientes.objects.create(
			nombre='Ada', apellido='Lovelace', telefono='04121234567',
			cedula='V12345678', direccion='Caracas', email='ada-pdf@example.com',
		)
		self.proveedor = Proveedores.objects.create(
			cedula='J12345678', nombre='Suministros PDF', telefono='04121234568',
			email='proveedor-pdf@example.com', direccion='San Cristobal',
		)

	def test_listados_pdf_incluyen_estilo_compartido_y_datos(self):
		with patch('Reportes.views.HTML') as pdf_engine:
			pdf_engine.return_value.write_pdf.return_value = b'%PDF-test'
			client_response = self.client.get(reverse('reporte_clientes_pdf'))
			client_html = pdf_engine.call_args.kwargs['string']
			provider_response = self.client.get(reverse('reporte_proveedores_pdf'))
			provider_html = pdf_engine.call_args.kwargs['string']

		self.assertEqual(client_response['Content-Type'], 'application/pdf')
		self.assertEqual(provider_response['Content-Type'], 'application/pdf')
		self.assertIn('.header-bar', client_html)
		self.assertIn('background-image: none !important', provider_html)
		self.assertIn(self.cliente.cedula, client_html)
		self.assertIn(self.proveedor.nombre, provider_html)

	def test_factura_pdf_renderiza_campos_y_totales_de_linea(self):
		producto = Productos.objects.create(
			Descripcion='Artículo factura PDF', Precio=Decimal('120.00'),
			Costo=Decimal('80.00'), Cantidad=5,
		)
		factura = Factura.objects.create(
			cliente=self.cliente, subtotal=Decimal('108.00'),
			iva=Decimal('17.28'), total=Decimal('125.28'),
		)
		DetalleFactura.objects.create(
			factura=factura, producto=producto, cantidad=1,
			precio=Decimal('120.00'), descuento=Decimal('10.00'),
			iva=Decimal('16.00'),
		)

		with patch('Reportes.views.HTML') as pdf_engine:
			pdf_engine.return_value.write_pdf.return_value = b'%PDF-test'
			response = self.client.get(reverse('reporte_factura_pdf', args=[factura.numero]))
			rendered_html = pdf_engine.call_args.kwargs['string']

		self.assertEqual(response['Content-Type'], 'application/pdf')
		self.assertIn('A0001', rendered_html)
		self.assertIn('Artículo factura PDF', rendered_html)
		self.assertIn('108,00', rendered_html)
		self.assertIn('17,28', rendered_html)
		self.assertIn('125,28', rendered_html)

	def test_fichas_individuales_renderizan_datos_y_estilos(self):
		with patch('Usuario.views.HTML') as client_pdf_engine:
			client_pdf_engine.return_value.write_pdf.return_value = b'%PDF-test'
			client_response = self.client.get(reverse('cliente_pdf', args=[self.cliente.pk]))
			client_html = client_pdf_engine.call_args.kwargs['string']

		with patch('Proveedores.views.HTML') as provider_pdf_engine:
			provider_pdf_engine.return_value.write_pdf.return_value = b'%PDF-test'
			provider_response = self.client.get(reverse('reporte_proveedor_pdf', args=[self.proveedor.pk]))
			provider_html = provider_pdf_engine.call_args.kwargs['string']

		self.assertEqual(client_response.status_code, 200)
		self.assertEqual(provider_response.status_code, 200)
		self.assertIn(self.cliente.nombre, client_html)
		self.assertIn(self.proveedor.nombre, provider_html)
		self.assertIn('background-image: none !important', provider_html)
