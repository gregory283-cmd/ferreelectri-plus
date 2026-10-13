from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class CxCListTemplateTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        user = user_model.objects.create_superuser(
            username='cxc-list-admin',
            email='cxc-list@example.com',
            password='CxcTest123!',
        )
        self.client.force_login(user)

    def test_list_renders_search_summary_and_report_dialog(self):
        response = self.client.get(reverse('listar_cxc'), {'q': 'factura'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="q"')
        self.assertContains(response, 'aria-labelledby="cxc-report-title"')
        self.assertContains(response, 'document.body.appendChild(modal)')
        self.assertContains(response, 'min-height:100dvh')
        self.assertContains(response, 'Cuentas por cobrar')
        self.assertEqual(response.context['total_cxc_accounts'], 0)
        self.assertEqual(response.context['total_cxc_pending'], Decimal('0.00'))