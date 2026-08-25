"""MovimientoCaja — un asiento del turno.

`es_efectivo` decide si el movimiento afecta la plata física de la caja. La
base, los retiros y los gastos son efectivo por definición y no llevan medio
de pago; los cobros sí lo llevan.
"""
from __future__ import annotations

from typing import Optional

from backend.modules.retail.domain.caja.estados import TipoMovimiento
from backend.modules.retail.domain.shared.dinero import Dinero

__all__ = ["MovimientoCaja"]


class MovimientoCaja:
    """Entidad hija de SesionCaja. El monto lleva signo."""

    def __init__(self, *, numero: int, tipo: TipoMovimiento, monto: Dinero,
                 medio_pago_id: Optional[str], motivo: str, usuario_id: str,
                 es_efectivo: bool, autorizado_por: Optional[str] = None,
                 venta_id: Optional[str] = None) -> None:
        self.numero = numero
        self.tipo = tipo
        self.monto = monto
        self.medio_pago_id = medio_pago_id
        self.motivo = motivo
        self.usuario_id = usuario_id
        self.es_efectivo = es_efectivo
        self.autorizado_por = autorizado_por
        self.venta_id = venta_id

    def __repr__(self) -> str:
        return f"MovimientoCaja(#{self.numero} {self.tipo.value} {self.monto.formateado()})"
