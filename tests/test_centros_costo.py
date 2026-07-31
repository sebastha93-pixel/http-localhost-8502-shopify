"""Centro de costos: FV-5 «Cambios» lo exige y FV-1 no.

    {"prefijo": "FV-5", "cost_center_obligatorio": true,
     "cost_center_default": null}

Por eso pasar a FV-5 NO es solo cambiar la variable de entorno: el payload
tiene que llevarlo o Siigo responde `document_settings`.

Ademas: `listar_centros_costo` devolvia [] tanto si no habia ninguno como si
la llamada fallaba. Indistinguible — el mismo patron que nos costo horas con
la bodega. Ahora el diagnostico dice cual de las dos cosas paso.
"""
import pytest
from backend.services import fiscal_logic as F
from backend.services import tiendas


FACTURA = {"id": "f1", "name": "FV-11-1202", "seller": 937,
           "customer": {"identification": "43424374"},
           "items": [{"code": "A-1", "price": 100000.0}]}


def _payload(**kw):
    return F.construir_payload_factura_reemplazo(
        factura_original=FACTURA,
        item_reemplazo={"code": "B-2", "description": "JEAN", "price_base": 100000.0},
        credito_con_iva=119000.0, modo="prueba", fecha="2026-07-30", **kw)


def test_sin_centro_de_costos_no_se_manda_el_campo():
    """FV-1 no lo exige: mandarlo vacio seria mandar basura."""
    assert "cost_center" not in _payload()


def test_con_centro_de_costos_va_en_el_documento():
    assert _payload(centro_costo_id=677)["cost_center"] == 677


def test_el_centro_de_costos_va_como_numero():
    """Misma leccion que warehouse: el POST quiere planos."""
    assert isinstance(_payload(centro_costo_id="677")["cost_center"], int)


# ── Config por punto de venta ──────────────────────────────────────────────

def test_cada_tienda_tiene_el_centro_de_costos_de_su_almacen():
    """Ids REALES leidos de GET /cost-centers, no del numero de pantalla."""
    assert tiendas.centro_costo_de("florida_caja1") == 774   # ALMACEN FLORIDA
    assert tiendas.centro_costo_de("florida_caja2") == 774   # misma tienda
    assert tiendas.centro_costo_de("arrayanes") == 677       # ALMACEN ARRAYANES


def test_se_configura_por_entorno(monkeypatch):
    monkeypatch.setenv("TIENDAS_JSON",
                       '{"florida_caja1": {"centro_costo_id": 677}}')
    assert tiendas.centro_costo_de("florida_caja1") == 677


def test_cada_tienda_puede_tener_el_suyo(monkeypatch):
    """El cambio queda contabilizado en la tienda donde ocurrio."""
    monkeypatch.setenv("TIENDAS_JSON",
                       '{"florida_caja1": {"centro_costo_id": 677},'
                       ' "arrayanes": {"centro_costo_id": 774}}')
    assert tiendas.centro_costo_de("florida_caja1") == 677
    assert tiendas.centro_costo_de("arrayanes") == 774


def test_una_tienda_desconocida_no_revienta():
    assert tiendas.centro_costo_de("no_existe") is None


# ── Cambio ONLINE: el centro de costos lo pone la factura original ─────────
# En MALE los centros de costo son CANALES: PAGINA WEB, INSTAGRAM, WHATSAPP
# ORGANICO, TIK TOK... El de una venta dice de donde vino.
#
# Por eso un cambio online COPIA el de la factura original: forzar uno fijo
# le quitaria la venta al canal que la genero y danaria la medicion de pauta.
# En tienda manda el del punto (ALMACEN FLORIDA / ARRAYANES), porque ahi el
# cambio si ocurrio fisicamente en ese local.

CC_PAGINA_WEB = 97
CC_FLORIDA = 774


def test_online_hereda_el_canal_de_la_factura_original():
    fac = dict(FACTURA, cost_center=CC_PAGINA_WEB)
    p = F.construir_payload_factura_reemplazo(
        factura_original=fac,
        item_reemplazo={"code": "B-2", "description": "J", "price_base": 100000.0},
        credito_con_iva=119000.0, modo="prueba", fecha="2026-07-30")
    assert p["cost_center"] == CC_PAGINA_WEB


def test_en_tienda_manda_el_del_punto():
    """El cambio presencial ocurrio en ese local, no en el canal original."""
    fac = dict(FACTURA, cost_center=CC_PAGINA_WEB)
    p = F.construir_payload_factura_reemplazo(
        factura_original=fac,
        item_reemplazo={"code": "B-2", "description": "J", "price_base": 100000.0},
        credito_con_iva=119000.0, modo="prueba", fecha="2026-07-30",
        centro_costo_id=CC_FLORIDA)
    assert p["cost_center"] == CC_FLORIDA


def test_si_la_factura_original_no_trae_canal_no_se_inventa():
    p = F.construir_payload_factura_reemplazo(
        factura_original=FACTURA,
        item_reemplazo={"code": "B-2", "description": "J", "price_base": 100000.0},
        credito_con_iva=119000.0, modo="prueba", fecha="2026-07-30")
    assert "cost_center" not in p


def test_siigo_lo_puede_mandar_expandido():
    """Como taxes y warehouse: el GET expande, el POST quiere plano."""
    fac = dict(FACTURA, cost_center={"id": CC_PAGINA_WEB, "name": "PAGINA WEB"})
    p = F.construir_payload_factura_reemplazo(
        factura_original=fac,
        item_reemplazo={"code": "B-2", "description": "J", "price_base": 100000.0},
        credito_con_iva=119000.0, modo="prueba", fecha="2026-07-30")
    assert p["cost_center"] == CC_PAGINA_WEB


# ── La nota credito tambien ────────────────────────────────────────────────

def test_la_nc_devuelve_la_venta_al_mismo_canal():
    """Si la NC no lleva el canal, la venta original queda inflada: se sumo
    a PAGINA WEB y nunca se resta."""
    fac = {"id": "f1", "name": "FV-1-1", "date": "2026-07-30",
           "cost_center": CC_PAGINA_WEB,
           "customer": {"identification": "1"},
           "items": [{"code": "A-1", "description": "J", "quantity": 1,
                      "price": 100000.0, "taxes": [{"id": 6352}]}]}
    p = F.construir_payload_nota_credito(
        factura=fac, skus_a_acreditar=["A-1"], modo="prueba", fecha="2026-07-30")
    assert p["cost_center"] == CC_PAGINA_WEB
