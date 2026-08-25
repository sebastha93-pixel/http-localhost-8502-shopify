"""Eventos de dominio de la venta.

Son el pegamento entre contextos: `VentaCerrada` es lo que hace que el
inventario descargue, la caja sume y el documento fiscal se encole, sin que la
Venta sepa que esas cosas existen.

`version` no es adorno. El día que `VentaCerrada` necesite un campo nuevo, los
eventos viejos que quedaron en el outbox tienen que seguir siendo procesables.
Un evento sin versión es una migración imposible dentro de dos años.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Tuple

from backend.modules.retail.domain.shared.dinero import Dinero

__all__ = ["EventoDominio", "VentaCerrada", "VentaAnulada", "DescuentoAutorizado"]


@dataclass(frozen=True)
class EventoDominio:
    ocurrido_en: datetime
    version: int = field(default=1, kw_only=True)


@dataclass(frozen=True)
class LineaVendida:
    """Lo mínimo que necesita el inventario para descargar."""

    sku: str
    cantidad: int
    total: Dinero


@dataclass(frozen=True)
class VentaCerrada(EventoDominio):
    venta_id: str = ""
    numero: str = ""
    tienda_id: str = ""
    caja_id: str = ""
    sesion_id: str = ""
    cajera_id: str = ""
    cliente_id: Optional[str] = None
    total: Dinero = None  # type: ignore[assignment]
    iva_total: Dinero = None  # type: ignore[assignment]
    descuento_total: Dinero = None  # type: ignore[assignment]
    pagado: Dinero = None  # type: ignore[assignment]
    vuelto: Dinero = None  # type: ignore[assignment]
    lineas: Tuple[LineaVendida, ...] = ()


@dataclass(frozen=True)
class VentaAnulada(EventoDominio):
    venta_id: str = ""
    numero: str = ""
    tienda_id: str = ""
    motivo: str = ""
    autorizado_por: str = ""
    total_revertido: Dinero = None  # type: ignore[assignment]
    lineas: Tuple[LineaVendida, ...] = ()


@dataclass(frozen=True)
class DescuentoAutorizado(EventoDominio):
    """Auditoría prioritaria: quién autorizó bajarle el precio a qué."""

    venta_id: str = ""
    numero_linea: int = 0
    sku: str = ""
    descripcion_descuento: str = ""
    monto: Dinero = None  # type: ignore[assignment]
    aplicado_por: str = ""
    autorizado_por: str = ""
