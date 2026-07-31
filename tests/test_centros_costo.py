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

def test_por_defecto_ninguna_tienda_tiene_centro_de_costos():
    """No se inventa: hasta no leerlos de Siigo, va None y FV-1 funciona."""
    assert tiendas.centro_costo_de("florida_caja1") is None


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
