import os

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible


@deconstructible
class PrivatePaymentStorage(FileSystemStorage):
    @property
    def location(self):
        return os.path.abspath(settings.PRIVATE_MEDIA_ROOT)

    @property
    def base_location(self):
        return self.location

    def url(self, name):
        raise ValueError('Los comprobantes solo se sirven mediante la vista administrativa protegida.')