import pytest
from backend.services import fiscal_logic as F
from backend.services import fiscal_shopify as FSH


FACTURA = {"id": "f2", "name": "FV-1-63043",
           "customer": {"identification": "30384838", "branch_office": 0},
           "seller": 658}


# ── conversión de precio ─────────────────────────────────────────────
def test_base_desde_precio_con_iva():
    assert F.base_desde_precio_con_iva(159900.0) == 134369.75


# ── payload factura reemplazo ────────────────────────────────────────
def test_reemplazo_mismo_precio_solo_anticipo():
    # nueva vale igual (base 134369.75 → total 159900), crédito 159900
    item = {"code": "REF-L", "description": "Jean flare - 12",
            "price_base": 134369.75, "warehouse": {"id": 32}}
    p = F.construir_payload_factura_reemplazo(
        factura_original=FACTURA, item_reemplazo=item,
        credito_con_iva=159900.0, modo="prueba", fecha="2026-07-07")
    assert p["document"]["id"] == 11810
    assert p["items"][0]["price"] == 134369.75
    assert p["items"][0]["warehouse"] == {"id": 32}
    # anticipo cubre todo, sin excedente
    assert p["payments"] == [{"id": 8316, "value": 159900.0,
                              "due_date": "2026-07-07"}]
    assert p["_resumen"]["excedente"] == 0


def test_reemplazo_mas_caro_cobra_excedente():
    # nueva base 168067.23 → total 199_999.999 ≈ 200000; crédito 159900
    item = {"code": "REF-CARA", "description": "Jean premium",
            "price_base": 168067.23}
    p = F.construir_payload_factura_reemplazo(
        factura_original=FACTURA, item_reemplazo=item,
        credito_con_iva=159900.0, modo="prueba", fecha="2026-07-07")
    total = p["_resumen"]["total"]
    assert p["payments"][0] == {"id": 8316, "value": 159900.0,
                                "due_date": "2026-07-07"}   # anticipo
    assert p["payments"][1]["id"] == 8857                        # cuentas por cobrar
    assert round(p["payments"][1]["value"], 2) == round(total - 159900.0, 2)
    # los pagos suman el total de la factura
    assert round(sum(x["value"] for x in p["payments"]), 2) == round(total, 2)


def test_reemplazo_sin_item_falla():
    with pytest.raises(ValueError, match="sin_item_reemplazo"):
        F.construir_payload_factura_reemplazo(
            factura_original=FACTURA, item_reemplazo={},
            credito_con_iva=159900.0, modo="prueba", fecha="2026-07-07")


# ── lookup Shopify ───────────────────────────────────────────────────
def test_precio_base_variante_convierte_de_shopify(monkeypatch):
    monkeypatch.setattr(FSH.clientes, "_shopify_graphql", lambda q, v=None: {
        "data": {"productVariants": {"edges": [
            {"node": {"sku": "REF-L", "price": "159900.00", "displayName": "Jean / 12"}}
        ]}}})
    assert FSH.precio_base_variante("REF-L") == 134369.75


def test_precio_base_variante_no_existe(monkeypatch):
    monkeypatch.setattr(FSH.clientes, "_shopify_graphql", lambda q, v=None: {
        "data": {"productVariants": {"edges": []}}})
    assert FSH.precio_base_variante("NADA") is None


# ── Búsqueda de una prenda más cara (para probar el excedente) ────────
_VARIANTES = {"data": {"productVariants": {"edges": [
    {"node": {"sku": "BARATA", "price": "99900.00"}},
    {"node": {"sku": "IGUAL",  "price": "149900.00"}},
    {"node": {"sku": "CARA-1", "price": "169900.00"}},
    {"node": {"sku": "CARA-2", "price": "259900.00"}},
]}}}


def test_encuentra_la_mas_barata_que_supera_el_umbral(monkeypatch):
    monkeypatch.setattr(FSH.clientes, "_shopify_graphql", lambda q, v=None: _VARIANTES)
    # base 125966.39 -> con IVA 149900. La siguiente por encima es 169900.
    r = FSH.variante_mas_cara_que(125966.39)
    assert r["sku"] == "CARA-1"          # no salta a la de 259900
    assert r["precio_con_iva"] == 169900.0
    assert r["precio_base"] == 142773.11


def test_excluye_el_sku_devuelto(monkeypatch):
    monkeypatch.setattr(FSH.clientes, "_shopify_graphql", lambda q, v=None: _VARIANTES)
    r = FSH.variante_mas_cara_que(125966.39, excluir_sku="CARA-1")
    assert r["sku"] == "CARA-2"


def test_sin_ninguna_mas_cara(monkeypatch):
    monkeypatch.setattr(FSH.clientes, "_shopify_graphql", lambda q, v=None: _VARIANTES)
    assert FSH.variante_mas_cara_que(500000.0) is None


def test_error_de_shopify_no_lanza(monkeypatch):
    monkeypatch.setattr(FSH.clientes, "_shopify_graphql",
                        lambda q, v=None: {"errors": [{"message": "boom"}]})
    assert FSH.variante_mas_cara_que(100000.0) is None
