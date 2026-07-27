import pytest
from backend.services import fiscal_siigo as FS


FACTURAS = {"results": [
    {"id": "f1", "name": "FV-1-63041",
     "observations": "Orden Nº: 60110 - Medio de Pago: Wompi"},
    {"id": "f2", "name": "FV-1-63043",
     "observations": "Orden Nº: 60112 - Medio de Pago: Mercado Pago"},
]}


def test_busca_factura_por_numero_de_pedido(monkeypatch):
    monkeypatch.setattr(FS.siigo, "siigo_get", lambda p, params=None: FACTURAS)
    e = FS.EmisorSiigo()
    f = e.buscar_factura_original(numero_pedido="#60112")
    assert f["id"] == "f2"


def test_no_encuentra_devuelve_none(monkeypatch):
    monkeypatch.setattr(FS.siigo, "siigo_get",
                        lambda p, params=None: {"results": []})
    e = FS.EmisorSiigo()
    assert e.buscar_factura_original(numero_pedido="#99999") is None


def test_emitir_nota_credito_devuelve_ids(monkeypatch):
    llamadas = []

    def fake_post(path, body):
        llamadas.append((path, body))
        return {"id": "nc-99", "name": "NC-1-6985", "number": 6985}

    monkeypatch.setattr(FS.siigo, "siigo_post", fake_post)
    e = FS.EmisorSiigo()
    r = e.emitir(payload={"document": {"id": 27141}}, doc_kind="nota_credito")
    assert r["siigo_document_id"] == "nc-99"
    assert r["siigo_document_number"] == "NC-1-6985"
    assert llamadas[0][0] == "/credit-notes"


def test_emitir_factura_usa_endpoint_invoices(monkeypatch):
    llamadas = []
    monkeypatch.setattr(FS.siigo, "siigo_post",
                        lambda p, b: llamadas.append((p, b)) or {"id": "fv-1"})
    e = FS.EmisorSiigo()
    e.emitir(payload={}, doc_kind="factura")
    assert llamadas[0][0] == "/invoices"


def test_emitir_doc_kind_invalido():
    e = FS.EmisorSiigo()
    with pytest.raises(ValueError, match="doc_kind_invalido"):
        e.emitir(payload={}, doc_kind="recibo")


def test_modo_actual_default_prueba(monkeypatch):
    monkeypatch.delenv("SIIGO_POSTVENTA_MODO", raising=False)
    assert FS.modo_actual() == "prueba"
    monkeypatch.setenv("SIIGO_POSTVENTA_MODO", "produccion")
    assert FS.modo_actual() == "produccion"


def test_cache_evita_repetir_llamadas_a_siigo(monkeypatch):
    FS.limpiar_cache_facturas()
    llamadas = []
    monkeypatch.setattr(FS.siigo, "siigo_get",
                        lambda p, params=None: llamadas.append(1) or FACTURAS)
    e = FS.EmisorSiigo()
    assert e.buscar_factura_original(numero_pedido="#60112")["id"] == "f2"
    assert e.buscar_factura_original(numero_pedido="#60112")["id"] == "f2"
    assert e.buscar_factura_original(numero_pedido="#60112")["id"] == "f2"
    assert len(llamadas) == 1        # una sola vez contra Siigo


def test_cache_guarda_todas_las_de_la_pagina(monkeypatch):
    # Buscar un pedido cachea también los otros de la misma página: el
    # siguiente caso del banco no vuelve a llamar a Siigo.
    FS.limpiar_cache_facturas()
    llamadas = []
    monkeypatch.setattr(FS.siigo, "siigo_get",
                        lambda p, params=None: llamadas.append(1) or FACTURAS)
    e = FS.EmisorSiigo()
    e.buscar_factura_original(numero_pedido="#60112")
    e.buscar_factura_original(numero_pedido="#60110")   # otro pedido, misma página
    assert len(llamadas) == 1


def test_cache_no_repite_el_no_encontrado(monkeypatch):
    FS.limpiar_cache_facturas()
    llamadas = []
    monkeypatch.setattr(FS.siigo, "siigo_get",
                        lambda p, params=None: llamadas.append(1) or {"results": []})
    e = FS.EmisorSiigo()
    assert e.buscar_factura_original(numero_pedido="#99999") is None
    assert e.buscar_factura_original(numero_pedido="#99999") is None
    assert len(llamadas) == 1
