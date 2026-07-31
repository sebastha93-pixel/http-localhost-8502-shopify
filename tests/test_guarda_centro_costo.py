"""Que la config de la tienda se pueda VER y que falte lo que falta.

Dos huecos que se descubrieron al intentar verificar el despliegue:

1. `listar()` no exponia `centro_costo_id`, asi que no habia forma de
   confirmar desde la app si estaba configurado. Un dato que no se puede ver
   es un dato en el que no se puede confiar.

2. FV-5 «Cambios» exige centro de costos. Si se activa FV-5 y una tienda no
   lo tiene, Siigo rechaza la factura AL EMITIR — con la clienta enfrente.
   Eso se tiene que detectar antes.
"""
import pytest
from backend.services import tiendas


def test_el_panel_puede_ver_el_centro_de_costos():
    p = {t["clave"]: t for t in tiendas.listar()}
    assert p["florida_caja1"]["centro_costo_id"] == 774
    assert p["arrayanes"]["centro_costo_id"] == 677


def test_con_fv1_no_hace_falta_centro_de_costos(monkeypatch):
    """FV-1 no lo exige: una tienda sin el sigue lista para facturar."""
    monkeypatch.setenv("TIENDAS_JSON", '{"arrayanes": {"centro_costo_id": null}}')
    assert tiendas.validar_para_facturar("arrayanes")["bodega_id"] == 37


def test_con_fv5_una_tienda_sin_centro_de_costos_se_niega(monkeypatch):
    """Mejor negarse aqui que dejar que Siigo rechace con la clienta enfrente."""
    monkeypatch.setenv("SIIGO_DOC_FACTURA_CAMBIO", str(tiendas.DOC_FV5_CAMBIOS))
    monkeypatch.setenv("TIENDAS_JSON", '{"arrayanes": {"centro_costo_id": null}}')
    with pytest.raises(ValueError) as e:
        tiendas.validar_para_facturar("arrayanes")
    assert "centro_costo" in str(e.value)


def test_con_fv5_y_centro_configurado_pasa(monkeypatch):
    monkeypatch.setenv("SIIGO_DOC_FACTURA_CAMBIO", str(tiendas.DOC_FV5_CAMBIOS))
    assert tiendas.validar_para_facturar("florida_caja1")["centro_costo_id"] == 774


def test_el_panel_avisa_que_falta(monkeypatch):
    monkeypatch.setenv("SIIGO_DOC_FACTURA_CAMBIO", str(tiendas.DOC_FV5_CAMBIOS))
    monkeypatch.setenv("TIENDAS_JSON", '{"arrayanes": {"centro_costo_id": null}}')
    arr = {t["clave"]: t for t in tiendas.listar()}["arrayanes"]
    assert arr["lista"] is False
    assert "centro_costo_id" in arr["falta"]


def test_el_documento_de_facturacion_se_ve_en_el_panel():
    """Para saber de un vistazo si se esta facturando por FV-1 o FV-5."""
    p = {t["clave"]: t for t in tiendas.listar()}
    assert p["florida_caja1"]["documento_facturacion_id"] == tiendas.DOC_FV1_ONLINE
