from backend.services import postventa_shopify as PS


def test_diagnostico_sin_scopes(monkeypatch):
    monkeypatch.setattr(PS.clientes, "_shopify_graphql",
                        lambda q, v=None: {"errors": [{"message": "sin acceso"}]})
    r = PS.diagnostico()
    assert r["_error"] == "no_se_pudieron_leer_scopes"


def test_diagnostico_detecta_capacidades(monkeypatch):
    def fake(q, v=None):
        if "accessScopes" in q:
            return {"data": {"currentAppInstallation": {"accessScopes": [
                {"handle": "read_orders"}, {"handle": "read_inventory"},
                {"handle": "write_inventory"}]}}}
        return {"data": {"locations": {"edges": [
            {"node": {"id": "gid://1", "name": "MELONN", "isActive": True}}]}}}
    monkeypatch.setattr(PS.clientes, "_shopify_graphql", fake)
    r = PS.diagnostico()
    # tiene write_inventory -> puede reservar
    assert r["capacidades"]["reservar_inventario"]["disponible"] is True
    # NO tiene write_orders -> no puede descontar la venta
    assert r["capacidades"]["descontar_venta_reembolso"]["disponible"] is False
    assert "write_orders" in r["capacidades"]["descontar_venta_reembolso"]["faltan"]
    assert r["bodegas"][0]["name"] == "MELONN"
