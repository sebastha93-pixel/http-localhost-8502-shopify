"""Pago — plata que entró por una venta.

`es_efectivo` no es cosmético: decide si el excedente es un vuelto legítimo o
un error de digitación. Un datáfono no da vuelto (INV-V3).

El dato lo resuelve la capa de aplicación desde la tabla `medios_pago` y lo
entrega ya resuelto, para que el dominio no tenga que consultar nada.
"""
from __future__ import annotations

from typing import Optional

from backend.modules.retail.domain.shared.dinero import Dinero
from backend.modules.retail.domain.venta.errores import ReglaDeNegocio

__all__ = ["Pago"]


class Pago:
    """Entidad hija del agregado Venta."""

    def __init__(
        self,
        *,
        numero: int,
        medio_pago_id: str,
        monto: Dinero,
        es_efectivo: bool,
        referencia: Optional[str] = None,
    ) -> None:
        if not monto.es_positivo():
            raise ReglaDeNegocio(
                f"un pago de {monto.formateado()} no abona nada. "
                f"Para quitar un pago, elimínalo."
            )
        if not medio_pago_id:
            raise ReglaDeNegocio("el pago necesita un medio de pago")

        self.numero = numero
        self.medio_pago_id = medio_pago_id
        self.monto = monto
        self.es_efectivo = es_efectivo
        # Últimos 4 del voucher. Mientras el datáfono no esté integrado, es lo
        # único que permite casar el arqueo contra el cierre del datáfono.
        self.referencia = (referencia or "").strip() or None

    def __repr__(self) -> str:
        return f"Pago(#{self.numero} {self.medio_pago_id} {self.monto.formateado()})"
