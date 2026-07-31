"""Cierre diario de postventa por punto de venta.

EL PROBLEMA: el excedente lo paga la clienta en el datafono o la caja fisica
de la tienda, pero la factura sale por FV-5 desde Siigo Nube. El POS nunca se
entera. Al cerrar el dia la cajera tiene MAS plata de la que su cierre dice, y
no sabe de donde salio.

No podemos conectarnos al POS, asi que el modulo entrega el dato al reves:
esto es lo que la cajera suma a su arqueo.

REGLA CENTRAL: aqui solo va PLATA QUE ENTRO A LA CAJA. El anticipo NO es
plata — es el credito de la nota credito. Contarlo inflaria el arqueo con
dinero que nunca paso por ahi.
"""
from backend.services import postventa_caja as C
from backend.services import fiscal_logic as F

DATAFONO_FL, CAJA_FL = 12244, 12243
DATAFONO_ARR = 8987


def _doc(tienda, dia, pagos, *, caso="PV-2026-0001", factura="FV-5-1",
         kind="factura", status="emitido"):
    """Fila de postventa_fiscal como la guarda el motor: `amount` es el total
    del documento (incluye el anticipo), y `payload_snapshot` los pagos."""
    return {"doc_kind": kind, "status": status, "created_at": f"{dia}T15:00:00Z",
            "siigo_document_number": factura,
            "amount": sum(p["value"] for p in pagos),
            "payload_snapshot": {"payments": pagos},
            "caso": {"tienda": tienda, "case_number": caso}}


HOY = "2026-07-30"


def test_suma_lo_cobrado_en_ese_punto_ese_dia():
    docs = [_doc("florida_caja1", HOY, [{"id": DATAFONO_FL, "value": 30000}]),
            _doc("florida_caja1", HOY, [{"id": CAJA_FL, "value": 15000}])]
    r = C.cierre_del_dia(docs, tienda="florida_caja1", fecha=HOY)
    assert r["total_cobrado"] == 45000


def test_el_anticipo_no_es_plata_de_la_caja():
    """Es el credito de la NC. Sumarlo inflaria el arqueo."""
    docs = [_doc("florida_caja1", HOY, [
        {"id": F.ANTICIPO_CLIENTES_ID, "value": 149900},
        {"id": DATAFONO_FL, "value": 20000}])]
    r = C.cierre_del_dia(docs, tienda="florida_caja1", fecha=HOY)
    assert r["total_cobrado"] == 20000


def test_desglosa_por_medio_de_pago():
    """Lo que la cajera necesita: cuanto por datafono y cuanto en efectivo."""
    docs = [_doc("florida_caja1", HOY, [{"id": DATAFONO_FL, "value": 30000}]),
            _doc("florida_caja1", HOY, [{"id": DATAFONO_FL, "value": 10000},
                                        {"id": CAJA_FL, "value": 5000}])]
    r = C.cierre_del_dia(docs, tienda="florida_caja1", fecha=HOY)
    por = {m["id"]: m["total"] for m in r["por_medio"]}
    assert por[DATAFONO_FL] == 40000
    assert por[CAJA_FL] == 5000


def test_el_medio_trae_su_nombre():
    docs = [_doc("florida_caja1", HOY, [{"id": DATAFONO_FL, "value": 30000}])]
    r = C.cierre_del_dia(docs, tienda="florida_caja1", fecha=HOY)
    assert r["por_medio"][0]["nombre"] == "Datáfono Florida"


def test_no_mezcla_tiendas():
    """Arrayanes no puede aparecer en el cierre de Florida."""
    docs = [_doc("florida_caja1", HOY, [{"id": DATAFONO_FL, "value": 30000}]),
            _doc("arrayanes", HOY, [{"id": DATAFONO_ARR, "value": 99000}])]
    assert C.cierre_del_dia(docs, tienda="florida_caja1",
                            fecha=HOY)["total_cobrado"] == 30000


def test_no_mezcla_dias():
    docs = [_doc("florida_caja1", HOY, [{"id": DATAFONO_FL, "value": 30000}]),
            _doc("florida_caja1", "2026-07-29", [{"id": DATAFONO_FL, "value": 99000}])]
    assert C.cierre_del_dia(docs, tienda="florida_caja1",
                            fecha=HOY)["total_cobrado"] == 30000


def test_lo_no_emitido_no_cuenta():
    """Un preview que nunca se emitio no cobro nada."""
    docs = [_doc("florida_caja1", HOY, [{"id": DATAFONO_FL, "value": 30000}],
                 status="pendiente")]
    assert C.cierre_del_dia(docs, tienda="florida_caja1",
                            fecha=HOY)["total_cobrado"] == 0


def test_las_notas_credito_no_son_plata_pero_se_reportan():
    """No entran al arqueo, pero la tienda recibio prendas: se informa aparte."""
    docs = [_doc("florida_caja1", HOY, [{"id": F.ANTICIPO_CLIENTES_ID, "value": 149900}],
                 kind="nota_credito", factura="NC-1-7120")]
    r = C.cierre_del_dia(docs, tienda="florida_caja1", fecha=HOY)
    assert r["total_cobrado"] == 0
    assert r["notas_credito"]["cantidad"] == 1
    assert r["notas_credito"]["total"] == 149900


def test_lista_los_casos_para_poder_auditarlos():
    """Si el arqueo no cuadra, la cajera tiene que poder ir caso por caso."""
    docs = [_doc("florida_caja1", HOY, [{"id": DATAFONO_FL, "value": 30000}],
                 caso="PV-2026-0007", factura="FV-5-12")]
    c = C.cierre_del_dia(docs, tienda="florida_caja1", fecha=HOY)["casos"][0]
    assert c["caso"] == "PV-2026-0007"
    assert c["factura"] == "FV-5-12"
    assert c["cobrado"] == 30000


def test_un_dia_sin_movimiento_da_cero_no_error():
    r = C.cierre_del_dia([], tienda="florida_caja1", fecha=HOY)
    assert r["total_cobrado"] == 0
    assert r["casos"] == []


def test_las_dos_cajas_de_florida_se_reportan_por_separado():
    """Comparten bodega pero son cajas distintas: cada una cierra la suya."""
    docs = [_doc("florida_caja1", HOY, [{"id": DATAFONO_FL, "value": 30000}]),
            _doc("florida_caja2", HOY, [{"id": DATAFONO_FL, "value": 12000}])]
    assert C.cierre_del_dia(docs, tienda="florida_caja2",
                            fecha=HOY)["total_cobrado"] == 12000
