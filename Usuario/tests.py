from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import Client, TestCase
from django.urls import reverse
from unittest.mock import patch

from .models import Clientes


class ClientesDirectoryTests(TestCase):
	def setUp(self):
		user_model = get_user_model()
		self.user = user_model.objects.create_superuser(
			username='clientes-directory-admin',
			email='clientes-directory@example.com',
			password='ClienteTest123!',
		)
		self.client.force_login(self.user)
		self.cliente = Clientes.objects.create(
			nombre='Ada', apellido='Lovelace', telefono='04121234567',
			cedula='V12345678', direccion='Caracas', email='ada@example.com',
		)

	def test_busqueda_filtra_por_nombre_y_conserva_el_conteo(self):
		Clientes.objects.create(
			nombre='Grace', apellido='Hopper', telefono='04121234568',
			cedula='V12345679', direccion='Maracay', email='grace@example.com',
		)

		response = self.client.get(reverse('usuarios'), {'q': 'lovelace'})

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Ada Lovelace')
		self.assertNotContains(response, 'Grace Hopper')
		self.assertEqual(response.context['clientes'].paginator.count, 1)

	def test_eliminar_cliente_solo_acepta_post(self):
		url = reverse('dltUser', args=[self.cliente.pk])

		self.assertEqual(self.client.get(url).status_code, 405)
		self.assertTrue(Clientes.objects.filter(pk=self.cliente.pk).exists())
		self.assertEqual(self.client.post(url).status_code, 302)
		self.assertFalse(Clientes.objects.filter(pk=self.cliente.pk).exists())

	def test_ficha_cliente_requiere_autenticacion(self):
		response = Client().get(reverse('ver_cliente', args=[self.cliente.pk]))

		self.assertEqual(response.status_code, 302)

	def test_colision_al_guardar_cliente_no_produce_error_500(self):
		with patch('Usuario.views.ClienteForm.is_valid', return_value=True), patch(
			'Usuario.views.ClienteForm.save', side_effect=IntegrityError,
		):
			response = self.client.post(reverse('addUser'), {})

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Ya existe un cliente con esa cédula o correo.')
