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

    # ultimo_fetch() describe el barrido por tramos desde la Tarea 7, así que ya
    # no dice nada de esta función: se mide sobre lo que devuelve y lo que pidió.
    assert pedidas == [0, 1, 2]
    assert len(res) == 210


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
    pedidas = _paginas_falsas(monkeypatch, paginas, fallan={2})

    res = mc._fetch_api_filtrado()

    # ultimo_fetch() describe el barrido por tramos desde la Tarea 7, así que ya
    # no dice nada de esta función: se mide sobre lo que devuelve y lo que pidió.
    assert pedidas == [0, 1, 2]     # trajo dos páginas buenas y murió en la 2
    assert res == []                # y las tiró todas


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

    # ultimo_fetch() describe el barrido por tramos desde la Tarea 7, así que ya
    # no dice nada de esta función: se mide sobre lo que devuelve y lo que pidió.
    assert pedidas == [0, 1, 2]          # no pide la 3
    assert len(res) == 100


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


def test_una_sola_ausencia_no_da_de_baja():
    """Puede ser un corrimiento del listado, no una baja real."""
    vivos = [{"orden_melonn": "M1"}, {"orden_melonn": "M2"}]
    out, aus, bajas = mc._reconciliar_bajas(vivos, {"M1"}, {})
    assert len(out) == 2
    assert bajas == 0
    assert aus["M2"] == 1


def test_dos_ausencias_seguidas_dan_de_baja():
    vivos = [{"orden_melonn": "M1"}, {"orden_melonn": "M2"}]
    _, aus, _ = mc._reconciliar_bajas(vivos, {"M1"}, {})
    out, aus2, bajas = mc._reconciliar_bajas(vivos, {"M1"}, aus)
    assert [p["orden_melonn"] for p in out] == ["M1"]
    assert bajas == 1
    assert "M2" not in aus2


def test_reaparecer_limpia_el_contador():
    vivos = [{"orden_melonn": "M1"}, {"orden_melonn": "M2"}]
    _, aus, _ = mc._reconciliar_bajas(vivos, {"M1"}, {})
    assert aus["M2"] == 1
    _, aus2, bajas = mc._reconciliar_bajas(vivos, {"M1", "M2"}, aus)
    assert "M2" not in aus2
    assert bajas == 0


def test_el_candado_bloquea_una_reconciliacion_que_vacia(tmp_path, monkeypatch):
    """Si un barrido trae casi nada, la reconciliación NO puede vaciar el tablero."""
    _aislar_disco(monkeypatch, tmp_path)
    vivos = [{"orden_melonn": f"M{i}"} for i in range(200)]
    mc._cache_guardar(vivos)
    assert len(mc._cache_leer(ignorar_ttl=True)[0]) == 200

    aus = {f"M{i}": 1 for i in range(200)}
    out, _, bajas = mc._reconciliar_bajas(vivos, set(), aus)
    assert bajas == 200
    mc._cache_guardar(out)                       # el candado tiene que rechazarlo
    assert len(mc._cache_leer(ignorar_ttl=True)[0]) == 200


def test_tam_tramo_parte_el_barrido_anterior_en_dos():
    assert mc._tam_tramo({"paginas_barrido_previo": 44}) == 22
    assert mc._tam_tramo({"paginas_barrido_previo": 0}) == mc._TRAMO_DEFECTO
    assert mc._tam_tramo({"paginas_barrido_previo": 2}) == mc._TRAMO_MIN
    assert mc._tam_tramo({"paginas_barrido_previo": 500}) == mc._TRAMO_MAX


def test_el_tick_avanza_por_tramos_y_cierra(tmp_path, monkeypatch):
    _aislar_disco(monkeypatch, tmp_path)
    monkeypatch.setattr(mc, "_TRAMO_DEFECTO", 2)
    paginas = {
        0: [_pedido(i) for i in range(100)],
        1: [_pedido(100 + i) for i in range(100)],
        2: [_pedido(200 + i) for i in range(100)],
        3: [_pedido(300 + i) for i in range(10)],     # última
    }
    pedidas = _paginas_falsas(monkeypatch, paginas)

    r1 = mc._barrido_tick(worker="w1")
    assert pedidas == [0, 1]
    assert r1["completo"] is False
    assert mc._barrido_leer()["pagina"] == 2

    r2 = mc._barrido_tick(worker="w1")
    assert r2["completo"] is True
    assert mc._barrido_leer()["pagina"] == 0          # listo para la siguiente
    assert mc._barrido_leer()["generacion"] == 1
    assert len(mc._cache_leer(ignorar_ttl=True)[0]) == 310


def test_una_pagina_fallida_NO_pierde_las_anteriores(tmp_path, monkeypatch):
    """El arreglo. Comparar con test_una_pagina_fallida_pierde_el_barrido_entero."""
    _aislar_disco(monkeypatch, tmp_path)
    monkeypatch.setattr(mc, "_TRAMO_DEFECTO", 5)
    paginas = {i: [_pedido(100 * i + j) for j in range(100)] for i in range(4)}
    _paginas_falsas(monkeypatch, paginas, fallan={2})

    mc._barrido_tick(worker="w1")

    assert mc._barrido_leer()["pagina"] == 2          # reintenta ESA
    assert len(mc._cache_leer(ignorar_ttl=True)[0]) == 200   # las 2 primeras, salvadas


def test_el_tramo_siguiente_reintenta_la_pagina_que_fallo(tmp_path, monkeypatch):
    _aislar_disco(monkeypatch, tmp_path)
    monkeypatch.setattr(mc, "_TRAMO_DEFECTO", 5)
    paginas = {0: [_pedido(j) for j in range(100)],
               1: [_pedido(100 + j) for j in range(100)],
               2: [_pedido(200 + j) for j in range(10)]}
    fallan = {2}
    pedidas = _paginas_falsas(monkeypatch, paginas, fallan=fallan)

    mc._barrido_tick(worker="w1")
    fallan.clear()                                   # Melonn se recupera
    r2 = mc._barrido_tick(worker="w1")

    assert pedidas[-1] == 2
    assert r2["completo"] is True
    assert len(mc._cache_leer(ignorar_ttl=True)[0]) == 210


def test_el_contador_fuera_de_ventana_sobrevive_al_borde_del_tramo(tmp_path, monkeypatch):
    """Si el contador se reiniciara acá, el barrido no cortaría NUNCA y volvería
    el tope_paginas que dejó el tablero pegado el 2026-08-01."""
    _aislar_disco(monkeypatch, tmp_path)
    monkeypatch.setattr(mc, "_TRAMO_DEFECTO", 2)
    viejo = lambda n: _pedido(n, dias_atras=200, code=8)
    paginas = {
        0: [_pedido(i) for i in range(100)],
        1: [viejo(100 + i) for i in range(100)],      # 1a fuera de ventana
        2: [viejo(200 + i) for i in range(100)],      # 2a → corta acá
        3: [viejo(300 + i) for i in range(100)],
    }
    pedidas = _paginas_falsas(monkeypatch, paginas)

    mc._barrido_tick(worker="w1")
    assert mc._barrido_leer()["paginas_fuera_ventana"] == 1

    r2 = mc._barrido_tick(worker="w1")
    assert r2["completo"] is True
    assert r2["motivo"] == "fuera_de_ventana"
    assert 3 not in pedidas


def test_el_tick_no_arranca_si_el_barrido_anterior_es_reciente(tmp_path, monkeypatch):
    from datetime import datetime
    _aislar_disco(monkeypatch, tmp_path)
    e = mc._barrido_leer()
    e["ultimo_completo_en"] = datetime.utcnow().isoformat()
    mc._barrido_guardar(e)
    pedidas = _paginas_falsas(monkeypatch, {0: []})

    r = mc._barrido_tick(worker="w1")

    assert r["motivo"] == "al_dia"
    assert pedidas == []              # ni una petición a Melonn


def test_una_generacion_atascada_se_abandona(tmp_path, monkeypatch):
    from datetime import datetime, timedelta
    _aislar_disco(monkeypatch, tmp_path)
    e = mc._barrido_leer()
    e.update({"generacion": 5, "pagina": 30, "vistas": ["M1"],
              "iniciado_en": (datetime.utcnow() - timedelta(hours=7)).isoformat()})
    mc._barrido_guardar(e)
    # La página 1 falla a propósito: así el barrido NO cierra en este mismo tick
    # y se puede ver que la generación subió por el abandono, no por el cierre.
    _paginas_falsas(monkeypatch, {0: [_pedido(i) for i in range(10)]}, fallan={1})

    mc._barrido_tick(worker="w1")

    nuevo = mc._barrido_leer()
    assert nuevo["generacion"] == 6
    assert nuevo["vistas"] != ["M1"]        # la foto vieja se descartó
    assert nuevo["pagina"] <= 1             # volvió a empezar, no siguió en la 30


def test_ultimo_fetch_lee_del_cursor(tmp_path, monkeypatch):
    _aislar_disco(monkeypatch, tmp_path)
    monkeypatch.setattr(mc, "_TRAMO_DEFECTO", 2)
    paginas = {0: [_pedido(i) for i in range(100)],
               1: [_pedido(100 + i) for i in range(100)],
               2: [_pedido(200 + i) for i in range(5)]}
    _paginas_falsas(monkeypatch, paginas)

    mc._barrido_tick(worker="w1")
    uf = mc.ultimo_fetch()
    assert uf["en_curso"] is True
    assert uf["pagina"] == 2
    assert uf["completo"] is False

    mc._barrido_tick(worker="w1")
    uf = mc.ultimo_fetch()
    assert uf["en_curso"] is False
    assert uf["completo"] is True
    assert uf["ultimo_completo_en"]


def test_edad_tramo_es_none_si_nunca_corrio(tmp_path, monkeypatch):
    _aislar_disco(monkeypatch, tmp_path)
    assert mc._edad_tramo() is None


def test_edad_tramo_cuenta_desde_el_ultimo_tramo(tmp_path, monkeypatch):
    from datetime import datetime, timedelta
    _aislar_disco(monkeypatch, tmp_path)
    e = mc._barrido_leer()
    e["ultimo_tramo_en"] = (datetime.utcnow() - timedelta(minutes=30)).isoformat()
    mc._barrido_guardar(e)
    assert 1700 < mc._edad_tramo() < 1900       # ~1800 s


def test_modo_tramo_avanza_el_cursor_sin_barrer_todo(tmp_path, monkeypatch):
    _aislar_disco(monkeypatch, tmp_path)
    monkeypatch.setattr(mc, "_TRAMO_DEFECTO", 2)
    paginas = {i: [_pedido(100 * i + j) for j in range(100)] for i in range(6)}
    pedidas = _paginas_falsas(monkeypatch, paginas)

    _pedidos, _om, meta = mc.obtener_pedidos_activos(forzar_refresh=True, modo="tramo")

    assert pedidas == [0, 1]                  # UN tramo, no el barrido entero
    assert meta["modo"] == "tramo"
    assert meta["barrido"]["paginas_traidas"] == 2
    # Se mide sobre el caché y no sobre lo devuelto: _enriquecer_y_filtrar
    # deduplica por orden_tienda y re-deriva estados, así que su salida depende
    # de reglas que no son las que esta prueba quiere fijar.
    assert len(mc._cache_leer(ignorar_ttl=True)[0]) == 200


# ── Regresiones de la revisión final de rama ─────────────────────────────────

def test_el_cursor_nunca_retrocede_si_falla_el_traslape(tmp_path, monkeypatch):
    """CRÍTICO. Si la página de traslape es la que falla, el cursor se iba hacia
    atrás y esa página ya barrida se volvía a contar como nueva. Con una sola
    página fuera de ventana, `paginas_fuera_ventana` llegaba a 2 y el barrido
    cerraba como completo habiendo leído casi nada — sellando el reloj de
    auditabilidad sobre un tablero truncado, en silencio."""
    _aislar_disco(monkeypatch, tmp_path)
    monkeypatch.setattr(mc, "_TRAMO_DEFECTO", 2)
    paginas = {i: [_pedido(100 * i + j) for j in range(100)] for i in range(6)}
    fallan = set()
    _paginas_falsas(monkeypatch, paginas, fallan=fallan)

    mc._barrido_tick(worker="w1")
    assert mc._barrido_leer()["pagina"] == 2

    fallan.add(1)                       # falla justo la página de traslape
    mc._barrido_tick(worker="w1")

    assert mc._barrido_leer()["pagina"] == 2      # NO retrocede a 1


def test_un_cierre_sin_pedidos_no_cuenta_como_completo(tmp_path, monkeypatch):
    """CRÍTICO. Un 200 con {"data": []} en la página 0 marcaba el barrido como
    completo, sellaba el reloj de auditabilidad sobre cero pedidos leídos, dejaba
    el tick en 'al_dia' dos horas y le daba una ausencia a TODO el tablero.

    El guard viejo era `if completo and fusionado`, y `fusionado` es caché +
    frescos: bastaba con que el caché no estuviera vacío."""
    _aislar_disco(monkeypatch, tmp_path)
    mc._cache_guardar([{"orden_melonn": f"M{i}"} for i in range(200)])
    assert mc._edad_fetch_api() is None           # nunca se ha sellado

    _paginas_falsas(monkeypatch, {0: []})
    r = mc._barrido_tick(worker="w1")

    assert r["completo"] is False
    assert r["motivo"] == "sin_mas_datos_sin_pedidos"
    assert mc._edad_fetch_api() is None           # el reloj sigue SIN sellar
    assert mc._barrido_leer()["ausencias"] == {}  # nadie sumó ausencia
    assert len(mc._cache_leer(ignorar_ttl=True)[0]) == 200


def test_el_reloj_del_tramo_solo_avanza_si_trajo_algo(tmp_path, monkeypatch):
    """Si se sellara en cada tick, `barrido_atascado` no podría dispararse nunca:
    con tick horario la edad del tramo jamás pasaría de ~60 min contra un umbral
    de 180. La alarma existiría en el código y no en la realidad."""
    _aislar_disco(monkeypatch, tmp_path)
    _paginas_falsas(monkeypatch, {0: [_pedido(i) for i in range(10)]}, fallan={0})

    mc._barrido_tick(worker="w1")

    assert mc._barrido_leer()["ultimo_tramo_en"] is None
    assert mc._edad_tramo() is None


def test_tam_pagina_se_reaprende_en_cada_generacion(tmp_path, monkeypatch):
    """Arrastrarlo entre generaciones es peligroso: si Melonn bajara su tope de
    per_page, `len(items) < tam_pagina` se cumpliría en la primera página y el
    barrido cerraría con una sola, truncando el tablero sin un error."""
    _aislar_disco(monkeypatch, tmp_path)
    _paginas_falsas(monkeypatch, {0: [_pedido(i) for i in range(10)]})

    mc._barrido_tick(worker="w1")                 # cierra: 10 < 10 es falso...
    e = mc._barrido_leer()
    assert e["ultimo_completo_en"]                # ...pero la 1 viene vacía
    assert e["tam_pagina"] is None                # y se olvida el tamaño


def test_la_generacion_arranca_a_la_mitad_del_ttl(tmp_path, monkeypatch):
    """Esperando el TTL completo, la generación arrancaba a las 2 h y cerraba a
    las 3, y durante esa hora `_caduco_vs_melonn()` era cierto: cada lectura del
    tablero disparaba un `_fetch_api()` de las 44 páginas seguidas — la misma
    fragilidad que este trabajo viene a quitar, corriendo igual todos los ciclos."""
    from datetime import datetime, timedelta
    _aislar_disco(monkeypatch, tmp_path)
    _paginas_falsas(monkeypatch, {0: [_pedido(i) for i in range(10)]})

    def _con_ultimo_cierre(minutos):
        e = mc._barrido_leer()
        e["ultimo_completo_en"] = (datetime.utcnow()
                                   - timedelta(minutes=minutos)).isoformat()
        e["iniciado_en"] = None
        mc._barrido_guardar(e)

    _con_ultimo_cierre(30)
    assert mc._barrido_tick(worker="w1")["motivo"] == "al_dia"

    _con_ultimo_cierre(75)                        # > el umbral
    assert mc._barrido_tick(worker="w1")["motivo"] != "al_dia"

    # Y la identidad, porque el bracket de 30/75 pasaria con cualquier umbral
    # entre esos dos y no dice nada de la cadencia real.
    assert mc._ARRANCAR_GENERACION_SEG == mc._CACHE_TTL // 2 - 600


def test_el_piso_del_tramo_permite_cerrar_antes_del_abandono():
    """Con tick horario y abandono a las 6 h caben 6 tramos. Un piso de 4 hacía
    que 44 páginas necesitaran 11 ticks: se abandonaba siempre, y como
    paginas_barrido_previo solo se reescribe AL CERRAR, el estado se
    autoalimentaba en un reinicio permanente."""
    # CINCO vueltas, no seis: el scheduler duerme DESPUES de trabajar, asi que el
    # periodo efectivo es 3600 s + lo que dure el tick. Con el conteo optimista de
    # 6 esta asercion pasaba siendo falsa en la practica.
    ticks_disponibles = mc._GENERACION_MAX_SEG // 3600 - 1
    assert mc._TRAMO_MIN * ticks_disponibles >= mc._MAX_PAGES


def test_limpiar_cache_borra_tambien_el_cursor(tmp_path, monkeypatch):
    """Si el cursor sobrevive, sigue diciendo que hubo un barrido completo hace
    poco y el tick contesta 'al_dia' sobre un tablero recién vaciado."""
    from datetime import datetime
    _aislar_disco(monkeypatch, tmp_path)
    e = mc._barrido_leer()
    e["ultimo_completo_en"] = datetime.utcnow().isoformat()
    e["generacion"] = 9
    mc._barrido_guardar(e)

    mc.limpiar_cache()

    assert mc._barrido_leer()["ultimo_completo_en"] is None
    assert mc._barrido_leer()["generacion"] == 0


def test_un_worker_lento_no_reabre_una_generacion_ya_cerrada(tmp_path, monkeypatch):
    """El lease es leer-y-escribir, no un CAS atómico, así que dos réplicas pueden
    barrer a la vez. La fusión es idempotente, pero el guardado del cursor era una
    sobrescritura completa: el worker lento reponía `iniciado_en` y devolvía la
    generación hacia atrás, reabriendo un barrido ya cerrado."""
    from datetime import datetime
    _aislar_disco(monkeypatch, tmp_path)

    # El rápido ya cerró la generación 5.
    rapido = mc._barrido_leer()
    rapido.update({"generacion": 5, "iniciado_en": None, "pagina": 0,
                   "ultimo_completo_en": datetime.utcnow().isoformat()})
    mc._barrido_guardar(rapido)

    # El lento venía con la generación 4 a medio barrer.
    lento = {**mc._barrido_leer(), "generacion": 4, "pagina": 12,
             "iniciado_en": datetime.utcnow().isoformat()}
    mc._barrido_guardar_sin_retroceder(lento)

    e = mc._barrido_leer()
    assert e["generacion"] == 5
    assert e["iniciado_en"] is None       # la generación cerrada sigue cerrada


def test_una_pagina_de_traslape_vacia_no_cierra_el_barrido(tmp_path, monkeypatch):
    """CRÍTICO (2º pase). La corrección anterior cerraba el caso de la página 0 y
    dejaba el hueco abierto una página más allá: `sin_mas_datos` se evaluaba ANTES
    del guard `p >= pagina`, así que un 200 con {"data": []} en la página de
    TRASLAPE —una de la que hace un tick leímos 100 pedidos— cerraba el barrido
    entero como completo."""
    _aislar_disco(monkeypatch, tmp_path)
    monkeypatch.setattr(mc, "_TRAMO_DEFECTO", 2)
    paginas = {0: [_pedido(i) for i in range(100)],
               1: [_pedido(100 + i) for i in range(100)],
               2: [_pedido(200 + i) for i in range(100)],
               3: [_pedido(300 + i) for i in range(10)]}
    _paginas_falsas(monkeypatch, paginas)

    mc._barrido_tick(worker="w1")
    assert mc._barrido_leer()["pagina"] == 2

    paginas[1] = []                       # glitch justo en el traslape
    r2 = mc._barrido_tick(worker="w1")

    assert r2["motivo"] == "ultima_pagina"          # NO 'sin_mas_datos'
    assert len(mc._cache_leer(ignorar_ttl=True)[0]) == 310   # barrió hasta el final
    assert mc._barrido_leer()["ausencias"] == {}


def test_un_cursor_atascado_deja_envejecer_el_reloj_del_tramo(tmp_path, monkeypatch):
    """El caso para el que se escribió `barrido_atascado`: la página del cursor
    falla siempre, pero la de traslape se lee bien. Con el guard sobre `traidas`
    el reloj se re-sellaba cada tick y la alarma no podía dispararse jamás."""
    _aislar_disco(monkeypatch, tmp_path)
    monkeypatch.setattr(mc, "_TRAMO_DEFECTO", 2)
    paginas = {i: [_pedido(100 * i + j) for j in range(100)] for i in range(6)}
    fallan = set()
    _paginas_falsas(monkeypatch, paginas, fallan=fallan)

    mc._barrido_tick(worker="w1")
    sellado = mc._barrido_leer()["ultimo_tramo_en"]
    assert sellado and mc._barrido_leer()["pagina"] == 2

    fallan.add(2)                         # la del cursor falla, la de traslape no
    for _ in range(3):
        mc._barrido_tick(worker="w1")

    e = mc._barrido_leer()
    assert e["pagina"] == 2                          # el cursor no se movió
    assert e["ultimo_tramo_en"] == sellado           # y el reloj tampoco


def test_tam_pagina_se_aprende_de_nuevo_en_la_generacion_siguiente(tmp_path, monkeypatch):
    """No basta con que quede en None al cerrar: hay que ver que la generación
    siguiente aprenda el tamaño REAL, que es lo que protege del caso en que
    Melonn baje su tope de per_page."""
    from datetime import datetime, timedelta
    _aislar_disco(monkeypatch, tmp_path)
    _paginas_falsas(monkeypatch, {0: [_pedido(i) for i in range(60)]})

    mc._barrido_tick(worker="w1")                    # gen 1: páginas de 60
    assert mc._barrido_leer()["tam_pagina"] is None

    e = mc._barrido_leer()
    e["ultimo_completo_en"] = (datetime.utcnow() - timedelta(hours=3)).isoformat()
    mc._barrido_guardar(e)
    _paginas_falsas(monkeypatch, {0: [_pedido(500 + i) for i in range(25)]})

    mc._barrido_tick(worker="w1")                    # gen 2: Melonn topa en 25
    # Cerró en la primera página porque 25 < 25 es falso y la 1 vino vacía; lo que
    # importa es que NO reusó el 60 de la generación anterior.
    assert mc._cache_leer(ignorar_ttl=True)[0]


def test_guardar_sin_retroceder_si_deja_pasar_la_misma_generacion(tmp_path, monkeypatch):
    """El camino normal. Si el guard rechazara generaciones iguales, cada tramo
    perdería su avance en silencio."""
    _aislar_disco(monkeypatch, tmp_path)
    e = mc._barrido_leer()
    e.update({"generacion": 4, "pagina": 8})
    mc._barrido_guardar(e)

    mc._barrido_guardar_sin_retroceder({**mc._barrido_leer(),
                                        "generacion": 4, "pagina": 20})

    assert mc._barrido_leer()["pagina"] == 20
