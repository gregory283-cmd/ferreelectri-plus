from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Proveedores


class ProveedoresDirectoryTests(TestCase):
	def setUp(self):
		user_model = get_user_model()
		self.user = user_model.objects.create_superuser(
			username='proveedores-directory-admin',
			email='proveedores-directory@example.com',
			password='ProveedorTest123!',
		)
		self.client.force_login(self.user)
		self.proveedor = Proveedores.objects.create(
			cedula='J12345678', nombre='Suministros Delta',
			telefono='04121234567', email='delta@example.com', direccion='Caracas',
		)

	def test_busqueda_filtra_por_rif_y_preserva_el_conteo(self):
		Proveedores.objects.create(
			cedula='V12345678', nombre='Ferretería Central',
			telefono='04121234568', email='central@example.com', direccion='Maracay',
		)

		response = self.client.get(reverse('Proveedor'), {'q': 'delta@example.com'})

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Suministros Delta')
		self.assertNotContains(response, 'Ferretería Central')
		self.assertEqual(response.context['proveedores'].paginator.count, 1)

	def test_eliminar_proveedor_solo_acepta_post(self):
		url = reverse('dltProveedor', args=[self.proveedor.pk])

		self.assertEqual(self.client.get(url).status_code, 405)
		self.assertTrue(Proveedores.objects.filter(pk=self.proveedor.pk).exists())
		self.assertEqual(self.client.post(url).status_code, 302)
		self.assertFalse(Proveedores.objects.filter(pk=self.proveedor.pk).exists())

	def test_datos_invalidos_al_crear_proveedor_no_producen_error_500(self):
		response = self.client.post(reverse('addProveedor'), {
			'nombre': 'Proveedor nuevo',
			'prefijo_cedula': 'J',
			'cedula': '12',
			'telefono': '123',
			'correo': 'correo-invalido',
			'direccion': 'Caracas',
		})

		self.assertEqual(response.status_code, 302)
		self.assertEqual(Proveedores.objects.count(), 1)
