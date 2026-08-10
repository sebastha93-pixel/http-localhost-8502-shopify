"""Descuento — el control anti-fraude más rentable de un POS.

Un descuento es la única forma legítima que tiene una cajera de bajar el
precio, y por eso es la vía por la que se saca mercancía. Las reglas de este
objeto de valor son las que hacen que quede rastro:

  · siempre lleva motivo escrito
  · nunca puede superar el valor de la línea (INV-V4: el total no es negativo)
  · un porcentaje está entre 0 y 100, sin excepciones

Quién puede aplicarlo y hasta cuánto es otra cosa —eso lo decide
`PoliticaDescuento` con el rol de quien lo aplica— y va aparte a propósito: el
objeto sabe *qué* es un descuento, la política sabe *quién* puede.
"""
from decimal import Decimal

import pytest

from backend.modules.retail.domain.shared.dinero import Dinero
from backend.modules.retail.domain.venta.descuento import (
    Descuento,
    DescuentoInvalido,
    TipoDescuento,
)

COP = "COP"


def precio(pesos: str) -> Dinero:
    return Dinero.desde_pesos(pesos, COP)


# ── Porcentaje ──────────────────────────────────────────────────────────────

def test_descuento_por_porcentaje():
    d = Descuento.porcentaje(10, motivo="prenda con defecto menor")
    assert d.tipo is TipoDescuento.PORCENTAJE
    assert d.calcular_sobre(precio("89900")) == precio("8990")


def test_porcentaje_acepta_decimales():
    d = Descuento.porcentaje(Decimal("12.5"), motivo="campaña")
    assert d.calcular_sobre(precio("100000")) == precio("12500")


def test_porcentaje_fuera_de_rango():
    for malo in [-1, 101, 150]:
        with pytest.raises(DescuentoInvalido):
            Descuento.porcentaje(malo, motivo="prueba de rango")


def test_porcentaje_de_cien_deja_la_linea_en_cero():
    """Es válido, pero es un obsequio: la política lo va a exigir autorizado."""
    d = Descuento.porcentaje(100, motivo="obsequio autorizado")
    assert d.calcular_sobre(precio("89900")) == precio("89900")


def test_porcentaje_no_acepta_float():
    with pytest.raises(TypeError):
        Descuento.porcentaje(10.5, motivo="x")  # type: ignore[arg-type]


# ── Valor fijo ──────────────────────────────────────────────────────────────

def test_descuento_por_valor():
    d = Descuento.valor(precio("10000"), motivo="cliente frecuente")
    assert d.tipo is TipoDescuento.VALOR
    assert d.calcular_sobre(precio("89900")) == precio("10000")


def test_el_descuento_por_valor_no_puede_superar_la_linea():
    """Un descuento mayor que el precio deja el total negativo.

    Se rechaza aquí, en el dominio, y no en la pantalla: la pantalla se puede
    saltar, el agregado no.
    """
    d = Descuento.valor(precio("100000"), motivo="prueba de tope")
    with pytest.raises(DescuentoInvalido, match="supera"):
        d.calcular_sobre(precio("89900"))


def test_el_descuento_por_valor_debe_ser_positivo():
    for malo in ["0", "-5000"]:
        with pytest.raises(DescuentoInvalido):
            Descuento.valor(precio(malo), motivo="prueba de signo")


# ── El motivo no es opcional ────────────────────────────────────────────────

def test_sin_motivo_no_hay_descuento():
    """Un descuento sin motivo es un descuadre sin explicación en la auditoría."""
    for vacio in ["", "   ", None]:
        with pytest.raises(DescuentoInvalido, match="motivo"):
            Descuento.porcentaje(10, motivo=vacio)  # type: ignore[arg-type]


def test_el_motivo_se_limpia_pero_se_conserva():
    d = Descuento.porcentaje(10, motivo="  defecto menor  ")
    assert d.motivo == "defecto menor"


def test_motivo_demasiado_corto_no_explica_nada():
    with pytest.raises(DescuentoInvalido):
        Descuento.porcentaje(10, motivo="x")


# ── Objeto de valor ─────────────────────────────────────────────────────────

def test_es_inmutable_y_comparable():
    a = Descuento.porcentaje(10, motivo="defecto menor")
    b = Descuento.porcentaje(10, motivo="defecto menor")
    assert a == b
    with pytest.raises(Exception):
        a.valor_aplicado = Decimal("20")  # type: ignore[misc]


def test_descripcion_legible_para_el_ticket():
    assert Descuento.porcentaje(10, motivo="defecto menor").descripcion() == "−10% · defecto menor"
    assert Descuento.valor(precio("10000"), motivo="cortesía").descripcion() == "−$10.000 · cortesía"


def test_moneda_distinta_al_calcular_es_un_error():
    from backend.modules.retail.domain.shared.dinero import MonedaDistinta
    d = Descuento.valor(Dinero.desde_pesos("100", "USD"), motivo="prueba de moneda")
    with pytest.raises(MonedaDistinta):
        d.calcular_sobre(precio("89900"))
