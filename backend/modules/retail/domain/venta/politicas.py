"""PoliticaDescuento — quién puede descontar cuánto.

Va aparte del objeto `Descuento` a propósito: el objeto de valor sabe **qué**
es un descuento, la política sabe **quién** puede aplicarlo. Mezclarlas
obligaría a cargar un usuario para poder calcular un número.

La regla que hace que el tope sirva de algo: un descuento en pesos se evalúa
por su **porcentaje efectivo** sobre la línea. Sin eso, el tope del 10% se
esquiva escribiendo el descuento en pesos, que es lo primero que descubre
quien quiera esquivarlo.

Los topes viven en la fila del usuario (`usuarios.tope_descuento_pct`), no en
este código: una campaña de fin de temporada no debería necesitar un deploy.
"""
from __future__ import annotations

from decimal import Decimal
from enum import Enum

from backend.modules.retail.domain.shared.dinero import Dinero
from backend.modules.retail.domain.venta.descuento import Descuento, TipoDescuento

__all__ = ["Decision", "PoliticaDescuento"]


class Decision(Enum):
    PERMITIDO = "permitido"
    REQUIERE_AUTORIZACION = "requiere_autorizacion"


class PoliticaDescuento:
    """Servicio de dominio. Sin estado: sólo decide."""

    @staticmethod
    def porcentaje_efectivo(descuento: Descuento, base: Dinero) -> Decimal:
        """Qué porcentaje de la línea representa este descuento.

        Es lo que iguala las dos formas de descontar: $30.000 sobre $100.000 es
        un 30% y pasa por el mismo control que escribir «30%».
        """
        if descuento.tipo is TipoDescuento.PORCENTAJE:
            assert descuento.porcentaje_aplicado is not None
            return descuento.porcentaje_aplicado

        assert descuento.valor_aplicado is not None
        if base.es_cero():
            return Decimal(100)
        # `calcular_sobre` valida de paso que el descuento quepa en la línea.
        monto = descuento.calcular_sobre(base)
        return (Decimal(monto.centavos) * 100) / Decimal(base.centavos)

    @classmethod
    def evaluar(cls, descuento: Descuento, base: Dinero, tope: Decimal) -> Decision:
        """¿Puede esta persona aplicar este descuento por su cuenta?"""
        if isinstance(tope, float):
            raise TypeError("el tope de descuento no se expresa en float")
        efectivo = cls.porcentaje_efectivo(descuento, base)
        if efectivo <= Decimal(tope):
            return Decision.PERMITIDO
        return Decision.REQUIERE_AUTORIZACION

    @classmethod
    def explicar(cls, descuento: Descuento, base: Dinero, tope: Decimal) -> str:
        """El mensaje que ve la cajera. Dice el número y dice qué hacer."""
        efectivo = cls.porcentaje_efectivo(descuento, base).quantize(Decimal("0.01"))
        return (
            f"Un descuento del {format(efectivo.normalize(), 'f')}% supera tu tope "
            f"({format(Decimal(tope).normalize(), 'f')}%). "
            f"Para aplicarlo tiene que entrar alguien con un tope mayor."
        )
