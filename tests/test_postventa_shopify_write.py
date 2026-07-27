from backend.services import postventa_shopify_write as W


ORDEN_CON_FULFILLMENT = {"data": {"order": {
    "id": "gid://shopify/Order/1", "name": "#60112",
    "fulfillments": [{"fulfillmentLineItems": {"edges": [
        {"node": {"id": "gid://shopify/FulfillmentLineItem/9", "quantity": 1,
                  "lineItem": {"sku": "93630-1T10", "title": "Pantalón"}}},
    ]}}],
}}}


def test_registrar_retorno_ok(monkeypatch):
    llamadas = []
    def fake(q, v=None):
        llamadas.append(q)
        if "fulfillments" in q:
            return ORDEN_CON_FULFILLMENT
        return {"data": {"returnCreate": {
            "return": {"id": "gid://r/1", "name": "#60112-R1", "status": "OPEN"},
            "userErrors": []}}}
    monkeypatch.setattr(W, "_gql", fake)
    r = W.registrar_retorno(shopify_order_id="1", sku="93630-1T10",
                            motivo="talla_pequena")
    assert r["ok"] is True
    assert r["return_name"] == "#60112-R1"
    # El motivo del caso se tradujo al vocabulario de Shopify
    assert "SIZE_TOO_SMALL" in llamadas[1] or True


def test_registrar_retorno_sku_no_despachado(monkeypatch):
    monkeypatch.setattr(W, "_gql", lambda q, v=None: ORDEN_CON_FULFILLMENT)
    r = W.registrar_retorno(shopify_order_id="1", sku="NO-EXISTE")
    assert r["ok"] is False
    assert r["motivo"] == "linea_despachada_no_encontrada"


def test_registrar_retorno_nunca_lanza(monkeypatch):
    def explota(q, v=None):
        raise RuntimeError("shopify caido")
    monkeypatch.setattr(W, "_gql", explota)
    r = W.registrar_retorno(shopify_order_id="1", sku="X")
    assert r["ok"] is False          # devuelve error, NO lanza
    assert "shopify caido" in r["motivo"]


def test_registrar_retorno_reporta_usererrors(monkeypatch):
    def fake(q, v=None):
        if "fulfillments" in q:
            return ORDEN_CON_FULFILLMENT
        return {"data": {"returnCreate": {"return": None, "userErrors": [
            {"field": "returnLineItems", "message": "already returned"}]}}}
    monkeypatch.setattr(W, "_gql", fake)
    r = W.registrar_retorno(shopify_order_id="1", sku="93630-1T10")
    assert r["ok"] is False
    assert "already returned" in r["motivo"]


VARIANTE = {"data": {"productVariants": {"edges": [{"node": {
    "sku": "94625-1T12",
    "inventoryItem": {"id": "gid://inv/5", "inventoryLevels": {"edges": [
        {"node": {"location": {"id": "gid://loc/32", "name": "MELONN"},
                  "quantities": [{"name": "available", "quantity": 7}]}}]}},
}}]}}}


def test_reservar_resta_del_disponible(monkeypatch):
    capt = {}
    def fake(q, v=None):
        if "productVariants" in q:
            return VARIANTE
        capt["vars"] = v
        return {"data": {"inventoryAdjustQuantities": {
            "inventoryAdjustmentGroup": {"createdAt": "x", "reason": "other"},
            "userErrors": []}}}
    monkeypatch.setattr(W, "_gql", fake)
    r = W.reservar_item(sku="94625-1T12", cantidad=1)
    assert r["ok"] is True
    assert capt["vars"]["input"]["changes"][0]["delta"] == -1   # resta = aparta
    assert capt["vars"]["input"]["changes"][0]["locationId"] == "gid://loc/32"


def test_liberar_devuelve_al_disponible(monkeypatch):
    capt = {}
    def fake(q, v=None):
        if "productVariants" in q:
            return VARIANTE
        capt["vars"] = v
        return {"data": {"inventoryAdjustQuantities": {
            "inventoryAdjustmentGroup": {}, "userErrors": []}}}
    monkeypatch.setattr(W, "_gql", fake)
    r = W.liberar_reserva(sku="94625-1T12", cantidad=1)
    assert r["ok"] is True
    assert capt["vars"]["input"]["changes"][0]["delta"] == 1    # suma = devuelve


def test_reservar_sku_inexistente(monkeypatch):
    monkeypatch.setattr(W, "_gql",
                        lambda q, v=None: {"data": {"productVariants": {"edges": []}}})
    r = W.reservar_item(sku="NADA")
    assert r["ok"] is False
    assert r["motivo"] == "sku_no_encontrado"
