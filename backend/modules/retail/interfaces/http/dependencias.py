"""Inyección de dependencias del módulo retail.

EL MOTOR SE CREA UNA VEZ Y PEREZOSAMENTE. Crearlo al importar haría que el
backend entero no arrancara si RETAIL_DATABASE_URL no está configurada — y
hoy no lo está en producción, porque el módulo todavía no se usa. Un módulo
nuevo no puede tumbar el ERP que ya funciona.
"""
from __future__ import annotations

import os
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncEngine

from backend.modules.retail.infrastructure.persistencia.unidad_de_trabajo import (
    UnidadDeTrabajoSQL,
    crear_fabrica,
    crear_motor,
)

_motor: Optional[AsyncEngine] = None
_fabrica = None


def configurado() -> bool:
    return bool(os.environ.get("RETAIL_DATABASE_URL", "").strip())


def _obtener_fabrica():
    global _motor, _fabrica
    if _fabrica is None:
        url = os.environ.get("RETAIL_DATABASE_URL", "").strip()
        if not url:
            raise RuntimeError(
                "RETAIL_DATABASE_URL no está configurada. El módulo retail "
                "habla con Postgres directo (ADR-004) y no comparte la "
                "conexión de supabase-py."
            )
        _motor = crear_motor(url)
        _fabrica = crear_fabrica(_motor)
    return _fabrica


async def unidad_de_trabajo():
    return UnidadDeTrabajoSQL(_obtener_fabrica())


async def sesion_lectura():
    """Sesión suelta para las consultas. Sin transacción de escritura."""
    fabrica = _obtener_fabrica()
    async with fabrica() as s:
        yield s


def reiniciar() -> None:
    """Sólo para pruebas: olvida el motor cacheado."""
    global _motor, _fabrica
    _motor, _fabrica = None, None
