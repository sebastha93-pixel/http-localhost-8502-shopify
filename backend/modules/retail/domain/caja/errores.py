"""Errores del dominio de caja."""
from __future__ import annotations

from backend.modules.retail.domain.venta.errores import ReglaDeNegocio

__all__ = ["ArqueoCiego", "SesionYaCerrada"]


class SesionYaCerrada(ReglaDeNegocio):
    """Se intentó mover una sesión que ya se cerró y se firmó (INV-C7)."""


class ArqueoCiego(ReglaDeNegocio):
    """Se pidió el esperado antes de declarar el conteo (INV-C4).

    No es un fallo: es la regla funcionando. Si la cajera ve el esperado,
    escribe el esperado, y el arqueo deja de medir nada.
    """
