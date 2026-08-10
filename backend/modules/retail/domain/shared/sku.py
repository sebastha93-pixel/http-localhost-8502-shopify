"""Sku — el identificador de una variante, y la llave de búsqueda del POS.

FORMATO MALE'DENIM: `<referencia>T<talla>`.

    92611-1T10  →  referencia '92611-1', talla '10'
    95527-1T4   →  referencia '95527-1', talla '4'

El `-1` es parte de la referencia, no de la talla. Se lee así porque es
exactamente lo que hace `backend.services.siigo._parse_ref_talla`, que ya
alimenta el inventario por bodega y el análisis de venta por colección. Si el
POS parseara distinto, la misma prenda tendría dos identidades dentro del
mismo sistema y ningún informe cuadraría.

Hay una prueba de contrato (`test_coincide_con_el_parseo_que_ya_usa_el_erp`)
que falla si alguno de los dos cambia sin el otro.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Tuple

__all__ = ["Sku", "SkuInvalido"]


class SkuInvalido(ValueError):
    """El código no sirve como identificador de una variante."""


# La talla es el número FINAL. La `T` que la precede puede aparecer también
# dentro de la referencia (`92T33-1T6`), y por eso el cuantificador es perezoso
# y el patrón está anclado al final: obliga a que la última T gane.
_PATRON = re.compile(r"^(.*?T)(\d+)$", re.IGNORECASE)


@dataclass(frozen=True)
class Sku:
    """Código de una variante, ya descompuesto. Inmutable y comparable."""

    codigo: str
    referencia: str
    talla: str

    # ── Construcción ────────────────────────────────────────────────────────

    @classmethod
    def parsear(cls, code: str) -> "Sku":
        if not isinstance(code, str):
            raise SkuInvalido(
                f"el SKU debe ser texto, no {type(code).__name__}. "
                f"Un código numérico pierde los ceros a la izquierda."
            )
        limpio = code.strip().upper()
        if not limpio:
            raise SkuInvalido("el SKU no puede estar vacío")

        referencia, talla = cls._descomponer(limpio)
        return cls(codigo=limpio, referencia=referencia, talla=talla)

    @staticmethod
    def _descomponer(limpio: str) -> Tuple[str, str]:
        m = _PATRON.match(limpio)
        if m:
            return m.group(1).rstrip("Tt"), m.group(2)
        # Sin talla al final no se adivina ninguna: un SKU así es un dato que
        # hay que revisar, no algo que el sistema deba completar solo.
        return limpio, ""

    # ── Lectura ─────────────────────────────────────────────────────────────

    @property
    def referencia_base(self) -> str:
        """La referencia sin el sufijo de variante: `92611-1` → `92611`.

        Sirve para agrupar colores en la rejilla del POS: quien busca '92611'
        quiere ver toda la referencia, no una sola variante.
        """
        return self.referencia.split("-", 1)[0]

    def tiene_talla(self) -> bool:
        return bool(self.talla)

    def orden_talla(self) -> Tuple[int, int, str]:
        """Clave de ordenamiento: la talla 4 va antes que la 10.

        Ordenar como texto pondría la 10 antes de la 4, y en la rejilla del POS
        eso obliga a buscar la talla en un desorden, cada vez.

        Las tallas no numéricas van al final, con el mismo criterio que
        `postventa_inventario._talla_num`, para que el POS y el inventario
        ordenen igual.
        """
        try:
            return (0, int(self.talla), "")
        except ValueError:
            return (1, 0, self.talla)

    def __str__(self) -> str:
        return self.codigo

    def __repr__(self) -> str:
        return f"Sku({self.codigo!r})  # ref={self.referencia} talla={self.talla or '—'}"
