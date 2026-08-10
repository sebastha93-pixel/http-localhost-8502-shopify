"""Estados de un turno de caja."""
from __future__ import annotations

from enum import Enum

__all__ = ["EstadoSesion", "TipoMovimiento"]


class EstadoSesion(Enum):
    ABIERTA = "abierta"
    EN_ARQUEO = "en_arqueo"   # se está contando; el esperado sigue oculto
    CERRADA = "cerrada"       # firmado e inmutable

    def es_mutable(self) -> bool:
        return self is not EstadoSesion.CERRADA


class TipoMovimiento(Enum):
    BASE_INICIAL = "base_inicial"
    VENTA = "venta"
    ANULACION = "anulacion"
    RETIRO = "retiro"       # sangría a caja fuerte
    INGRESO = "ingreso"     # aporte de sencillo
    GASTO = "gasto"         # caja menor
    AJUSTE = "ajuste"
