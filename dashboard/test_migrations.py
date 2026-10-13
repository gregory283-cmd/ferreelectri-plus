from decimal import Decimal

from django.conf import settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


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