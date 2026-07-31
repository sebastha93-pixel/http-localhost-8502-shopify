"""El precio del reemplazo sale de SIIGO, no de Shopify.

Un cambio de 169.900 salio facturado en 67.960 —exactamente el 40%— porque el
precio de la prenda nueva se tomaba de Shopify, donde esa referencia estaba en
promocion. Pero la clienta se lleva una prenda del INVENTARIO DE LA TIENDA:
tiene que pagar el precio de la tienda.

Siigo trae el precio en `prices[].price_list[].value` y un campo
`tax_included` que dice si ese valor ya lleva IVA. El payload lo quiere SIN
IVA, asi que hay que normalizar — y hacerlo al reves duplica o parte el
precio sin que nada avise.
"""
from backend.services import postventa_inventario as I


def _prod(valor, *, incluye_iva=True, code="92611-1T10"):
    return {"code": code, "tax_included": incluye_iva,
            "prices": [{"currency_code": "COP",
                        "price_list": [{"position": 1, "value": valor}]}]}


def test_un_precio_con_iva_se_baja_a_base():
    """149.900 con IVA son 125.966,39 de base — el numero real de la factura."""
    assert abs(I.precio_base(_prod(149900)) - 125966.39) < 0.01


def test_un_precio_sin_iva_se_usa_tal_cual():
    assert I.precio_base(_prod(125966.39, incluye_iva=False)) == 125966.39


def test_sin_precio_devuelve_none():
    """Y sin precio NO se factura: mejor parar que inventar un valor."""
    assert I.precio_base({"code": "X"}) is None
    assert I.precio_base({"code": "X", "prices": []}) is None


def test_una_lista_de_precios_vacia_no_revienta():
    assert I.precio_base({"prices": [{"price_list": []}]}) is None


def test_toma_la_primera_lista_de_precios():
    """MALE maneja una sola. Si algun dia hay varias, la 1 es la de venta."""
    p = {"tax_included": True, "prices": [{"price_list": [
        {"position": 1, "value": 149900}, {"position": 2, "value": 99900}]}]}
    assert abs(I.precio_base(p) - 125966.39) < 0.01


def test_un_precio_en_cero_es_como_no_tenerlo():
    assert I.precio_base(_prod(0)) is None


# ── El precio viaja hasta la fila del inventario ──────────────────────────

CRUDO = {"referencias": [
    {"code": "92611-1T10", "referencia": "92611-1", "talla": "10",
     "nombre": "JEAN", "stock": {"Florida": 3}, "total": 3,
     "precio_base": 125966.39},
]}


def test_la_fila_guarda_el_precio_base():
    f = I.filas_desde_siigo(CRUDO, brand_id="male")[0]
    assert f["precio_base"] == 125966.39


def test_una_referencia_sin_precio_se_guarda_igual():
    """Se puede ver en el inventario aunque no se pueda facturar todavia."""
    crudo = {"referencias": [{"code": "X-1", "stock": {"Florida": 1}, "total": 1}]}
    assert I.filas_desde_siigo(crudo, brand_id="male")[0]["precio_base"] is None


# ── En tienda manda el precio de la tienda ────────────────────────────────

def test_un_cambio_en_tienda_usa_el_precio_de_siigo(monkeypatch):
    """Y NO el de Shopify, que puede estar en promocion."""
    from backend.services import postventa_fiscal as PF
    monkeypatch.setattr(PF.INV, "precio_de", lambda bod, code: 125966.39)
    it = PF._item_reemplazo(
        {"tienda": "florida_caja1"},
        {"original_sku": "A-1", "requested_sku": "92611-1T10"},
        {"items": []})
    assert it["price_base"] == 125966.39


def test_si_la_tienda_no_tiene_precio_NO_se_inventa(monkeypatch):
    """Mejor parar que facturar un valor sacado de otra lista."""
    import pytest
    from backend.services import postventa_fiscal as PF
    monkeypatch.setattr(PF.INV, "precio_de", lambda bod, code: None)
    with pytest.raises(ValueError) as e:
        PF._item_reemplazo({"tienda": "florida_caja1"},
                           {"original_sku": "A-1", "requested_sku": "92611-1T10"},
                           {"items": []})
    assert "precio" in str(e.value).lower()


def test_un_cambio_ONLINE_sigue_usando_shopify(monkeypatch):
    """Ahi si es la venta de internet: el precio de internet es el correcto."""
    from backend.services import postventa_fiscal as PF
    monkeypatch.setattr(PF.fiscal_shopify, "precio_base_variante", lambda sku: 99000.0)
    it = PF._item_reemplazo({"tienda": None},
                            {"original_sku": "A-1", "requested_sku": "B-2"},
                            {"items": []})
    assert it["price_base"] == 99000.0


def test_la_misma_referencia_conserva_el_precio_de_la_factura():
    """Cambio de talla: se respeta lo que la clienta pago, no la lista de hoy."""
    from backend.services import postventa_fiscal as PF
    fac = {"items": [{"code": "A-1", "description": "J", "price": 111111.0,
                      "seller": 1, "warehouse": 48}]}
    it = PF._item_reemplazo({"tienda": "florida_caja1"},
                            {"original_sku": "A-1", "requested_sku": "A-1"}, fac)
    assert it["price_base"] == 111111.0
