# from django.db.models.signals import post_save, post_delete
# from django.dispatch import receiver
# from django.contrib.contenttypes.models import ContentType
# from .models import AuditLog
# from django.contrib.auth.models import User
# from FERREELECTRI_PLUS.middleware import get_current_user

# @receiver(post_save)
# def log_save_signal(sender, instance, created, **kwargs):
#     if sender not in [AuditLog, User]:
#         action = "CREAR" if created else "ACTUALIZAR"
#         user = get_current_user()
#         AuditLog.objects.create(
#             user=user if user else None,
#             action=action,
#             model_name=sender.__name__,
#             object_id=instance.pk,
#             details=str(instance)
#         )

# @receiver(post_delete)
# def log_delete(sender, instance, **kwargs):
#     if sender != AuditLog:
#         AuditLog.objects.create(
#             user=get_current_user(),
#             action="ELIMINAR",
#             model_name=sender.__name__,
#             object_id=instance.pk,
#             details=str(instance)
#         )

from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from Inventario.models import Productos

from .cache_utils import invalidate_catalog_cache


@receiver(pre_save, sender=Productos)
def mark_catalog_change(sender, instance, **kwargs):
	"""Marca cambios de precio/stock antes de persistir el producto."""
	if not instance.pk:
		instance._catalog_price_stock_changed = True
		return
	previous = sender.objects.filter(pk=instance.pk).values('Precio', 'Cantidad').first()
	instance._catalog_price_stock_changed = bool(
		previous and (
			previous['Precio'] != instance.Precio
			or previous['Cantidad'] != instance.Cantidad
		)
	)


@receiver(post_save, sender=Productos)
def invalidate_catalog_after_product_change(sender, instance, **kwargs):
	"""Invalida variantes de catálogo solo tras cambios relevantes confirmados."""
	if getattr(instance, '_catalog_price_stock_changed', False):
		invalidate_catalog_cache()


@receiver(post_delete, sender=Productos)
def invalidate_catalog_after_product_delete(sender, instance, **kwargs):
	"""Evita servir IDs de productos eliminados desde Redis."""
	invalidate_catalog_cache()