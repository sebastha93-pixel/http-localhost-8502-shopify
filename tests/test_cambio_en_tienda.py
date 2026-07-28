import pytest
from backend.services import fiscal_logic as F
from backend.services import tiendas


FACTURA_ONLINE = {
    "id": "f-online", "name": "FV-1-64151",
    "customer": {"identification": "30384838", "branch_office": 0},
    "seller": 658,
    "items": [{"code": "A-10", "description": "Jean - 10", "quantity": 1,
               "price": 125966.39, "seller": 658,
               "warehouse": {"id": 32, "name": "MELONN"},   # bodega online
               "taxes": [{"id": 6352}]}],
}

BODEGA_FLORIDA = 5      # confirmada por el fundador


# ── La prenda entra a la tienda, no a la bodega online ────────────────
def test_nc_en_tienda_ingresa_a_la_bodega_de_la_tienda():
    p = F.construir_payload_nota_credito(
        factura=FACTURA_ONLINE, skus_a_acreditar=["A-10"],
        modo="prueba", fecha="2026-07-27", bodega_destino=BODEGA_FLORIDA)
    # Sin traslado manual: la prenda queda donde físicamente está.
    assert p["items"][0]["warehouse"] == {"id": BODEGA_FLORIDA}


def test_nc_online_conserva_la_bodega_de_origen():
    p = F.construir_payload_nota_credito(
        factura=FACTURA_ONLINE, skus_a_acreditar=["A-10"],
        modo="prueba", fecha="2026-07-27")
    assert p["items"][0]["warehouse"] == {"id": 32}    # MELONN


# ── La factura sale del punto de venta correcto ───────────────────────
def test_factura_sale_con_el_documento_de_la_tienda():
    item = {"code": "B-12", "description": "Jean nuevo", "price_base": 134369.75}
    p = F.construir_payload_factura_reemplazo(
        factura_original=FACTURA_ONLINE, item_reemplazo=item,
        credito_con_iva=149900.0, modo="prueba", fecha="2026-07-27",
        documento_id=31433, bodega_id=BODEGA_FLORIDA)
    assert p["document"]["id"] == 31433              # FV-11, no el de online
    assert p["items"][0]["warehouse"] == {"id": BODEGA_FLORIDA}


def test_sin_documento_usa_el_de_online():
    item = {"code": "B-12", "description": "Jean", "price_base": 134369.75}
    p = F.construir_payload_factura_reemplazo(
        factura_original=FACTURA_ONLINE, item_reemplazo=item,
        credito_con_iva=149900.0, modo="prueba", fecha="2026-07-27")
    assert p["document"]["id"] == 11810


# ── El excedente se cobra en la tienda ────────────────────────────────
def test_excedente_se_cobra_con_la_forma_de_pago_de_la_tienda():
    item = {"code": "CARA", "description": "Jean premium", "price_base": 168067.23}
    p = F.construir_payload_factura_reemplazo(
        factura_original=FACTURA_ONLINE, item_reemplazo=item,
        credito_con_iva=149900.0, modo="prueba", fecha="2026-07-27",
        pago_excedente_id=12244)                      # Datáfono Florida
    pagos = {x["id"]: x["value"] for x in p["payments"]}
    assert 8316 in pagos                              # anticipo cruza
    assert 12244 in pagos                             # excedente en el datáfono
    assert 8857 not in pagos                          # NO cuentas por cobrar
    assert round(sum(pagos.values()), 2) == round(p["_resumen"]["total"], 2)


def test_online_sin_forma_de_pago_usa_cuentas_por_cobrar():
    item = {"code": "CARA", "description": "Jean", "price_base": 168067.23}
    p = F.construir_payload_factura_reemplazo(
        factura_original=FACTURA_ONLINE, item_reemplazo=item,
        credito_con_iva=149900.0, modo="prueba", fecha="2026-07-27")
    assert any(x["id"] == 8857 for x in p["payments"])


# ── Configuración de tiendas ──────────────────────────────────────────
def test_no_factura_sin_documento_confirmado():
    # La bodega ya se conoce, pero sin el documento la factura saldría con el
    # prefijo de otro punto y descuadraría la numeración DIAN.
    with pytest.raises(ValueError, match="tienda_sin_configurar"):
        tiendas.validar_para_facturar("florida_caja1")


def test_tienda_desconocida():
    with pytest.raises(ValueError, match="tienda_desconocida"):
        tiendas.validar_para_facturar("cartagena")


def test_config_por_env(monkeypatch):
    monkeypatch.setenv("TIENDAS_JSON",
                       '{"florida_caja1": {"documento_factura_id": 31433}}')
    t = tiendas.validar_para_facturar("florida_caja1")
    assert t["documento_factura_id"] == 31433
    assert t["bodega_id"] == 5                   # la bodega ya venía por default
    assert t["prefijo_factura"] == "FV-11"


def test_las_dos_cajas_de_florida_comparten_bodega():
    # Son puntos de cobro distintos (FV-11 / FV-12) de la MISMA tienda: la
    # prenda entra al mismo inventario sin importar en cuál se atienda.
    c1 = tiendas.obtener("florida_caja1")
    c2 = tiendas.obtener("florida_caja2")
    assert c1["bodega_id"] == c2["bodega_id"] == 5
    assert c1["prefijo_factura"] != c2["prefijo_factura"]
    assert c1["tienda"] == c2["tienda"] == "Florida"


def test_cada_tienda_tiene_su_bodega():
    assert tiendas.obtener("arrayanes")["bodega_id"] == 3
    assert tiendas.obtener("florida_caja1")["bodega_id"] == 5


def test_forma_de_pago_debe_ser_de_esa_tienda():
    assert tiendas.forma_pago_valida("florida_caja1", 12244) is True   # datáfono Florida
    assert tiendas.forma_pago_valida("florida_caja1", 8987) is False   # caja Arrayanes


def test_listar_dice_que_falta():
    fl = [t for t in tiendas.listar() if t["clave"] == "florida_caja1"][0]
    assert fl["lista"] is False
    assert "documento_factura_id" in fl["falta"]
