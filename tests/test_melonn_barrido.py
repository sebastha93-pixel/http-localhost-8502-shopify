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


def test_cursor_arranca_vacio(tmp_path, monkeypatch):
    _aislar_disco(monkeypatch, tmp_path)
    e = mc._barrido_leer()
    assert e["generacion"] == 0
    assert e["pagina"] == 0
    assert e["vistas"] == []
    assert e["ultimo_completo_en"] is None


def test_cursor_guarda_y_lee(tmp_path, monkeypatch):
    _aislar_disco(monkeypatch, tmp_path)
    e = mc._barrido_leer()
    e.update({"generacion": 7, "pagina": 22, "vistas": ["M1", "M2"],
              "paginas_fuera_ventana": 1})
    mc._barrido_guardar(e)

    leido = mc._barrido_leer()
    assert leido["generacion"] == 7
    assert leido["pagina"] == 22
    assert leido["vistas"] == ["M1", "M2"]
    assert leido["paginas_fuera_ventana"] == 1


def test_el_lease_bloquea_a_otro_worker(tmp_path, monkeypatch):
    _aislar_disco(monkeypatch, tmp_path)
    e = mc._barrido_leer()
    assert mc._barrido_tomar_lease(e, "worker-A") is True

    e2 = mc._barrido_leer()
    assert mc._barrido_tomar_lease(e2, "worker-B") is False


def test_el_mismo_worker_puede_renovar_su_lease(tmp_path, monkeypatch):
    _aislar_disco(monkeypatch, tmp_path)
    e = mc._barrido_leer()
    assert mc._barrido_tomar_lease(e, "worker-A") is True
    assert mc._barrido_tomar_lease(mc._barrido_leer(), "worker-A") is True


def test_un_lease_vencido_no_bloquea(tmp_path, monkeypatch):
    """Si un worker muere a mitad de tramo, el cursor no puede quedar tomado
    para siempre."""
    from datetime import datetime, timedelta
    _aislar_disco(monkeypatch, tmp_path)
    e = mc._barrido_leer()
    e["lease_worker"] = "worker-muerto"
    e["lease_hasta"] = (datetime.utcnow() - timedelta(seconds=10)).isoformat()
    mc._barrido_guardar(e)

    assert mc._barrido_tomar_lease(mc._barrido_leer(), "worker-B") is True


def test_filtrar_ventana_deja_pasar_lo_reciente(tmp_path, monkeypatch):
    corte = mc._fecha_corte()
    items = [_pedido(1, dias_atras=5), _pedido(2, dias_atras=200, code=8)]
    assert len(mc._filtrar_ventana(items, corte)) == 1


def test_filtrar_ventana_conserva_un_abierto_viejo():
    """Un pedido de hace 200 días que sigue EN TRÁNSITO no se descarta: sigue
    siendo trabajo pendiente."""
    corte = mc._fecha_corte()
    items = [_pedido(1, dias_atras=200, code=7)]   # 7 = en tránsito = abierto
    assert len(mc._filtrar_ventana(items, corte)) == 1


def test_normalizar_lote_descarta_b2b():
    crudo = _pedido(1)
    crudo["is_b2b"] = True
    assert mc._normalizar_lote([crudo]) == []


def test_normalizar_lote_descarta_estado_fuera_de_whitelist():
    assert mc._normalizar_lote([_pedido(1, code=15)]) == []   # 15 = Canceled


def test_normalizar_lote_normaliza_lo_valido():
    out = mc._normalizar_lote([_pedido(1, code=7)])
    assert len(out) == 1
    assert out[0]["orden_tienda"] == "T1"
    assert out[0]["sub_estado_logistico"] == "en_transito"


def test_fusionar_agrega_los_nuevos():
    vivos = [{"orden_melonn": "M1", "orden_tienda": "T1"}]
    frescos = [{"orden_melonn": "M2", "orden_tienda": "T2"}]
    out, nuevos = mc._fusionar_tramo(vivos, frescos)
    assert len(out) == 2
    assert nuevos == 1


def test_fusionar_conserva_lo_enriquecido():
    """El listado de Melonn NO trae cliente ni ciudad. Si el fresco los pisa con
    vacío, se pierde el dato de Shopify y no vuelve hasta el próximo enrich."""
    vivos = [{"orden_melonn": "M1", "nombre_comprador": "Ana",
              "ciudad_destino": "Medellin", "guia_real": "GUIA-9"}]
    frescos = [{"orden_melonn": "M1", "nombre_comprador": "",
                "ciudad_destino": "", "guia_real": "",
                "estado_melonn_code": 7}]
    out, _ = mc._fusionar_tramo(vivos, frescos)
    assert out[0]["nombre_comprador"] == "Ana"
    assert out[0]["ciudad_destino"] == "Medellin"
    assert out[0]["guia_real"] == "GUIA-9"
    assert out[0]["estado_melonn_code"] == 7      # el fresco SÍ manda en estado


def test_fusionar_detecta_el_despacho():
    vivos = [{"orden_melonn": "M1", "sub_estado_logistico": "pendiente_despacho"}]
    frescos = [{"orden_melonn": "M1", "sub_estado_logistico": "en_transito"}]
    out, _ = mc._fusionar_tramo(vivos, frescos)
    assert out[0]["fecha_despacho_observada"]
    assert out[0]["fecha_despacho_confiable"] is True


def test_fusionar_no_reanota_un_despacho_ya_visto():
    """Idempotencia: un pedido puede venir en dos tramos por el traslape."""
    vivos = [{"orden_melonn": "M1", "sub_estado_logistico": "pendiente_despacho"}]
    frescos = [{"orden_melonn": "M1", "sub_estado_logistico": "en_transito"}]
    out, _ = mc._fusionar_tramo(vivos, frescos)
    fecha = out[0]["fecha_despacho_observada"]

    out2, _ = mc._fusionar_tramo(out, [{"orden_melonn": "M1",
                                        "sub_estado_logistico": "en_transito"}])
    assert out2[0]["fecha_despacho_observada"] == fecha
    assert len(out2) == 1


def test_fusionar_nunca_quita():
    vivos = [{"orden_melonn": f"M{i}"} for i in range(10)]
    out, _ = mc._fusionar_tramo(vivos, [{"orden_melonn": "M3"}])
    assert len(out) == 10
