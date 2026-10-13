"""Claves y operaciones de caché del catálogo."""

import hashlib

from django.core.cache import cache

CATALOG_VERSION_KEY = 'catalog:version'
CATALOG_TIMEOUT = 300


def catalog_cache_key(query='', oferta=False):
    """Genera una clave versionada para invalidar el catálogo sin barridos globales."""
    version = cache.get(CATALOG_VERSION_KEY, 1)
    normalized_query = (query or '').strip().lower()
    query_digest = hashlib.sha256(normalized_query.encode('utf-8')).hexdigest()[:16]
    return f'catalog:product-ids:v{version}:q={query_digest}:offer={int(oferta)}'


def invalidate_catalog_cache():
    """Avanza la versión y vuelve obsoletas todas las variantes de consulta."""
    try:
        if not cache.add(CATALOG_VERSION_KEY, 1, timeout=None):
            cache.incr(CATALOG_VERSION_KEY)
    except Exception:
        # Una caída de Redis no debe impedir guardar el producto; la vista hará fallback SQL.
        return False
    return True
