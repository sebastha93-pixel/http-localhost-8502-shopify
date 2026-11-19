"""Lo que se lee de la tienda en línea para vender con envío.

Sin red: se prueba cómo se INTERPRETA lo que contesta Shopify, que es donde
un descuido cobra de más o vende lo que no hay.
"""
from __future__ import annotations

import pytest

from backend.modules.retail.infrastructure import tienda_en_linea as t


def _nodo(sku, precio, tachado=None, disponible=0, talla="TALLA 6",
          estado="ACTIVE", titulo="Jean flare."):
    return {"sku": sku, "title": talla, "price": precio,
            "compareAtPrice": tachado,
            "product": {"title": titulo, "status": estado},
            "inventoryItem": {"inventoryLevel": {
                "quantities": [{"quantity": disponible}]}}}


def test_el_precio_es_el_que_la_web_cobra_hoy_y_el_tachado_es_la_lista():
    v = t._variante(_nodo("26631-1T6", "99900.00", "149900.00", 4))
    assert (v["precio_centavos"], v["precio_lista_centavos"]) == (
        9_990_000, 14_990_000)
    assert (v["talla"], v["nombre"], v["disponible"]) == ("6", "Jean flare", 4)


def test_un_tachado_que_no_es_mayor_no_es_rebaja():
    v = t._variante(_nodo("26631-1T6", "149900.00", "149900.00"))
    assert v["precio_lista_centavos"] == v["precio_centavos"] == 14_990_000
    v = t._variante(_nodo("26631-1T6", "149900.00", "99900.00"))
    assert v["precio_lista_centavos"] == 14_990_000


def test_sin_nivel_en_la_bodega_de_melonn_no_hay_existencia():
    """La prenda puede no estar asignada a la sucursal de Melonn: eso es
    cero, no un error — y nunca negativo."""
    n = _nodo("26631-1T6", "149900.00")
    n["inventoryItem"] = {"inventoryLevel": None}
    assert t._variante(n)["disponible"] == 0
    assert t._variante(_nodo("X-1T6", "1.00", disponible=-3))["disponible"] == 0


def test_consultar_solo_acepta_el_sku_exacto_y_publicado(monkeypatch):
    """El filtro de Shopify es por tokens: pedir 92633-1T6 también trae
    92633-1T60. Y un producto en borrador no se vende."""
    monkeypatch.setattr(t, "_pedir", lambda consulta, variables: {
        "productVariants": {"nodes": [
            _nodo("92633-1T6", "169900.00", disponible=2),
            _nodo("92633-1T60", "169900.00", disponible=9),
            _nodo("92633-1T8", "169900.00", disponible=5, estado="DRAFT"),
        ]}})
    r = t.consultar(["92633-1t6", "92633-1T8"])
    assert list(r) == ["92633-1T6"]
    assert r["92633-1T6"]["disponible"] == 2


def test_si_shopify_contesta_con_error_no_se_inventa_una_respuesta(monkeypatch):
    # UN MÓDULO FALSO, no el de verdad: `backend.services.clientes` es del ERP
    # y arrastra a Supabase, que la tanda de dominio (sin base, sin red) no
    # tiene instalado. Con el import real esta prueba pasaba en el Mac y
    # fallaba en GitHub (2026-11-18).
    import sys
    import types
    falso = types.ModuleType("backend.services.clientes")
    falso._shopify_graphql = lambda q, v=None: {"errors": [{"message": "throttled"}]}
    monkeypatch.setitem(sys.modules, "backend.services.clientes", falso)
    with pytest.raises(t.TiendaEnLineaNoDisponible):
        t.consultar(["92633-1T6"])
    with pytest.raises(t.TiendaEnLineaNoDisponible):
        t.buscar("flare")


def test_buscar_pone_arriba_lo_que_se_puede_vender(monkeypatch):
    monkeypatch.setattr(t, "_pedir", lambda consulta, variables: {
        "products": {"nodes": [
            {"title": "Agotado.", "variants": {"nodes": [
                _nodo("A-1T6", "100.00", disponible=0)]}},
            {"title": "Con existencia", "variants": {"nodes": [
                _nodo("B-1T6", "100.00", disponible=3)]}},
        ]}})
    assert [p["nombre"] for p in t.buscar("jean")] == ["Con existencia", "Agotado"]
    assert t.buscar("j") == []          # una letra no es una búsqueda


def test_buscar_le_pide_a_shopify_solo_lo_que_tiene_existencia(monkeypatch):
    """MEDIDO EL 2026-11-19 contra la tienda: «jean» devolvía 25 productos
    publicados y NINGUNO con existencia en Melonn —el catálogo viejo, activo y
    en cero, sale primero—. La vendedora habría visto sólo «agotada». Con
    `inventory_total:>0` los 25 tienen existencia."""
    pedidas = []

    def pedir(consulta, variables):
        pedidas.append(variables)
        return {"products": {"nodes": []}}
    monkeypatch.setattr(t, "_pedir", pedir)
    t.buscar("jean bota")
    assert "inventory_total:>0" in pedidas[0]["q"]
    assert "status:active" in pedidas[0]["q"]
    assert pedidas[0]["q"].startswith("jean bota")
