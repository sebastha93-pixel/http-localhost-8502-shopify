"""Cobertura del cambio EN TIENDA en el banco de pruebas.

Este archivo existe por un bug real: el banco excluia a proposito las
facturas de tienda (`continue  # facturas de tienda fisica`), asi que los
"20/20 en verde" solo cubrian compras online. El flujo presencial —el que
mas plata mueve por caja— nunca se probo, y se rompio en produccion.

Lo que se verifica aqui es lo que NO puede fallar en un cambio presencial:
la prenda entra a la bodega correcta, la factura sale con el prefijo del
punto, y el excedente se cobra en esa caja.
"""
from backend.services import postventa_banco_pruebas as B
from backend.services import tiendas


# ── Que facturas sirven para probar el flujo de tienda ─────────────────────

FACTURAS = [
    # Online: tiene "Orden Nº", NO sirve para el escenario de tienda.
    {"id": "f1", "name": "FV-1-64151", "document": {"id": 11810},
     "observations": "Orden Nº: 61208", "stamp": {"status": "Accepted"}},
    # Florida Caja 1: la que buscamos.
    {"id": "f2", "name": "FV-11-1202", "document": {"id": 31433},
     "observations": "", "stamp": {"status": "Accepted"}},
    # Arrayanes, pero la DIAN aun no la acepta: no admite nota credito.
    {"id": "f3", "name": "FV-6-902", "document": {"id": 29192},
     "observations": "", "stamp": {"status": "InProcess"}},
    # Arrayanes aceptada.
    {"id": "f4", "name": "FV-6-880", "document": {"id": 29192},
     "observations": "", "stamp": {"status": "Accepted"}},
]


def test_solo_toma_facturas_de_tienda_ya_aceptadas():
    elegidas = B.facturas_de_tienda(FACTURAS)
    assert [f["factura"] for f in elegidas] == ["FV-11-1202", "FV-6-880"]


def test_cada_factura_sabe_a_que_punto_de_venta_pertenece():
    porc = {f["factura"]: f for f in B.facturas_de_tienda(FACTURAS)}
    assert porc["FV-11-1202"]["tienda"] == "florida_caja1"
    assert porc["FV-6-880"]["tienda"] == "arrayanes"


def test_lleva_el_id_de_la_factura_no_el_numero_de_pedido():
    """Una compra de tienda no tiene pedido: se enlaza por id."""
    f = B.facturas_de_tienda(FACTURAS)[0]
    assert f["factura_id"] == "f2"
    assert f.get("numero_pedido") in (None, "")


# ── La prenda entra a la bodega de ESA tienda ──────────────────────────────

def test_la_nc_ingresa_a_la_bodega_del_punto():
    payload = {"items": [{"code": "A-1", "warehouse": {"id": tiendas.BODEGA_FLORIDA}}]}
    ok, det = B.verificar_bodega_nc(payload, "florida_caja1")
    assert ok, det


def test_falla_si_la_nc_entra_a_la_bodega_equivocada():
    """El error silencioso mas caro: el inventario de la tienda queda corto
    y el de MELONN inflado, y nadie se entera hasta el conteo."""
    payload = {"items": [{"code": "A-1", "warehouse": {"id": 32}}]}
    ok, det = B.verificar_bodega_nc(payload, "florida_caja1")
    assert not ok
    assert "32" in det and str(tiendas.BODEGA_FLORIDA) in det


def test_las_dos_cajas_de_florida_comparten_bodega():
    payload = {"items": [{"code": "A-1", "warehouse": {"id": tiendas.BODEGA_FLORIDA}}]}
    assert B.verificar_bodega_nc(payload, "florida_caja2")[0]


def test_arrayanes_no_acepta_la_bodega_de_florida():
    payload = {"items": [{"code": "A-1", "warehouse": {"id": tiendas.BODEGA_FLORIDA}}]}
    assert not B.verificar_bodega_nc(payload, "arrayanes")[0]


# ── La factura sale con el prefijo del punto ───────────────────────────────

def test_la_factura_usa_el_documento_del_punto():
    ok, det = B.verificar_documento_factura({"document": {"id": tiendas.DOC_FV11}},
                                            "florida_caja1")
    assert ok, det


def test_falla_si_la_factura_sale_como_venta_online():
    """Facturar un cambio de tienda con FV-1 descuadra la venta del punto."""
    ok, det = B.verificar_documento_factura({"document": {"id": 11810}},
                                            "florida_caja1")
    assert not ok
    assert str(tiendas.DOC_FV11) in det


def test_cada_caja_de_florida_tiene_su_propio_prefijo():
    assert B.verificar_documento_factura({"document": {"id": tiendas.DOC_FV12}},
                                         "florida_caja2")[0]
    assert not B.verificar_documento_factura({"document": {"id": tiendas.DOC_FV12}},
                                             "florida_caja1")[0]


# ── El excedente se cobra en la caja de ese punto ──────────────────────────

def test_el_excedente_se_cobra_con_una_forma_de_pago_del_punto():
    pago = tiendas.obtener("arrayanes")["formas_pago"][0]["id"]
    ok, det = B.verificar_pago_excedente({"payments": [{"id": pago, "value": 20000}]},
                                         "arrayanes")
    assert ok, det


def test_falla_si_el_excedente_queda_como_cuenta_por_cobrar():
    """En tienda la clienta esta presente y paga ahi mismo: dejarlo en CxC
    es plata que nadie va a cobrar."""
    from backend.services import fiscal_logic as F
    ok, det = B.verificar_pago_excedente(
        {"payments": [{"id": F.EXCEDENTE_PAYMENT_ID, "value": 20000}]}, "arrayanes")
    assert not ok


def test_falla_si_cobra_en_la_caja_de_otra_tienda():
    pago_florida = tiendas.obtener("florida_caja1")["formas_pago"][0]["id"]
    ok, _ = B.verificar_pago_excedente(
        {"payments": [{"id": pago_florida, "value": 20000}]}, "arrayanes")
    assert not ok


def test_sin_excedente_no_hay_nada_que_validar():
    """Si la prenda nueva vale igual o menos, el anticipo cubre todo."""
    assert B.verificar_pago_excedente({"payments": []}, "arrayanes")[0]


def test_una_nc_sin_items_no_puede_pasar_como_verificada():
    """Un payload vacio no prueba nada. Si la verificacion lo diera por bueno,
    el banco daria verde sin haber mirado la bodega — el mismo hueco que dejo
    pasar este bug la primera vez."""
    ok, det = B.verificar_bodega_nc({}, "florida_caja1")
    assert not ok
    assert "sin items" in det.lower()


def test_el_anticipo_no_es_un_cobro_de_caja():
    """El ANTICIPO (8316) es el credito que dejo la nota credito, no plata que
    entre por la caja: siempre esta en la factura y es legitimo. Exigirle que
    sea una forma de pago de la tienda hacia fallar todo cambio sin excedente."""
    from backend.services import fiscal_logic as F
    ok, det = B.verificar_pago_excedente(
        {"payments": [{"id": F.ANTICIPO_CLIENTES_ID, "value": 119000}]}, "arrayanes")
    assert ok, det


def test_con_anticipo_mas_excedente_solo_se_juzga_el_excedente():
    from backend.services import fiscal_logic as F
    pago = tiendas.obtener("arrayanes")["formas_pago"][0]["id"]
    ok, det = B.verificar_pago_excedente({"payments": [
        {"id": F.ANTICIPO_CLIENTES_ID, "value": 119000},
        {"id": pago, "value": 20000}]}, "arrayanes")
    assert ok, det


def test_excedente_en_caja_ajena_falla_aunque_el_anticipo_este_bien():
    from backend.services import fiscal_logic as F
    pago_florida = tiendas.obtener("florida_caja1")["formas_pago"][0]["id"]
    ok, _ = B.verificar_pago_excedente({"payments": [
        {"id": F.ANTICIPO_CLIENTES_ID, "value": 119000},
        {"id": pago_florida, "value": 20000}]}, "arrayanes")
    assert not ok
