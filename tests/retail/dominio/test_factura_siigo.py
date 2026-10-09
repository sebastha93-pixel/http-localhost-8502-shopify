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

def test_sin_descuento_viaja_el_precio_DE_ETIQUETA_en_taxed_price():
    """Siigo deriva la base con sus seis decimales. Mandarle la base ya
    redondeada a dos fue lo que metió el centavo en la factura ARRT-1."""
    f = _factura()
    assert f["items"][0]["taxed_price"] == 149900.0
    assert "price" not in f["items"][0] and "discount" not in f["items"][0]
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


# ── LA FACTURA DA EXACTAMENTE LO QUE COBRÓ LA CAJA ──────────────────────────

def test_la_aritmetica_es_la_de_siigo_con_SUS_numeros():
    """Oráculos: lo que DEVOLVIÓ Siigo, no lo que se calculó aquí.
      · ARRT-2 (2026-10-09): 2 × $149.900 → 299.800,00; 1 × $149.900 al 10 %
        con base 125966.386555 → 134.910,00; 1 × $129.900 → 129.900,00.
      · Portal Mayoristas: 3 × $74.950 al 25 % → 168.637,51 (un rechazo).
      · ARRT-1: 2 × base 125966,39 (dos decimales) → 299.800,01."""
    from backend.modules.retail.infrastructure.siigo.factura_venta import (
        base6_de, total_linea,
    )
    assert base6_de(14990000) == 125966386555
    assert total_linea(2, base6_de(14990000)) == 29980000
    assert total_linea(1, 125966386555, 10) == 13491000
    assert total_linea(1, base6_de(12990000)) == 12990000
    assert total_linea(3, base6_de(7495000), 25) == 16863751
    assert total_linea(2, 125966390000) == 29980001


def test_dos_unidades_dan_el_doble_EXACTO_sin_centavo():
    venta = {**VENTA, "total": 29980000}
    f = _factura(venta=venta, lineas=[_linea(cantidad=2)],
                 pagos=[_pago(29980000)])
    assert [(i["quantity"], i["taxed_price"]) for i in f["items"]] == [(2, 149900.0)]
    assert f["_resumen"] == {"total_pos": 299800.0, "total_siigo": 299800.0,
                             "ajuste_centavos": 0.0}
    assert f["payments"][0]["value"] == 299800.0


def test_a_siigo_van_los_pagos_NETOS():
    """Entregó $300.000 por $299.800: lo que se factura en efectivo es lo que
    entró. Aquí llega ya neto; si llegara lo entregado, no se emite."""
    venta = {**VENTA, "total": 29980000}
    with pytest.raises(FacturaInvalida, match="no cubren"):
        _factura(venta=venta, lineas=[_linea(cantidad=2)],
                 pagos=[_pago(30000000)])


def test_un_pago_mixto_suma_el_total():
    venta = {**VENTA, "total": 29980000}
    f = _factura(venta=venta, lineas=[_linea(cantidad=2)],
                 pagos=[_pago(10000000, forma=8987, medio="datafono"),
                        _pago(19980000)])
    assert {p["id"]: p["value"] for p in f["payments"]} == {
        8987: 100000.0, 8282: 199800.0}


# ── El descuento ────────────────────────────────────────────────────────────

def test_un_porcentaje_ENTERO_viaja_como_descuento_y_cuadra_exacto():
    """Siigo sólo acepta el porcentaje entero. Va con `price` —la base a seis
    decimales— y no con el precio de etiqueta, que con descuento casi nunca
    cuadra al centavo."""
    venta = {**VENTA, "total": 13491000}
    f = _factura(venta=venta, lineas=[_linea(descuento=1499000)],
                 pagos=[_pago(13491000)], tipo_descuento="Percentage")
    [it] = f["items"]
    assert it["discount"] == 10 and it["price"] == 125966.386555
    assert "taxed_price" not in it
    assert f["_resumen"]["total_siigo"] == 134910.0


def test_la_base_se_BUSCA_cuando_la_nominal_no_cuadra():
    """1 × $89.900 al 25 % da 67.425,01 con la base nominal. Se mueve unas
    millonésimas hasta que da 67.425 — sin dejar de ser un precio de $89.900."""
    from backend.modules.retail.infrastructure.siigo.factura_venta import (
        base6_de, base_con_descuento, total_linea,
    )
    assert total_linea(1, base6_de(8990000), 25) == 6742501
    base = base_con_descuento(1, 8990000, 6742500, 25)
    assert base is not None and base != base6_de(8990000)
    assert total_linea(1, base, 25) == 6742500
    assert round(base * 119 / 100 / 10_000) == 8990000


def test_un_descuento_en_PESOS_viaja_como_el_precio_ya_rebajado():
    """«$20.000 menos» no es un porcentaje entero. La factura dice lo que se
    cobró —$129.900— sin campo de descuento."""
    venta = {**VENTA, "total": 12990000}
    f = _factura(venta=venta, lineas=[_linea(descuento=2000000)],
                 pagos=[_pago(12990000)], tipo_descuento="Percentage")
    [it] = f["items"]
    assert it["taxed_price"] == 129900.0 and "discount" not in it
    assert f["_resumen"]["total_siigo"] == 129900.0


def test_si_el_neto_no_divide_entre_las_unidades_va_una_linea_por_unidad():
    """$30.001,01 de descuento sobre 2 unidades: no hay un precio unitario que
    multiplicado por 2 dé el total. Cada unidad va con el suyo."""
    total = 2 * 14990000 - 3000101
    f = _factura(venta={**VENTA, "total": total},
                 lineas=[_linea(cantidad=2, descuento=3000101)],
                 pagos=[_pago(total)], tipo_descuento="Percentage")
    assert [i["quantity"] for i in f["items"]] == [1, 1]
    assert round(sum(i["taxed_price"] for i in f["items"]) * 100) == total
    assert f["_resumen"]["ajuste_centavos"] == 0.0


def test_si_el_comprobante_no_maneja_porcentaje_NO_se_arriesga_el_campo():
    """En un comprobante de descuento en pesos, o del que no se sabe, el
    número de `discount` significaría otra cosa. Va el precio rebajado, que
    vale en cualquiera."""
    venta = {**VENTA, "total": 13491000}
    for tipo in ("Value", None):
        f = _factura(venta=venta, lineas=[_linea(descuento=1499000)],
                     pagos=[_pago(13491000)], tipo_descuento=tipo)
        assert "discount" not in f["items"][0]
        assert f["items"][0]["taxed_price"] == 134910.0


def test_un_descuento_que_se_lleva_todo_no_se_factura():
    with pytest.raises(FacturaInvalida, match="obsequio"):
        _factura(venta={**VENTA, "total": 0}, lineas=[_linea(descuento=14990000)],
                 pagos=[_pago(1)])


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


# ── La nota crédito copia la factura ────────────────────────────────────────

def test_la_nota_credito_aplana_el_descuento_que_devuelve_el_GET():
    """El GET trae `{"percentage": 10.0, "value": 12596.64}`; con eso tal
    cual, Siigo respondió 400 «Invalid data type: discount» (2026-10-09)."""
    from backend.modules.retail.infrastructure.siigo.nota_credito_venta import (
        construir_nota_credito,
    )
    factura = {
        "id": "f-1", "seller": 842, "cost_center": 677,
        "customer": {"identification": "222222222222", "branch_office": 0},
        "items": [{"code": "25625-1T10", "description": "Jean", "quantity": 1.0,
                   "price": 125966.386555,
                   "discount": {"percentage": 10.0, "value": 12596.64},
                   "taxes": [{"id": 6352, "name": "IVA 19%"}],
                   "warehouse": {"id": 37, "name": "Arrayanes"}}],
        "payments": [{"id": 8282, "name": "Caja", "value": 134910.0}],
    }
    nc = construir_nota_credito(factura=factura, documento_id=11817,
                                fecha="2026-10-09", marca="POS ANULA x")
    [it] = nc["items"]
    assert it["discount"] == 10 and it["price"] == 125966.386555
    assert it["warehouse"] == 37 and it["taxes"] == [{"id": 6352}]
    assert nc["payments"] == [{"id": 8282, "value": 134910.0,
                               "due_date": "2026-10-09"}]
