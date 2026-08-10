"""Puerto de la unidad de trabajo.

EL CONTRATO QUE JUSTIFICA TODO ADR-004: al cerrar una venta se escriben la
venta, sus líneas, sus pagos, los asientos de inventario, el movimiento de
caja, la auditoría y el outbox. **O entran todos, o no entra ninguno.**

Con `supabase-py` (PostgREST) eso no se puede: cada llamada es una petición
HTTP independiente. Un fallo a mitad de camino dejaba stock descargado sin
venta, o venta sin plata en la caja — y nadie se enteraba hasta el cierre.

La capa de aplicación depende de este protocolo, no de SQLAlchemy. Los tests
de casos de uso usan una implementación en memoria.
"""
from __future__ import annotations

from typing import Any, Protocol

__all__ = ["UnidadDeTrabajo"]


class UnidadDeTrabajo(Protocol):
    """Una transacción, con los repositorios que participan en ella."""

    ventas: Any
    sesiones: Any
    inventario: Any
    auditoria: Any
    outbox: Any

    async def __aenter__(self) -> "UnidadDeTrabajo": ...

    async def __aexit__(self, exc_type, exc, tb) -> None:
        """Sale SIEMPRE con rollback si no hubo commit explícito.

        Es el default seguro: olvidar el commit pierde datos, que es molesto y
        visible. Olvidar el rollback los deja a medio escribir, que es
        silencioso y mucho peor.
        """

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...
