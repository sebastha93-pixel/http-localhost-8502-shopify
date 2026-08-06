"""Barrido del listado de Melonn por tramos con cursor.

Las dos primeras pruebas describen el comportamiento de ANTES del cursor, y la
segunda es el bug que este trabajo viene a arreglar: si falla una página, se
pierde todo lo que ya se había traído. Se conservan porque son la red que dice
si el refactor cambió algo sin querer.
"""
from datetime import date, timedelta

import melonn_client as mc


def _pedido(n: int, dias_atras: int = 1, code: int = 7) -> dict:
    """Un pedido crudo del listado, como lo devuelve GET /sell-orders.

    code=7 es "Shipped - in transit": operativo y dentro de la whitelist, así
    que sobrevive todos los filtros y llega al tablero.
    """
    return {
        "internal_order_number": f"{n}",
        "external_order_number": f"T{n}",
        "creation_date": (date.today() - timedelta(days=dias_atras)).isoformat(),
        "sell_order_state": {"code": code, "name": "Shipped - in transit"},
        "payment_on_delivery_amount": "100000",
        "shipping_method": {"code": "SM", "name": "Envia"},
        "warehouse": {"code": "MED-2", "name": "Medellin"},
    }


def _paginas_falsas(monkeypatch, paginas: dict, fallan: set = ()):
    """Sustituye mc._get por un listado simulado. `fallan` son números de
    página que devuelven None, como haría un 429 o un timeout."""
    pedidas = []

    def fake_get(path, params=None):
        p = params["page"]
        pedidas.append(p)
        if p in fallan:
            return None
        return {"data": paginas.get(p, [])}

    monkeypatch.setattr(mc, "_get", fake_get)
    return pedidas


def _aislar_disco(monkeypatch, tmp_path):
    """El caché SQLite por defecto apunta a data/db/ del repo. Las pruebas no
    pueden depender del estado de la máquina."""
    monkeypatch.setattr(mc, "_DB_PATH", tmp_path / "melonn.db")


def test_barrido_completo_trae_todas_las_paginas(tmp_path, monkeypatch):
    _aislar_disco(monkeypatch, tmp_path)
    paginas = {
        0: [_pedido(i) for i in range(100)],
        1: [_pedido(100 + i) for i in range(100)],
        2: [_pedido(200 + i) for i in range(10)],   # incompleta = última
    }
    pedidas = _paginas_falsas(monkeypatch, paginas)

    res = mc._fetch_api_filtrado()

    assert pedidas == [0, 1, 2]
    assert len(res) == 210
    assert mc.ultimo_fetch()["motivo_fin"] == "ultima_pagina"
    assert mc.ultimo_fetch()["completo"] is True


def test_una_pagina_fallida_pierde_el_barrido_entero(tmp_path, monkeypatch):
    """EL BUG. 200 pedidos ya traídos se descartan porque falló la página 2.

    Descartarlos es lo correcto —mejor viejo que mutilado— pero el costo de un
    solo fallo no debería ser el barrido completo. Eso es lo que arregla el
    cursor: a partir de la Tarea 6 esas 2 páginas quedan fusionadas y el tick
    siguiente reintenta solo la 2.
    """
    _aislar_disco(monkeypatch, tmp_path)
    paginas = {
        0: [_pedido(i) for i in range(100)],
        1: [_pedido(100 + i) for i in range(100)],
    }
    _paginas_falsas(monkeypatch, paginas, fallan={2})

    res = mc._fetch_api_filtrado()

    assert res == []
    assert mc.ultimo_fetch()["completo"] is False
    assert mc.ultimo_fetch()["motivo_fin"].startswith("fallo_get_pagina_2")


def test_corte_por_fecha_para_al_salir_de_la_ventana(tmp_path, monkeypatch):
    """El corte de 4ca695d: DOS páginas llenas seguidas sin nada en ventana."""
    _aislar_disco(monkeypatch, tmp_path)
    viejo = lambda n: _pedido(n, dias_atras=200, code=8)   # entregado y viejo
    paginas = {
        0: [_pedido(i) for i in range(100)],
        1: [viejo(100 + i) for i in range(100)],
        2: [viejo(200 + i) for i in range(100)],
        3: [viejo(300 + i) for i in range(100)],
    }
    pedidas = _paginas_falsas(monkeypatch, paginas)

    res = mc._fetch_api_filtrado()

    assert pedidas == [0, 1, 2]          # no pide la 3
    assert len(res) == 100
    assert mc.ultimo_fetch()["motivo_fin"] == "fuera_de_ventana"
    assert mc.ultimo_fetch()["completo"] is True
