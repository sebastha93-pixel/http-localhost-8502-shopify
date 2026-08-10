"""Estados de una venta.

El punto de no retorno es CERRADA, no FISCALIZADA (ADR-002). Cuando una venta
llega a CERRADA ya se descargó el stock, se afectó la caja y se imprimió el
ticket: la clienta se fue. Que el documento fiscal todavía esté en cola es un
asunto nuestro, no suyo.

Esa decisión es la que hace posible la promesa de 30 segundos por venta.
"""
from __future__ import annotations

from enum import Enum

__all__ = ["EstadoVenta", "EstadoFiscal"]


class EstadoVenta(Enum):
    BORRADOR = "borrador"      # carrito abierto; lo único mutable
    CERRADA = "cerrada"        # hecho consumado: hay plata y hay stock movido
    ANULADA = "anulada"        # se cerró y se revirtió, con firma
    DESCARTADA = "descartada"  # se abandonó el carrito; no deja rastro fiscal

    def es_mutable(self) -> bool:
        return self is EstadoVenta.BORRADOR


class EstadoFiscal(Enum):
    """Dónde va el documento ante la DIAN. Independiente del estado de la venta."""

    NO_APLICA = "no_aplica"
    PENDIENTE = "pendiente"
    ENVIANDO = "enviando"
    EMITIDO = "emitido"
    RECHAZADO = "rechazado"
    FALLIDO = "fallido"
    # La factura existe en Siigo pero no dice lo que le mandamos. Siigo descarta
    # campos en silencio (pasó con `warehouse`), así que sin releer el documento
    # no hay forma de saberlo. Alerta crítica.
    DISCREPANTE = "discrepante"
