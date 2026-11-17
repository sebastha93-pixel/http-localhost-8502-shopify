"""Cola de webhooks de Melonn (2026-11-17).

Cada webhook reescribía el caché entero (>1 MB) en Supabase; varios por segundo
tumbaron la base el 17-nov. Ahora el webhook solo anota el pedido y una pasada
lo fusiona todo con UN guardado. Estas pruebas cuidan que eso siga así y que no
se pierdan pedidos en el camino.
"""
import pytest

import melonn_client as mc


@pytest.fixture
def cola(tmp_path, monkeypatch):
    """Cola en un archivo temporal + Melonn y el caché simulados."""
    monkeypatch.setattr(mc, "_COLA_PATH", tmp_path / "cola.db")
    cache = {"pedidos": [
        {"orden_melonn": "M1", "orden_tienda": "T1", "estado_melonn": "viejo", "nombre_comprador": "Ana"},
        {"orden_melonn": "M2", "orden_tienda": "T2", "estado_melonn": "viejo"},
    ]}
    guardados = []
    detalles_pedidos = []

    def fake_detalle(ident):
        detalles_pedidos.append(ident)
        n = str(ident).lstrip("MmT")
        if n == "404":
            return None, "no encontrado"
        return {"orden_melonn": f"M{n}", "orden_tienda": f"T{n}",
                "estado_melonn": "nuevo", "nombre_comprador": ""}, ""

    monkeypatch.setattr(mc, "_detalle_normalizado", fake_detalle)
    monkeypatch.setattr(mc, "_cache_leer",
                        lambda ignorar_ttl=False: ([dict(p) for p in cache["pedidos"]],
                                                   None, True, "api_live"))
    monkeypatch.setattr(mc, "_cache_guardar",
                        lambda pedidos, fuente="api_live", forzar=False: guardados.append(list(pedidos)))
    monkeypatch.setattr(mc, "cuota_agotada", lambda: False)
    return {"guardados": guardados, "detalles": detalles_pedidos, "cache": cache}


def test_muchos_webhooks_un_solo_guardado(cola):
    for _ in range(5):
        assert mc.encolar_webhook("T1", "SHIPPED")["accion"] == "encolado"
    mc.encolar_webhook("T2", "SHIPPED")
    assert mc.pendientes_cola_webhooks() == 2      # T1 repetido = una fila

    r = mc.procesar_cola_webhooks()

    assert r["procesados"] == 2 and r["guardado"] is True
    assert len(cola["guardados"]) == 1             # UNA escritura, no seis
    assert cola["detalles"] == ["T1", "T2"]        # un detalle por pedido
    guardado = {p["orden_tienda"]: p for p in cola["guardados"][0]}
    assert guardado["T1"]["estado_melonn"] == "nuevo"
    assert guardado["T1"]["nombre_comprador"] == "Ana"   # lo enriquecido no se borra
    assert mc.pendientes_cola_webhooks() == 0


def test_cola_vacia_no_toca_el_cache(cola):
    r = mc.procesar_cola_webhooks()
    assert r["procesados"] == 0 and cola["guardados"] == []


def test_pedido_nuevo_se_agrega(cola):
    mc.encolar_webhook("T9", "CREATED")
    mc.procesar_cola_webhooks()
    assert {p["orden_tienda"] for p in cola["guardados"][0]} == {"T1", "T2", "T9"}


def test_entregado_no_se_pierde_con_un_evento_posterior(cola):
    mc.encolar_webhook("T1", "DELIVERED_TO_BUYER")
    mc.encolar_webhook("T1", "SOME_OTHER_EVENT")
    r = mc.procesar_cola_webhooks()
    assert [p["orden_tienda"] for p in r["entregados"]] == ["T1"]


def test_fallido_se_reintenta_y_luego_se_descarta(cola):
    mc.encolar_webhook("T404", "SHIPPED")
    for i in range(mc._MAX_INTENTOS_COLA - 1):
        r = mc.procesar_cola_webhooks()
        assert r["fallidos"] == 1 and mc.pendientes_cola_webhooks() == 1
    mc.procesar_cola_webhooks()
    assert mc.pendientes_cola_webhooks() == 0
    assert cola["guardados"] == []                 # nada que guardar


def test_cuota_agotada_no_gasta_y_conserva_la_cola(cola, monkeypatch):
    monkeypatch.setattr(mc, "cuota_agotada", lambda: True)
    mc.encolar_webhook("T1", "SHIPPED")
    r = mc.procesar_cola_webhooks()
    assert r["omitido"] == "cuota_melonn_agotada"
    assert cola["detalles"] == [] and mc.pendientes_cola_webhooks() == 1


def test_cache_ilegible_no_escribe_lista_parcial(cola, monkeypatch):
    lanzado = []
    monkeypatch.setattr(mc, "_cache_leer", lambda ignorar_ttl=False: None)
    monkeypatch.setattr(mc, "_refresh_background", lambda: lanzado.append(1))
    mc.encolar_webhook("T1", "SHIPPED")
    r = mc.procesar_cola_webhooks()
    assert r["omitido"] == "cache_ilegible_refresh_lanzado"
    assert cola["guardados"] == [] and lanzado == [1]


def test_si_vuelve_a_llegar_durante_la_pasada_queda_para_la_siguiente(cola, monkeypatch):
    mc.encolar_webhook("T1", "SHIPPED")
    original = mc._detalle_normalizado

    def detalle_y_llega_otro(ident):
        mc.encolar_webhook("T1", "OUT_FOR_DELIVERY")   # llega mientras procesamos
        return original(ident)

    monkeypatch.setattr(mc, "_detalle_normalizado", detalle_y_llega_otro)
    mc.procesar_cola_webhooks()
    assert mc.pendientes_cola_webhooks() == 1      # no se borró el aviso nuevo


def test_si_la_cola_falla_cae_al_refresco_directo(cola, monkeypatch, tmp_path):
    llamado = []
    monkeypatch.setattr(mc, "_cola_conn", lambda: (_ for _ in ()).throw(OSError("disco")))
    monkeypatch.setattr(mc, "refrescar_un_pedido",
                        lambda ident: llamado.append(ident) or {"ok": True, "accion": "actualizado"})
    assert mc.encolar_webhook("T1", "SHIPPED")["accion"] == "actualizado"
    assert llamado == ["T1"]
