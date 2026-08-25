"""Descuento — la única forma legítima de bajar un precio en el POS.

Y por eso mismo, la vía por la que se saca mercancía. Estas reglas son las que
hacen que siempre quede rastro:

  · lleva motivo escrito, siempre
  · nunca supera el valor de la línea (INV-V4: el total no es negativo)
  · un porcentaje vive entre 0 y 100

Lo que este objeto NO decide es **quién** puede aplicarlo y hasta cuánto. Eso
es `PoliticaDescuento`, que necesita el rol de quien lo aplica. La separación
es deliberada: el objeto de valor sabe qué es un descuento; la política sabe
quién puede. Mezclarlas obligaría a cargar un usuario para poder calcular un
número.

Editar el precio a mano no existe en este POS — sólo descuentos, con tope y
con firma. Un campo de precio libre es el agujero clásico.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Optional, Union

from backend.modules.retail.domain.shared.dinero import Dinero

__all__ = ["Descuento", "DescuentoInvalido", "TipoDescuento"]

_MOTIVO_MINIMO = 4


class DescuentoInvalido(ValueError):
    """El descuento no cumple una regla del dominio."""


class TipoDescuento(Enum):
    PORCENTAJE = "porcentaje"
    VALOR = "valor"


@dataclass(frozen=True)
class Descuento:
    """Un descuento ya validado. Inmutable."""

    tipo: TipoDescuento
    motivo: str
    porcentaje_aplicado: Optional[Decimal] = None
    valor_aplicado: Optional[Dinero] = None

    # ── Construcción ────────────────────────────────────────────────────────

    @classmethod
    def porcentaje(cls, tasa: Union[int, str, Decimal], *, motivo: str) -> "Descuento":
        if isinstance(tasa, float):
            raise TypeError(
                f"el porcentaje no se expresa en float ({tasa!r}). "
                f"Usa int, str o Decimal: 10.5 no es exactamente 10,5."
            )
        try:
            t = Decimal(tasa)
        except Exception as e:  # noqa: BLE001
            raise DescuentoInvalido(f"porcentaje inválido: {tasa!r}") from e
        if t < 0 or t > 100:
            raise DescuentoInvalido(
                f"un descuento del {t}% no existe: el porcentaje va de 0 a 100."
            )
        return cls(
            tipo=TipoDescuento.PORCENTAJE,
            motivo=cls._motivo_valido(motivo),
            porcentaje_aplicado=t,
        )

    @classmethod
    def valor(cls, monto: Dinero, *, motivo: str) -> "Descuento":
        if not isinstance(monto, Dinero):
            raise DescuentoInvalido("el descuento por valor se expresa en Dinero")
        if not monto.es_positivo():
            raise DescuentoInvalido(
                f"un descuento de {monto.formateado()} no descuenta nada."
            )
        return cls(
            tipo=TipoDescuento.VALOR,
            motivo=cls._motivo_valido(motivo),
            valor_aplicado=monto,
        )

    @staticmethod
    def _motivo_valido(motivo: str) -> str:
        """Un descuento sin motivo es un descuadre sin explicación.

        Cuando la gerencia revise por qué el margen del mes bajó, el motivo es
        lo único que distingue una política comercial de una fuga.
        """
        if not isinstance(motivo, str):
            raise DescuentoInvalido("el descuento necesita un motivo escrito")
        limpio = motivo.strip()
        if len(limpio) < _MOTIVO_MINIMO:
            raise DescuentoInvalido(
                f"el motivo del descuento tiene que explicar algo "
                f"(mínimo {_MOTIVO_MINIMO} caracteres): {motivo!r}"
            )
        return limpio

    # ── Cálculo ─────────────────────────────────────────────────────────────

    def calcular_sobre(self, base: Dinero) -> Dinero:
        """Cuánto se descuenta de `base`. No devuelve el precio final."""
        if self.tipo is TipoDescuento.PORCENTAJE:
            assert self.porcentaje_aplicado is not None
            return base.porcentaje(self.porcentaje_aplicado)

        assert self.valor_aplicado is not None
        # `>` compara monedas y lanza MonedaDistinta si no coinciden, que es lo
        # que queremos: descontar dólares de pesos daría un número plausible.
        if self.valor_aplicado > base:
            raise DescuentoInvalido(
                f"el descuento de {self.valor_aplicado.formateado()} supera el "
                f"valor de la línea ({base.formateado()}): dejaría el total en "
                f"negativo."
            )
        return self.valor_aplicado

    def descripcion(self) -> str:
        """Como se lee en el ticket y en la auditoría."""
        if self.tipo is TipoDescuento.PORCENTAJE:
            assert self.porcentaje_aplicado is not None
            # `normalize()` sola devuelve '1E+1' para 10 — notación científica
            # en el ticket de una clienta. El formato 'f' la evita.
            t = format(self.porcentaje_aplicado.normalize(), "f")
            return f"−{t}% · {self.motivo}"
        assert self.valor_aplicado is not None
        return f"−{self.valor_aplicado.formateado()} · {self.motivo}"

    def __str__(self) -> str:
        return self.descripcion()
