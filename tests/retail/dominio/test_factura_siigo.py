"""La factura que el POS le manda a Siigo.

Corre sin red y sin base: se prueba la TRADUCCIÓN, que es donde está el
riesgo. Lo que Siigo hace con ella no lo puede validar una prueba —sólo la
primera emisión real, en modo prueba— y por eso aquí cada aserción dice de
dónde sale: de cómo emite Postventa, que lleva meses haciéndolo, o de un
rechazo ya visto.
"""
from __future__ import annotations

import pytest

from backend.modules.retail.infrastructure.siigo.factura_venta import (
    CONSUMIDOR_FINAL,
    FacturaInvalida,
    construir_factura,
    marca_de,
)

VENTA = {"id": "01M4E2HW87DDSGBPZ9DYNK6W2V", "numero": "ARRPOS-11390",
         "total": 14990000}


def _linea(precio=14990000, cantidad=1, descuento=0, sku="12617-2T6"):
    return {"sku": sku, "descripcion": "JEAN SKINNY · Talla 6",
            "cantidad": cantidad, "precio_unitario": precio,
            "descuento_monto": descuento, "tasa_iva": "19.00"}


def _pago(neto, forma=8282, medio="efectivo_arrayanes"):
    return {"medio_pago_id": medio, "siigo_forma_pago_id": forma, "neto": neto}


def _factura(**kw):
    base = dict(venta=VENTA, lineas=[_linea()], pagos=[_pago(14990000)],
                documento_id=40001, tipo_descuento="Value", vendedor_id=842,
                fecha="2026-10-08", bodega_id=37, centro_costo_id=677)
    base.update(kw)
    return construir_factura(**base)


# ── Lo básico ───────────────────────────────────────────────────────────────

def test_el_precio_viaja_SIN_iva():
    """$149.900 de etiqueta son $125.966,39 de base. Mandar el de la etiqueta
    haría que Siigo le sumara el 19 % otra vez."""
    f = _factura()
    assert f["items"][0]["price"] == 125966.39
    assert f["items"][0]["taxes"] == [{"id": 6352}]
    assert f["payments"] == [{"id": 8282, "value": 149900.0,
                              "due_date": "2026-10-08"}]


def test_sin_clienta_va_a_consumidor_final():
    assert _factura()["customer"] == {"identification": CONSUMIDOR_FINAL,
                                      "branch_office": 0}
    con = _factura(identificacion="24435107")
    assert con["customer"]["identification"] == "24435107"


def test_la_bodega_es_un_NUMERO():
    """`{"id": 37}` no da error: Siigo lo descarta y el inventario no se
    mueve. Pasó con las notas crédito de Postventa."""
    assert _factura()["items"][0]["warehouse"] == 37


def test_la_factura_lleva_la_marca_para_reencontrarla():
    """Siigo no tiene llave de idempotencia. Si el envío se corta sin
    respuesta, lo único que permite saber si llegó es buscarla por esto."""
    f = _factura()
    assert f["observations"] == marca_de(VENTA["id"], "ARRPOS-11390")
    assert VENTA["id"] in f["observations"]


def test_en_prueba_NO_se_estampa():
    """Sin `stamp` el documento queda en Siigo y no va a la DIAN."""
    assert "stamp" not in _factura()
    assert _factura(estampar=True)["stamp"] == {"send": True}


# ── EL CENTAVO ──────────────────────────────────────────────────────────────

def test_los_pagos_cuadran_con_lo_que_calcula_SIIGO_no_con_el_pos():
    """Dos jeans de $149.900 son $299.800 para el POS y $299.800,01 para
    Siigo, que redondea la base antes del impuesto. Un centavo de diferencia
    en los pagos rechaza la factura entera."""
    venta = {**VENTA, "total": 29980000}
    f = _factura(venta=venta, lineas=[_linea(cantidad=2)],
                 pagos=[_pago(29980000)])
    assert f["_resumen"]["total_pos"] == 299800.0
    assert f["_resumen"]["total_siigo"] == 299800.01
    assert f["payments"][0]["value"] == 299800.01
    assert f["_resumen"]["ajuste_centavos"] == 0.01


def test_el_ajuste_va_al_pago_mas_grande():
    venta = {**VENTA, "total": 29980000}
    f = _factura(venta=venta, lineas=[_linea(cantidad=2)],
                 pagos=[_pago(10000000, forma=8987, medio="datafono"),
                        _pago(19980000)])
    por_forma = {p["id"]: p["value"] for p in f["payments"]}
    assert por_forma == {8987: 100000.0, 8282: 199800.01}
    assert round(sum(por_forma.values()), 2) == f["_resumen"]["total_siigo"]


def test_a_siigo_van_los_pagos_NETOS():
    """Entregó $300.000 por $299.800: lo que se factura en efectivo es lo que
    entró. Aquí llega ya neto; si llegara lo entregado, no se emite."""
    venta = {**VENTA, "total": 29980000}
    with pytest.raises(FacturaInvalida, match="no cubren"):
        _factura(venta=venta, lineas=[_linea(cantidad=2)],
                 pagos=[_pago(30000000)])


# ── El descuento ────────────────────────────────────────────────────────────

def test_el_descuento_en_PESOS_cuando_el_comprobante_lo_pide_asi():
    """20 % sobre $149.900 = $29.980 con IVA = $25.193,28 de base."""
    venta = {**VENTA, "total": 11992000}
    f = _factura(venta=venta, lineas=[_linea(descuento=2998000)],
                 pagos=[_pago(11992000)], tipo_descuento="Value")
    assert f["items"][0]["discount"] == 25193.28
    assert f["_resumen"]["total_siigo"] == 119920.0


def test_el_descuento_en_PORCENTAJE_cuando_el_comprobante_lo_pide_asi():
    venta = {**VENTA, "total": 11992000}
    f = _factura(venta=venta, lineas=[_linea(descuento=2998000)],
                 pagos=[_pago(11992000)], tipo_descuento="Percentage")
    assert f["items"][0]["discount"] == 20.0


def test_sin_saber_la_unidad_del_descuento_NO_se_emite():
    """Mandarlo en la unidad equivocada no da error: sale una factura con
    otro valor, y ya fue a la DIAN."""
    venta = {**VENTA, "total": 11992000}
    with pytest.raises(FacturaInvalida, match="pesos o en"):
        _factura(venta=venta, lineas=[_linea(descuento=2998000)],
                 pagos=[_pago(11992000)], tipo_descuento=None)


# ── Lo que no se factura ────────────────────────────────────────────────────

def test_un_medio_sin_forma_de_pago_en_siigo_no_se_emite():
    with pytest.raises(FacturaInvalida, match="forma de pago"):
        _factura(pagos=[_pago(14990000, forma=None, medio="transferencia")])


def test_un_iva_que_no_es_19_no_se_emite_con_el_impuesto_equivocado():
    linea = {**_linea(), "tasa_iva": "5.00"}
    with pytest.raises(FacturaInvalida, match="IVA"):
        _factura(lineas=[linea])


def test_si_el_total_no_coincide_con_la_venta_no_se_emite():
    """Más de un peso de diferencia ya no es redondeo."""
    with pytest.raises(FacturaInvalida, match="no coincide"):
        _factura(venta={**VENTA, "total": 13990000})
