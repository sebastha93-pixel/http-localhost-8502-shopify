import pytest
from backend.services import fiscal_logic as F


# ── extracción / normalización ───────────────────────────────────────
def test_extraer_numero_pedido():
    obs = "Orden Nº: 60112 - Medio de Pago: Mercado Pago Tarjetas"
    assert F.extraer_numero_pedido(obs) == "60112"


def test_extraer_numero_pedido_variantes():
    assert F.extraer_numero_pedido("Orden No: 999") == "999"
    assert F.extraer_numero_pedido("orden n: 1") == "1"
    assert F.extraer_numero_pedido("") is None
    assert F.extraer_numero_pedido("sin numero") is None


def test_normalizar_numero_pedido_quita_almohadilla():
    assert F.normalizar_numero_pedido("#60112") == "60112"
    assert F.normalizar_numero_pedido(" 60112 ") == "60112"
    assert F.normalizar_numero_pedido("60112") == "60112"


# ── config por modo ──────────────────────────────────────────────────
def test_config_documentos_modo_prueba_no_es_electronico():
    c = F.config_documentos("prueba")
    assert c["nota_credito_id"] == 27141
    assert c["electronico"] is False


def test_config_documentos_modo_produccion():
    c = F.config_documentos("produccion")
    assert c["nota_credito_id"] == 11817
    assert c["electronico"] is True


# ── montos ───────────────────────────────────────────────────────────
def test_calcular_iva_19():
    assert F.calcular_iva(100000.0) == 19000.0


def test_total_con_iva():
    assert F.total_con_iva(100000.0) == 119000.0


# ── nota crédito ─────────────────────────────────────────────────────
FACTURA = {
    "id": "3ed6b96c-38bc-4334-87fa-e33e60298637",
    "name": "FV-1-63043",
    "customer": {"identification": "30384838", "branch_office": 0},
    "seller": 658,
    "items": [
        {"code": "REF-10-M", "description": "Jean flare - 10", "quantity": 1,
         "price": 134369.75, "taxes": [{"id": 6352}]},
        {"code": "REF-99-S", "description": "Blusa - 8", "quantity": 1,
         "price": 50000.0, "taxes": [{"id": 6352}]},
    ],
}


def test_items_factura_por_sku_filtra_por_code():
    r = F.items_factura_por_sku(FACTURA, ["REF-10-M"])
    assert len(r) == 1
    assert r[0]["code"] == "REF-10-M"
    assert r[0]["price"] == 134369.75


def test_payload_nc_copia_montos_de_la_factura_y_usa_anticipo():
    p = F.construir_payload_nota_credito(
        factura=FACTURA, skus_a_acreditar=["REF-10-M"],
        modo="prueba", fecha="2026-07-07")
    assert p["document"]["id"] == 27141
    assert p["invoice"] == FACTURA["id"]
    assert p["customer"]["identification"] == "30384838"
    assert p["items"][0]["code"] == "REF-10-M"
    assert p["items"][0]["price"] == 134369.75
    assert p["items"][0]["taxes"] == [{"id": 6352}]
    assert p["payments"][0]["id"] == 8316
    assert p["payments"][0]["value"] == 159900.0


def test_payload_nc_modo_produccion_usa_electronica():
    p = F.construir_payload_nota_credito(
        factura=FACTURA, skus_a_acreditar=["REF-10-M"],
        modo="produccion", fecha="2026-07-07")
    assert p["document"]["id"] == 11817


def test_payload_nc_sku_inexistente_falla():
    with pytest.raises(ValueError, match="items_no_encontrados"):
        F.construir_payload_nota_credito(
            factura=FACTURA, skus_a_acreditar=["NO-EXISTE"],
            modo="prueba", fecha="2026-07-07")
