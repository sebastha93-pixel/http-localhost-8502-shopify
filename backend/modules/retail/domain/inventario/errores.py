"""Errores del dominio de inventario."""
from __future__ import annotations

from backend.modules.retail.domain.venta.errores import ReglaDeNegocio

__all__ = ["SinStock"]


class SinStock(ReglaDeNegocio):
    """No hay unidades disponibles suficientes (INV-I1).

    Estando SIN internet esto no se levanta: la prenda física ya está en la
    mano de la clienta y bloquear la venta pierde plata real para proteger un
    dato que de todos modos está desactualizado (INV-I2).
    """
