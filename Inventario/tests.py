import json
from pathlib import Path
from tempfile import TemporaryDirectory
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from .models import Categoria, PresentacionProducto, Productos

User = get_user_model()

class InventarioTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass',
            is_staff=True,
            is_superuser=True,
        )
        self.client.force_login(self.user)
        self.producto = Productos.objects.create(Descripcion="Martillo", Cantidad=5)

    def test_imagen_de_producto_se_sirve_sin_exponer_archivos_privados(self):
        with TemporaryDirectory() as media_root:
            products_directory = Path(media_root) / 'productos'
            products_directory.mkdir()
            (products_directory / 'test-image.png').write_bytes(b'public-image')
            (Path(media_root) / 'private-media').mkdir()
            (Path(media_root) / 'private-media' / 'receipt.png').write_bytes(b'private')

            with override_settings(MEDIA_ROOT=media_root):
                response = self.client.get('/media/productos/test-image.png')
                traversal_response = self.client.get(
                    '/media/productos/%2E%2E/private-media/receipt.png'
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(b''.join(response.streaming_content), b'public-image')
            self.assertEqual(traversal_response.status_code, 404)

    def test_imagen_versionada_se_sirve_si_no_hay_disco_montado(self):
        with TemporaryDirectory() as media_root, TemporaryDirectory() as base_dir:
            product_directory = Path(base_dir) / 'media' / 'productos'
            product_directory.mkdir(parents=True)
            (product_directory / 'tracked-image.jfif').write_bytes(b'tracked-image')

            with override_settings(MEDIA_ROOT=media_root, BASE_DIR=Path(base_dir)):
                response = self.client.get('/media/productos/tracked-image.jfif')

            self.assertEqual(response.status_code, 200)
            self.assertEqual(b''.join(response.streaming_content), b'tracked-image')

    def test_lista_productos_renderiza_busqueda_y_resumen(self):
        response = self.client.get(reverse('listar_productos'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="q"')
        self.assertContains(response, 'productos registrados')

    def test_eliminar_producto_solo_acepta_post(self):
        url = reverse('dltProducto', args=[self.producto.Codigo])

        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertTrue(Productos.objects.filter(pk=self.producto.pk).exists())
        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertFalse(Productos.objects.filter(pk=self.producto.pk).exists())

    def test_inventario_pagina_completa_sin_truncar_productos(self):
        for index in range(2, 12):
            Productos.objects.create(
                Descripcion=f"Producto {index}",
                Cantidad=index,
            )

        first_page = self.client.get('/admin-panel/inventario/')
        second_page = self.client.get('/admin-panel/inventario/?page=2')

        self.assertEqual(first_page.status_code, 200)
        self.assertEqual(first_page.context['productos'].paginator.count, 11)
        self.assertEqual(len(first_page.context['productos']), 5)
        self.assertEqual(len(second_page.context['productos']), 5)
        self.assertContains(first_page, 'Página 1 de 3')
        self.assertContains(second_page, 'Página 2 de 3')

    def test_no_permitir_stock_negativo(self):
        response = self.client.post(reverse('registrar_salida'), {
            'producto_id': self.producto.pk,
            'cantidad': 10
        })
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.Cantidad, 5)  # No debe cambiar

    def test_salida_valida_descuenta_stock(self):
        response = self.client.post(reverse('registrar_salida'), {
            'producto_id': self.producto.pk,
            'cantidad': 2
        })
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.Cantidad, 3)

    def test_actualizar_precio_ajax_requiere_permiso_de_cambio(self):
        user = User.objects.create_user(username='staff-sin-inventario', is_staff=True)
        self.client.force_login(user)

        response = self.client.post(
            reverse('actualizar_precio_ajax'),
            data=json.dumps({'producto_id': self.producto.pk, 'nuevo_precio': '99.00'}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 403)

    def test_actualizar_precio_ajax_acepta_solo_precio_valido(self):
        response = self.client.post(
            reverse('actualizar_precio_ajax'),
            data=json.dumps({'producto_id': self.producto.pk, 'nuevo_precio': '99.00'}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.Precio, 99)

    def test_actualizar_precio_ajax_rechaza_post_sin_csrf(self):
        csrf_client = type(self.client)(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)

        response = csrf_client.post(
            reverse('actualizar_precio_ajax'),
            data=json.dumps({'producto_id': self.producto.pk, 'nuevo_precio': '99.00'}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 403)

    def test_editar_producto_persiste_categoria_presentacion_y_unidad(self):
        categoria = Categoria.objects.create(name='Canalización QA')
        response = self.client.post(
            reverse('updtProducto', kwargs={'id': self.producto.Codigo}),
            {
                'Descripcion': 'Martillo actualizado',
                'Precio': '18.50',
                'iva': '16.00',
                'Costo': '7.25',
                'Cantidad': '9',
                'Categoria': str(categoria.pk),
                'presentacion_nombre[]': ['Caja'],
                'presentacion_factor[]': ['12.50'],
                'presentacion_unidad[]': ['Unidades'],
                'presentations_json': json.dumps([
                    {'type': 'Caja', 'factor': '12.50', 'unit': 'Unidades'},
                ]),
            },
        )

        self.assertEqual(response.status_code, 302)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.Categoria_id, categoria.pk)
        self.assertEqual(self.producto.presentaciones.count(), 1)
        presentation = self.producto.presentaciones.get()
        self.assertEqual(presentation.nombre, 'Caja')
        self.assertEqual(presentation.factor, Decimal('12.50'))
        self.assertEqual(presentation.unidad_medida, 'Unidades')

    def test_crear_producto_guarda_sin_error_500(self):
        response = self.client.post(reverse('addProducto'), {
            'Descripcion': 'Taladro nuevo',
            'Precio': '45.00',
            'iva': '16.00',
            'Costo': '30.00',
            'Cantidad': '4',
            'presentations_json': '[]',
        })

        self.assertEqual(response.status_code, 302)
        self.assertTrue(Productos.objects.filter(Descripcion='Taladro nuevo').exists())

    def test_edicion_muestra_json_de_presentaciones_invalido_sin_error_500(self):
        response = self.client.post(
            reverse('updtProducto', kwargs={'id': self.producto.Codigo}),
            {
                'Descripcion': 'Martillo',
                'Precio': '10.00',
                'Costo': '4.00',
                'Cantidad': '5',
                'presentations_json': '{not-json',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No se pudieron procesar las presentaciones.')


class CostoLoteFifoTest(TestCase):
    def test_propuesta_barata_se_activa_al_agotar_lote_caro_sin_cambiar_precio(self):
        from decimal import Decimal
        from .models import CostoLote, CostoPendiente
        from .utils import registrar_movimiento

        producto = Productos.objects.create(
            Codigo='FIFO01', Descripcion='Producto con lotes',
            Precio=Decimal('22.00'), Costo=Decimal('11.00'), Cantidad=10,
        )
        registrar_movimiento(
            producto, 'entrada', 12, 'Compra a menor costo',
            costo_unitario=Decimal('9.00'), compra_id=123,
        )
        lote_nuevo = CostoLote.objects.get(compra_id=123)
        propuesta = CostoPendiente.objects.create(
            producto=producto,
            lote=lote_nuevo,
            cantidad_compra=12,
            unidad_compra='unidades',
            costo_propuesto=Decimal('9.00'),
            estado='espera_stock',
        )

        registrar_movimiento(producto, 'salida', 10, 'Venta de lote caro')
        producto.refresh_from_db()
        propuesta.refresh_from_db()
        lote_nuevo.refresh_from_db()

        self.assertEqual(producto.Cantidad, 12)
        self.assertEqual(producto.Costo, Decimal('11.00'))
        self.assertEqual(producto.Precio, Decimal('22.00'))
        self.assertEqual(lote_nuevo.cantidad_disponible, 12)
        self.assertEqual(propuesta.estado, 'pendiente')
        self.assertIsNotNone(propuesta.pendiente_desde)

    def test_lote_caro_restante_mantiene_propuesta_en_espera(self):
        from decimal import Decimal
        from .models import CostoLote, CostoPendiente
        from .utils import registrar_movimiento

        producto = Productos.objects.create(
            Codigo='FIFO02', Descripcion='Producto con inventario caro',
            Precio=Decimal('22.00'), Costo=Decimal('11.00'), Cantidad=10,
        )
        registrar_movimiento(producto, 'entrada', 12, 'Compra económica', costo_unitario=Decimal('9.00'))
        lote_nuevo = CostoLote.objects.filter(producto=producto).order_by('-pk').first()
        propuesta = CostoPendiente.objects.create(
            producto=producto, lote=lote_nuevo, cantidad_compra=12,
            costo_propuesto=Decimal('9.00'), estado='espera_stock',
        )

        registrar_movimiento(producto, 'salida', 9, 'Venta parcial del lote caro')

        propuesta.refresh_from_db()
        self.assertEqual(propuesta.estado, 'espera_stock')
