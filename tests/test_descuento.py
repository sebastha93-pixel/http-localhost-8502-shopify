"""Descuento en la factura del reemplazo.

TRAMPA: `discount_type` NO es igual en todos los comprobantes.

    FV-1  discount_type: "Value"        -> el descuento va en PESOS
    FV-5  discount_type: "Percentage"   -> el descuento va en PORCENTAJE

Escribirlo fijo produce una factura con el monto equivocado segun cual este
activo — y sale SIN ERROR, solo mal. Peor que un rechazo.

La asesora escribe pesos, que es como piensa con la clienta enfrente. La
conversion es trabajo nuestro.
"""
import pytest
from backend.services import fiscal_logic as F


def test_en_pesos_se_manda_tal_cual():
    assert F.descuento_para("Value", base=100000, descuento_pesos=15000) == 15000


def test_en_porcentaje_se_convierte():
    assert F.descuento_para("Percentage", base=100000, descuento_pesos=15000) == 15.0


def test_el_porcentaje_admite_decimales():
    """FV-5 tiene decimals: true, asi que no hay que redondear a entero."""
    d = F.descuento_para("Percentage", base=125966.39, descuento_pesos=20000)
    assert 15.87 < d < 15.88


def test_el_porcentaje_vuelve_al_mismo_valor():
    """Lo que Siigo va a recalcular tiene que dar los mismos pesos."""
    base, pesos = 125966.39, 20000
    pct = F.descuento_para("Percentage", base=base, descuento_pesos=pesos)
    assert abs(base * pct / 100 - pesos) < 1.0


def test_sin_descuento_no_se_manda_nada():
    assert F.descuento_para("Value", base=100000, descuento_pesos=0) is None
    assert F.descuento_para("Percentage", base=100000, descuento_pesos=0) is None


def test_un_tipo_desconocido_no_manda_descuento():
    """Ante la duda NO se manda: una factura sin descuento se corrige; una con
    el monto equivocado ya salio a la DIAN."""
    assert F.descuento_para("", base=100000, descuento_pesos=15000) is None
    assert F.descuento_para(None, base=100000, descuento_pesos=15000) is None


def test_no_se_puede_descontar_mas_que_el_precio():
    with pytest.raises(ValueError):
        F.descuento_para("Value", base=100000, descuento_pesos=120000)


def test_base_en_cero_no_divide_por_cero():
    assert F.descuento_para("Percentage", base=0, descuento_pesos=0) is None


# ── El payload ────────────────────────────────────────────────────────────

FACTURA = {"id": "f1", "name": "FV-11-1", "seller": 937,
           "customer": {"identification": "1"},
           "items": [{"code": "A-1", "price": 100000.0}]}


def _payload(**kw):
    return F.construir_payload_factura_reemplazo(
        factura_original=FACTURA,
        item_reemplazo={"code": "B-2", "description": "JEAN", "price_base": 100000.0},
        credito_con_iva=119000.0, modo="prueba", fecha="2026-07-31", **kw)


def test_el_item_lleva_el_descuento():
    p = _payload(descuento_pesos=15000, discount_type="Value")
    assert p["items"][0]["discount"] == 15000


def test_el_precio_de_lista_NO_se_toca():
    """La clienta ve cuanto costaba y cuanto se ahorro. Bajar el precio en vez
    de descontar borraria esa informacion de la factura."""
    p = _payload(descuento_pesos=15000, discount_type="Value")
    assert p["items"][0]["price"] == 100000.0


def test_sin_descuento_el_item_no_trae_el_campo():
    assert "discount" not in _payload()["items"][0]


def test_el_anticipo_cubre_el_precio_YA_descontado():
    """Si se calculara sobre el precio de lista, el excedente saldria inflado
    y la clienta pagaria de mas."""
    p = _payload(descuento_pesos=100000, discount_type="Value")
    # Prenda de 100.000 con 100.000 de descuento => no hay nada que cobrar.
    assert p["_resumen"]["excedente"] == 0


# ── Leer el discount_type del comprobante en uso ──────────────────────────

def test_lee_el_tipo_de_descuento_del_documento(monkeypatch):
    """No se asume: cada comprobante declara el suyo y son distintos."""
    from backend.services import postventa_siigo as S
    S.limpiar_cache_tipos()
    monkeypatch.setattr(S, "documentos_por_prefijo", lambda **k: {})
    monkeypatch.setattr(S, "_get_seguro", lambda p, params=None: {"results": [
        {"id": 11810, "code": "1", "discount_type": "Value"},
        {"id": 27154, "code": "5", "discount_type": "Percentage"},
    ]})
    assert S.tipo_de_descuento(27154) == "Percentage"
    assert S.tipo_de_descuento(11810) == "Value"


def test_un_documento_desconocido_devuelve_none(monkeypatch):
    """Y sin tipo NO se manda descuento — mejor sin que con el monto errado."""
    from backend.services import postventa_siigo as S
    S.limpiar_cache_tipos()
    monkeypatch.setattr(S, "_get_seguro", lambda p, params=None: {"results": []})
    assert S.tipo_de_descuento(99999) is None


def test_si_siigo_falla_no_se_inventa_un_tipo(monkeypatch):
    from backend.services import postventa_siigo as S
    S.limpiar_cache_tipos()
    monkeypatch.setattr(S, "_get_seguro",
                        lambda p, params=None: {"_error": "timeout"})
    assert S.tipo_de_descuento(27154) is None
