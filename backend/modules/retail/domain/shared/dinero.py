"""Dinero — cantidad monetaria exacta.

REGLA DEL MÓDULO: el dinero se guarda, se opera y se transporta en **centavos
enteros**. Nunca en float. La conversión a decimal ocurre sólo en dos bordes:
al pintar en pantalla y al armar el payload de Siigo.

El motivo no es teórico. En este repositorio un cambio salió facturado por
67.960 cuando la prenda valía 169.900, porque el precio se tomó de una fuente
que ya traía el IVA incluido y se volvió a normalizar. El error no revienta:
produce un número plausible, la factura se emite, y la diferencia aparece
semanas después.

Este objeto hace imposible esa familia entera de errores:

  · construir con un float lanza TypeError, no redondea en silencio
  · sumar monedas distintas lanza, no produce un número sin sentido
  · el redondeo es una decisión explícita (medio hacia arriba), no el que
    traiga Python por defecto
  · repartir un monto entre varias líneas conserva hasta el último centavo

Compatible con Python 3.10 (Railway corre sobre jammy).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import List, Sequence, Union

__all__ = ["Dinero", "MonedaDistinta"]


class MonedaDistinta(ValueError):
    """Se intentó operar entre dos monedas. El resultado no significaría nada."""


# Lo que se acepta como cantidad de pesos al construir. `float` está excluido
# a propósito y su ausencia es la mitad del valor de esta clase.
Pesos = Union[int, str, Decimal]


def _a_decimal(valor: Pesos, campo: str) -> Decimal:
    if isinstance(valor, float):
        raise TypeError(
            f"{campo} recibió un float ({valor!r}). El dinero no se representa en "
            f"float: 0.1 + 0.2 no es 0.3, y un centavo perdido por línea es una "
            f"factura que no cuadra. Usa int, str o Decimal."
        )
    if isinstance(valor, Decimal):
        return valor
    if isinstance(valor, (int, str)):
        return Decimal(valor)
    raise TypeError(f"{campo} no acepta {type(valor).__name__}")


@dataclass(frozen=True, order=False)
class Dinero:
    """Una cantidad de dinero. Inmutable: toda operación devuelve otra."""

    centavos: int
    moneda: str

    def __post_init__(self) -> None:
        if isinstance(self.centavos, float):
            raise TypeError(
                f"Dinero recibió un float ({self.centavos!r}). Se construye con "
                f"centavos enteros, o con Dinero.desde_pesos()."
            )
        if not isinstance(self.centavos, int):
            raise TypeError(f"centavos debe ser int, no {type(self.centavos).__name__}")
        if not self.moneda or len(self.moneda) != 3:
            raise ValueError(f"moneda inválida: {self.moneda!r} (se espera ISO-4217)")

    # ── Construcción ────────────────────────────────────────────────────────

    @classmethod
    def desde_pesos(cls, valor: Pesos, moneda: str) -> "Dinero":
        """Desde una cantidad en la unidad mayor: '169900' → 16.990.000 centavos."""
        d = _a_decimal(valor, "desde_pesos")
        return cls(int((d * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)), moneda)

    @classmethod
    def cero(cls, moneda: str) -> "Dinero":
        return cls(0, moneda)

    # ── Aritmética ──────────────────────────────────────────────────────────

    def _misma_moneda(self, otro: "Dinero") -> None:
        if self.moneda != otro.moneda:
            raise MonedaDistinta(
                f"No se puede operar {self.moneda} con {otro.moneda}. "
                f"Una venta lleva una sola moneda."
            )

    def __add__(self, otro: "Dinero") -> "Dinero":
        self._misma_moneda(otro)
        return Dinero(self.centavos + otro.centavos, self.moneda)

    def __sub__(self, otro: "Dinero") -> "Dinero":
        self._misma_moneda(otro)
        return Dinero(self.centavos - otro.centavos, self.moneda)

    def __neg__(self) -> "Dinero":
        return Dinero(-self.centavos, self.moneda)

    def __mul__(self, cantidad: int) -> "Dinero":
        """Multiplicar por unidades. Un factor fraccionario va por porcentaje()."""
        if isinstance(cantidad, bool) or not isinstance(cantidad, int):
            raise TypeError(
                f"Dinero se multiplica por un número entero de unidades, no por "
                f"{type(cantidad).__name__}. Para un factor, usa porcentaje()."
            )
        return Dinero(self.centavos * cantidad, self.moneda)

    __rmul__ = __mul__

    def __lt__(self, otro: "Dinero") -> bool:
        self._misma_moneda(otro)
        return self.centavos < otro.centavos

    def __le__(self, otro: "Dinero") -> bool:
        self._misma_moneda(otro)
        return self.centavos <= otro.centavos

    def __gt__(self, otro: "Dinero") -> bool:
        self._misma_moneda(otro)
        return self.centavos > otro.centavos

    def __ge__(self, otro: "Dinero") -> bool:
        self._misma_moneda(otro)
        return self.centavos >= otro.centavos

    # ── Predicados ──────────────────────────────────────────────────────────

    def es_cero(self) -> bool:
        return self.centavos == 0

    def es_positivo(self) -> bool:
        return self.centavos > 0

    def es_negativo(self) -> bool:
        return self.centavos < 0

    # ── Porcentaje ──────────────────────────────────────────────────────────

    def porcentaje(self, tasa: Union[int, str, Decimal]) -> "Dinero":
        """El `tasa` % de esta cantidad, redondeado MEDIO HACIA ARRIBA.

        El redondeo es explícito a propósito. Python redondea al par por
        defecto (ROUND_HALF_EVEN), que en los empates da un resultado distinto
        al que espera la facturación colombiana; esa diferencia de un centavo,
        multiplicada por las líneas de un turno, aparece en el arqueo.
        """
        t = _a_decimal(tasa, "porcentaje")
        bruto = (Decimal(self.centavos) * t) / Decimal(100)
        return Dinero(int(bruto.quantize(Decimal("1"), rounding=ROUND_HALF_UP)), self.moneda)

    # ── Reparto ─────────────────────────────────────────────────────────────

    def repartir(self, partes: int) -> List["Dinero"]:
        """Divide en `partes` conservando hasta el último centavo.

        $100 entre 3 no son tres veces $33,33: sobra un centavo. Ese centavo se
        le entrega a las primeras partes en vez de desaparecer. Si se perdiera,
        la suma de las líneas no daría el total de la factura.
        """
        if partes <= 0:
            raise ValueError("repartir necesita al menos una parte")
        base, resto = divmod(abs(self.centavos), partes)
        signo = -1 if self.centavos < 0 else 1
        return [
            Dinero(signo * (base + (1 if i < resto else 0)), self.moneda)
            for i in range(partes)
        ]

    def repartir_proporcional(self, pesos: Sequence[int]) -> List["Dinero"]:
        """Reparte en proporción a `pesos`, conservando el total exacto.

        Es como se prorratea un descuento global entre las líneas de una venta.
        El residuo del redondeo se asigna a las partes de mayor peso, que es
        donde menos se nota y donde el error relativo es menor.

        Si todos los pesos son cero no hay proporción posible y se reparte en
        partes iguales — devolver ceros escondería plata.
        """
        if not pesos:
            raise ValueError("repartir_proporcional necesita al menos un peso")
        if any(p < 0 for p in pesos):
            raise ValueError("los pesos del reparto no pueden ser negativos")

        total_pesos = sum(pesos)
        if total_pesos == 0:
            return self.repartir(len(pesos))

        signo = -1 if self.centavos < 0 else 1
        monto = abs(self.centavos)

        crudos = [(monto * p) // total_pesos for p in pesos]
        residuo = monto - sum(crudos)

        # El residuo (siempre menor que el número de partes) va a las de mayor
        # peso, en orden estable para que el reparto sea reproducible.
        orden = sorted(range(len(pesos)), key=lambda i: (-pesos[i], i))
        for i in orden[:residuo]:
            crudos[i] += 1

        return [Dinero(signo * c, self.moneda) for c in crudos]

    # ── Bordes: sólo aquí se sale de los centavos ───────────────────────────

    def a_decimal(self) -> Decimal:
        """Para el payload de Siigo. Siempre con dos decimales."""
        return (Decimal(self.centavos) / Decimal(100)).quantize(Decimal("0.01"))

    def formateado(self) -> str:
        """Para la pantalla. En COP el peso es la unidad: los centavos sólo
        aparecen cuando existen, para no llenar el POS de ',00'."""
        signo = "-" if self.centavos < 0 else ""
        pesos, centavos = divmod(abs(self.centavos), 100)
        entero = f"{pesos:,}".replace(",", ".")
        if centavos:
            return f"{signo}${entero},{centavos:02d}"
        return f"{signo}${entero}"

    def __str__(self) -> str:
        return self.formateado()

    def __repr__(self) -> str:
        return f"Dinero({self.centavos}, {self.moneda!r})  # {self.formateado()}"
