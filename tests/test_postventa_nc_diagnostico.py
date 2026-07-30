"""Diagnostico: ver una nota credito ya emitida tal cual la guardo Siigo.

Existe porque una NC de cambio en tienda no movio el inventario y no habia
forma de saber si la bodega habia llegado a Siigo o no. Sin esto solo queda
adivinar entre "bug de codigo" y "parametrizacion de Siigo".
"""
from backend.services import postventa_siigo as S


NOTAS = {
    7111: {"name": "NC-1-7111", "number": 7111, "date": "2026-07-30",
           "items": [{"code": "22624-1T8", "quantity": 1}]},
    7100: {"name": "NC-1-7100", "number": 7100, "date": "2026-07-30",
           "items": [{"code": "95527-1T10", "quantity": 1,
                      "warehouse": {"id": 5, "name": "Florida"}}]},
}


def _mock(monkeypatch, paginas):
    monkeypatch.setattr(S.siigo, "siigo_configurado", lambda: True)

    def _get(path, params=None):
        pag = (params or {}).get("page", 1)
        return {"results": paginas[pag - 1] if pag <= len(paginas) else []}
    monkeypatch.setattr(S.siigo, "siigo_get", _get)


def test_encuentra_la_nota_aunque_este_paginas_atras(monkeypatch):
    _mock(monkeypatch, [[NOTAS[7111]], [NOTAS[7100]]])
    r = S.nota_credito_por_numero(7100)
    assert r["nombre"] == "NC-1-7100"
    assert r["items"][0]["warehouse"]["id"] == 5


def test_dice_a_que_bodega_entro_cada_item(monkeypatch):
    """Lo que se quiere saber de un tiron: la prenda entro o no a la tienda."""
    _mock(monkeypatch, [[NOTAS[7100]]])
    r = S.nota_credito_por_numero(7100)
    assert r["bodegas"] == [{"code": "95527-1T10", "bodega_id": 5,
                             "bodega": "Florida"}]


def test_avisa_cuando_el_item_no_trae_bodega(monkeypatch):
    """Sin bodega Siigo no sabe a que inventario devolver la prenda."""
    _mock(monkeypatch, [[NOTAS[7111]]])
    r = S.nota_credito_por_numero(7111)
    assert r["bodegas"] == [{"code": "22624-1T8", "bodega_id": None,
                             "bodega": None}]
    assert r["sin_bodega"] is True


def test_si_no_existe_lo_dice(monkeypatch):
    _mock(monkeypatch, [[NOTAS[7111]]])
    assert S.nota_credito_por_numero(9999)["_error"] == "nota_no_encontrada"
