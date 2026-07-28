from backend.services import postventa_siigo as pv


def test_descubrir_config_no_configurado(monkeypatch):
    monkeypatch.setattr(pv.siigo, "siigo_configurado", lambda: False)
    r = pv.descubrir_config()
    assert r["_error"] == "siigo_no_configurado"


def test_descubrir_config_llama_endpoints(monkeypatch):
    llamadas = []

    def fake_get(path, params=None):
        llamadas.append((path, params))
        return {"ok": path}

    monkeypatch.setattr(pv.siigo, "siigo_configurado", lambda: True)
    monkeypatch.setattr(pv.siigo, "siigo_get", fake_get)
    r = pv.descubrir_config()
    # Trae las 5 secciones de config
    assert set(r.keys()) == {
        "tipos_documento_factura", "tipos_documento_nota_credito",
        "impuestos", "formas_pago", "vendedores",
    }
    paths = [c[0] for c in llamadas]
    assert "/document-types" in paths
    assert "/taxes" in paths
    assert "/payment-types" in paths
    assert "/users" in paths


def test_descubrir_config_un_endpoint_falla_no_rompe_los_demas(monkeypatch):
    def fake_get(path, params=None):
        if path == "/taxes":
            raise RuntimeError("boom 500")
        return {"ok": path}

    monkeypatch.setattr(pv.siigo, "siigo_configurado", lambda: True)
    monkeypatch.setattr(pv.siigo, "siigo_get", fake_get)
    r = pv.descubrir_config()
    assert r["impuestos"]["_error"].startswith("boom")   # el que falló
    assert r["vendedores"]["ok"] == "/users"             # los demás siguen


def test_inspeccionar_facturas_extrae_llaves(monkeypatch):
    factura = {
        "id": "abc", "name": "FV-1-1052", "number": 1052, "date": "2026-07-01",
        "document": {"id": 24446}, "customer": {"identification": "123"},
        "observations": "Pedido Shopify #1052", "items": [], "payments": [],
    }
    monkeypatch.setattr(pv.siigo, "siigo_configurado", lambda: True)
    monkeypatch.setattr(pv.siigo, "siigo_get",
                        lambda path, params=None: {"results": [factura]})
    r = pv.inspeccionar_facturas(3)
    assert r["total_en_muestra"] == 1
    m = r["facturas"][0]
    assert m["id"] == "abc"
    assert m["document_id"] == 24446
    assert "observations" in m["llaves_disponibles"]
    # El nº de pedido Shopify aparece en observations → candidato de enlace
    assert "#1052" in (m["campos_ref_candidatos"].get("observations") or "")


def test_inspeccionar_notas_credito_extrae_estructura(monkeypatch):
    nc = {
        "id": "nc-1", "name": "NC-1-7049", "number": 7049, "date": "2026-07-24",
        "document": {"id": 11817}, "customer": {"identification": "1020409206"},
        "invoice": "abc-factura", "items": [{"code": "REF-10", "quantity": 1}],
        "payments": [{"id": 8316, "value": 159900}],
    }
    monkeypatch.setattr(pv.siigo, "siigo_configurado", lambda: True)
    monkeypatch.setattr(pv.siigo, "siigo_get",
                        lambda path, params=None: {"results": [nc]})
    r = pv.inspeccionar_notas_credito(2)
    assert r["total_en_muestra"] == 1
    m = r["notas"][0]
    assert m["document_id"] == 11817
    assert m["invoice_ref"] == "abc-factura"
    assert "items" in m["llaves_disponibles"]


def test_facturas_aceptadas_pagina_hasta_encontrarlas(monkeypatch):
    # Página 1: todas de hoy (InProcess). Página 2: ya aceptadas.
    paginas = {
        1: {"results": [
            {"id": "a", "name": "FV-1-64200", "observations": "Orden Nº: 61226",
             "stamp": {"status": "InProcess"}},
        ]},
        2: {"results": [
            {"id": "b", "name": "FV-1-63043", "observations": "Orden Nº: 60112",
             "stamp": {"status": "Accepted"}},
        ]},
    }
    monkeypatch.setattr(pv.siigo, "siigo_configurado", lambda: True)
    monkeypatch.setattr(pv.siigo, "siigo_get",
                        lambda path, params=None: paginas.get(params.get("page"), {"results": []}))
    r = pv.facturas_aceptadas(minimo=1)
    assert len(r) == 1
    assert r[0]["name"] == "FV-1-63043"      # saltó la de hoy


def test_facturas_aceptadas_descarta_tienda_fisica(monkeypatch):
    monkeypatch.setattr(pv.siigo, "siigo_configurado", lambda: True)
    monkeypatch.setattr(pv.siigo, "siigo_get", lambda path, params=None: {
        "results": [{"id": "x", "name": "FV-11-1121", "observations": "",
                     "stamp": {"status": "Accepted"}}]} if params.get("page") == 1
        else {"results": []})
    assert pv.facturas_aceptadas(minimo=1) == []   # sin pedido Shopify
