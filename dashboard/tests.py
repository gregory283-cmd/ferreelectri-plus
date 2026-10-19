import base64
import json
import hashlib
import hmac
import tarfile
import time
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlparse
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from unittest.mock import patch
from decimal import Decimal
from PIL import Image
from django.conf import settings

from Inventario.models import Categoria, Productos, MovimientoInventario
from Usuario.models import Clientes as UsuarioClientes
from Ventas.models import DetalleFactura, Factura
from .ferrebot import _clean_assistant_reply, build_assistant_reply, search_catalog
from .models import AdminDashboardConfig, AdminDeviceSession, AdminLoginApproval, AdminPasskey, AdminSecurityConfig, AuditLog, Carrito, CarritoItem, Cliente, Customer, Pago, Pedido, PedidoItem, PerfilCliente


def make_test_payment_image():
    image_buffer = BytesIO()
    Image.new('RGB', (2, 2), color='white').save(image_buffer, format='PNG')
    image_buffer.seek(0)
    return SimpleUploadedFile('comprobante.png', image_buffer.getvalue(), content_type='image/png')


def confirm_customer_email(client, email):
    message = next(item for item in mail.outbox if email in item.to)
    verify_url = next(
        line for line in message.body.splitlines()
        if '/cliente/verificar-correo/' in line
    )
    return client.get(urlparse(verify_url).path, HTTP_HOST='localhost')


class AdminClientesDashboardPresentationTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='admin-clientes-presentation',
            email='admin-clientes-presentation@example.com',
            password='ClientesTest123!',
        )
        self.client.force_login(self.admin)

    def test_dashboard_clientes_renderiza_panel_y_acciones(self):
        response = self.client.get(reverse('clientes'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'customers-dashboard')
        self.assertContains(response, 'Cuentas registradas')
        self.assertContains(response, 'background:#176b78!important')

    def test_dashboard_proveedores_renderiza_metricas_reales_y_botones_solidos(self):
        response = self.client.get(reverse('proveedores'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'providers-dashboard')
        self.assertContains(response, 'Coincidencias')
        self.assertContains(response, 'background:#176b78!important')


class ExecutiveDashboardAnalyticsTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='executive-dashboard-admin',
            password='DashboardTest123!Safe',
            is_staff=True,
            is_superuser=True,
        )
        self.client.force_login(self.admin)
        self.customer = UsuarioClientes.objects.create(
            nombre='Cliente',
            apellido='Prueba',
            telefono='',
            direccion='',
            email='executive.dashboard.customer@example.com',
        )
        self.product = Productos.objects.create(
            Descripcion='Artículo con margen',
            Precio=Decimal('30.00'),
            Costo=Decimal('10.00'),
            Cantidad=20,
        )

    def test_dashboard_reports_period_comparison_margin_and_price_health(self):
        current_invoice = Factura.objects.create(
            cliente=self.customer,
            total=Decimal('60.00'),
            moneda='Bs.',
        )
        previous_invoice = Factura.objects.create(
            cliente=self.customer,
            total=Decimal('40.00'),
            moneda='Bs.',
        )
        Factura.objects.filter(pk=previous_invoice.pk).update(
            fecha=timezone.now() - timedelta(days=40),
        )
        DetalleFactura.objects.create(
            factura=current_invoice,
            producto=self.product,
            cantidad=2,
            precio=Decimal('30.00'),
            costo_unitario=Decimal('10.00'),
        )
        Productos.objects.create(
            Descripcion='Artículo a revisar',
            Precio=Decimal('5.00'),
            Costo=Decimal('10.00'),
            Cantidad=3,
        )
        AuditLog.objects.create(
            user=self.admin,
            action='CAMBIO',
            model_name='Productos',
            details='Actualización de precio',
        )

        response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['sales_30d'], Decimal('60.00'))
        self.assertEqual(response.context['sales_previous_30d'], Decimal('40.00'))
        self.assertEqual(response.context['sales_change_pct'], 50.0)
        self.assertEqual(response.context['units_sold_30d'], 2)
        self.assertEqual(response.context['gross_profit_30d'], Decimal('40.00'))
        self.assertEqual(response.context['products_below_cost'], 1)
        self.assertEqual(response.context['audit_total_7d'], 1)
        self.assertEqual(response.context['total_productos'], 2)
        self.assertEqual(response.context['inventory_units'], 21)
        self.assertEqual(response.context['top_products'][0]['producto__Descripcion'], 'Artículo con margen')
        self.assertContains(response, 'Resumen ejecutivo')
        self.assertContains(response, 'sales-trend-chart')

    def test_latest_backup_download_is_staff_only_and_attachment(self):
        with TemporaryDirectory() as backup_directory:
            archive_path = Path(backup_directory) / 'ferreelectri-backup-test.tar.gz'
            archive_path.write_bytes(b'test-backup-content')
            with override_settings(BACKUP_DIRECTORY=backup_directory):
                response = self.client.get(reverse('download_latest_backup'))
                self.assertEqual(response.status_code, 200)
                self.assertIn('attachment;', response['Content-Disposition'])
                self.assertEqual(b''.join(response.streaming_content), b'test-backup-content')

    def test_manual_backup_rejects_get_requests(self):
        response = self.client.get(reverse('manual_backup'))
        self.assertEqual(response.status_code, 405)


class DashboardCurrencySettingsTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='dashboard-currency-admin',
            email='dashboard-currency-admin@example.com',
            password='Currency123!Safe',
        )
        self.client.force_login(self.admin)
        self.customer = UsuarioClientes.objects.create(
            nombre='Cliente',
            apellido='Dólar',
            telefono='',
            direccion='',
            email='dashboard.currency.customer@example.com',
        )

    def test_rate_is_saved_and_dashboard_converts_display_amounts(self):
        Factura.objects.create(cliente=self.customer, total=Decimal('100.00'), moneda='VES')

        response = self.client.post(reverse('actualizar_tasa_bcv'), {
            'bcv_rate': '50.0000',
            'moneda': 'USD',
        })

        self.assertRedirects(response, f"{reverse('dashboard')}?moneda=USD")
        config = AdminDashboardConfig.objects.get(pk=1)
        self.assertEqual(config.bcv_rate, Decimal('50.0000'))
        self.assertEqual(config.updated_by, self.admin)

        response = self.client.get(reverse('dashboard'), {'moneda': 'USD'})
        self.assertEqual(response.context['currency'], 'USD')
        self.assertEqual(response.context['sales_30d'], Decimal('2.00'))
        self.assertEqual(response.context['sales_chart'][-1]['total'], 2.0)
        self.assertContains(response, 'Equivalencia referencial')

    def test_invalid_rate_is_not_persisted(self):
        response = self.client.post(reverse('actualizar_tasa_bcv'), {'bcv_rate': '-5'})

        self.assertRedirects(response, reverse('dashboard'))
        self.assertFalse(AdminDashboardConfig.objects.exists())

    def test_dashboard_converts_usd_invoices_to_bolivares(self):
        AdminDashboardConfig.objects.create(bcv_rate=Decimal('50.0000'))
        Factura.objects.create(cliente=self.customer, total=Decimal('3.00'), moneda='USD')

        response = self.client.get(reverse('dashboard'), {'moneda': 'Bs.'})

        self.assertEqual(response.context['currency'], 'Bs.')
        self.assertEqual(response.context['sales_30d'], Decimal('150.00'))

    def test_dashboard_treats_order_invoice_amount_as_usd_and_defaults_to_bolivares(self):
        AdminDashboardConfig.objects.create(bcv_rate=Decimal('50.0000'))
        order = Pedido.objects.create(
            cliente=self.admin,
            total=Decimal('100.00'),
            estado='pagado',
        )
        Factura.objects.create(
            pedido=order,
            cliente=self.customer,
            total=Decimal('100.00'),
            moneda='Bs.',
        )

        response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.context['currency'], 'Bs.')
        self.assertEqual(response.context['sales_30d'], Decimal('5000.00'))

    def test_manual_invoice_with_legacy_default_currency_is_converted_from_usd(self):
        AdminDashboardConfig.objects.create(bcv_rate=Decimal('50.0000'))
        Factura.objects.create(cliente=self.customer, total=Decimal('60.00'), moneda='Bs.')

        response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.context['currency'], 'Bs.')
        self.assertEqual(response.context['sales_30d'], Decimal('3000.00'))


class CashCloseChannelsTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            username='cash-close-admin',
            email='cash-close-admin@example.com',
            password='CashClose123!Safe',
        )
        self.client.force_login(self.user)
        self.customer = UsuarioClientes.objects.create(
            nombre='Cliente',
            apellido='Caja',
            telefono='',
            direccion='',
            email='cash.close.customer@example.com',
        )
        self.product = Productos.objects.create(
            Descripcion='Producto para cierre',
            Precio=Decimal('100.00'),
            Costo=Decimal('40.00'),
            Cantidad=10,
        )

    def test_close_reports_ecommerce_and_manual_gross_profit_separately(self):
        ecommerce_order = Pedido.objects.create(
            cliente=self.user,
            total=Decimal('116.00'),
            estado='pagado',
        )
        ecommerce_invoice = Factura.objects.create(
            pedido=ecommerce_order,
            cliente=self.customer,
            total=Decimal('116.00'),
            moneda='Bs.',
        )
        DetalleFactura.objects.create(
            factura=ecommerce_invoice,
            producto=self.product,
            cantidad=1,
            precio=Decimal('100.00'),
            costo_unitario=Decimal('40.00'),
            iva=Decimal('16.00'),
        )
        manual_invoice = Factura.objects.create(
            cliente=self.customer,
            total=Decimal('58.00'),
            moneda='Bs.',
        )
        DetalleFactura.objects.create(
            factura=manual_invoice,
            producto=self.product,
            cantidad=1,
            precio=Decimal('50.00'),
            costo_unitario=Decimal('20.00'),
            iva=Decimal('16.00'),
        )

        response = self.client.get(reverse('cierre_caja'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Abrir informe ejecutivo')
        self.assertNotContains(response, 'Reporte de ganancias')
        self.assertNotContains(response, 'Exportar reporte')
        today = response.context['cash_periods'][0]
        self.assertEqual(today['ecommerce']['invoice_count'], 1)
        self.assertEqual(today['manual']['invoice_count'], 1)
        self.assertEqual(today['ecommerce']['gross_profit']['USD'], Decimal('60.00'))
        self.assertEqual(today['manual']['gross_profit']['USD'], Decimal('30.00'))
        self.assertContains(response, 'E-commerce')
        self.assertContains(response, 'Facturación manual')

    def test_close_keeps_mixed_currencies_separate_without_bcv_rate(self):
        Factura.objects.create(cliente=self.customer, total=Decimal('100.00'), moneda='VES')
        Factura.objects.create(cliente=self.customer, total=Decimal('2.00'), moneda='USD')

        response = self.client.get(reverse('cierre_caja'))

        today = response.context['cash_periods'][0]
        self.assertFalse(response.context['cash_chart_available'])
        self.assertEqual(today['total_display'], 'Bs. 100,00 · USD 2,00')

    def test_close_converts_order_invoice_usd_to_bolivares(self):
        AdminDashboardConfig.objects.create(bcv_rate=Decimal('50.0000'))
        order = Pedido.objects.create(cliente=self.user, total=Decimal('100.00'), estado='pagado')
        Factura.objects.create(
            pedido=order,
            cliente=self.customer,
            total=Decimal('100.00'),
            moneda='Bs.',
        )

        response = self.client.get(reverse('cierre_caja'))

        self.assertEqual(response.context['cash_periods'][0]['ecommerce']['revenue_display'], 'Bs. 5.000,00')


class ExecutiveProfitReportTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='executive-report-admin',
            email='executive-report-admin@example.com',
            password='ExecutiveReport123!Safe',
        )
        self.client.force_login(self.admin)
        self.customer = UsuarioClientes.objects.create(
            nombre='Cliente',
            apellido='Reporte',
            telefono='',
            direccion='',
            email='executive.report.customer@example.com',
        )
        self.product = Productos.objects.create(
            Descripcion='Producto de reporte',
            Precio=Decimal('100.00'),
            Costo=Decimal('40.00'),
            Cantidad=10,
        )
        AdminDashboardConfig.objects.create(bcv_rate=Decimal('50.0000'))

    def _create_invoice(self, amount, unit_price, cost, order=None):
        invoice = Factura.objects.create(
            pedido=order,
            cliente=self.customer,
            total=amount,
            subtotal=Decimal(str(unit_price)),
            iva=amount - Decimal(str(unit_price)),
            moneda='Bs.',
        )
        DetalleFactura.objects.create(
            factura=invoice,
            producto=self.product,
            cantidad=1,
            precio=Decimal(str(unit_price)),
            costo_unitario=Decimal(str(cost)),
            iva=Decimal('16.00'),
        )
        return invoice

    def test_executive_report_reconciles_tax_margin_channels_and_pdf(self):
        order = Pedido.objects.create(
            cliente=self.admin,
            total=Decimal('116.00'),
            estado='pagado',
        )
        first_invoice = self._create_invoice(Decimal('116.00'), Decimal('100.00'), Decimal('40.00'), order)
        self._create_invoice(Decimal('58.00'), Decimal('50.00'), Decimal('20.00'))
        high_volume_product = Productos.objects.create(
            Descripcion='Producto de alto volumen',
            Precio=Decimal('0.00'),
            Costo=Decimal('0.00'),
            Cantidad=20,
        )
        DetalleFactura.objects.create(
            factura=first_invoice,
            producto=high_volume_product,
            cantidad=3,
            precio=Decimal('0.00'),
            costo_unitario=Decimal('0.00'),
            iva=Decimal('0.00'),
        )
        old_invoice = self._create_invoice(Decimal('232.00'), Decimal('200.00'), Decimal('80.00'))
        Factura.objects.filter(pk=old_invoice.pk).update(fecha=timezone.now() - timedelta(days=2))

        today = timezone.localdate()
        date_filter = {'inicio': today.isoformat(), 'fin': today.isoformat()}
        response = self.client.get(reverse('reporte_utilidad'), date_filter)

        self.assertEqual(response.status_code, 200)
        summary = response.context['resumen']
        self.assertEqual(response.context['moneda_reporte'], 'Bs.')
        self.assertEqual(summary['ventas_netas'], Decimal('7500.00'))
        self.assertEqual(summary['iva'], Decimal('1200.00'))
        self.assertEqual(summary['ventas'], Decimal('8700.00'))
        self.assertEqual(summary['costo_ventas'], Decimal('3000.00'))
        self.assertEqual(summary['utilidad'], Decimal('4500.00'))
        self.assertEqual(summary['margen_porcentaje'], Decimal('60.0'))
        self.assertEqual(response.context['canales']['ecommerce']['ventas_netas'], Decimal('5000.00'))
        self.assertEqual(response.context['canales']['manual']['ventas_netas'], Decimal('2500.00'))
        self.assertIn(
            Decimal('16.00'),
            [grupo['alicuota'] for grupo in response.context['iva_resumen']],
        )
        self.assertEqual(response.context['resumen']['transacciones'], 2)
        self.assertEqual(response.context['ventas_chart'][0]['total'], 8700.0)
        self.assertEqual(response.context['producto_mas_vendido']['nombre'], high_volume_product.Descripcion)
        self.assertEqual(response.context['producto_mas_vendido']['unidades'], 3)
        self.assertContains(response, 'Informe financiero')
        self.assertContains(response, 'Mayores ventas netas')
        self.assertContains(response, 'REPORTE EJECUTIVO')

        pdf_response = self.client.get(reverse('reporte_utilidad_pdf'), date_filter)
        self.assertEqual(pdf_response.status_code, 200)
        self.assertEqual(pdf_response['Content-Type'], 'application/pdf')
        self.assertIn('fe-rpt-', pdf_response['Content-Disposition'])

        legacy_response = self.client.get(reverse('reporte_caja_diario_pdf'))
        self.assertEqual(legacy_response.status_code, 200)
        self.assertEqual(legacy_response['Content-Type'], 'application/pdf')


class AdminOrderHistoryPresentationTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='order-history-admin',
            email='order-history-admin@example.com',
            password='OrderHistory123!Safe',
        )
        self.client.force_login(self.admin)
        self.customer = User.objects.create_user(
            username='order-history-customer',
            email='order-history-customer@example.com',
            first_name='Ana',
            last_name='Pérez',
            password='Customer123!Safe',
        )
        self.order = Pedido.objects.create(cliente=self.customer, total=Decimal('69.60'), estado='pendiente')

    def test_history_shows_global_metrics_and_theme_aware_layout(self):
        response = self.client.get(reverse('admin_historial_pedidos'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['orders_total'], 1)
        self.assertEqual(response.context['orders_pending'], 1)
        self.assertEqual(response.context['orders_customers'], 1)
        self.assertContains(response, 'admin-utility-dock')
        self.assertContains(response, 'admin-orders.css')
        self.assertContains(response, 'Aprobar')
        self.assertContains(response, 'Buscar pedidos')
        self.assertNotContains(response, 'orders-status-chart')

    def test_order_detail_loads_its_responsive_theme_styles(self):
        response = self.client.get(reverse('detalle_pedido_admin', args=[self.order.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'admin-order-detail.css')
        self.assertContains(response, 'Productos del pedido')
        self.assertContains(response, 'Rechazar pedido')

    def test_status_filter_keeps_global_counts_and_filters_rows(self):
        response = self.client.get(reverse('admin_historial_pedidos'), {'estado': 'aprobado'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['orders_total'], 1)
        self.assertEqual(response.context['pedidos'].paginator.count, 0)
        self.assertContains(response, 'No hay pedidos para mostrar')


class OperationalFulfillmentPermissionsTest(TestCase):
    def setUp(self):
        from django.contrib.auth.models import Permission
        from .models import Envio

        self.operator = User.objects.create_user(
            username='warehouse-operator',
            email='warehouse-operator@example.com',
            password='WarehouseTest123!',
            is_staff=True,
        )
        self.customer = User.objects.create_user(
            username='warehouse-customer',
            email='warehouse-customer@example.com',
            password='WarehouseCustomer123!',
        )
        self.order = Pedido.objects.create(
            cliente=self.customer,
            total=Decimal('80.00'),
            estado='pagado',
            estado_operativo='confirmado',
        )
        self.shipment = Envio.objects.create(
            pedido=self.order,
            nombre_destinatario='Ana Cliente',
            telefono='04121234567',
            direccion='Calle Central 123',
        )
        self.permissions = Permission.objects
        self.client.force_login(self.operator)

    def grant(self, *codenames):
        self.operator.user_permissions.add(*[
            self.permissions.get(
                content_type__app_label='dashboard',
                codename=codename,
            )
            for codename in codenames
        ])

    def shipment_post(self, estado, **overrides):
        self.shipment.refresh_from_db()
        data = {
            'estado': estado,
            'nombre_destinatario': self.shipment.nombre_destinatario,
            'telefono': self.shipment.telefono,
            'direccion': self.shipment.direccion,
            'transportista': self.shipment.transportista,
            'numero_guia': self.shipment.numero_guia,
            'url_seguimiento': self.shipment.url_seguimiento,
            'observaciones': self.shipment.observaciones,
        }
        data.update(overrides)
        return self.client.post(reverse('actualizar_envio_admin', args=[self.order.pk]), data)

    def test_staff_requires_specific_permission_to_view_orders(self):
        response = self.client.get(reverse('admin_historial_pedidos'))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.get(reverse('admin_envios')).status_code, 403)

        self.grant('view_operational_orders')
        response = self.client.get(reverse('admin_historial_pedidos'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get(reverse('admin_envios')).status_code, 200)

        dashboard = self.client.get(reverse('dashboard'))
        self.assertContains(dashboard, 'href="/admin-panel/envios/"')
        self.assertNotContains(dashboard, '<span class="label">Envíos</span>')
        self.assertNotContains(dashboard, '<span class="label">Pedidos</span>')

        detail = self.client.get(reverse('detalle_pedido_admin', args=[self.order.pk]))
        self.assertEqual(detail.status_code, 200)
        self.assertNotContains(detail, 'Guardar seguimiento')

        self.grant('manage_fulfillment')
        detail = self.client.get(reverse('detalle_pedido_admin', args=[self.order.pk]))
        self.assertContains(detail, 'Guardar seguimiento')

    def test_shipment_queue_filters_and_searches(self):
        self.grant('view_operational_orders')
        self.shipment.requiere_revision = True
        self.shipment.save(update_fields=['requiere_revision'])

        response = self.client.get(reverse('admin_envios'), {
            'estado': 'revision',
            'q': self.customer.email,
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['envios'].paginator.count, 1)
        self.assertEqual(response.context['stats']['revision'], 1)
        self.assertContains(response, 'Cola de envíos')
        self.assertContains(response, f'#{self.order.pk}')
        detail_url = reverse('detalle_pedido_admin', args=[self.order.pk])
        self.assertContains(response, f'href="{detail_url}"')
        self.assertNotContains(response, '{% url')

        empty_response = self.client.get(reverse('admin_envios'), {'q': 'no-existe'})
        self.assertEqual(empty_response.context['envios'].paginator.count, 0)

    def test_fulfillment_permission_updates_state_and_records_actor(self):
        self.grant('view_operational_orders', 'manage_fulfillment')
        response = self.shipment_post('preparando')

        self.assertEqual(response.status_code, 302)
        self.shipment.refresh_from_db()
        self.assertEqual(self.shipment.estado, 'preparando')
        event = self.shipment.eventos.get(estado_anterior='no_preparado')
        self.assertEqual(event.estado_nuevo, 'preparando')
        self.assertEqual(event.actor, self.operator)

        self.shipment_post('listo')
        self.shipment.refresh_from_db()
        self.assertEqual(self.shipment.estado, 'listo')

        self.shipment_post('despachado')
        self.shipment.refresh_from_db()
        self.assertEqual(self.shipment.estado, 'listo')

        self.shipment_post(
            'despachado',
            transportista='Transportes Demo',
            numero_guia='GUIA-100',
        )
        self.shipment_post('en_transito')
        self.shipment_post('entregado')
        self.shipment.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.shipment.estado, 'entregado')
        self.assertEqual(self.order.estado_operativo, 'completado')
        self.assertEqual(self.shipment.eventos.count(), 5)
        self.assertTrue(AuditLog.objects.filter(model_name='Envio', object_id=str(self.shipment.pk)).exists())

    def test_dispatch_cannot_skip_preparation_or_ignore_payment_review(self):
        self.grant('view_operational_orders', 'manage_fulfillment')
        response = self.shipment_post(
            'despachado',
            transportista='Transportes Demo',
            numero_guia='GUIA-100',
        )
        self.assertEqual(response.status_code, 302)
        self.shipment.refresh_from_db()
        self.assertEqual(self.shipment.estado, 'no_preparado')

        self.order.estado_operativo = 'pendiente_pago'
        self.order.requiere_revision_operativa = True
        self.order.save(update_fields=['estado_operativo', 'requiere_revision_operativa'])
        response = self.shipment_post('preparando')
        self.assertEqual(response.status_code, 302)
        self.shipment.refresh_from_db()
        self.assertEqual(self.shipment.estado, 'no_preparado')

    def test_payment_evidence_download_needs_its_own_permission(self):
        self.grant('view_operational_orders')
        payment = Pago.objects.create(
            pedido=self.order,
            metodo='PAGO_MOVIL',
            monto=Decimal('80.00'),
            comprobante='comprobantes/permission-check.png',
        )
        response = self.client.get(reverse('admin_comprobante_pago', args=[payment.pk]))
        self.assertEqual(response.status_code, 403)

    def test_payment_approval_needs_its_own_permission(self):
        self.grant('view_operational_orders', 'manage_fulfillment')
        response = self.client.post(reverse('aprobar_pedido', args=[self.order.pk]))
        self.assertEqual(response.status_code, 403)

    def test_shipping_post_requires_csrf(self):
        from django.test import Client

        self.grant('view_operational_orders', 'manage_fulfillment')
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.operator)
        response = csrf_client.post(
            reverse('actualizar_envio_admin', args=[self.order.pk]),
            {'estado': 'preparando'},
        )
        self.assertEqual(response.status_code, 403)


class BackupArchiveIntegrityTest(TestCase):
    def test_backup_verifier_rejects_changed_database_member(self):
        from FERREELECTRI_PLUS.backup_utils import BackupError, _verify_archive

        with TemporaryDirectory() as temporary_directory:
            archive_path = Path(temporary_directory) / 'tampered-backup.tar.gz'
            database_payload = b'not-the-database-hash-in-the-manifest'
            manifest = {
                'database_member': 'database.dump',
                'database_sha256': hashlib.sha256(b'expected-original-dump').hexdigest(),
            }
            members = {
                'database.dump': database_payload,
                'backup-manifest.json': json.dumps(manifest).encode('utf-8'),
                'RESTORE.txt': b'Restore the database to a new empty database.',
            }
            with tarfile.open(archive_path, 'w:gz') as archive:
                for name, payload in members.items():
                    member = tarfile.TarInfo(name)
                    member.size = len(payload)
                    archive.addfile(member, BytesIO(payload))

            with self.assertRaises(BackupError):
                _verify_archive(archive_path, 'database.dump')


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    DEFAULT_FROM_EMAIL='registro@example.test',
)
class ClienteRegistroPersistenceTest(TestCase):
    def test_pending_registration_can_resend_verification_without_duplicate_profile_data(self):
        registration = self.client.post(reverse('cliente_registro'), {
            'nombre': 'María Reenvío',
            'email': 'maria.reenvio@example.com',
            'cedula': 'V-12345679',
            'telefono': '+58 414 123 4567',
            'direccion': 'San Cristóbal, Centro',
            'password1': 'Quito!Fuerte-2026-123',
            'password2': 'Quito!Fuerte-2026-123',
        }, HTTP_HOST='localhost')
        self.assertEqual(registration.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)

        resend = self.client.post(reverse('cliente_registro'), {
            'email': 'maria.reenvio@example.com',
        }, HTTP_HOST='localhost')

        self.assertEqual(resend.status_code, 200)
        self.assertContains(resend, 'Revisa tu correo')
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(Customer.objects.filter(email='maria.reenvio@example.com').count(), 1)

    def test_registration_persists_identification_and_delivery_data(self):
        response = self.client.post(reverse('cliente_registro'), {
            'nombre': 'María Pérez',
            'email': 'maria.perez@example.com',
            'cedula': 'V-12345678',
            'telefono': '+58 414 123 4567',
            'direccion': 'San Cristóbal, Centro',
            'password1': 'Quito!Fuerte-2026-123',
            'password2': 'Quito!Fuerte-2026-123',
        }, HTTP_HOST='localhost')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Revisa tu correo')
        customer = Customer.objects.get(email='maria.perez@example.com')
        self.assertFalse(customer.email_verified)
        self.assertFalse(Cliente.objects.filter(email=customer.email).exists())
        self.client.post(reverse('cliente_login'), {
            'username': customer.email,
            'password': 'Quito!Fuerte-2026-123',
        })
        self.assertNotIn('customer_id', self.client.session)

        verification = confirm_customer_email(self.client, customer.email)
        self.assertEqual(verification.status_code, 200)
        self.assertContains(verification, 'Correo confirmado')
        customer.refresh_from_db()
        self.assertTrue(customer.email_verified)
        cliente = Cliente.objects.get(email='maria.perez@example.com')
        self.assertEqual(customer.cedula, 'V-12345678')
        self.assertEqual(customer.telefono, '+584141234567')
        self.assertEqual(customer.direccion, 'San Cristóbal, Centro')
        self.assertEqual(cliente.cedula, customer.cedula)
        self.assertEqual(cliente.telefono, customer.telefono)
        self.assertEqual(cliente.direccion, customer.direccion)
        admin_cliente = UsuarioClientes.objects.get(email='maria.perez@example.com')
        self.assertEqual(admin_cliente.cedula, 'V-12345678')
        self.assertEqual(admin_cliente.telefono, '+584141234567')
        self.assertEqual(admin_cliente.direccion, 'San Cristóbal, Centro')

    def test_google_profile_appears_in_admin_without_invented_data(self):
        from .services import sync_admin_cliente_record

        cliente = Cliente.objects.create(
            nombre='Google Cliente',
            email='google.cliente@example.com',
        )
        sync_admin_cliente_record(cliente)
        admin = User.objects.create_superuser(
            username='admin-google-profile',
            email='admin-google-profile@example.com',
            password='QATest123!',
        )
        self.client.force_login(admin)

        response = self.client.get(reverse('clientes'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'google.cliente@example.com')
        record = UsuarioClientes.objects.get(email='google.cliente@example.com')
        self.assertIsNone(record.cedula)
        self.assertIsNone(record.fecha_nacimiento)

    def test_admin_distinguishes_registered_account_from_confirmed_buyer(self):
        registered = UsuarioClientes.objects.create(
            nombre='Cuenta', apellido='Registrada', telefono='04140000000',
            email='registered.only@example.com', direccion='Dirección QA',
        )
        buyer = UsuarioClientes.objects.create(
            nombre='Cliente', apellido='Comprador', telefono='04140000001',
            email='confirmed.buyer@example.com', direccion='Dirección QA',
        )
        buyer_user = User.objects.create_user(
            username='confirmed-buyer', email=buyer.email, password='QATest123!',
        )
        Pedido.objects.create(cliente=buyer_user, total=Decimal('50.00'), estado='pagado')
        admin = User.objects.create_superuser(
            username='admin-customer-state',
            email='admin-customer-state@example.com',
            password='QATest123!',
        )
        self.client.force_login(admin)

        response = self.client.get(reverse('clientes'))

        self.assertEqual(response.status_code, 200)
        records = {record.email: record for record in response.context['clientes'].object_list}
        self.assertFalse(records[registered.email].es_comprador)
        self.assertTrue(records[buyer.email].es_comprador)
        self.assertEqual(response.context['compradores_confirmados'], 1)
        self.assertContains(response, 'Cuentas registradas')
        self.assertContains(response, 'Compradores confirmados')


class ClientePerfilSeguridadTest(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(
            nombre='Elena Seguridad',
            email='elena.security@example.com',
            is_guest=False,
        )
        self.customer.set_password('OldCustomerPassword123!')
        self.customer.save(update_fields=['password'])
        self.login_response = self.client.post(reverse('cliente_login'), {
            'username': self.customer.email,
            'password': 'OldCustomerPassword123!',
        })

    def test_profile_password_change_checks_and_syncs_customer_credentials(self):
        self.assertEqual(self.login_response.status_code, 302)
        profile_data = {
            'nombre': 'Elena',
            'apellido': 'Seguridad',
            'cedula_rif': 'V-76543213',
            'telefono': '04140000000',
            'direccion': 'Dirección de seguridad',
            'email': self.customer.email,
            'password_current': 'WrongPassword123!',
            'password_new': 'NewCustomerPassword123!Safe',
            'password_new_confirm': 'NewCustomerPassword123!Safe',
        }

        rejected = self.client.post(reverse('perfil_cliente'), profile_data)
        self.assertRedirects(rejected, reverse('perfil_cliente'))
        self.customer.refresh_from_db()
        self.assertTrue(self.customer.check_password('OldCustomerPassword123!'))

        profile_data['password_current'] = 'OldCustomerPassword123!'
        updated = self.client.post(reverse('perfil_cliente'), profile_data)
        self.assertRedirects(updated, reverse('perfil_cliente'))
        self.customer.refresh_from_db()
        django_user = User.objects.get(email=self.customer.email)
        self.assertTrue(self.customer.check_password('NewCustomerPassword123!Safe'))
        self.assertTrue(django_user.check_password('NewCustomerPassword123!Safe'))


class ClientePanelDashboardDataTest(TestCase):
    def test_new_customer_gets_useful_empty_states(self):
        user = User.objects.create_user(
            username='cliente-vacio-dashboard',
            email='cliente.vacio.dashboard@example.com',
            password='ClienteDashboard123!',
            first_name='Lucía',
            last_name='Nueva',
        )
        Cliente.objects.create(user=user, nombre='Lucía Nueva', email=user.email)
        self.client.force_login(user)

        response = self.client.get(reverse('cliente_panel'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Aún no hay compras confirmadas')
        self.assertContains(response, 'Aún no tienes pedidos')
        self.assertContains(response, 'No hay facturas emitidas')
        self.assertContains(response, 'Sin movimientos de pago')
        self.assertEqual(response.context['total_orders'], 0)
        self.assertEqual(response.context['profile_completion'], 40)

    def test_dashboard_metrics_are_scoped_and_use_recent_confirmed_orders(self):
        user = User.objects.create_user(
            username='cliente-dashboard-qa',
            email='cliente.dashboard@example.com',
            password='ClienteDashboard123!',
            first_name='Ana',
            last_name='Prueba',
        )
        cliente = Cliente.objects.create(
            user=user,
            nombre='Ana Prueba',
            email=user.email,
            cedula='V-76543210',
            telefono='04140000000',
            direccion='Dirección de prueba',
        )
        PerfilCliente.objects.create(
            user=user,
            cedula_rif='V-76543210',
            telefono='04140000000',
            direccion='Dirección de prueba',
        )
        usuario_cliente = UsuarioClientes.objects.create(
            nombre='Ana',
            apellido='Prueba',
            telefono='04140000000',
            email=user.email,
            direccion='Dirección de prueba',
        )
        pedido_pagado = Pedido.objects.create(cliente=user, total=Decimal('125.50'), estado='pagado')
        pedido_pendiente = Pedido.objects.create(cliente=user, total=Decimal('40.00'), estado='pendiente')
        Pedido.objects.create(
            cliente=User.objects.create_user(
                username='otro-cliente-dashboard',
                email='otro.dashboard@example.com',
                password='OtroDashboard123!',
            ),
            total=Decimal('900.00'),
            estado='pagado',
        )
        Factura.objects.create(
            cliente=usuario_cliente,
            pedido=pedido_pagado,
            total=Decimal('125.50'),
        )
        Pago.objects.create(
            pedido=pedido_pendiente,
            metodo='PAYPAL',
            monto=Decimal('40.00'),
            estado='pendiente',
        )
        self.client.force_login(user)

        response = self.client.get(reverse('cliente_panel'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['pedidos_activos'], 2)
        self.assertEqual(response.context['total_orders'], 2)
        self.assertEqual(response.context['total_gastado'], Decimal('125.50'))
        self.assertEqual(response.context['pending_payment_count'], 1)
        self.assertEqual(response.context['facturas_emitidas'], 1)
        self.assertEqual(response.context['profile_completion'], 100)
        self.assertEqual(len(response.context['monthly_spend']), 6)
        self.assertEqual(response.context['monthly_spend'][-1]['total'], 125.5)
        self.assertEqual(response.context['order_statuses'][1]['count'], 1)
        self.assertContains(response, 'id="client-spend-series"')
        self.assertContains(response, 'id="client-order-status-series"')
        self.assertContains(response, 'data-chart-type="line"')
        self.assertContains(response, 'data-chart-type="doughnut"')


class ClienteFinanzasModulesTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='finanzas-alicia',
            email='alicia.finanzas@example.com',
            password='FinanzasCliente123!',
        )
        self.other_user = User.objects.create_user(
            username='finanzas-otro',
            email='otro.finanzas@example.com',
            password='FinanzasOtro123!',
        )
        Cliente.objects.create(user=self.user, nombre='Alicia', email=self.user.email)
        Cliente.objects.create(user=self.other_user, nombre='Otro', email=self.other_user.email)
        self.billing_customer = UsuarioClientes.objects.create(
            nombre='Alicia', apellido='Finanzas', telefono='04140000000',
            email=self.user.email, direccion='Dirección de Alicia',
        )
        other_billing_customer = UsuarioClientes.objects.create(
            nombre='Otro', apellido='Cliente', telefono='04140000001',
            email=self.other_user.email, direccion='Dirección de otro',
        )
        self.order = Pedido.objects.create(cliente=self.user, total=Decimal('125.50'), estado='pendiente')
        other_order = Pedido.objects.create(
            cliente=self.other_user, total=Decimal('88.00'), estado='pendiente',
        )
        self.invoice = Factura.objects.create(
            cliente=self.billing_customer,
            pedido=self.order,
            total=Decimal('125.50'),
        )
        self.other_invoice = Factura.objects.create(
            cliente=other_billing_customer,
            pedido=other_order,
            total=Decimal('88.00'),
        )
        Pago.objects.create(
            pedido=self.order,
            metodo='PAGO_MOVIL',
            monto=Decimal('125.50'),
            referencia='ALICIA-REF-74',
            estado='pendiente',
        )
        Pago.objects.create(
            pedido=other_order,
            metodo='PAYPAL',
            monto=Decimal('88.00'),
            referencia='OTRO-REF-29',
            estado='pendiente',
        )
        self.client.force_login(self.user)

    def test_invoice_and_payment_modules_only_show_the_current_customer(self):
        invoices = self.client.get(reverse('cliente_facturas'))
        payments = self.client.get(reverse('cliente_pagos'))

        self.assertEqual(invoices.status_code, 200)
        self.assertContains(invoices, f'<strong>#{self.invoice.numero}</strong>')
        self.assertNotContains(invoices, f'<strong>#{self.other_invoice.numero}</strong>')
        self.assertContains(invoices, 'Descargar nota de entrega')
        self.assertEqual(len(invoices.context['invoice_month_chart']), 6)
        self.assertEqual(invoices.context['invoice_month_chart'][-1]['value'], 1)
        self.assertEqual(invoices.context['invoice_status_chart'][0]['value'], 1)
        self.assertContains(invoices, 'id="client-invoice-month-series"')
        self.assertContains(invoices, 'data-source="client-invoice-status-series"')
        self.assertEqual(payments.status_code, 200)
        self.assertContains(payments, 'ALICIA-REF-74')
        self.assertNotContains(payments, 'OTRO-REF-29')
        self.assertEqual(payments.context['payment_status_chart'][1]['value'], 1)
        self.assertEqual(payments.context['payment_method_chart'][0]['label'], 'Pago Móvil')
        self.assertContains(payments, 'id="client-payment-status-series"')
        self.assertContains(payments, 'data-chart-type="bar" data-axis="y"')

        filtered = self.client.get(reverse('cliente_pagos'), {
            'metodo': 'PAGO_MOVIL',
            'estado': 'pendiente',
            'q': 'ALICIA-REF-74',
        })
        self.assertContains(filtered, 'ALICIA-REF-74')
        self.assertNotContains(filtered, 'OTRO-REF-29')

    def test_invoice_download_and_legacy_payment_detail_reject_other_customer(self):
        foreign_invoice = self.client.get(
            reverse('descargar_factura_pdf_cliente', args=[self.other_invoice.numero]),
        )
        self.assertEqual(foreign_invoice.status_code, 403)

        customer_account = Customer.objects.create(
            nombre='Alicia Finanzas', email=self.user.email, is_guest=False,
        )
        customer_account.set_password('FinanzasCliente123!')
        customer_account.save(update_fields=['password'])
        customer_client = Client()
        login_response = customer_client.post(reverse('cliente_login'), {
            'username': self.user.email,
            'password': 'FinanzasCliente123!',
        })
        self.assertEqual(login_response.status_code, 302)
        other_order_id = Pedido.objects.get(cliente=self.other_user).id
        foreign_payments = customer_client.get(reverse('ver_pagos_pedido', args=[other_order_id]))
        self.assertEqual(foreign_payments.status_code, 404)


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    DEFAULT_FROM_EMAIL='registro@example.test',
    PAGO_MOVIL_RECEPTOR='FerreElectri QA',
    PAGO_MOVIL_BANCO='Banesco',
    PAGO_MOVIL_TELEFONO='04140000000',
    PAGO_MOVIL_CEDULA='V-12345678',
    TRANSFERENCIA_RECEPTOR='FerreElectri QA',
    TRANSFERENCIA_BANCO='Banesco',
    TRANSFERENCIA_CUENTA='01020000000000000000',
    TRANSFERENCIA_CEDULA='V-12345678',
)
class ClienteCompraEndToEndTest(TestCase):
    def setUp(self):
        from .models import AdminDashboardConfig

        self.media_directory = TemporaryDirectory()
        self.media_settings = override_settings(
            MEDIA_ROOT=self.media_directory.name,
            PRIVATE_MEDIA_ROOT=self.media_directory.name,
            STORAGES={
                'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
                'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
            },
        )
        self.media_settings.enable()
        AdminDashboardConfig.objects.update_or_create(
            pk=1,
            defaults={'bcv_rate': Decimal('50.0000')},
        )
        self.product = Productos.objects.create(
            Codigo='E2E001',
            Descripcion='Lámpara de prueba E2E',
            Precio=Decimal('100.00'),
            Cantidad=4,
            iva=Decimal('16.00'),
        )

    def tearDown(self):
        self.media_settings.disable()
        self.media_directory.cleanup()

    def test_customer_registers_orders_and_admin_approves_with_data_isolated(self):
        from .models import Envio

        registration = self.client.post(reverse('cliente_registro'), {
            'nombre': 'Camila Demo',
            'email': 'camila.e2e@example.com',
            'cedula': 'V-76543210',
            'telefono': '+58 414 765 4321',
            'direccion': 'Avenida Central 123, Coloncito',
            'password1': 'FerreE2E!Secure-2026',
            'password2': 'FerreE2E!Secure-2026',
        }, HTTP_HOST='localhost')
        self.assertEqual(registration.status_code, 200)
        verification = confirm_customer_email(self.client, 'camila.e2e@example.com')
        self.assertEqual(verification.status_code, 200)

        customer = Customer.objects.get(email='camila.e2e@example.com')
        cliente = Cliente.objects.get(email=customer.email)
        account_record = UsuarioClientes.objects.get(email=customer.email)
        self.assertEqual(customer.cedula, 'V-76543210')
        self.assertEqual(cliente.direccion, 'Avenida Central 123, Coloncito')
        self.assertFalse(account_record.frecuente)

        self.assertEqual(self.client.get(reverse('producto_detalle', args=[self.product.Codigo])).status_code, 200)
        add_response = self.client.post(
            reverse('agregar_al_carrito', kwargs={'codigo': self.product.Codigo}),
            {'cantidad': '1', 'presentation_factor': '1'},
        )
        self.assertEqual(add_response.status_code, 302)
        cart = Carrito.objects.get(cliente=cliente)
        self.assertEqual(cart.items.get(producto=self.product).cantidad, 1)

        checkout_response = self.client.get(reverse('checkout'))
        self.assertRedirects(checkout_response, reverse('completar_datos_facturacion'))
        fiscal_response = self.client.post(reverse('completar_datos_facturacion'), {
            'nombre': 'Camila',
            'apellido': 'Demo',
            'razon_social': '',
            'cedula_rif': 'V-76543210',
            'telefono': '+58 414 765 4321',
            'direccion': 'Avenida Central 123, Coloncito',
            'email': 'camila.e2e@example.com',
        })
        self.assertRedirects(fiscal_response, reverse('checkout'))
        self.assertEqual(self.client.get(reverse('checkout')).status_code, 200)

        order_response = self.client.post(
            reverse('checkout'),
            {
                'metodo': 'PAGO_MOVIL',
                'banco': 'Banesco',
                'cedula_pagador': 'V-76543210',
                'referencia': 'E2E-REF-01',
                'telefono': '+58 414 765 4321',
                'direccion': 'Avenida Central 123, Coloncito',
                'capture': make_test_payment_image(),
            },
            follow=True,
        )
        self.assertEqual(order_response.status_code, 200)
        pedido = Pedido.objects.get(cliente__email='camila.e2e@example.com')
        pago = pedido.pagos.get()
        self.assertEqual(pedido.estado, 'pendiente')
        self.assertEqual(pedido.estado_operativo, 'pendiente_pago')
        self.assertEqual(pago.estado, 'en_revision')
        envio = Envio.objects.get(pedido=pedido)
        self.assertEqual(envio.telefono, '+58 414 765 4321')
        self.assertEqual(envio.direccion, 'Avenida Central 123, Coloncito')
        self.assertEqual(json.loads(pago.gateway_payload), {
            'currency': 'VES',
            'bcv_rate': '50.0000',
            'amount_bs': '5800.00',
        })
        cliente.refresh_from_db()
        self.assertEqual(cliente.telefono, '+58 414 765 4321')
        self.assertEqual(cliente.direccion, 'Avenida Central 123, Coloncito')
        self.assertEqual(pedido.total, Decimal('116.00'))
        self.assertEqual(pedido.items.get().iva, Decimal('16.00'))
        self.assertTrue(pago.comprobante)
        self.assertFalse(pago.verificado)
        self.product.refresh_from_db()
        self.assertEqual(self.product.Cantidad, 4)

        admin = User.objects.create_superuser(
            username='e2e-payment-admin',
            email='e2e-payment-admin@example.com',
            password='QATest123!',
        )
        admin_client = Client()
        admin_client.force_login(admin)
        pending_clients = admin_client.get(reverse('clientes'))
        self.assertEqual(pending_clients.status_code, 200)
        registered_row = next(
            row for row in pending_clients.context['clientes'].object_list
            if row.email == customer.email
        )
        self.assertFalse(registered_row.es_comprador)

        approval = admin_client.post(reverse('aprobar_pedido', args=[pedido.id]))
        self.assertEqual(approval.status_code, 302)
        pedido.refresh_from_db()
        pago.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(pedido.estado, 'pagado')
        self.assertEqual(pedido.estado_operativo, 'confirmado')
        self.assertTrue(pago.verificado)
        self.assertEqual(self.product.Cantidad, 3)
        factura = Factura.objects.get(pedido=pedido)
        self.assertEqual(factura.total, Decimal('116.00'))
        self.assertEqual(factura.cliente.email, customer.email)

        confirmed_clients = admin_client.get(reverse('clientes'))
        confirmed_row = next(
            row for row in confirmed_clients.context['clientes'].object_list
            if row.email == customer.email
        )
        self.assertTrue(confirmed_row.es_comprador)
        self.assertEqual(confirmed_clients.context['compradores_confirmados'], 1)
        admin_order_detail = admin_client.get(reverse('detalle_pedido_admin', args=[pedido.id]))
        self.assertEqual(admin_order_detail.status_code, 200)
        self.assertContains(admin_order_detail, customer.email)
        self.assertContains(admin_order_detail, 'E2E-REF-01')
        self.assertContains(admin_order_detail, 'https://wa.me/584147654321')
        self.assertContains(admin_order_detail, 'Confirmar dirección por WhatsApp')

        customer_admin_response = self.client.get('/admin-panel/clientes/')
        self.assertEqual(customer_admin_response.status_code, 302)
        outsider = Client()
        self.assertEqual(
            outsider.get(reverse('admin_comprobante_pago', args=[pago.id])).status_code,
            302,
        )

    def test_binance_checkout_is_rejected_when_only_manual_methods_are_enabled(self):
        registration = self.client.post(reverse('cliente_registro'), {
            'nombre': 'Camila Binance',
            'email': 'camila.binance.e2e@example.com',
            'cedula': 'V-76543211',
            'telefono': '+58 414 765 4321',
            'direccion': 'Avenida Central 123, Coloncito',
            'password1': 'FerreE2E!Secure-2026',
            'password2': 'FerreE2E!Secure-2026',
        }, HTTP_HOST='localhost')
        self.assertEqual(registration.status_code, 200)
        verification = confirm_customer_email(self.client, 'camila.binance.e2e@example.com')
        self.assertEqual(verification.status_code, 200)
        cliente = Cliente.objects.get(email='camila.binance.e2e@example.com')
        self.client.post(
            reverse('agregar_al_carrito', kwargs={'codigo': self.product.Codigo}),
            {'cantidad': '1', 'presentation_factor': '1'},
        )
        self.client.post(reverse('completar_datos_facturacion'), {
            'nombre': 'Camila',
            'apellido': 'Binance',
            'cedula_rif': 'V-76543211',
            'telefono': '+58 414 765 4321',
            'direccion': 'Avenida Central 123, Coloncito',
            'email': cliente.email,
        })

        checkout = self.client.post(reverse('checkout'), {
            'metodo': 'BINANCE',
            'telefono': '+58 414 765 4321',
            'direccion': 'Avenida Central 123, Coloncito',
        })

        self.assertEqual(checkout.status_code, 200)
        self.assertContains(checkout, 'El método de pago seleccionado no es válido.')
        self.assertFalse(Pedido.objects.filter(cliente__email=cliente.email).exists())

    def test_transfer_checkout_requires_receipt_and_admin_can_approve(self):
        registration = self.client.post(reverse('cliente_registro'), {
            'nombre': 'Camila Transferencia',
            'email': 'camila.transfer.e2e@example.com',
            'cedula': 'V-76543212',
            'telefono': '+58 414 765 4321',
            'direccion': 'Avenida Central 123, Coloncito',
            'password1': 'FerreE2E!Secure-2026',
            'password2': 'FerreE2E!Secure-2026',
        }, HTTP_HOST='localhost')
        self.assertEqual(registration.status_code, 200)
        verification = confirm_customer_email(self.client, 'camila.transfer.e2e@example.com')
        self.assertEqual(verification.status_code, 200)
        cliente = Cliente.objects.get(email='camila.transfer.e2e@example.com')
        self.client.post(
            reverse('agregar_al_carrito', kwargs={'codigo': self.product.Codigo}),
            {'cantidad': '1', 'presentation_factor': '1'},
        )
        self.client.post(reverse('completar_datos_facturacion'), {
            'nombre': 'Camila',
            'apellido': 'Transferencia',
            'cedula_rif': 'V-76543212',
            'telefono': '+58 414 765 4321',
            'direccion': 'Avenida Central 123, Coloncito',
            'email': cliente.email,
        })

        checkout_data = {
            'metodo': 'TRANSFERENCIA',
            'referencia': 'TRANSFER-REF-01',
            'telefono': '+58 414 765 4321',
            'direccion': 'Avenida Central 123, Coloncito',
        }
        missing_receipt = self.client.post(reverse('checkout'), checkout_data)
        self.assertEqual(missing_receipt.status_code, 200)
        self.assertFalse(Pedido.objects.filter(cliente__email=cliente.email).exists())

        checkout_data['comprobante'] = make_test_payment_image()
        checkout = self.client.post(reverse('checkout'), checkout_data)
        self.assertRedirects(checkout, reverse('cliente_panel'), fetch_redirect_response=False)
        pedido = Pedido.objects.get(cliente__email=cliente.email)
        pago = pedido.pagos.get()
        self.assertTrue(pago.comprobante)
        self.assertEqual(pago.metodo, 'TRANSFERENCIA')
        self.assertEqual(pago.referencia, 'TRANSFER-REF-01')
        self.assertEqual(json.loads(pago.gateway_payload)['amount_bs'], '5800.00')

        admin = User.objects.create_superuser(
            username='e2e-transfer-admin',
            email='e2e-transfer-admin@example.com',
            password='QATest123!',
        )
        admin_client = Client()
        admin_client.force_login(admin)
        approval = admin_client.post(reverse('aprobar_pedido', args=[pedido.id]))

        self.assertEqual(approval.status_code, 302)
        pedido.refresh_from_db()
        pago.refresh_from_db()
        self.assertEqual(pedido.estado, 'pagado')
        self.assertTrue(pago.verificado)
        self.assertTrue(Factura.objects.filter(pedido=pedido).exists())


class HomeCatalogPresentationTest(TestCase):
    def test_full_catalog_is_only_rendered_in_products_view(self):
        cache.clear()
        producto = Productos.objects.create(
            Codigo='A9001', Descripcion='Producto solo catalogo QA', Precio=25, Cantidad=3,
        )

        home = self.client.get(reverse('index'))
        catalog = self.client.get(reverse('productos'), {'orden': 'novedades'})

        self.assertEqual(home.status_code, 200)
        self.assertNotContains(home, producto.Descripcion)
        self.assertNotContains(home, 'filtered-products-title')
        self.assertEqual(catalog.status_code, 200)
        self.assertContains(catalog, producto.Descripcion)
        self.assertContains(catalog, 'filtered-products-title')

    def test_mobile_catalog_carousel_and_footer_controls(self):
        catalog = self.client.get(reverse('productos'), {'vista': 'catalogo'})
        home = self.client.get(reverse('index'))

        self.assertEqual(catalog.status_code, 200)
        self.assertContains(catalog, 'scroll-snap-type: x mandatory')
        self.assertContains(catalog, 'flex: 0 0 min(74vw, 270px)')
        self.assertEqual(home.status_code, 200)
        self.assertContains(home, 'Calle 7, Coloncito, Municipio Panamericano, Táchira, Venezuela')
        self.assertContains(home, 'Abrir en Google Maps')
        self.assertContains(home, reverse('index') + '#inicio')
        self.assertNotContains(home, 'Boletín de Suscripción')
        self.assertNotContains(home, 'Preguntas frecuentes')

    def test_mobile_catalog_filters_and_assistant_navigation_render(self):
        response = self.client.get(reverse('productos'), {'vista': 'catalogo'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'lg:sticky lg:top-24')
        self.assertContains(response, 'overflow-x-auto pb-2 lg:flex-col')
        self.assertContains(response, 'data-mobile-assistant-trigger')

    def test_home_keeps_promotions_and_confirmed_best_sellers_in_separate_panels(self):
        from datetime import date

        from Usuario.models import Clientes as ClienteVenta

        for index in range(4):
            Productos.objects.create(
                Codigo=f'P91{index:02d}',
                Descripcion=f'Promoción QA {index}',
                Precio=20,
                Cantidad=5,
                promocion=True,
            )
        cliente = ClienteVenta.objects.create(
            nombre='Cliente', apellido='QA', telefono='04140000000', cedula='V90000001',
            direccion='Dirección QA', email='venta.qa@example.com', fecha_nacimiento=date(1990, 1, 1),
        )
        factura = Factura.objects.create(cliente=cliente, total=Decimal('400.00'), estado='facturada')
        for index in range(4):
            producto = Productos.objects.create(
                Codigo=f'V91{index:02d}',
                Descripcion=f'Vendido QA {index}',
                Precio=100,
                Cantidad=5,
            )
            DetalleFactura.objects.create(factura=factura, producto=producto, cantidad=4, precio=100)

        response = self.client.get(reverse('index'))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertEqual(content.count('id="promociones"'), 1, 'falta la sección de promociones')
        self.assertEqual(content.count('id="mas-vendidos"'), 1, 'falta la sección de más vendidos')
        self.assertEqual(content.count('class="home-picks-toggle"'), 2, 'cada panel debe tener su expansor')
        self.assertEqual(content.count('home-pick-card-more'), 2, 'cada panel debe reservar sus tarjetas extra')
        self.assertIn('Promoción QA 0', content)
        self.assertIn('Vendido QA 0', content)


class CookieConsentTemplateTest(TestCase):
    def test_cookie_choices_render_globally_and_can_be_reopened_from_privacy(self):
        home = self.client.get(reverse('index'))
        privacy = self.client.get(reverse('politica_privacidad'))

        self.assertEqual(home.status_code, 200)
        self.assertContains(home, 'cookieNotice')
        self.assertContains(home, 'cookieAcceptAll')
        self.assertContains(home, 'cookieAcceptNecessary')
        self.assertEqual(privacy.status_code, 200)
        self.assertContains(privacy, 'js-open-cookie-preferences')
        self.assertContains(privacy, 'Actualmente no activamos cookies de analítica ni publicidad.')


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    DEFAULT_FROM_EMAIL='ventas@example.test',
)
class PaidOrderNoteEmailTest(TestCase):
    def test_verified_paid_order_emails_the_non_fiscal_delivery_note_pdf(self):
        user = User.objects.create_user(
            username='nota-cliente',
            email='cliente.nota@example.test',
            password='TestPassword123!',
            first_name='Cliente',
            last_name='Nota',
        )
        customer = UsuarioClientes.objects.create(
            nombre='Cliente', apellido='Nota', telefono='04140000000',
            cedula='V90000002', direccion='Calle 7, Coloncito',
            email=user.email,
        )
        product = Productos.objects.create(
            Codigo='N9001', Descripcion='Lámpara de prueba', Precio=116, Cantidad=0,
        )
        order = Pedido.objects.create(
            cliente=user, total=Decimal('116.00'), estado='pagado', stock_descontado=True,
        )
        PedidoItem.objects.create(pedido=order, producto=product, cantidad=1, precio=Decimal('100.00'))
        Pago.objects.create(
            pedido=order, metodo='PAGO_MOVIL', monto=Decimal('116.00'),
            numero_referencia='NOTA-REF-1', verificado=True, estado='confirmado',
            gateway_payload=json.dumps({'currency': 'VES', 'bcv_rate': '50.0000', 'amount_bs': '5800.00'}),
        )
        invoice = Factura.objects.create(
            pedido=order, cliente=customer, total=Decimal('116.00'),
            subtotal=Decimal('100.00'), iva=Decimal('16.00'), moneda='USD',
        )
        DetalleFactura.objects.create(
            factura=invoice, producto=product, cantidad=1, precio=Decimal('100.00'),
            iva=Decimal('16.00'),
        )

        from .tasks import send_paid_order_note_email
        result = send_paid_order_note_email.run(invoice.pk)

        self.assertTrue(result['sent'])
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertEqual(email.to, [user.email])
        self.assertIn('pedido #', email.subject.lower())
        self.assertIn('Total pagado: USD 116.00', email.body)
        self.assertIn('Equivalente recibido: Bs. 5800.00 a tasa BCV 50.0000', email.body)
        self.assertIn('NOTA-REF-1', email.body)
        self.assertIn('Mis pedidos', email.body)
        self.assertIn(reverse('cliente_panel'), email.body)
        self.assertEqual(email.attachments[0][0], f'nota_entrega_pedido_{order.pk}.pdf')
        self.assertTrue(email.attachments[0][1].startswith(b'%PDF'))


@override_settings(
    PAGO_MOVIL_RECEPTOR='FerreElectri QA',
    PAGO_MOVIL_BANCO='Banesco',
    PAGO_MOVIL_TELEFONO='04140000000',
    PAGO_MOVIL_CEDULA='V-12345678',
    TRANSFERENCIA_RECEPTOR='FerreElectri QA',
    TRANSFERENCIA_BANCO='Banesco',
    TRANSFERENCIA_CUENTA='01020000000000000000',
    TRANSFERENCIA_CEDULA='V-12345678',
)
class CheckoutProfileValidationTest(TestCase):
    def setUp(self):
        from .models import AdminDashboardConfig

        self.client = Client()
        self.media_directory = TemporaryDirectory()
        self.media_settings = override_settings(
            MEDIA_ROOT=self.media_directory.name,
            PRIVATE_MEDIA_ROOT=self.media_directory.name,
        )
        self.media_settings.enable()
        AdminDashboardConfig.objects.update_or_create(
            pk=1,
            defaults={'bcv_rate': Decimal('50.0000')},
        )
        self.product_code = 'A0001'
        self.user = User.objects.create_user(
            username='qa_checkout_user',
            email='qa_checkout@example.com',
            password='QATest123!'
        )
        self.product = Productos.objects.create(
            Codigo=self.product_code,
            Descripcion='Producto QA checkout',
            Precio=50,
            Cantidad=5,
        )

    def tearDown(self):
        for item in CarritoItem.objects.filter(producto__Codigo=self.product_code):
            item.delete()
        for carrito in Carrito.objects.filter(cliente__email='qa_checkout@example.com'):
            carrito.delete()
        for cliente in Cliente.objects.filter(email='qa_checkout@example.com'):
            cliente.delete()
        for perfil in PerfilCliente.objects.filter(user__email='qa_checkout@example.com'):
            perfil.delete()
        for pedido in Pedido.objects.filter(cliente__email='qa_checkout@example.com'):
            pedido.delete()
        for pago in Pago.objects.filter(pedido__cliente__email='qa_checkout@example.com'):
            pago.delete()
        Productos.objects.filter(Codigo=self.product_code).delete()
        User.objects.filter(email='qa_checkout@example.com').delete()
        self.media_settings.disable()
        self.media_directory.cleanup()

    def test_checkout_redirects_to_facturacion_when_profile_is_missing(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('checkout'))

        self.assertEqual(response.status_code, 302)
        self.assertIn('/cliente/completar-datos-facturacion/', response.url)

    def test_staff_separates_admin_session_from_guest_cart_and_customer_forms(self):
        self.user.is_staff = True
        self.user.save(update_fields=['is_staff'])
        self.client.force_login(self.user)
        session = self.client.session
        session['anon_cart'] = {self.product_code: 1}
        session.save()

        home = self.client.get(reverse('index'))
        self.assertEqual(home.context['cantidad_carrito'], 0)
        self.assertContains(home, 'Ir al Panel Administrativo')
        self.assertNotContains(home, '>Ingresar</a>')
        self.assertRedirects(self.client.get(reverse('carrito')), reverse('dashboard'), fetch_redirect_response=False)
        self.assertRedirects(
            self.client.get(reverse('completar_datos_facturacion')),
            reverse('dashboard'),
            fetch_redirect_response=False,
        )

    def test_cart_modal_collects_complete_fiscal_data(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('carrito'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'action="{reverse("completar_datos_facturacion")}"')
        self.assertContains(response, 'max-w-3xl')
        self.assertContains(response, 'minmax(145px,.9fr)')
        self.assertContains(response, 'body.fiscal-modal-open #aiAssistantDrawer')
        self.assertContains(response, 'body.fiscal-modal-open #aiAssistantFabContainer')
        for field in ('nombre', 'apellido', 'razon_social', 'tipo_documento', 'numero_documento', 'telefono', 'direccion', 'email'):
            self.assertContains(response, f'name="{field}"')
        for document_type in ('V', 'G', 'J'):
            self.assertContains(response, f'value="{document_type}"')

    def test_duplicate_fiscal_document_redirects_to_login_and_preserves_cart(self):
        document_owner = User.objects.create_user(
            username='cedula-owner',
            email='titular-cedula@example.test',
            password='OwnerLogin123!',
        )
        Cliente.objects.create(
            user=document_owner,
            nombre='Titular de cédula',
            email='titular-cedula@example.test',
            cedula='V-12345009',
        )
        self.client.force_login(self.user)
        session = self.client.session
        session['anon_cart'] = {self.product_code: 1}
        session['anon_cart_meta'] = {self.product_code: {'presentacion_type': 'Unidad'}}
        session.save()

        response = self.client.post(reverse('completar_datos_facturacion'), {
            'nombre': 'Cliente',
            'apellido': 'Prueba',
            'razon_social': '',
            'tipo_documento': 'V',
            'numero_documento': '12345009',
            'telefono': '04141234567',
            'direccion': 'Calle de prueba 123',
            'email': self.user.email,
        })

        expected_login = f'{reverse("cliente_login")}?next={reverse("completar_datos_facturacion")}'
        self.assertRedirects(response, expected_login, fetch_redirect_response=False)
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertEqual(self.client.session['anon_cart'], {self.product_code: 1})

        login_page = self.client.get(expected_login)
        self.assertEqual(login_page.status_code, 200)
        self.assertContains(login_page, 'Por seguridad, cerramos esta sesión')
        self.assertContains(login_page, 'El carrito se conserva en este navegador')
        self.assertContains(login_page, 'name="next" value="/cliente/completar-datos-facturacion/"')

        login_response = self.client.post(reverse('cliente_login'), {
            'username': document_owner.email,
            'password': 'OwnerLogin123!',
            'next': reverse('completar_datos_facturacion'),
        })
        self.assertRedirects(login_response, reverse('completar_datos_facturacion'))
        self.assertEqual(self.client.get(reverse('completar_datos_facturacion')).status_code, 200)

    def test_fiscal_checkout_builds_and_validates_document_prefixes(self):
        self.client.force_login(self.user)
        form_data = {
            'nombre': 'Cliente',
            'apellido': 'Prueba',
            'razon_social': '',
            'numero_documento': '12345001',
            'telefono': '04141234567',
            'direccion': 'Calle de prueba 123',
            'email': self.user.email,
        }
        invalid = self.client.post(reverse('completar_datos_facturacion'), {
            **form_data,
            'tipo_documento': 'X',
        })
        self.assertEqual(invalid.status_code, 200)
        self.assertContains(invalid, 'Selecciona V, G o J')
        self.assertFalse(Cliente.objects.filter(email=self.user.email).exists())

        for index, document_type in enumerate(('V', 'G', 'J'), start=1):
            email = self.user.email if document_type == 'V' else f'cliente-{document_type.lower()}@example.com'
            user = self.user if document_type == 'V' else User.objects.create_user(
                username=f'cliente-{document_type.lower()}',
                email=email,
                password='ClienteFiscal123!',
            )
            self.client.force_login(user)
            valid = self.client.post(reverse('completar_datos_facturacion'), {
                **form_data,
                'tipo_documento': document_type,
                'numero_documento': f'1234500{index}',
                'email': email,
            })
            self.assertEqual(valid.status_code, 302)
            self.assertEqual(valid.url, reverse('checkout'))
            profile = PerfilCliente.objects.get(user=user)
            self.assertEqual(profile.cedula_rif, f'{document_type}-1234500{index}')

    def test_contador_carrito_mide_productos_distintos_no_unidades(self):
        self.product.Cantidad = 10
        self.product.save(update_fields=['Cantidad'])
        first_add = self.client.post(
            reverse('agregar_al_carrito', kwargs={'codigo': self.product_code}),
            {'cantidad': '6', 'presentation_factor': '1'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        second_product = Productos.objects.create(
            Codigo='A0002',
            Descripcion='Segundo producto QA',
            Precio=25,
            Cantidad=5,
        )
        second_add = self.client.post(
            reverse('agregar_al_carrito', kwargs={'codigo': second_product.Codigo}),
            {'cantidad': '3', 'presentation_factor': '1'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        response = self.client.get(reverse('carrito'))

        self.assertEqual(first_add.json()['count'], 1)
        self.assertEqual(second_add.status_code, 200, second_add.content.decode())
        self.assertEqual(second_add.json()['count'], 2)
        self.assertEqual(response.context['cantidad_carrito'], 2)
        self.assertContains(response, '2 artículo')
        self.assertContains(response, 'id="checkoutButton"')
        self.assertContains(response, 'ferrebot_checkout_guide')

    def test_carrito_vacio_enlaza_directamente_al_catalogo(self):
        response = self.client.get(reverse('carrito'))

        catalog_url = f'{reverse("productos")}?vista=catalogo#productos-grid'
        self.assertContains(response, f'<a href="{catalog_url}" class="btn-primary">Ver productos</a>')
        self.assertContains(response, f'<a href="{catalog_url}" class="checkout-button">Explorar productos</a>')

    def test_ferrebot_guia_checkout_segun_metodo_seleccionado(self):
        instructions = {
            'PAGO_MOVIL': ('Pago Móvil', 'banco'),
            'TRANSFERENCIA': ('Transferencia bancaria', 'referencia'),
        }
        for method, (label, expected_field) in instructions.items():
            with self.subTest(method=method):
                reply, action = build_assistant_reply(
                    f'Seleccioné {label}. ¿Qué campos debo completar ahora?',
                    page_context={
                        'path': '/checkout/',
                        'payment_method': method,
                        'cart_count': 1,
                    },
                )

                self.assertIn('Paso 3 de 4', reply)
                self.assertIn(expected_field, reply.lower())
                self.assertIsNone(action)

    def test_completar_facturacion_reutiliza_cliente_creado_por_registro(self):
        cliente = Cliente.objects.create(
            nombre='QA Registro',
            email='qa-profile-link@example.test',
        )
        user = User.objects.create_user(
            username='qa-profile-link',
            email=cliente.email,
            password='CheckoutQA123!',
        )
        self.client.force_login(user)

        response = self.client.post(
            reverse('completar_datos_facturacion'),
            {
                'nombre': 'QA Registro',
                'apellido': 'Checkout',
                'cedula_rif': 'V12345678',
                'telefono': '04120000000',
                'direccion': 'Direccion QA temporal',
                'email': cliente.email,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('checkout'))
        cliente.refresh_from_db()
        self.assertEqual(cliente.user_id, user.id)
        self.assertEqual(Cliente.objects.filter(email__iexact=user.email).count(), 1)

    def test_nuevo_login_reemplaza_carrito_db_por_carrito_de_sesion_actual(self):
        cliente = Cliente.objects.create(
            user=self.user,
            nombre='QA Checkout',
            email=self.user.email,
        )
        carrito = Carrito.objects.create(cliente=cliente)
        CarritoItem.objects.create(carrito=carrito, producto=self.product, cantidad=2)
        new_product = Productos.objects.create(
            Codigo='A0002',
            Descripcion='Producto de sesión nueva',
            Precio=12,
            Cantidad=8,
        )
        session = self.client.session
        session['anon_cart'] = {new_product.Codigo: 3}
        session.save()

        response = self.client.post(
            reverse('login_cliente'),
            {'username': self.user.username, 'password': 'QATest123!'},
        )

        self.assertEqual(response.status_code, 302)
        items = list(carrito.items.select_related('producto'))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].producto_id, new_product.Codigo)
        self.assertEqual(items[0].cantidad, 3)
        self.assertNotIn('anon_cart', self.client.session)

    def test_logout_elimina_carrito_persistente_y_vacia_sesion(self):
        cliente = Cliente.objects.create(
            user=self.user,
            nombre='QA Logout',
            email=self.user.email,
        )
        carrito = Carrito.objects.create(cliente=cliente)
        CarritoItem.objects.create(carrito=carrito, producto=self.product, cantidad=4)
        self.client.force_login(self.user)
        session = self.client.session
        session['cliente_id'] = cliente.id
        session['anon_cart'] = {self.product_code: 1}
        session.save()

        response = self.client.post(reverse('logout'))

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Carrito.objects.filter(cliente=cliente).exists())
        self.assertNotIn('anon_cart', self.client.session)

    def test_cliente_elimina_item_propio_de_carrito(self):
        cliente = Cliente.objects.create(
            user=self.user,
            nombre='QA Remove',
            email=self.user.email,
        )
        carrito = Carrito.objects.create(cliente=cliente)
        item = CarritoItem.objects.create(carrito=carrito, producto=self.product, cantidad=2)
        self.client.force_login(self.user)
        session = self.client.session
        session['cliente_id'] = cliente.id
        session.save()

        cart_page = self.client.get(reverse('carrito'))
        self.assertContains(
            cart_page,
            f'action="{reverse("eliminar_item_carrito", args=[item.id])}"',
        )
        self.assertContains(cart_page, 'name="csrfmiddlewaretoken"')

        response = self.client.post(reverse('eliminar_item_carrito', args=[item.id]))

        self.assertRedirects(response, reverse('carrito'))
        self.assertFalse(CarritoItem.objects.filter(id=item.id).exists())

    def test_cliente_no_puede_eliminar_item_de_otra_cuenta(self):
        other_user = User.objects.create_user(
            username='qa-other-cart-owner',
            email='qa-other-cart-owner@example.test',
            password='OtherCheckout123!',
        )
        cliente = Cliente.objects.create(
            user=self.user,
            nombre='QA Owner',
            email=self.user.email,
        )
        other_cliente = Cliente.objects.create(
            user=other_user,
            nombre='QA Other',
            email=other_user.email,
        )
        other_cart = Carrito.objects.create(cliente=other_cliente)
        other_item = CarritoItem.objects.create(
            carrito=other_cart,
            producto=self.product,
            cantidad=1,
        )
        self.client.force_login(self.user)
        session = self.client.session
        session['cliente_id'] = cliente.id
        session.save()

        response = self.client.post(reverse('eliminar_item_carrito', args=[other_item.id]))

        self.assertEqual(response.status_code, 404)
        self.assertTrue(CarritoItem.objects.filter(id=other_item.id).exists())

    def test_invitado_elimina_item_temporal_con_post(self):
        session = self.client.session
        session['anon_cart'] = {self.product_code: 3}
        session.save()

        response = self.client.post(
            reverse('eliminar_item_carrito_anon', args=[self.product_code])
        )

        self.assertRedirects(response, reverse('carrito'))
        self.assertNotIn(self.product_code, self.client.session.get('anon_cart', {}))

    @override_settings(STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    })
    def test_checkout_get_renders_with_unbound_payment_form(self):
        self.client.force_login(self.user)
        self.user.first_name = 'QA'
        self.user.last_name = 'Tester'
        self.user.save(update_fields=['first_name', 'last_name'])
        PerfilCliente.objects.create(
            user=self.user,
            cedula_rif='V12345678',
            telefono='04121234567',
            direccion='Dirección de prueba QA',
        )
        cliente = Cliente.objects.create(
            user=self.user,
            nombre='QA Tester',
            email=self.user.email,
            telefono='04121234567',
            direccion='Dirección de prueba QA',
        )
        carrito = Carrito.objects.create(cliente=cliente)
        CarritoItem.objects.create(carrito=carrito, producto=self.product, cantidad=1)
        session = self.client.session
        session['cliente_id'] = cliente.id
        session.save()

        response = self.client.get(reverse('checkout'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Método de pago premium')

    def test_checkout_requires_fiscal_address_even_when_client_has_delivery_address(self):
        self.client.force_login(self.user)
        self.user.first_name = 'QA'
        self.user.last_name = 'Tester'
        self.user.save(update_fields=['first_name', 'last_name'])
        PerfilCliente.objects.create(
            user=self.user,
            cedula_rif='V12345678',
            telefono='04121234567',
        )
        cliente = Cliente.objects.create(
            user=self.user,
            nombre='QA Tester',
            email=self.user.email,
            telefono='04121234567',
            direccion='Dirección de entrega de prueba',
        )
        carrito = Carrito.objects.create(cliente=cliente)
        CarritoItem.objects.create(carrito=carrito, producto=self.product, cantidad=1)

        response = self.client.get(reverse('checkout'))

        self.assertRedirects(response, reverse('completar_datos_facturacion'))

    @override_settings(STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    })
    def test_invalid_payment_capture_returns_visible_checkout_errors(self):
        self.client.force_login(self.user)
        self.user.first_name = 'QA'
        self.user.last_name = 'Tester'
        self.user.save(update_fields=['first_name', 'last_name'])
        PerfilCliente.objects.create(
            user=self.user,
            cedula_rif='V12345678',
            telefono='04121234567',
            direccion='Dirección de prueba QA',
        )
        cliente = Cliente.objects.create(
            user=self.user,
            nombre='QA Tester',
            email=self.user.email,
            telefono='04121234567',
            direccion='Dirección de prueba QA',
        )
        carrito = Carrito.objects.create(cliente=cliente)
        CarritoItem.objects.create(carrito=carrito, producto=self.product, cantidad=2)
        session = self.client.session
        session['cliente_id'] = cliente.id
        session.save()

        response = self.client.post(
            reverse('checkout'),
            {
                'metodo': 'PAGO_MOVIL',
                'banco': 'Banesco',
                'cedula_pagador': 'V12345678',
                'referencia': 'REF-QA-123',
                'telefono': '04121234567',
                'direccion': 'Dirección de prueba QA',
                'capture': SimpleUploadedFile('capture.png', b'not an image', content_type='image/png'),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'El capture de pago debe ser una imagen válida.')
        self.assertContains(response, 'REF-QA-123')
        self.assertEqual(Pedido.objects.filter(cliente=self.user).count(), 0)
        self.product.refresh_from_db()
        self.assertEqual(self.product.Cantidad, 5)

    @override_settings(STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    })
    def test_checkout_reserves_stock_until_admin_approves_payment(self):
        self.client.force_login(self.user)
        self.user.first_name = 'QA'
        self.user.last_name = 'Tester'
        self.user.save(update_fields=['first_name', 'last_name'])

        PerfilCliente.objects.create(
            user=self.user,
            cedula_rif='V12345678',
            telefono='04121234567',
            direccion='Dirección de prueba QA',
        )
        cliente = Cliente.objects.create(
            user=self.user,
            nombre='QA Tester',
            email=self.user.email,
            telefono='04121234567',
            direccion='Dirección de prueba QA',
        )
        carrito = Carrito.objects.create(cliente=cliente)
        CarritoItem.objects.create(carrito=carrito, producto=self.product, cantidad=2)
        producto_exento = Productos.objects.create(
            Codigo='A0002', Descripcion='Producto exento QA', Precio=20, Cantidad=5, iva=Decimal('0.00'),
        )
        CarritoItem.objects.create(carrito=carrito, producto=producto_exento, cantidad=1)
        session = self.client.session
        session['cliente_id'] = cliente.id
        session.save()

        response = self.client.post(
            reverse('checkout'),
            {
                'metodo': 'PAGO_MOVIL',
                'banco': 'Banesco',
                'cedula_pagador': 'V12345678',
                'referencia': 'REF-QA-123',
                'telefono': '04121234567',
                'direccion': 'Dirección de prueba QA',
                'capture': make_test_payment_image(),
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        pedido = Pedido.objects.filter(cliente=self.user).order_by('-id').first()
        self.assertIsNotNone(pedido)
        self.assertContains(response, f'Pedido #{pedido.id} recibido')
        self.assertContains(response, 'pendiente de revisión')
        self.assertEqual(pedido.total, Decimal('136.00'))
        self.assertEqual(pedido.estado, 'pendiente')
        self.assertEqual(list(pedido.items.values_list('cantidad', flat=True)), [2, 1])
        self.assertEqual(
            set(pedido.items.values_list('iva', flat=True)),
            {Decimal('0.00'), Decimal('16.00')},
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.Cantidad, 5)
        self.assertFalse(Factura.objects.filter(pedido=pedido).exists())

        pago = pedido.pagos.get()
        self.assertFalse(pago.verificado)
        self.assertEqual(pago.banco_origen, 'Banesco')
        self.assertEqual(pago.cedula_pagador, 'V-12345678')
        self.assertEqual(pago.numero_referencia, 'REF-QA-123')
        self.assertTrue(pago.comprobante)

        receipt_url = reverse('admin_comprobante_pago', args=[pago.id])
        self.assertEqual(self.client.get(receipt_url).status_code, 302)
        private_media_url = f'/media/{pago.comprobante.name}'
        self.assertEqual(self.client.get(private_media_url).status_code, 302)

        admin = User.objects.create_superuser(
            username='qa_payment_admin',
            email='qa_payment_admin@example.com',
            password='QATest123!',
        )
        self.client.force_login(admin)
        approval = self.client.post(reverse('aprobar_pedido', args=[pedido.id]))

        self.assertEqual(approval.status_code, 302)
        pedido.refresh_from_db()
        pago.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(pedido.estado, 'pagado')
        self.assertTrue(pago.verificado)
        self.assertEqual(self.product.Cantidad, 3)
        self.assertTrue(Factura.objects.filter(pedido=pedido, estado='facturada').exists())
        factura = Factura.objects.get(pedido=pedido)
        self.assertEqual(factura.subtotal, Decimal('120.00'))
        self.assertEqual(factura.iva, Decimal('16.00'))
        self.assertEqual(factura.total, Decimal('136.00'))
        self.assertEqual(factura.moneda, 'USD')
        self.assertEqual(
            set(DetalleFactura.objects.filter(factura=factura).values_list('iva', flat=True)),
            {Decimal('0.00'), Decimal('16.00')},
        )
        detail = self.client.get(reverse('detalle_pedido_admin', args=[pedido.id]))
        self.assertContains(detail, 'Banesco')
        self.assertContains(detail, 'V-12345678')
        self.assertContains(detail, 'REF-QA-123')
        self.assertContains(detail, receipt_url)
        self.assertContains(detail, 'Detalle administrativo para revisar productos y evidencia de pago.')
        self.assertContains(detail, 'Despacho')
        from .models import Envio
        self.assertTrue(Envio.objects.filter(pedido=pedido).exists())
        self.assertContains(detail, 'Clientes')
        self.assertContains(detail, 'css/admin-theme.css')
        self.assertContains(detail, 'Modo oscuro')
        self.assertNotContains(detail, 'Mi perfil')

        self.client.force_login(self.user)
        customer_panel = self.client.get(reverse('cliente_panel'))
        self.assertContains(
            customer_panel,
            reverse('descargar_factura_pdf_cliente', args=[factura.numero]),
        )

    def test_admin_cannot_approve_order_without_payment_evidence(self):
        order = Pedido.objects.create(cliente=self.user, total=Decimal('100.00'), estado='pendiente')
        PedidoItem.objects.create(pedido=order, producto=self.product, cantidad=2, precio=Decimal('50.00'))
        admin = User.objects.create_superuser(
            username='qa_missing_payment_admin',
            email='qa_missing_payment_admin@example.com',
            password='QATest123!',
        )
        self.client.force_login(admin)

        response = self.client.post(reverse('aprobar_pedido', args=[order.id]))

        self.assertEqual(response.status_code, 302)
        order.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(order.estado, 'pendiente')
        self.assertEqual(self.product.Cantidad, 5)
        self.assertFalse(Factura.objects.filter(pedido=order).exists())

    def test_rejecting_legacy_order_restores_previously_deducted_stock(self):
        order = Pedido.objects.create(
            cliente=self.user,
            total=Decimal('100.00'),
            estado='pendiente',
            stock_descontado=True,
        )
        PedidoItem.objects.create(pedido=order, producto=self.product, cantidad=2, precio=Decimal('50.00'))
        self.product.Cantidad = 3
        self.product.save(update_fields=['Cantidad'])
        admin = User.objects.create_superuser(
            username='qa_reject_admin',
            email='qa_reject_admin@example.com',
            password='QATest123!',
        )
        self.client.force_login(admin)

        response = self.client.post(reverse('rechazar_pedido', args=[order.id]))

        self.assertEqual(response.status_code, 302)
        order.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(order.estado, 'cancelado')
        self.assertFalse(order.stock_descontado)
        self.assertEqual(self.product.Cantidad, 5)
        self.assertTrue(MovimientoInventario.objects.filter(
            producto=self.product,
            tipo='entrada',
            cantidad=2,
            descripcion=f'Reverso de pedido cancelado #{order.id}',
        ).exists())

    @override_settings(STRIPE_WEBHOOK_SECRET='stripe-test-secret', STRIPE_CURRENCY='usd')
    def test_stripe_webhook_fulfills_only_a_paid_matching_order(self):
        order = Pedido.objects.create(cliente=self.user, total=Decimal('100.00'), estado='pendiente')
        PedidoItem.objects.create(pedido=order, producto=self.product, cantidad=2, precio=Decimal('50.00'))
        pago = Pago.objects.create(
            pedido=order,
            metodo='STRIPE',
            monto=Decimal('100.00'),
            gateway='STRIPE',
            gateway_reference='cs_test_order',
            gateway_status='pending',
        )
        event = {
            'type': 'checkout.session.completed',
            'data': {'object': {
                'id': 'cs_test_order',
                'payment_status': 'paid',
                'amount_total': 10000,
                'currency': 'usd',
                'metadata': {'pedido_id': str(order.id)},
            }},
        }

        with patch('dashboard.views.stripe', create=True) as stripe_api:
            stripe_api.Webhook.construct_event.return_value = event
            response = self.client.post(
                reverse('stripe_webhook'),
                data=b'{}',
                content_type='application/json',
                HTTP_STRIPE_SIGNATURE='signed-test-event',
            )

        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        pago.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(order.estado, 'pagado')
        self.assertTrue(pago.verificado)
        self.assertEqual(self.product.Cantidad, 3)
        self.assertTrue(Factura.objects.filter(pedido=order, estado='facturada').exists())


class RecuperacionNombreClienteTest(TestCase):
    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', EMAIL_HOST_USER='tests@example.com')
    def test_solicitar_recuperacion_usa_nombre_del_cliente_en_sesion(self):
        user = User.objects.create_user(
            username='gregorygomez2004.28',
            email='gregorygomez2004.28@gmail.com',
            password='StrongPass123!'
        )
        user.first_name = 'Gregory'
        user.last_name = 'Gomez'
        user.save(update_fields=['first_name', 'last_name'])

        Cliente.objects.create(
            user=user,
            nombre='Gregory Gomez',
            email=user.email,
            telefono='04141234567',
            direccion='Av. Principal',
        )

        response = self.client.post(
            reverse('solicitar_recuperacion'),
            {'email': user.email},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.session['recupera_usuario'], 'Gregory Gomez')

        code_page = self.client.get(reverse('recuperar_codigo_cliente'))
        self.assertEqual(code_page.status_code, 200)
        self.assertContains(code_page, 'Código enviado')
        self.assertNotContains(code_page, user.email)
        self.assertContains(code_page, 'código de 8 caracteres')
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [user.email])

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', EMAIL_HOST_USER='tests@example.com')
    def test_recuperacion_no_registrada_muestra_error_y_no_envia_codigo(self):
        response = self.client.post(
            reverse('solicitar_recuperacion_cliente'),
            {'email': 'alguien@example.com'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No existe una cuenta registrada con ese correo')
        self.assertContains(response, 'Revisa el correo o regístrate')
        self.assertEqual(len(mail.outbox), 0)
        self.assertNotIn('recupera_codigo_hash', self.client.session)

    def test_customer_recovery_code_page_rejects_admin_scope_and_staff_user(self):
        session = self.client.session
        session['recupera_scope'] = 'admin'
        session.save()

        admin_scope_response = self.client.get(reverse('recuperar_codigo_cliente'))
        self.assertEqual(admin_scope_response.status_code, 403)

        self.client.logout()
        staff_user = User.objects.create_user(
            username='staff-customer-recovery',
            email='staff-customer-recovery@example.test',
            password='StaffPass123!',
            is_staff=True,
        )
        self.client.force_login(staff_user)
        staff_response = self.client.get(reverse('recuperar_codigo_cliente'))
        self.assertEqual(staff_response.status_code, 403)


class LegalPagesTest(TestCase):
    def test_public_terms_and_privacy_pages_render_from_footer_routes(self):
        terms = self.client.get(reverse('condiciones_servicio'))
        privacy = self.client.get(reverse('politica_privacidad'))

        self.assertEqual(terms.status_code, 200)
        self.assertContains(terms, 'Términos y condiciones de servicio')
        self.assertContains(terms, 'El pedido solo se aprueba después de la verificación')
        self.assertEqual(privacy.status_code, 200)
        self.assertContains(privacy, 'Política de privacidad')
        self.assertContains(privacy, 'Los comprobantes manuales son revisados')


class AdminPWASecurityTest(TestCase):
    def test_manifest_and_service_worker_are_available(self):
        manifest = self.client.get(reverse('admin_pwa_manifest'))
        worker = self.client.get(reverse('admin_pwa_service_worker'))

        self.assertEqual(manifest.status_code, 200)
        self.assertEqual(manifest['Content-Type'], 'application/manifest+json; charset=utf-8')
        self.assertEqual(manifest.json()['display'], 'standalone')
        self.assertEqual(manifest.json()['background_color'], '#08243b')
        self.assertEqual(manifest.json()['start_url'], reverse('admin_pwa_launch'))
        self.assertIn('no-cache', manifest['Cache-Control'])
        for icon in manifest.json()['icons']:
            response = self.client.get(icon['src'])
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response['Content-Type'], 'image/png')
        self.assertEqual(worker.status_code, 200)
        self.assertContains(worker, "addEventListener('push'")

    def test_admin_login_includes_branded_pwa_launch_screen(self):
        response = self.client.get(reverse('login_admin_custom'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="pwa-launch-splash"')
        self.assertContains(response, 'class="pwa-launch-logo"')
        self.assertContains(response, 'rel="manifest"')

    def test_pwa_launch_is_public_and_renders_progress_before_login(self):
        response = self.client.get(reverse('admin_pwa_launch'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="launch-progress"')
        self.assertContains(response, reverse('admin_app_session_lock'))
        self.assertContains(response, 'rel="manifest"')

    def test_admin_password_login_ajax_returns_success_destination(self):
        staff = User.objects.create_superuser(
            username='ajax-login-admin', email='ajax-login@example.test', password='TestPassword123!',
        )

        response = self.client.post(
            reverse('login_admin_custom'),
            data={'username': staff.username, 'password': 'TestPassword123!', 'next': '', 'remember_device': '0'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'ok': True, 'next': reverse('dashboard')})
        login_event = AuditLog.objects.get(action='ADMIN_PASSWORD_LOGIN', user=staff)
        self.assertEqual(login_event.model_name, 'AdminAuth')
        self.assertEqual(login_event.ip_address, '127.0.0.1')

    def test_password_login_can_request_passkey_enrollment_after_validation(self):
        staff = User.objects.create_superuser(
            username='passkey-enrollment-admin', email='passkey-enrollment@example.test',
            password='TestPassword123!',
        )

        response = self.client.post(
            reverse('login_admin_custom'),
            {'username': staff.username, 'password': 'TestPassword123!', 'remember_device': '1'},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.client.session.get('admin_passkey_enrollment_prompt'))
        self.assertContains(response, 'Activar acceso con huella o PIN')

    def test_invalid_password_does_not_request_passkey_enrollment(self):
        User.objects.create_superuser(
            username='passkey-invalid-admin', email='passkey-invalid@example.test',
            password='TestPassword123!',
        )

        response = self.client.post(
            reverse('login_admin_custom'),
            {'username': 'passkey-invalid-admin', 'password': 'wrong', 'remember_device': '1'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.client.session.get('admin_passkey_enrollment_prompt', False))
        self.assertTrue(AuditLog.objects.filter(action='ADMIN_PASSWORD_LOGIN_FAILED').exists())

    def test_pwa_session_lock_closes_administrative_session(self):
        staff = User.objects.create_user(
            username='pwa-session-lock-admin', password='TestPassword123!', is_staff=True,
        )
        self.client.force_login(staff)

        response = self.client.post(reverse('admin_app_session_lock'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'ok': True})
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertTrue(AuditLog.objects.filter(action='ADMIN_LOGOUT', user=staff).exists())

    def test_standard_logout_closes_the_tracked_admin_device_session(self):
        staff = User.objects.create_user(
            username='standard-logout-admin', password='TestPassword123!', is_staff=True,
        )
        self.client.force_login(staff)
        self.client.get(reverse('dashboard'))
        session_key = self.client.session.session_key

        response = self.client.post(reverse('logout'))

        self.assertEqual(response.status_code, 302)
        self.assertFalse(AdminDeviceSession.objects.get(session_key=session_key).is_active)
        self.assertTrue(AuditLog.objects.filter(action='ADMIN_LOGOUT', user=staff).exists())

    def test_pwa_session_lock_is_safe_after_session_expiration(self):
        response = self.client.post(reverse('admin_app_session_lock'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'ok': True})

    def test_second_admin_login_requires_approval_and_keeps_approving_session(self):
        cache.clear()
        active_admin = User.objects.create_user(
            username='session-transfer-active', password='TestPassword123!', is_staff=True,
        )
        requesting_admin = User.objects.create_user(
            username='session-transfer-requester', password='TestPassword123!', is_staff=True,
        )
        self.client.force_login(active_admin)
        self.client.get(reverse('dashboard'))
        active_session_key = self.client.session.session_key
        self.assertTrue(AdminDeviceSession.objects.filter(session_key=active_session_key, is_active=True).exists())

        requesting_client = Client(HTTP_HOST='localhost')
        login_response = requesting_client.post(
            reverse('login_admin_custom'),
            {'username': requesting_admin.username, 'password': 'TestPassword123!', 'remember_device': '0'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
            HTTP_USER_AGENT='Approval test phone',
        )
        requesting_session_key = requesting_client.session.session_key

        self.assertEqual(login_response.status_code, 202)
        self.assertTrue(login_response.json()['approval_required'])
        approval = AdminLoginApproval.objects.get(pk=login_response.json()['approval_id'])
        self.assertEqual(approval.status, AdminLoginApproval.Status.PENDING)
        self.assertEqual(approval.active_session_key, active_session_key)
        self.assertEqual(approval.user_id, requesting_admin.pk)
        self.assertNotIn('_auth_user_id', requesting_client.session)

        pending_response = self.client.get(reverse('admin_login_approval_pending'))
        self.assertEqual(pending_response.status_code, 200)
        self.assertEqual(pending_response.json()['approvals'][0]['user_agent'], 'Approval test phone')
        decision_response = self.client.post(
            reverse('admin_login_approval_respond', args=[approval.pk]),
            data=json.dumps({'decision': 'approve'}),
            content_type='application/json',
        )
        self.assertEqual(decision_response.status_code, 200)
        pending_device = AdminDeviceSession.objects.get(session_key=requesting_session_key)
        self.assertEqual(pending_device.user_id, requesting_admin.pk)
        self.assertFalse(pending_device.is_active)
        self.assertEqual(pending_device.user_agent, 'Approval test phone')

        completion_response = requesting_client.get(
            reverse('admin_login_approval_status', args=[approval.pk]),
        )
        self.assertEqual(completion_response.status_code, 200)
        self.assertTrue(completion_response.json()['complete'])
        self.assertEqual(approval.__class__.objects.get(pk=approval.pk).status, AdminLoginApproval.Status.COMPLETED)
        self.assertIn('_auth_user_id', requesting_client.session)
        self.assertEqual(int(requesting_client.session['_auth_user_id']), requesting_admin.pk)
        self.assertTrue(AdminDeviceSession.objects.get(session_key=active_session_key).is_active)
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 200)
        self.assertTrue(AuditLog.objects.filter(action='ADMIN_SESSION_APPROVED', user=requesting_admin).exists())

    def test_active_admin_can_deny_a_second_login(self):
        cache.clear()
        active_admin = User.objects.create_user(
            username='session-denial-active', password='TestPassword123!', is_staff=True,
        )
        requesting_admin = User.objects.create_user(
            username='session-denial-requester', password='TestPassword123!', is_staff=True,
        )
        self.client.force_login(active_admin)
        self.client.get(reverse('dashboard'))
        requesting_client = Client(HTTP_HOST='localhost')
        login_response = requesting_client.post(
            reverse('login_admin_custom'),
            {'username': requesting_admin.username, 'password': 'TestPassword123!', 'remember_device': '0'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        approval_id = login_response.json()['approval_id']

        decision_response = self.client.post(
            reverse('admin_login_approval_respond', args=[approval_id]),
            data=json.dumps({'decision': 'deny'}),
            content_type='application/json',
        )
        status_response = requesting_client.get(
            reverse('admin_login_approval_status', args=[approval_id]),
        )

        self.assertEqual(decision_response.status_code, 200)
        self.assertEqual(status_response.status_code, 200)
        self.assertEqual(status_response.json()['status'], AdminLoginApproval.Status.DENIED)
        self.assertNotIn('_auth_user_id', requesting_client.session)
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 200)

    def test_primary_device_remains_approval_authority_after_inactivity(self):
        owner = User.objects.create_superuser(
            username='persistent-primary-owner', email='persistent-primary@example.test', password='TestPassword123!',
        )
        requester = User.objects.create_user(
            username='persistent-primary-requester', password='TestPassword123!', is_staff=True,
        )
        primary_key = AdminPasskey.objects.create(
            user=owner, credential_id='cGVyc2lzdGVudC1wcmltYXJ5', public_key=b'primary-key', name='Teléfono principal',
        )
        config, _ = AdminSecurityConfig.objects.get_or_create(pk=1)
        config.owner_user = owner
        config.primary_passkey = primary_key
        config.save(update_fields=['owner_user', 'primary_passkey', 'updated_at'])
        self.client.force_login(owner)
        owner_session = self.client.session
        owner_session['admin_current_passkey_id'] = primary_key.pk
        owner_session.save()
        self.client.get(reverse('dashboard'))
        primary_device = AdminDeviceSession.objects.get(session_key=self.client.session.session_key)
        primary_device.last_seen_at = timezone.now() - timedelta(minutes=8)
        primary_device.save(update_fields=['last_seen_at'])

        requesting_client = Client(HTTP_HOST='localhost')
        response = requesting_client.post(
            reverse('login_admin_custom'),
            {'username': requester.username, 'password': 'TestPassword123!', 'remember_device': '0'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 202)
        approval = AdminLoginApproval.objects.get(pk=response.json()['approval_id'])
        self.assertEqual(approval.active_session_key, primary_device.session_key)
        self.assertTrue(AdminDeviceSession.objects.get(pk=primary_device.pk).is_active)

    def test_primary_owner_can_revoke_secondary_session_without_revoking_itself(self):
        owner = User.objects.create_superuser(
            username='session-revoker-owner', email='session-revoker@example.test', password='TestPassword123!',
        )
        secondary = User.objects.create_user(
            username='secondary-device-user', password='TestPassword123!', is_staff=True,
        )
        primary_key = AdminPasskey.objects.create(
            user=owner, credential_id='c2Vzc2lvbi1yZXZva2Vy', public_key=b'revoker-key', name='Teléfono principal',
        )
        config, _ = AdminSecurityConfig.objects.get_or_create(pk=1)
        config.owner_user = owner
        config.primary_passkey = primary_key
        config.save(update_fields=['owner_user', 'primary_passkey', 'updated_at'])
        self.client.force_login(owner)
        primary_session = self.client.session
        primary_session['admin_current_passkey_id'] = primary_key.pk
        primary_session.save()
        self.client.get(reverse('dashboard'))

        secondary_client = Client(HTTP_HOST='localhost')
        secondary_client.force_login(secondary)
        secondary_client.get(reverse('dashboard'))
        secondary_key = secondary_client.session.session_key
        secondary_device = AdminDeviceSession.objects.get(session_key=secondary_key)

        response = self.client.post(reverse('admin_security_devices'), {
            'action': 'revoke_session',
            'session_id': secondary_device.pk,
        })

        self.assertEqual(response.status_code, 302)
        self.assertFalse(AdminDeviceSession.objects.get(pk=secondary_device.pk).is_active)
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 200)
        self.assertEqual(secondary_client.get(reverse('dashboard')).status_code, 302)

    def test_primary_passkey_bypasses_login_approval(self):
        from django.contrib.sessions.middleware import SessionMiddleware
        from django.test import RequestFactory
        from .views import _pending_admin_login_approval

        owner = User.objects.create_superuser(
            username='primary-passkey-login', email='primary-passkey-login@example.test', password='TestPassword123!',
        )
        primary_key = AdminPasskey.objects.create(
            user=owner, credential_id='cHJpbWFyeS1ieXBhc3M', public_key=b'primary-key', name='Teléfono principal',
        )
        config, _ = AdminSecurityConfig.objects.get_or_create(pk=1)
        config.owner_user = owner
        config.primary_passkey = primary_key
        config.save(update_fields=['owner_user', 'primary_passkey', 'updated_at'])
        AdminDeviceSession.objects.create(
            user=owner, passkey=primary_key, session_key='primary-active-session-000001', is_active=True,
        )
        request = RequestFactory().post('/admin-panel/passkeys/login/verify/')
        SessionMiddleware(lambda response: response).process_request(request)
        request.session.save()
        request.session['admin_current_passkey_id'] = primary_key.pk
        request.session.save()

        self.assertIsNone(_pending_admin_login_approval(request, owner))
        self.assertFalse(AdminLoginApproval.objects.filter(user=owner).exists())

    def test_primary_owner_can_revoke_and_restore_secondary_passkey(self):
        owner = User.objects.create_superuser(
            username='passkey-revoker-owner', email='passkey-revoker@example.test', password='TestPassword123!',
        )
        primary_key = AdminPasskey.objects.create(
            user=owner, credential_id='cHJpbWFyeS1wYXNza2V5', public_key=b'primary-key', name='Teléfono principal',
        )
        secondary_key = AdminPasskey.objects.create(
            user=owner, credential_id='c2Vjb25kYXJ5LXBhc3NrZXk', public_key=b'secondary-key', name='Tableta compartida',
        )
        config, _ = AdminSecurityConfig.objects.get_or_create(pk=1)
        config.owner_user = owner
        config.primary_passkey = primary_key
        config.save(update_fields=['owner_user', 'primary_passkey', 'updated_at'])
        self.client.force_login(owner)
        session = self.client.session
        session['admin_current_passkey_id'] = primary_key.pk
        session.save()

        response = self.client.post(reverse('admin_security_devices'), {
            'action': 'revoke_passkey', 'passkey_id': secondary_key.pk,
        })
        self.assertEqual(response.status_code, 302)
        secondary_key.refresh_from_db()
        primary_key.refresh_from_db()
        self.assertFalse(secondary_key.is_active)
        self.assertTrue(primary_key.is_active)

        response = self.client.post(reverse('admin_security_devices'), {
            'action': 'restore_passkey', 'passkey_id': secondary_key.pk,
        })
        self.assertEqual(response.status_code, 302)
        secondary_key.refresh_from_db()
        self.assertTrue(secondary_key.is_active)
        self.assertTrue(AuditLog.objects.filter(action='ADMIN_PASSKEY_RESTORED_BY_OWNER').exists())

    def test_revoked_passkey_is_not_offered_for_administrative_login(self):
        staff = User.objects.create_user(
            username='revoked-passkey-admin', email='revoked-passkey@example.test',
            password='TestPassword123!', is_staff=True,
        )
        AdminPasskey.objects.create(
            user=staff, credential_id='cmV2b2tlZC1wYXNza2V5', public_key=b'revoked-key', is_active=False,
        )

        response = self.client.post(
            reverse('admin_passkey_login_options'),
            data=json.dumps({'username': staff.username}),
            content_type='application/json', HTTP_HOST='localhost', secure=True,
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()['error'], 'No hay llaves de acceso registradas para esta cuenta.')

    def test_staff_panel_renders_mobile_menu_install_push_and_passkey_controls(self):
        staff = User.objects.create_superuser(
            username='pwa-render-admin', email='pwa-render-admin@example.test', password='TestPassword123!',
        )
        security_config, _ = AdminSecurityConfig.objects.get_or_create(pk=1)
        security_config.owner_user = staff
        security_config.save(update_fields=['owner_user', 'primary_passkey', 'updated_at'])
        self.client.force_login(staff)

        response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="admin-sidebar-toggle"')
        self.assertContains(response, 'id="admin-ecommerce-link"')
        self.assertNotContains(response, 'class="quiet-action ecommerce-action"')
        self.assertNotContains(response, 'class="label">E-commerce</span>')
        self.assertContains(response, 'css/admin-theme.css')
        self.assertContains(response, 'id="admin-theme-toggle"')
        self.assertContains(response, 'id="admin-auth-identity"')
        self.assertContains(response, f'data-dashboard-url="{reverse("dashboard")}"')
        self.assertContains(response, 'id="admin-session-dialog"')
        self.assertContains(response, 'id="admin-session-continue"')
        self.assertContains(response, 'id="admin-session-close"')
        self.assertContains(response, 'id="admin-ecommerce-link"')
        self.assertNotContains(response, 'class="quiet-action ecommerce-action"')
        self.assertContains(response, 'id="admin-install-app"')
        self.assertContains(response, 'id="admin-enable-push"')
        self.assertContains(response, 'id="admin-register-passkey"')
        self.assertContains(response, 'id="admin-revoke-passkeys"')
        self.assertContains(response, 'class="dashboard-quick-actions"')
        self.assertContains(response, 'action-security')
        self.assertNotContains(response, 'action-audit')

    def test_audit_is_superuser_only_and_standard_admin_does_not_see_link(self):
        staff = User.objects.create_user(
            username='standard-audit-admin', password='TestPassword123!', is_staff=True,
        )
        self.client.force_login(staff)

        dashboard_response = self.client.get(reverse('dashboard'))
        audit_response = self.client.get(reverse('auditoria_completa'))
        export_response = self.client.get(reverse('descargar_auditoria_csv'))

        self.assertEqual(dashboard_response.status_code, 200)
        self.assertNotContains(dashboard_response, 'action-audit')
        self.assertNotContains(dashboard_response, 'Actividad del sistema')
        self.assertNotContains(dashboard_response, 'Registro reciente')
        self.assertNotContains(dashboard_response, 'audit-chart-data')
        self.assertEqual(audit_response.status_code, 403)
        self.assertEqual(export_response.status_code, 403)

        owner = User.objects.create_superuser(
            username='audit-owner', email='audit-owner@example.test', password='TestPassword123!',
        )
        security_config, _ = AdminSecurityConfig.objects.get_or_create(pk=1)
        security_config.owner_user = owner
        owner_passkey = AdminPasskey.objects.create(
            user=owner, credential_id='YXVkaXQtb3duZXIta2V5', public_key=b'audit-owner-key', name='Teléfono titular',
        )
        security_config.primary_passkey = owner_passkey
        security_config.save(update_fields=['owner_user', 'primary_passkey', 'updated_at'])
        self.client.force_login(owner)
        session = self.client.session
        session['admin_current_passkey_id'] = owner_passkey.pk
        session.save()
        AuditLog.objects.create(
            user=owner,
            action='ADMIN_PASSKEY_LOGIN',
            model_name='AdminAuth',
            details='Acceso de prueba',
            ip_address='203.0.113.18',
            user_agent='Android · Chrome móvil',
        )
        owner_dashboard = self.client.get(reverse('dashboard'))
        self.assertContains(owner_dashboard, 'Actividad del sistema')
        self.assertContains(owner_dashboard, 'Registro reciente')
        self.assertContains(owner_dashboard, 'audit-chart-data')
        audit_page = self.client.get(reverse('auditoria_completa'))
        self.assertEqual(audit_page.status_code, 200)
        self.assertContains(audit_page, 'audit-mobile-list')
        self.assertContains(audit_page, 'audit-event-device')
        self.assertContains(audit_page, 'data-label="Usuario"')
        self.assertContains(audit_page, 'data-label="Acción"')
        self.assertContains(audit_page, 'data-label="Detalles"')
        self.assertContains(audit_page, 'data-label="IP"')
        self.assertContains(audit_page, 'data-label="Dispositivo"')
        self.assertContains(audit_page, 'Android · Chrome móvil')
        self.assertEqual(audit_page.content.decode().count('<td class="td-useragent audit-device-cell"'), 1)
        self.assertEqual(self.client.get(reverse('descargar_auditoria_csv')).status_code, 200)

    def test_security_owner_can_designate_only_its_own_primary_passkey(self):
        owner = User.objects.create_superuser(
            username='primary-device-owner', email='primary-device@example.test', password='TestPassword123!',
        )
        another_admin = User.objects.create_user(
            username='other-device-admin', password='TestPassword123!', is_staff=True,
        )
        owner_passkey = AdminPasskey.objects.create(
            user=owner, credential_id='b3duZXIta2V5', public_key=b'owner-key', name='Teléfono principal',
        )
        other_passkey = AdminPasskey.objects.create(
            user=another_admin, credential_id='b3RoZXIta2V5', public_key=b'other-key', name='Otra llave',
        )
        config, _ = AdminSecurityConfig.objects.get_or_create(pk=1)
        config.owner_user = owner
        config.save(update_fields=['owner_user', 'updated_at'])
        self.client.force_login(owner)
        session = self.client.session
        session['admin_current_passkey_id'] = owner_passkey.pk
        session.save()

        response = self.client.post(reverse('admin_security_devices'), {
            'action': 'set_primary',
            'passkey_id': other_passkey.pk,
        })
        self.assertEqual(response.status_code, 404)
        self.assertIsNone(AdminSecurityConfig.objects.get(pk=1).primary_passkey_id)

        response = self.client.post(reverse('admin_security_devices'), {
            'action': 'set_primary',
            'passkey_id': owner_passkey.pk,
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(AdminSecurityConfig.objects.get(pk=1).primary_passkey_id, owner_passkey.pk)

        session = self.client.session
        session['admin_current_passkey_id'] = owner_passkey.pk
        session.save()
        AdminDeviceSession.objects.create(
            user=another_admin,
            passkey=other_passkey,
            session_key='secondary-device-session-test-0001',
            ip_address='203.0.113.25',
            user_agent='Secondary device test',
            last_seen_at=timezone.now(),
            is_active=True,
        )
        security_page = self.client.get(reverse('admin_security_devices'))
        self.assertEqual(security_page.status_code, 200)
        self.assertContains(security_page, 'security-page-heading')
        self.assertContains(security_page, 'security-mobile-list')
        self.assertContains(security_page, 'Revocar sesión')
        self.assertEqual(self.client.get(reverse('auditoria_completa')).status_code, 200)

    def test_security_owner_can_transfer_superuser_role_to_another_admin(self):
        current_owner = User.objects.create_superuser(
            username='current-security-owner', email='current-security-owner@example.test', password='TestPassword123!',
        )
        next_owner = User.objects.create_user(
            username='next-security-owner', email='next-security-owner@example.test',
            password='TestPassword123!', is_staff=True,
        )
        primary_key = AdminPasskey.objects.create(
            user=current_owner, credential_id='Y3VycmVudC1vd25lcg', public_key=b'current-key',
        )
        config, _ = AdminSecurityConfig.objects.get_or_create(pk=1)
        config.owner_user = current_owner
        config.primary_passkey = primary_key
        config.save(update_fields=['owner_user', 'primary_passkey', 'updated_at'])
        session = self.client.session
        session['_auth_user_id'] = str(current_owner.pk)
        session['_auth_user_backend'] = 'django.contrib.auth.backends.ModelBackend'
        session['_auth_user_hash'] = current_owner.get_session_auth_hash()
        session['admin_current_passkey_id'] = primary_key.pk
        session.save()

        response = self.client.post(reverse('admin_security_devices'), {
            'action': 'transfer_owner',
            'user_id': next_owner.pk,
        })

        current_owner.refresh_from_db()
        next_owner.refresh_from_db()
        config.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertFalse(current_owner.is_superuser)
        self.assertTrue(current_owner.is_staff)
        self.assertTrue(next_owner.is_superuser)
        self.assertEqual(config.owner_user_id, next_owner.pk)
        self.assertIsNone(config.primary_passkey_id)
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertFalse(AdminDeviceSession.objects.filter(user=current_owner, is_active=True).exists())
        self.assertTrue(AuditLog.objects.filter(action='ADMIN_SECURITY_OWNER_TRANSFER').exists())

    def test_non_staff_cannot_save_push_subscription(self):
        customer = User.objects.create_user(
            username='pwa-customer', email='pwa-customer@example.test', password='TestPassword123!',
        )
        self.client.force_login(customer)

        response = self.client.post(
            reverse('admin_push_subscribe'),
            data=json.dumps({
                'endpoint': 'https://push.example.test/subscription/1',
                'keys': {'p256dh': 'public', 'auth': 'secret'},
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 302)

    @override_settings(
        ADMIN_WEBPUSH_VAPID_PUBLIC_KEY='public-key',
        ADMIN_WEBPUSH_VAPID_PRIVATE_KEY='private-key',
    )
    def test_staff_can_register_push_subscription(self):
        from .models import AdminPushSubscription

        staff = User.objects.create_user(
            username='pwa-admin', email='pwa-admin@example.test', password='TestPassword123!', is_staff=True,
        )
        self.client.force_login(staff)

        response = self.client.post(
            reverse('admin_push_subscribe'),
            data=json.dumps({
                'endpoint': 'https://push.example.test/subscription/1',
                'keys': {'p256dh': 'public', 'auth': 'secret'},
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        subscription = AdminPushSubscription.objects.get(user=staff)
        self.assertEqual(subscription.subscription['keys']['p256dh'], 'public')

    def test_passkey_login_options_do_not_expose_unregistered_credentials(self):
        response = self.client.post(
            reverse('admin_passkey_login_options'),
            data='{}',
            content_type='application/json',
            HTTP_HOST='localhost',
            secure=True,
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error'], 'Escribe tu usuario o correo para usar la llave de acceso.')

    def test_passkey_login_options_only_return_the_selected_admin_key(self):
        from .models import AdminPasskey

        selected_admin = User.objects.create_user(
            username='selected-passkey-admin', email='selected-passkey@example.test',
            password='TestPassword123!', is_staff=True,
        )
        other_admin = User.objects.create_user(
            username='other-passkey-admin', email='other-passkey@example.test',
            password='TestPassword123!', is_staff=True,
        )
        AdminPasskey.objects.create(user=selected_admin, credential_id='YWJj', public_key=b'selected')
        AdminPasskey.objects.create(user=other_admin, credential_id='ZGVm', public_key=b'other')

        response = self.client.post(
            reverse('admin_passkey_login_options'),
            data=json.dumps({'username': selected_admin.username}),
            content_type='application/json',
            HTTP_HOST='localhost',
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['allowCredentials'][0]['id'], 'YWJj')
        self.assertEqual(len(response.json()['allowCredentials']), 1)

    def test_admin_recovery_requires_registered_passkey_before_sending_email_code(self):
        from .models import AdminPasskey

        staff = User.objects.create_user(
            username='recovery-passkey-admin', email='recovery-passkey@example.test',
            password='TestPassword123!', is_staff=True,
        )
        AdminPasskey.objects.create(user=staff, credential_id='YWJj', public_key=b'recovery-key')

        response = self.client.post(
            reverse('solicitar_recuperacion_admin'),
            {'email': staff.email},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Verifica la huella registrada en esta cuenta')
        self.assertNotIn('recupera_codigo_hash', self.client.session)

    def test_admin_recovery_cannot_skip_missing_passkey(self):
        staff = User.objects.create_user(
            username='recovery-no-passkey-admin', email='recovery-no-passkey@example.test',
            password='TestPassword123!', is_staff=True,
        )

        response = self.client.post(
            reverse('solicitar_recuperacion_admin'),
            {'email': staff.email},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'no tiene una huella registrada')
        self.assertNotIn('recupera_codigo_hash', self.client.session)

    def test_recovery_passkey_options_are_bound_to_the_account(self):
        from .models import AdminPasskey

        staff = User.objects.create_user(
            username='recovery-options-admin', email='recovery-options@example.test',
            password='TestPassword123!', is_staff=True,
        )
        AdminPasskey.objects.create(user=staff, credential_id='YWJj', public_key=b'recovery-key')

        response = self.client.post(
            reverse('admin_recovery_passkey_options'),
            data=json.dumps({'email': staff.email}),
            content_type='application/json',
            HTTP_HOST='localhost',
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['allowCredentials'][0]['id'], 'YWJj')
        self.assertEqual(self.client.session['admin_recovery_passkey_challenge']['user_id'], staff.pk)

    def test_staff_gets_passkey_registration_options_for_https_origin(self):
        staff = User.objects.create_user(
            username='passkey-admin', email='passkey-admin@example.test',
            password='TestPassword123!', is_staff=True,
        )
        self.client.force_login(staff)

        response = self.client.post(
            reverse('admin_passkey_registration_options'),
            data='{}',
            content_type='application/json',
            HTTP_HOST='localhost',
            secure=True,
        )

        self.assertEqual(response.status_code, 200)
        options = response.json()
        self.assertIn('challenge', options)
        self.assertEqual(options['rp']['id'], 'localhost')
        self.assertEqual(options['authenticatorSelection']['residentKey'], 'required')

    def test_login_keeps_fingerprint_button_for_mobile_only(self):
        response = self.client.get(reverse('login_admin_custom'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'autocomplete="username webauthn"')
        self.assertContains(response, 'id="admin-passkey-login"')
        self.assertNotContains(response, 'admin-passkey-key-login')
        self.assertContains(response, 'Iniciar con huella')
        self.assertContains(response, 'viewBox="0 0 32 32"')
        self.assertNotContains(response, 'fingerprint</span>')
        self.assertNotContains(response, 'class="auth-brand"')
        self.assertNotContains(response, 'class="auth-subtitle"')

    @override_settings(
        ADMIN_WEBPUSH_VAPID_PUBLIC_KEY='public-key',
        ADMIN_WEBPUSH_VAPID_PRIVATE_KEY='private-key',
        ADMIN_WEBPUSH_VAPID_CONTACT='mailto:admin@example.test',
    )
    def test_new_order_push_only_targets_active_staff_subscriptions(self):
        from .models import AdminPushSubscription
        from .tasks import notify_admin_order_created

        customer = User.objects.create_user(
            username='push-order-customer', email='push-order-customer@example.test', password='TestPassword123!',
        )
        staff = User.objects.create_user(
            username='push-order-admin', email='push-order-admin@example.test', password='TestPassword123!', is_staff=True,
        )
        order = Pedido.objects.create(cliente=customer, total=Decimal('25.00'))
        AdminPushSubscription.objects.create(
            user=staff,
            endpoint_hash='f' * 64,
            endpoint='https://push.example.test/subscription/2',
            subscription={
                'endpoint': 'https://push.example.test/subscription/2',
                'keys': {'p256dh': 'public', 'auth': 'secret'},
            },
        )

        with patch('pywebpush.webpush') as send_push:
            result = notify_admin_order_created.run(order.pk)

        self.assertEqual(result['sent'], 1)
        payload = json.loads(send_push.call_args.kwargs['data'])
        self.assertEqual(payload['title'], f'Nuevo pedido #{order.pk}')
        self.assertEqual(payload['url'], reverse('detalle_pedido_admin', args=[order.pk]))


class AdminLoginResponsivePresentationTest(TestCase):
    def test_mobile_login_promotes_typewriter_and_removes_duplicate_badge(self):
        response = self.client.get(reverse('login_admin_custom'))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, reverse('cliente_registro'))
        self.assertContains(response, reverse('recuperar_admin'))
        self.assertContains(response, '.hero-badge, .hero-logo, .hero-features, .hero-footer { display: none; }')
        self.assertContains(response, 'html, body { height: auto; min-height: 100%; overflow-x: hidden; overflow-y: auto; }')
        self.assertContains(response, 'class="hero-title-line full rotating-line"')


class CreditsGalleryTest(TestCase):
    def test_credits_page_renders_full_gallery_and_profile_dialog(self):
        staff = User.objects.create_user(
            username='credits-gallery-staff',
            password='StrongTestPass123!',
            is_staff=True,
        )
        self.client.force_login(staff)

        response = self.client.get(reverse('admin_creditos'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Equipo del proyecto')
        self.assertNotContains(response, 'Chips of Glassart')
        self.assertContains(response, 'credits-gallery')
        self.assertContains(response, 'class="credits-shard"', count=3)
        self.assertContains(response, 'class="credits-card-open"', count=3)
        self.assertContains(response, 'Presiona aquí para ver la ficha', count=3)
        self.assertContains(response, 'class="credits-photo-control"', count=3)
        self.assertContains(response, 'class="credits-report-control"', count=3)
        self.assertContains(response, reverse('creditos_reporte_pdf'))
        self.assertContains(response, 'id="creditDetailReport"')
        self.assertContains(response, 'id="creditDetailContributions"')
        self.assertContains(response, 'data-project-role="Diseño de interfaces y experiencia de usuario"')
        self.assertContains(response, 'id="creditDetailProjectRole"')
        self.assertContains(response, 'id="creditReportForm"')
        self.assertContains(response, 'data-photo-input="gregory"')
        self.assertContains(response, 'color: #f4f7fa !important')
        self.assertContains(response, '#main-content .credits-page .credits-card-controls {')
        self.assertContains(response, 'background-color: transparent !important;')
        self.assertContains(response, 'background-color: rgba(7,18,32,.94) !important; background-image: none !important;')
        self.assertContains(response, 'credit-dialog-visual')
        self.assertContains(response, 'credit-dialog-content')
        self.assertContains(response, 'transform: translate(-50%, -50%)')
        self.assertContains(response, 'creditDetailDialog')
        self.assertContains(response, 'Yulimar Cabeza')
        self.assertContains(response, 'Gregory Gómez')
        self.assertContains(response, 'Yeferson Ramírez')

    def test_credit_reports_are_pdf_files_and_require_staff_access(self):
        staff = User.objects.create_user(username='credit-report-staff', password='StrongTestPass123!', is_staff=True)
        self.client.force_login(staff)

        group_report = self.client.get(reverse('creditos_reporte_pdf'))
        individual_report = self.client.get(reverse('credito_individual_pdf', args=['gregory-gomez']))
        missing_report = self.client.get(reverse('credito_individual_pdf', args=['unknown-person']))

        self.assertEqual(group_report.status_code, 200)
        self.assertEqual(group_report['Content-Type'], 'application/pdf')
        self.assertIn(b'%PDF-', group_report.content[:10])
        self.assertIn('informe-grupal', group_report['Content-Disposition'])
        self.assertEqual(individual_report.status_code, 200)
        self.assertEqual(individual_report['Content-Type'], 'application/pdf')
        self.assertIn(b'%PDF-', individual_report.content[:10])
        self.assertIn('gregory-gomez', individual_report['Content-Disposition'])
        self.assertEqual(missing_report.status_code, 404)

        self.client.logout()
        anonymous_report = self.client.get(reverse('creditos_reporte_pdf'))
        self.assertEqual(anonymous_report.status_code, 302)

    def test_group_report_is_one_page_and_individual_report_embeds_browser_photo(self):
        staff = User.objects.create_user(username='credit-photo-staff', password='StrongTestPass123!', is_staff=True)
        self.client.force_login(staff)
        image_buffer = BytesIO()
        Image.new('RGB', (24, 32), color='#2878b8').save(image_buffer, format='JPEG')
        photo_data = 'data:image/jpeg;base64,' + base64.b64encode(image_buffer.getvalue()).decode('ascii')

        group_report = self.client.post(
            reverse('creditos_reporte_pdf'),
            {'photos_json': json.dumps({'gregory-gomez': photo_data})},
        )
        individual_report = self.client.post(
            reverse('credito_individual_pdf', args=['gregory-gomez']),
            {'photos_json': json.dumps({'gregory-gomez': photo_data})},
        )

        self.assertEqual(group_report.status_code, 200)
        self.assertIn(b'/Count 1', group_report.content)
        self.assertIn(b'/Subtype /Image', group_report.content)
        self.assertEqual(individual_report.status_code, 200)
        self.assertIn(b'/Subtype /Image', individual_report.content)


class SeguridadTest(TestCase):
    def setUp(self):
        cache.clear()

    def test_login_legacy_abre_el_login_de_cliente(self):
        response = self.client.get('/login/')

        self.assertRedirects(response, reverse('login_cliente'))

    def test_login_generico_de_django_no_expone_formulario_admin(self):
        response = self.client.get('/accounts/login/')

        self.assertRedirects(response, reverse('login_cliente'))

    def test_login_cliente_no_muestra_google_one_tap(self):
        response = self.client.get(reverse('login_cliente'), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'g_id_onload')

    def test_google_one_tap_solo_aparece_en_el_hero(self):
        home = self.client.get(reverse('index'), secure=True, HTTP_HOST='localhost')
        catalog = self.client.get(
            f"{reverse('productos')}?vista=catalogo",
            secure=True,
            HTTP_HOST='localhost',
        )

        self.assertEqual(home.status_code, 200)
        self.assertContains(home, 'https://accounts.google.com/gsi/client')
        self.assertContains(home, 'data-auto_prompt="true"')
        self.assertContains(home, 'data-callback="handleCustomerGoogleCredential"')
        self.assertNotContains(home, 'class="g_id_signin"')
        self.assertContains(home, 'google-login-feedback')
        self.assertNotContains(home, 'landing-google-button')
        self.assertContains(home, 'Esta cuenta tiene acceso administrativo.')
        self.assertContains(home, reverse('google_auth_api'))
        self.assertEqual(catalog.status_code, 200)
        self.assertNotContains(catalog, 'g_id_onload')

    def test_google_one_tap_rate_limit_devuelve_json(self):
        with patch('django_ratelimit.decorators.is_ratelimited', return_value=True):
            response = self.client.post(
                reverse('google_auth_api'),
                data='{}',
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()['error'], 'rate_limited')

    def test_google_one_tap_autentica_cliente_no_administrador(self):
        customer = Customer.objects.create(
            nombre='Cliente Google',
            email='google-regular-client@example.com',
            password='GoogleClientTest123!',
        )
        cliente = customer.ensure_cliente_profile()
        verified_payload = {
            'aud': settings.GOOGLE_CLIENT_ID,
            'iss': 'https://accounts.google.com',
            'email_verified': True,
            'email': customer.email,
            'given_name': 'Google Client',
            'family_name': 'Google',
        }

        csrf_client = Client(enforce_csrf_checks=True)
        with patch('dashboard.views.id_token.verify_oauth2_token', return_value=verified_payload):
            response = csrf_client.post(
                reverse('google_auth_api'),
                data=json.dumps({'credential': 'verified-test-token', 'next': '/carrito/'}),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'success')
        user = User.objects.get(email__iexact=customer.email)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertEqual(csrf_client.session['_auth_user_id'], str(user.pk))
        self.assertEqual(csrf_client.session['cliente_id'], cliente.pk)
        cliente.refresh_from_db()
        self.assertEqual(cliente.user_id, user.pk)
        customer.refresh_from_db()
        self.assertEqual(customer.cliente_id, cliente.pk)

    @override_settings(DEBUG=False)
    def test_login_admin_directo_en_produccion(self):
        admin_user = User.objects.create_user(
            username='admin-prod-login',
            email='admin-prod-login@test.com',
            password='Admin123!',
            is_staff=True,
            is_superuser=True,
        )

        response = self.client.get(reverse('login_admin_custom'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'adminLoginCountdown')
        post_response = self.client.post(
            reverse('login_admin_custom'),
            {'username': admin_user.username, 'password': 'Admin123!'},
        )
        self.assertRedirects(post_response, reverse('dashboard'))

    @override_settings(DEBUG=True)
    def test_login_admin_es_directo_en_desarrollo_y_no_renderiza_modal(self):
        admin_user = User.objects.create_user(
            username='admin-dev-login',
            email='admin-dev-login@test.com',
            password='Admin123!',
            is_staff=True,
        )

        login_page = self.client.get(reverse('login_admin_custom'))
        store_page = self.client.get(reverse('index'))
        login_response = self.client.post(
            reverse('login_admin_custom'),
            {'username': admin_user.username, 'password': 'Admin123!'},
        )
        unlock_response = self.client.post(
            reverse('admin_login_unlock'),
            {'action': 'start'},
        )

        self.assertEqual(login_page.status_code, 200)
        self.assertNotContains(login_page, 'adminLoginCountdown')
        self.assertNotContains(store_page, 'id="adminGate"')
        self.assertRedirects(login_response, reverse('dashboard'))
        self.assertEqual(unlock_response.status_code, 404)

    @override_settings(DEBUG=False)
    def test_credenciales_de_cliente_no_desbloquean_login_admin(self):
        User.objects.create_user(
            username='cliente-no-admin',
            email='cliente-no-admin@test.com',
            password='Cliente123!',
        )

        response = self.client.post(
            reverse('admin_login_unlock'),
            {'password': 'Cliente123!'},
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.json()['ok'])

    @override_settings(BINANCE_SECRET_KEY='webhook-test-secret')
    def test_webhook_binance_no_acepta_firma_en_query_string(self):
        payload = b'{}'
        signature = hmac.new(
            b'webhook-test-secret', payload, hashlib.sha256
        ).hexdigest()

        query_response = self.client.post(
            f"{reverse('binance_webhook')}?signature={signature}",
            data=payload,
            content_type='application/json',
        )
        header_response = self.client.post(
            reverse('binance_webhook'),
            data=payload,
            content_type='application/json',
            HTTP_X_BINANCEPAY_SIGNATURE=signature,
        )

        self.assertEqual(query_response.status_code, 403)
        self.assertEqual(header_response.status_code, 404)

    def test_dashboard_requiere_login(self):
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url,
            f"{reverse('login_admin_custom')}?next=%2Fadmin-panel%2Fdashboard%2F",
        )

    def test_backend_reconoce_admin_por_email_sin_request(self):
        user = User.objects.create_user(username='admin-email-test', email='admin-email@test.com', password='Admin123!')
        user.is_staff = True
        user.is_superuser = True
        user.save(update_fields=['is_staff', 'is_superuser'])

        authenticated = authenticate(username='admin-email@test.com', password='Admin123!')

        self.assertIsNotNone(authenticated)
        self.assertTrue(authenticated.is_staff)
        self.assertTrue(authenticated.is_superuser)

    @override_settings(DEBUG=False)
    def test_admin_login_redirige_al_dashboard(self):
        user = User.objects.create_user(username='admin-test', email='admin@test.com', password='Admin123!')
        user.is_staff = True
        user.is_superuser = True
        user.save(update_fields=['is_staff', 'is_superuser'])

        client = Client(HTTP_HOST='localhost')
        challenge_response = client.post(
            reverse('admin_login_unlock'),
            {'action': 'start'},
        )
        self.assertEqual(challenge_response.status_code, 200)
        challenge = challenge_response.json()
        self.assertGreater(challenge['expires_at'], time.time())
        unlock_response = client.post(
            reverse('admin_login_unlock'),
            {
                'action': 'verify',
                'challenge': challenge['challenge'],
                'password': 'Admin123!',
            },
        )
        self.assertEqual(unlock_response.status_code, 200)
        self.assertTrue(unlock_response.json()['ok'])
        self.assertGreater(unlock_response.json()['login_expires_at'], time.time())

        response = client.post(
            reverse('login_admin_custom'),
            {'username': 'admin-test', 'password': 'Admin123!'},
            follow=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('dashboard'))

    @override_settings(DEBUG=False)
    def test_tres_claves_incorrectas_bloquean_solo_la_sesion_que_falla(self):
        User.objects.create_user(
            username='admin-lockout-test',
            email='admin-lockout@test.com',
            password='Admin123!',
            is_staff=True,
        )
        client = Client(HTTP_HOST='localhost')

        for attempt in range(3):
            challenge = client.post(
                reverse('admin_login_unlock'), {'action': 'start'}
            ).json()
            response = client.post(
                reverse('admin_login_unlock'),
                {
                    'action': 'verify',
                    'challenge': challenge['challenge'],
                    'password': 'Incorrecta123!',
                },
            )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()['attempts_remaining'], 0)
        blocked = client.post(reverse('admin_login_unlock'), {'action': 'start'})
        self.assertEqual(blocked.status_code, 429)
        another_session = Client(HTTP_HOST='localhost')
        available_again = another_session.post(
            reverse('admin_login_unlock'), {'action': 'start'}
        )
        self.assertEqual(available_again.status_code, 200)
        self.assertTrue(available_again.json()['ok'])

    @override_settings(DEBUG=False)
    def test_desafio_admin_vencido_consume_un_intento(self):
        session = self.client.session
        session['admin_login_challenge'] = {
            'token': 'expired-challenge',
            'expires_at': time.time() - 1,
        }
        session.save()

        response = self.client.post(
            reverse('admin_login_unlock'),
            {'action': 'start'},
        )

        self.assertEqual(response.status_code, 408)
        self.assertEqual(response.json()['attempts_used'], 1)
        self.assertGreater(response.json()['expires_at'], time.time())

    @override_settings(
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
        EMAIL_HOST_USER='tests@example.com',
    )
    def test_recuperacion_admin_usa_otp_corto_hasheado_y_valida_nueva_clave(self):
        from .models import AdminPasskey

        user = User.objects.create_user(
            username='admin-recovery-test',
            email='admin-recovery@test.com',
            password='OldAdmin123!',
            is_staff=True,
        )
        AdminPasskey.objects.create(user=user, credential_id='cmVjb3Zlcnk', public_key=b'test-key')
        session = self.client.session
        session['admin_recovery_passkey_authorization'] = {
            'user_id': user.pk,
            'expires_at': time.time() + 60,
        }
        session.save()
        with patch('dashboard.views.get_random_string', return_value='87654321'):
            response = self.client.post(
                reverse('solicitar_recuperacion_admin'),
                {'email': user.email},
            )

        self.assertRedirects(response, reverse('recuperar_codigo_admin'))
        session = self.client.session
        self.assertIn('recupera_codigo_hash', session)
        self.assertNotIn('recupera_codigo', session)
        self.assertGreater(session['recupera_expira_en'], time.time())

        verification_page = self.client.get(reverse('recuperar_codigo_admin'))
        self.assertContains(verification_page, 'Código enviado al correo')
        self.assertContains(verification_page, 'ad**********ry@test.com')

        response = self.client.post(
            reverse('recuperar_codigo_admin'),
            {
                'codigo': '87654321',
                'new_password1': 'NewSecureP@ssw0rd#2026',
                'new_password2': 'NewSecureP@ssw0rd#2026',
            },
        )

        self.assertRedirects(response, reverse('login_admin_custom'))
        user.refresh_from_db()
        self.assertTrue(user.check_password('NewSecureP@ssw0rd#2026'))
        self.assertGreater(self.client.session['admin_login_unlocked_until'], time.time())

    def test_codigo_de_recuperacion_vencido_no_se_acepta(self):
        session = self.client.session
        session['recupera_scope'] = 'admin'
        session['recupera_email'] = 'admin-expired@test.com'
        session['recupera_codigo_hash'] = 'unused'
        session['recupera_expira_en'] = time.time() - 1
        session.save()

        response = self.client.post(
            reverse('recuperar_codigo_admin'),
            {
                'codigo': '12345678',
                'new_password1': 'NewSecureP@ssw0rd#2026',
                'new_password2': 'NewSecureP@ssw0rd#2026',
            },
        )

        self.assertContains(response, 'El código venció o ya no es válido.')
        self.assertNotIn('recupera_codigo_hash', self.client.session)

    def test_login_admin_no_depende_del_desbloqueo_temporal(self):
        session = self.client.session
        session['admin_login_unlocked_until'] = time.time() - 1
        session.save()

        response = self.client.get(reverse('login_admin_custom'))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'adminLoginCountdown')

    def test_staff_no_va_al_admin_desde_vista_cliente(self):
        user = User.objects.create_user(username='staff-client-view', email='staff-client-view@test.com', password='Admin123!')
        user.is_staff = True
        user.is_superuser = False
        user.save(update_fields=['is_staff', 'is_superuser'])

        client = Client(HTTP_HOST='localhost')
        client.force_login(user)

        response = client.get(reverse('perfil_cliente'))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('dashboard'))
        self.assertNotIn('/admin/', response.url)

    def test_perfil_cliente_redirige_a_checkout_cuando_viene_del_carrito(self):
        user = User.objects.create_user(username='cliente-checkout-redir', email='cliente-checkout-redir@test.com', password='Cliente123!')
        user.is_staff = False
        user.is_superuser = False
        user.save(update_fields=['is_staff', 'is_superuser'])

        Cliente.objects.create(user=user, nombre='Cliente', email=user.email)
        PerfilCliente.objects.create(user=user, cedula_rif='', telefono='', direccion='')

        client = Client(HTTP_HOST='localhost')
        client.force_login(user)

        response = client.post(
            reverse('perfil_cliente'),
            {'nombre': 'Cliente', 'apellido': 'Prueba', 'cedula_rif': 'V12345678', 'telefono': '04141234567', 'direccion': 'Calle prueba', 'email': user.email, 'next': reverse('checkout')},
            follow=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('checkout'))

    def test_backend_acepta_staff_en_ruta_admin_default(self):
        user = User.objects.create_user(username='admin-default-path', email='admin-default@local.com', password='Admin123!')
        user.is_staff = True
        user.is_superuser = True
        user.save(update_fields=['is_staff', 'is_superuser'])

        request = type('Request', (), {'path': '/admin/login/'})()
        authenticated = authenticate(request=request, username='admin-default-path', password='Admin123!')

        self.assertIsNotNone(authenticated)
        self.assertTrue(authenticated.is_staff)
        self.assertTrue(authenticated.is_superuser)


class PagoModelTest(TestCase):
    def test_pago_guarda_metodo_en_formato_estandar(self):
        user = User.objects.create_user(username='cliente-test', email='cliente@test.com', password='testpass123')
        pedido = Pedido.objects.create(cliente=user, total=125.50, estado='pendiente')

        pago = Pago.objects.create(
            pedido=pedido,
            metodo='stripe',
            monto=125.50,
            referencia='REF-001',
            verificado=False,
        )

        self.assertEqual(pago.metodo, 'STRIPE')
        self.assertFalse(pago.verificado)
        self.assertEqual(pago.pedido, pedido)


class CarritoPresentationTest(TestCase):
    def test_agregar_al_carrito_con_presentacion_valida(self):
        producto = Productos.objects.create(
            Codigo='A0002',
            Descripcion='Producto de prueba',
            Precio=100,
            Cantidad=1,
            presentations=[{'type': 'Caja', 'factor': 12, 'unit': 'Unidades'}],
        )

        response = self.client.post(
            reverse('agregar_al_carrito', args=[producto.Codigo]),
            {
                'cantidad': '1',
                'presentation_factor': '12',
                'presentation_type': 'Caja',
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.assertEqual(self.client.session['anon_cart'][producto.Codigo], 1)


class FerreBotCatalogSearchTest(TestCase):
    def test_assistant_reply_does_not_start_with_repeated_acknowledgement(self):
        self.assertEqual(_clean_assistant_reply('Entendido. Te recomiendo este producto.'), 'Te recomiendo este producto.')

    def test_catalog_search_api_returns_current_product_details(self):
        category = Categoria.objects.create(name='Domótica para búsqueda')
        product = Productos.objects.create(
            Codigo='A9885',
            Descripcion='Sensor de movimiento inteligente',
            Precio=Decimal('31.40'),
            Cantidad=7,
            Categoria=category,
        )

        response = self.client.get(reverse('catalog_search_api'), {'q': 'sensor movimiento'})

        self.assertEqual(response.status_code, 200)
        result = response.json()['results'][0]
        self.assertEqual(result['code'], product.Codigo)
        self.assertEqual(result['name'], product.Descripcion)
        self.assertEqual(result['category'], category.name)
        self.assertEqual(result['price'], '31.40')
        self.assertEqual(result['stock'], 7)
        self.assertEqual(result['url'], reverse('producto_detalle', args=[product.Codigo]))

    def test_purchase_guide_in_cart_returns_next_action_for_footer_button(self):
        response, action = build_assistant_reply(
            'Ayúdame con el paso a paso para realizar la compra',
            [],
            {'path': '/carrito/', 'cart_count': 2},
        )

        self.assertIn('Paso 2 de 4', response)
        self.assertIn('Listo, siguiente', response)
        self.assertEqual(action['type'], 'guide_next')

    def test_ready_button_from_cart_advances_to_checkout(self):
        response, action = build_assistant_reply(
            'Listo, siguiente',
            [],
            {'path': '/carrito/', 'cart_count': 2},
        )

        self.assertIn('Paso 2 de 4', response)
        self.assertEqual(action['target'], '/checkout/')

    def test_ready_button_from_product_advances_to_cart_when_item_exists(self):
        response, action = build_assistant_reply(
            'Listo, siguiente',
            [],
            {'path': '/producto/A0005/', 'cart_count': 1},
        )

        self.assertIn('Paso 2 de 4', response)
        self.assertEqual(action['type'], 'navigate_url')
        self.assertEqual(action['target'], '/carrito/')

    def test_ready_button_from_product_explains_empty_cart(self):
        Productos.objects.create(
            Codigo='A0005',
            Descripcion='Bombillo de prueba',
            Precio=Decimal('12.00'),
            Cantidad=5,
        )
        response, action = build_assistant_reply(
            'Listo, siguiente',
            [],
            {'path': '/producto/A0005/', 'cart_count': 0},
        )

        self.assertIn('agrega este producto al carrito', response)
        self.assertIsNone(action)

    def test_purchase_guide_returns_to_catalog_when_cart_is_empty(self):
        response, action = build_assistant_reply(
            '¿Cuál es el siguiente paso?',
            [],
            {'path': '/carrito/', 'cart_count': 0},
        )

        self.assertIn('carrito está vacío', response)
        self.assertEqual(action['target'], '/?vista=catalogo#productos-grid')

    def test_purchase_guide_explains_manual_payment_validation_at_checkout(self):
        response, action = build_assistant_reply(
            'Guíame paso a paso',
            [],
            {'path': '/checkout/'},
        )

        self.assertIn('pendiente de validación administrativa', response)
        self.assertIn('se reserva el stock', response)
        self.assertIsNone(action)

    def test_checkout_step_takes_priority_over_nonempty_cart(self):
        response, action = build_assistant_reply(
            '¿Cuál es el siguiente paso?',
            [],
            {'path': '/checkout/', 'cart_count': 2},
        )

        self.assertIn('Paso 3 de 4', response)
        self.assertIsNone(action)

    def test_purchase_guide_recognizes_customer_panel_after_order_submission(self):
        response, action = build_assistant_reply(
            '¿Cuál es el siguiente paso?',
            [],
            {'path': '/cliente/panel/'},
        )

        self.assertIn('Paso 4 de 4', response)
        self.assertEqual(action['target'], '/cliente/mis-pedidos/')

    def test_purchase_guide_does_not_restart_on_catalog_page(self):
        response, action = build_assistant_reply(
            '¿Cuál es el paso a paso para comprar?',
            [],
            {'path': '/', 'view': 'catalogo'},
        )

        self.assertIn('Paso 1 de 4', response)
        self.assertEqual(action['type'], 'guide_next')

    def test_purchase_guide_offers_next_button_in_catalog(self):
        response, action = build_assistant_reply(
            'Quiero que me guíes paso a paso para realizar una compra',
            [],
            {'path': '/', 'view': 'catalogo', 'cart_count': 0},
        )

        self.assertIn('Listo, siguiente', response)
        self.assertEqual(action['type'], 'guide_next')

    def test_new_purchase_guide_starts_at_catalog_with_existing_cart_items(self):
        response, action = build_assistant_reply(
            'Quiero que me guíes paso a paso para realizar una compra',
            [],
            {'path': '/', 'view': 'catalogo', 'cart_count': 2},
        )

        self.assertIn('Paso 1 de 4', response)
        self.assertIn('2 productos distintos', response)
        self.assertEqual(action['type'], 'guide_next')

    def test_new_purchase_guide_returns_to_catalog_from_cart_without_clearing_it(self):
        response, action = build_assistant_reply(
            'Quiero que me guíes paso a paso para realizar una compra',
            [],
            {'path': '/carrito/', 'cart_count': 2},
        )

        self.assertIn('Paso 1 de 4', response)
        self.assertIn('2 productos distintos', response)
        self.assertEqual(action['target'], '/?vista=catalogo#productos-grid')

    def test_step_two_command_advances_to_cart_in_catalog(self):
        response, action = build_assistant_reply(
            'paso dos',
            [],
            {'path': '/', 'view': 'catalogo', 'cart_count': 1},
        )

        self.assertIn('Paso 2 de 4', response)
        self.assertEqual(action['target'], '/carrito/')

    def test_ready_button_advances_to_cart_with_existing_items(self):
        response, action = build_assistant_reply(
            'Listo, siguiente',
            [],
            {'path': '/', 'view': 'catalogo', 'cart_count': 2},
        )

        self.assertIn('Paso 2 de 4', response)
        self.assertEqual(action['type'], 'navigate_url')
        self.assertEqual(action['target'], '/carrito/')

    def test_product_search_for_valve_is_not_treated_as_step_two(self):
        category = Categoria.objects.create(name='Llaves')
        product = Productos.objects.create(
            Codigo='A9884',
            Descripcion='Llave de paso 2 pulgadas',
            Precio=Decimal('12.00'),
            Cantidad=3,
            Categoria=category,
        )

        results = search_catalog('llave de paso 2 pulgadas')

        self.assertIn(product, results)

    def test_purchase_guide_advances_to_cart_when_product_is_already_added(self):
        response, action = build_assistant_reply(
            '¿Cuál es el siguiente paso?',
            [],
            {'path': '/producto/A0005/', 'cart_count': 1},
        )

        self.assertIn('Paso 2 de 4', response)
        self.assertEqual(action['target'], '/carrito/')

    def test_chat_endpoint_uses_current_page_for_purchase_guide(self):
        session = self.client.session
        session['anon_cart'] = {'A9888': 1}
        session.save()
        response = self.client.post(
            reverse('ai_chat_api'),
            json.dumps({
                'message': 'Guíame paso a paso para completar la compra',
                'page_context': {'path': '/carrito/'},
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('Paso 2 de 4', response.json()['text'])
        self.assertEqual(response.json()['action']['type'], 'guide_next')

    def test_chat_endpoint_restarts_guide_without_clearing_saved_cart(self):
        saved_cart = {'A0002': 1, 'A0001': 1}
        session = self.client.session
        session['anon_cart'] = saved_cart
        session.save()

        response = self.client.post(
            reverse('ai_chat_api'),
            json.dumps({
                'message': 'Quiero que me guíes paso a paso para realizar una compra',
                'page_context': {'path': '/carrito/'},
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('Paso 1 de 4', response.json()['text'])
        self.assertIn('2 productos distintos', response.json()['text'])
        self.assertEqual(response.json()['action']['target'], '/?vista=catalogo#productos-grid')
        self.assertEqual(self.client.session['anon_cart'], saved_cart)

    @patch('dashboard.ferrebot._generate_gemini_plan')
    def test_product_page_context_keeps_current_product_in_recommendation(self, generate_plan):
        product = Productos.objects.create(
            Codigo='A9886',
            Descripcion='Interruptor WiFi para iluminación',
            Precio=Decimal('22.00'),
            Cantidad=5,
        )
        generate_plan.return_value = {
            'reply': 'Esta opción coincide con la ficha que estás consultando.',
            'search_terms': [],
            'category_slug': '',
            'action': 'none',
            'destination': '',
            'promotions_only': False,
            'in_stock_only': False,
        }

        response_text, _ = build_assistant_reply(
            '¿Qué me recomiendas para este producto?',
            [],
            {'path': f'/producto/{product.Codigo}/'},
        )

        self.assertIn(product.Descripcion, response_text)
        generate_plan.assert_called_once()
        self.assertEqual(generate_plan.call_args.args[3]['product']['code'], product.Codigo)

    def test_search_finds_product_in_a_new_category_without_category_rules(self):
        category = Categoria.objects.create(name='Energía fotovoltaica')
        product = Productos.objects.create(
            Codigo='A9876',
            Descripcion='Panel solar portátil de 100W',
            Precio=79.50,
            Cantidad=4,
            Categoria=category,
        )

        results = search_catalog(['panel solar portatil'])

        self.assertIn(product, results)
        self.assertIn(product, search_catalog(['portátil']))

    def test_search_can_filter_any_category_created_in_the_database(self):
        category = Categoria.objects.create(name='Accesorios para paneles')
        product = Productos.objects.create(
            Codigo='A9877',
            Descripcion='Conector fotovoltaico',
            Precio=8.25,
            Cantidad=3,
            Categoria=category,
        )

        results = search_catalog([], category_slug=category.slug)

        self.assertEqual(results, [product])

    def test_promotions_and_stock_filters_use_current_product_values(self):
        category = Categoria.objects.create(name='Control de energía')
        promoted = Productos.objects.create(
            Codigo='A9879',
            Descripcion='Controlador inteligente',
            Precio=Decimal('15.00'),
            Cantidad=2,
            promocion=True,
            Categoria=category,
        )
        Productos.objects.create(
            Codigo='A9880',
            Descripcion='Controlador estándar',
            Precio=Decimal('12.00'),
            Cantidad=0,
            promocion=False,
            Categoria=category,
        )

        results = search_catalog([], promotions_only=True, in_stock_only=True)
        available_results = search_catalog([], in_stock_only=True)

        self.assertEqual(results, [promoted])
        self.assertEqual(available_results, [promoted])

    @patch('dashboard.ferrebot._generate_gemini_plan', return_value=None)
    def test_offline_fallback_recognizes_categories_added_later(self, _generate_plan):
        category = Categoria.objects.create(name='Domótica inteligente')
        product = Productos.objects.create(
            Codigo='A9881',
            Descripcion='Enchufe programable WiFi',
            Precio=Decimal('19.95'),
            Cantidad=5,
            Categoria=category,
        )

        result = build_assistant_reply('domótica', [])

        self.assertIsNotNone(result)
        self.assertIn(product.Descripcion, result[0])

    def test_bestseller_question_with_greeting_uses_sales_results_without_ai(self):
        customer = UsuarioClientes.objects.create(
            nombre='Cliente',
            apellido='QA',
            telefono='04120000000',
            cedula='V98765432',
            direccion='Dirección de prueba',
            email='ferrebot-sales@example.com',
            fecha_nacimiento=date(1990, 1, 1),
        )
        invoice = Factura.objects.create(cliente=customer, total=Decimal('125.00'))
        best_seller = Productos.objects.create(
            Codigo='A9882', Descripcion='Interruptor inteligente vendido',
            Precio=Decimal('12.50'), Cantidad=3,
        )
        second_seller = Productos.objects.create(
            Codigo='A9883', Descripcion='Cable de instalación vendido',
            Precio=Decimal('4.00'), Cantidad=8,
        )
        canceled = Productos.objects.create(
            Codigo='A9884', Descripcion='Producto de factura anulada',
            Precio=Decimal('1.00'), Cantidad=0,
        )
        DetalleFactura.objects.create(factura=invoice, producto=best_seller, cantidad=7, precio=best_seller.Precio)
        DetalleFactura.objects.create(factura=invoice, producto=second_seller, cantidad=2, precio=second_seller.Precio)
        canceled_invoice = Factura.objects.create(cliente=customer, estado='anulada')
        DetalleFactura.objects.create(factura=canceled_invoice, producto=canceled, cantidad=100, precio=canceled.Precio)

        with patch('dashboard.ferrebot._generate_gemini_plan') as generate_plan:
            response = self.client.post(
                reverse('ai_chat_api'),
                json.dumps({'message': 'hola, cuales son los productos mas vendidos'}),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 200)
        response_text = response.json()['text']
        self.assertIn(best_seller.Descripcion, response_text)
        self.assertIn(second_seller.Descripcion, response_text)
        self.assertNotIn(canceled.Descripcion, response_text)
        self.assertLess(response_text.index(best_seller.Descripcion), response_text.index(second_seller.Descripcion))
        self.assertNotIn('Hola, soy FerreBot', response_text)
        generate_plan.assert_not_called()

    @patch('dashboard.ferrebot._generate_gemini_plan')
    def test_chat_uses_verified_live_catalog_data(self, generate_plan):
        category = Categoria.objects.create(name='Automatización residencial')
        product = Productos.objects.create(
            Codigo='A9878',
            Descripcion='Interruptor inteligente WiFi',
            Precio=Decimal('24.90'),
            Cantidad=6,
            Categoria=category,
        )
        generate_plan.return_value = {
            'reply': 'Encontré una opción que coincide con lo que necesitas.',
            'search_terms': ['interruptor inteligente'],
            'category_slug': category.slug,
            'action': 'catalog',
            'destination': '',
            'promotions_only': False,
            'in_stock_only': False,
        }

        response = self.client.post(
            reverse('ai_chat_api'),
            json.dumps({'message': 'necesito controlar las luces desde el teléfono'}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(product.Descripcion, response.json()['text'])
        self.assertIn('$24.90', response.json()['text'])
        self.assertEqual(response.json()['action']['target'], category.slug)
