"""IVA — y el viaje de ida y vuelta que casi nadie prueba.

EL PROBLEMA. En Colombia el precio se define CON IVA y es redondo: $139.900.
Siigo, en cambio, quiere la base sin IVA. Así que el catálogo guarda la base y
la pantalla vuelve a sumar el impuesto.

Ese viaje NO siempre regresa al mismo número. Dividir 139.900 entre 1,19 da
117.563,025…, se redondea a 117.563,03, y al multiplicar de vuelta sale
139.900,01. Un centavo — pero la cajera ve **$139.900,01** en la etiqueta de
una prenda que cuesta $139.900, y eso no se puede explicar en un mostrador.

Lo encontré mirando la rejilla del POS: una de cada seis referencias de la
siembra mostraba el centavo de más.

LA SOLUCIÓN. No redondear a ciegas: elegir la base que SÍ regresa. Siempre
existe —el error nunca pasa de un centavo— y encontrarla cuesta una resta.

Esto lo necesita el sincronizador de catálogo tanto como la siembra: el
precio llega de Shopify con IVA incluido, y guardarlo mal significa vender
todo el año con un centavo de diferencia entre la etiqueta y la factura.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Union

__all__ = ["iva_de", "con_iva", "base_desde_vitrina", "separar_iva"]

Tasa = Union[int, str, Decimal]


def _tasa(t: Tasa) -> Decimal:
    if isinstance(t, float):
        raise TypeError("la tarifa de IVA no se expresa en float")
    return Decimal(t)


def iva_de(base_centavos: int, tasa: Tasa = 19) -> int:
    """El impuesto sobre una base, redondeado medio hacia arriba.

    Mismo redondeo que `Dinero.porcentaje` — si difirieran, el total de la
    pantalla no coincidiría con el de la factura.
    """
    return int((Decimal(base_centavos) * _tasa(tasa) / 100).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))


def con_iva(base_centavos: int, tasa: Tasa = 19) -> int:
    """El precio de vitrina: lo que la clienta reconoce."""
    return base_centavos + iva_de(base_centavos, tasa)


def base_desde_vitrina(precio_con_iva_centavos: int, tasa: Tasa = 19) -> int:
    """La base que, al volver a sumarle el IVA, da EXACTAMENTE este precio.

    La división redondeada no siempre regresa (139.900 → 117.563,03 →
    139.900,01). Aquí se prueba la candidata y, si se pasa o se queda corta,
    se ajusta de a un centavo. El error nunca supera uno, así que el bucle da
    a lo sumo dos vueltas.

    ATENCIÓN — NO SIEMPRE EXISTE. Con IVA del 19% el total salta de a uno o de
    a dos centavos según la base, así que hay precios INALCANZABLES: para
    $139.900 la base 11756302 da 13.989.999 y la siguiente da 13.990.001. El
    número exacto no se puede formar.

    Cuando pasa, se devuelve la base más cercana POR DEBAJO: cobrar un centavo
    de menos es preferible a cobrar uno de más, y desde luego preferible a
    mostrar un precio que no existe.

    ESTO ES UN PARCHE, NO LA SOLUCIÓN. El modelo correcto es el del handoff:
    el precio ES el de vitrina, y el IVA se DERIVA del total
    (`separar_iva`). Guardar la base como fuente de verdad obliga a este
    baile y deja un centavo suelto en los precios inalcanzables. Ver
    docs/retail-pos/02-DOMINIO-DDD.md.
    """
    t = _tasa(tasa)
    if precio_con_iva_centavos <= 0:
        return 0

    candidata = int((Decimal(precio_con_iva_centavos) / (1 + t / 100)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))

    for ajuste in (0, -1, 1, -2, 2):
        base = candidata + ajuste
        if base > 0 and con_iva(base, tasa) == precio_con_iva_centavos:
            return base

    # Ninguna cuadra exacto: la mayor que no se pase.
    base = candidata
    while base > 1 and con_iva(base, tasa) > precio_con_iva_centavos:
        base -= 1
    return base


def separar_iva(precio_con_iva_centavos: int, tasa: Tasa = 19) -> tuple:
    """Parte un precio de vitrina en (base, IVA). SIEMPRE suma el total.

    Es el modelo del handoff —«IVA incluido, calculado como total − total/1,19»—
    y el que usa el comercio colombiano: el precio es el número redondo de la
    etiqueta, y el impuesto es una lectura de ese número.

    A diferencia de `base_desde_vitrina`, esto no puede fallar: la base sale
    por resta, así que base + IVA da el total exacto para CUALQUIER precio.
    """
    t = _tasa(tasa)
    if t == 0:
        return (precio_con_iva_centavos, 0)
    base = int((Decimal(precio_con_iva_centavos) / (1 + t / 100)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))
    return (base, precio_con_iva_centavos - base)
