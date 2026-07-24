import pytest
from backend.services import postventa_fiscal as PF


CASO = {"id": "c1", "case_number": "PV-2026-0001", "type": "cambio_talla",
        "shopify_order_name": "#60112", "status": "aprobado"}

FACTURA = {"id": "f2", "name": "FV-1-63043",
           "customer": {"identification": "30384838", "branch_office": 0},
           "seller": 658,
           "items": [{"code": "REF-1", "description": "Jean", "quantity": 1,
                      "price": 100000.0, "taxes": [{"id": 6352}]}]}

ITEMS = [{"original_sku": "REF-1", "original_variant": "M",
          "original_price": 100000.0}]


def _mock_base(monkeypatch, *, fiscal_existente=None):
    monkeypatch.setattr(PF, "_caso", lambda cid: CASO)
    monkeypatch.setattr(PF, "_items_caso", lambda cid: ITEMS)
    monkeypatch.setattr(PF, "_fiscal_existente", lambda cid, dk: fiscal_existente)
    monkeypatch.setattr(PF, "_guardar_fiscal", lambda **k: {"id": "fx", **k})

    class E:
        def buscar_factura_original(self, **k):
            return FACTURA
    monkeypatch.setattr(PF, "obtener_emisor", lambda: E())


def test_preview_arma_payload_y_no_emite(monkeypatch):
    _mock_base(monkeypatch)
    r = PF.preview_nota_credito("c1")
    assert r["factura_original"]["name"] == "FV-1-63043"
    assert r["payload"]["invoice"] == "f2"
    assert r["payload"]["payments"][0]["id"] == 8316
    assert r["totales"]["total"] == 119000.0
    assert r["emitido"] is False


def test_preview_bloquea_si_ya_se_emitio(monkeypatch):
    _mock_base(monkeypatch, fiscal_existente={"status": "emitido"})
    with pytest.raises(ValueError, match="nota_credito_ya_emitida"):
        PF.preview_nota_credito("c1")


def test_preview_sin_factura_original(monkeypatch):
    _mock_base(monkeypatch)

    class E:
        def buscar_factura_original(self, **k):
            return None
    monkeypatch.setattr(PF, "obtener_emisor", lambda: E())
    with pytest.raises(ValueError, match="factura_original_no_encontrada"):
        PF.preview_nota_credito("c1")


def test_emitir_persiste_y_avanza_estado(monkeypatch):
    _mock_base(monkeypatch)
    guardado = {}
    monkeypatch.setattr(PF, "_pendiente", lambda cid, dk: {
        "id": "fx", "payload_snapshot": {"document": {"id": 27141}},
        "siigo_invoice_ref": "f2", "amount": 119000.0})
    monkeypatch.setattr(PF, "_marcar_emitido", lambda **k: guardado.update(k) or k)
    monkeypatch.setattr(PF.pv, "registrar_evento", lambda *a, **k: {})
    estados = []
    monkeypatch.setattr(PF.pv, "cambiar_estado",
                        lambda cid, e, **k: estados.append(e))

    class E:
        def emitir(self, *, payload, doc_kind):
            return {"siigo_document_id": "nc-99",
                    "siigo_document_number": "NC-1-6985"}
    monkeypatch.setattr(PF, "obtener_emisor", lambda: E())

    r = PF.emitir_nota_credito("c1", actor="u1")
    assert r["siigo_document_number"] == "NC-1-6985"
    assert guardado["siigo_document_id"] == "nc-99"
    assert estados == ["nota_credito_emitida"]


def test_emitir_sin_preview_falla(monkeypatch):
    _mock_base(monkeypatch)
    monkeypatch.setattr(PF, "_pendiente", lambda cid, dk: None)
    with pytest.raises(ValueError, match="sin_preview"):
        PF.emitir_nota_credito("c1")


def test_emitir_error_siigo_marca_error_y_relanza(monkeypatch):
    _mock_base(monkeypatch)
    monkeypatch.setattr(PF, "_pendiente", lambda cid, dk: {
        "id": "fx", "payload_snapshot": {}})
    marcado = {}
    monkeypatch.setattr(PF, "_marcar_error",
                        lambda **k: marcado.update(k))
    monkeypatch.setattr(PF.pv, "registrar_evento", lambda *a, **k: {})

    class E:
        def emitir(self, *, payload, doc_kind):
            raise RuntimeError("siigo_post /credit-notes HTTP 400: IVA malo")
    monkeypatch.setattr(PF, "obtener_emisor", lambda: E())

    with pytest.raises(RuntimeError, match="400"):
        PF.emitir_nota_credito("c1", actor="u1")
    assert marcado["fiscal_id"] == "fx"  # quedó registrado el error, no se pierde


# ── factura del reemplazo ────────────────────────────────────────────
FACTURA_CON_ITEM = {**FACTURA, "seller": 658,
    "items": [{"code": "REF-1", "description": "Jean - 10", "quantity": 1,
               "price": 100000.0, "seller": 658, "warehouse": {"id": 32},
               "taxes": [{"id": 6352}]}]}


def _mock_factura(monkeypatch, *, nc=None, factura_ya=None, tipo="cambio_talla",
                  requested_sku=""):
    monkeypatch.setattr(PF, "_caso", lambda cid: {**CASO, "type": tipo})
    monkeypatch.setattr(PF, "_items_caso", lambda cid: [
        {"original_sku": "REF-1", "requested_sku": requested_sku,
         "original_price": 100000.0}])
    def fx(cid, dk):
        return nc if dk == "nota_credito" else factura_ya
    monkeypatch.setattr(PF, "_fiscal_existente", fx)
    monkeypatch.setattr(PF, "_guardar_fiscal", lambda **k: {"id": "fx", **k})

    class E:
        def buscar_factura_original(self, **k):
            return FACTURA_CON_ITEM
    monkeypatch.setattr(PF, "obtener_emisor", lambda: E())


def test_factura_reemplazo_misma_ref_usa_precio_original(monkeypatch):
    _mock_factura(monkeypatch, nc={"amount": 119000.0})
    r = PF.preview_factura_reemplazo("c1")
    assert r["payload"]["items"][0]["price"] == 100000.0     # de la factura original
    assert r["resumen"]["excedente"] == 0                    # mismo precio
    assert r["payload"]["payments"][0]["id"] == 8316


def test_factura_reemplazo_requiere_nc_primero(monkeypatch):
    _mock_factura(monkeypatch, nc=None)
    with pytest.raises(ValueError, match="nota_credito_no_emitida"):
        PF.preview_factura_reemplazo("c1")


def test_factura_reemplazo_reembolso_no_lleva_factura(monkeypatch):
    _mock_factura(monkeypatch, nc={"amount": 119000.0}, tipo="reembolso")
    with pytest.raises(ValueError, match="tipo_sin_factura"):
        PF.preview_factura_reemplazo("c1")


def test_factura_reemplazo_otra_ref_usa_shopify(monkeypatch):
    _mock_factura(monkeypatch, nc={"amount": 119000.0}, requested_sku="REF-NUEVA")
    monkeypatch.setattr(PF.fiscal_shopify, "precio_base_variante",
                        lambda sku: 168067.23)
    r = PF.preview_factura_reemplazo("c1")
    assert r["payload"]["items"][0]["code"] == "REF-NUEVA"
    assert r["payload"]["items"][0]["price"] == 168067.23
    assert r["payload"]["payments"][1]["id"] == 8857        # excedente
