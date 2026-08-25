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
    # Plata que se le devuelve a una clienta por una venta de otro día. NO es
    # `ANULACION` —eso deshace una venta del turno en curso— ni `RETIRO`, que
    # es plata que sale hacia el banco.
    #
    # ⚠️ ESTE VALOR TIENE QUE EXISTIR AQUÍ AUNQUE NADIE LO ESCRIBA A MANO. Al
    # recargar un turno, `repo_sesion_caja` hace `TipoMovimiento(m["tipo"])`
    # con lo que traiga la base: si la migración 0020 admite 'devolucion' en el
    # CHECK y el enum no lo conoce, la primera devolución en efectivo deja el
    # turno IMPOSIBLE DE CARGAR — y con él, imposible de cerrar.
    DEVOLUCION = "devolucion"
