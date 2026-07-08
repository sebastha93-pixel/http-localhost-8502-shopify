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
