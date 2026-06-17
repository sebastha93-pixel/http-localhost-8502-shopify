"""
backend.core.cache — LRU cache con TTL en memoria.

Para reducir carga al backend en endpoints leídos frecuentemente
(stats, advisors/ranking, etc.). El cache es por-proceso (no compartido
entre workers). Si Railway escalara horizontalmente cada worker tendría
su propio cache — para nuestro tamaño actual es suficiente.
"""
from __future__ import annotations

import functools
import time
from typing import Callable


def cached_ttl(ttl_seconds: int, max_size: int = 128) -> Callable:
    """Decorador: cachea el resultado de una función por TTL segundos.

    Usa la firma (args, kwargs) como key. Las funciones decoradas deben
    retornar valores serializables (dicts/listas/primitivos).
    """

    def decorator(fn: Callable) -> Callable:
        cache: dict = {}
        cache_order: list = []

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            # Skip params especiales (CurrentUser inyectado por FastAPI)
            key_args = tuple(a for a in args if not hasattr(a, "rol"))
            key_kwargs = tuple(
                (k, v) for k, v in sorted(kwargs.items())
                if not hasattr(v, "rol")
            )
            key = (key_args, key_kwargs)
            now = time.time()
            hit = cache.get(key)
            if hit and (now - hit[0]) < ttl_seconds:
                return hit[1]
            result = fn(*args, **kwargs)
            cache[key] = (now, result)
            cache_order.append(key)
            # LRU eviction
            while len(cache_order) > max_size:
                evict = cache_order.pop(0)
                cache.pop(evict, None)
            return result

        wrapper.cache_clear = lambda: (cache.clear(), cache_order.clear())  # type: ignore[attr-defined]
        wrapper.cache_info = lambda: {"size": len(cache), "max": max_size, "ttl": ttl_seconds}  # type: ignore[attr-defined]
        return wrapper

    return decorator
