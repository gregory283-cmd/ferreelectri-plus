from decimal import Decimal
from datetime import timedelta

from django.conf import settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class CommercialFlowMigrationTests(TransactionTestCase):
	migrate_from = ('dashboard', '0026_admindashboardconfig')
	migrate_to = ('dashboard', '0028_alter_envio_options_alter_pago_options_and_more')
	reset_sequences = True

	def setUp(self):
		executor = MigrationExecutor(connection)
		executor.migrate([self.migrate_from])
		old_apps = executor.loader.project_state([self.migrate_from]).apps

		user_app, user_model_name = settings.AUTH_USER_MODEL.split('.')
		User = old_apps.get_model(user_app, user_model_name)
		Pedido = old_apps.get_model('dashboard', 'Pedido')
		Pago = old_apps.get_model('dashboard', 'Pago')
		self.user = User.objects.create(username='commercial-migration-test')

		self.confirmed_order = Pedido.objects.create(
			cliente_id=self.user.pk,
			total=Decimal('100.00'),
			estado='pagado',
		)
		Pago.objects.create(
			pedido_id=self.confirmed_order.pk,
			metodo='PAGO_MOVIL',
			monto=Decimal('100.00'),
			estado='confirmado',
			verificado=True,
		)

		self.ambiguous_order = Pedido.objects.create(
			cliente_id=self.user.pk,
			total=Decimal('50.00'),
			estado='pagado',
		)
		self.shipped_order = Pedido.objects.create(
			cliente_id=self.user.pk,
			total=Decimal('75.00'),
			estado='enviado',
		)
		self.pending_order = Pedido.objects.create(
			cliente_id=self.user.pk,
			total=Decimal('25.00'),
			estado='pendiente',
		)
		Pago.objects.create(
			pedido_id=self.pending_order.pk,
			metodo='PAGO_MOVIL',
			monto=Decimal('25.00'),
			estado='pendiente',
			verificado=False,
			referencia='LEGACY-REF-25',
			comprobante='comprobantes/legacy.png',
		)

		executor = MigrationExecutor(connection)
		executor.migrate([self.migrate_to])
		self.apps = executor.loader.project_state([self.migrate_to]).apps

	def tearDown(self):
		executor = MigrationExecutor(connection)
		executor.migrate(executor.loader.graph.leaf_nodes())
		super().tearDown()

	def test_backfill_preserves_legacy_states_and_flags_uncertain_records(self):
		Pedido = self.apps.get_model('dashboard', 'Pedido')
		Pago = self.apps.get_model('dashboard', 'Pago')
		Envio = self.apps.get_model('dashboard', 'Envio')
		EnvioEvento = self.apps.get_model('dashboard', 'EnvioEvento')

		confirmed = Pedido.objects.get(pk=self.confirmed_order.pk)
		self.assertEqual(confirmed.estado, 'pagado')
		self.assertEqual(confirmed.estado_operativo, 'confirmado')
		self.assertFalse(confirmed.requiere_revision_operativa)

		ambiguous = Pedido.objects.get(pk=self.ambiguous_order.pk)
		self.assertEqual(ambiguous.estado, 'pagado')
		self.assertEqual(ambiguous.estado_operativo, 'pendiente_pago')
		self.assertTrue(ambiguous.requiere_revision_operativa)

		shipped = Pedido.objects.get(pk=self.shipped_order.pk)
		self.assertEqual(shipped.estado, 'enviado')
		self.assertEqual(shipped.estado_operativo, 'pendiente_pago')
		self.assertTrue(shipped.requiere_revision_operativa)
		shipment = Envio.objects.get(pedido_id=shipped.pk)
		self.assertEqual(shipment.estado, 'despachado')
		self.assertTrue(shipment.requiere_revision)
		self.assertEqual(shipment.direccion, '')
		initial_event = EnvioEvento.objects.get(envio_id=shipment.pk)
		self.assertEqual(initial_event.estado_nuevo, 'despachado')

		pending_payment = Pago.objects.get(pedido_id=self.pending_order.pk)
		self.assertEqual(pending_payment.estado, 'en_revision')
		self.assertEqual(pending_payment.comprobante, 'comprobantes/legacy.png')


class AdminDeviceRegistryMigrationTests(TransactionTestCase):
	migrate_from = ('dashboard', '0037_developmentrequest')
	migrate_to = ('dashboard', '0040_admindevice_uuid_per_user')
	reset_sequences = True

	def setUp(self):
		executor = MigrationExecutor(connection)
		executor.migrate([self.migrate_from])
		old_apps = executor.loader.project_state([self.migrate_from]).apps
		User = old_apps.get_model(*settings.AUTH_USER_MODEL.split('.'))
		AdminPasskey = old_apps.get_model('dashboard', 'AdminPasskey')
		AdminSecurityConfig = old_apps.get_model('dashboard', 'AdminSecurityConfig')
		AdminDeviceSession = old_apps.get_model('dashboard', 'AdminDeviceSession')
		self.user = User.objects.create(username='device-migration-owner', is_staff=True)
		passkey = AdminPasskey.objects.create(
			user_id=self.user.pk,
			credential_id='ZGV2aWNlLW1pZ3JhdGlvbg',
			public_key=b'migration-key',
			name='Passkey principal',
		)
		AdminSecurityConfig.objects.filter(pk=1).update(
			owner_user_id=self.user.pk,
			primary_passkey_id=passkey.pk,
		)
		self.assertTrue(AdminSecurityConfig.objects.filter(pk=1).exists())
		self.first_seen = timezone.now() - timedelta(days=8)
		self.last_seen = timezone.now() - timedelta(hours=2)
		for session_key, last_seen, ip_address in (
			('legacy-device-session-0000001', self.first_seen, '203.0.113.11'),
			('legacy-device-session-0000002', self.last_seen, '203.0.113.22'),
		):
			AdminDeviceSession.objects.create(
				user_id=self.user.pk,
				passkey_id=passkey.pk,
				session_key=session_key,
				name='Yulimar móvil',
				ip_address=ip_address,
				user_agent='Chrome Android',
				last_seen_at=last_seen,
				is_active=session_key.endswith('2'),
			)
		for session_key, last_seen in (
			('legacy-unknown-device-000001', timezone.now() - timedelta(minutes=35)),
			('legacy-unknown-device-000002', timezone.now() - timedelta(minutes=20)),
		):
			AdminDeviceSession.objects.create(
				user_id=self.user.pk,
				session_key=session_key,
				user_agent='Chrome Android',
				last_seen_at=last_seen,
				is_active=True,
			)

		executor = MigrationExecutor(connection)
		executor.migrate([self.migrate_to])
		self.apps = executor.loader.project_state([self.migrate_to]).apps

	def tearDown(self):
		executor = MigrationExecutor(connection)
		executor.migrate(executor.loader.graph.leaf_nodes())
		super().tearDown()

	def test_sessions_for_the_same_named_device_are_consolidated(self):
		AdminDevice = self.apps.get_model('dashboard', 'AdminDevice')
		AdminDeviceSession = self.apps.get_model('dashboard', 'AdminDeviceSession')
		devices = AdminDevice.objects.filter(user_id=self.user.pk)

		self.assertEqual(devices.count(), 3)
		device = devices.get(name='Yulimar móvil')
		self.assertEqual(device.name, 'Yulimar móvil')
		self.assertEqual(device.first_seen_at, self.first_seen)
		self.assertEqual(device.last_seen_at, self.last_seen)
		self.assertEqual(device.ip_address, '203.0.113.22')
		self.assertTrue(device.is_primary)
		self.assertEqual(AdminDeviceSession.objects.filter(device_id=device.pk).count(), 2)
		self.assertEqual(devices.filter(name='').count(), 2)

		User = self.apps.get_model(*settings.AUTH_USER_MODEL.split('.'))
		other_user = User.objects.create(username='second-device-migration-owner', is_staff=True)
		second_account_device = AdminDevice.objects.create(
			user_id=other_user.pk,
			device_id=device.device_id,
			name='Mismo navegador, otra cuenta',
		)
		self.assertEqual(second_account_device.device_id, device.device_id)
		self.assertEqual(devices.filter(name='').count(), 2)