"""Eventos del dominio de caja."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional

from backend.modules.retail.domain.shared.dinero import Dinero

__all__ = ["SesionCajaCerrada", "VentaDesfasada"]


@dataclass(frozen=True)
class SesionCajaCerrada:
    ocurrido_en: datetime
    sesion_id: str
    tienda_id: str
    caja_id: str
    numero_turno: int
    cerrada_por: str
    diferencia: Dinero
    diferencia_por_medio: Dict[str, Dinero]
    cuadro: bool
    justificacion: Optional[str] = None
    autorizado_por: Optional[str] = None
    version: int = field(default=1, kw_only=True)


@dataclass(frozen=True)
class VentaDesfasada:
    """Una venta offline que sincronizo despues de que su turno cerro (INV-C8).

    No entra al arqueo —ese cierre ya esta firmado— pero tampoco se pierde.
    Va al supervisor, que decide que hacer con la plata.
    """

    ocurrido_en: datetime
    sesion_id: str
    tienda_id: str
    caja_id: str
    venta_id: str
    medio_pago_id: str
    monto: Dinero
    es_efectivo: bool
    version: int = field(default=1, kw_only=True)
