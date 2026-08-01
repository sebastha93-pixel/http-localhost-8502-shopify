"""
Cliente Melonn API — MALE'DENIM

Estrategia de caché (simple y robusta):
  1. SQLite local  → si hay datos frescos (<4h), retorna sin tocar la API
  2. Melonn API    → si el caché venció o se forzó refresh
  3. SQLite stale  → si la API falla, usa datos viejos del disco
  4. JSON bootstrap→ si no hay nada en disco, carga datos pre-generados del repo

⚠️  Límite de la API Melonn: 1 request/segundo (fuente: docs oficiales)
    Usamos 0.8 req/s → 1.25s de intervalo mínimo entre llamadas.

📦  El endpoint GET /sell-orders (list) devuelve solo 12 campos básicos.
    Cliente, producto y fechas de despacho se obtienen de Shopify API.
"""

import hashlib
import json
import logging
import re
import sqlite3
import threading
import time
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import requests

log = logging.getLogger(__name__)

# ── Background refresh ─────────────────────────────────────────────────────────
_bg_lock    = threading.Lock()
_bg_running = False

# Candado COMPARTIDO entre los 4 workers de Uvicorn. `_bg_running` es una
# variable de proceso, así que solo frenaba refreshes dentro del MISMO worker:
# los 4 podían estar martillando Melonn al mismo tiempo.
#
# El círculo vicioso que esto rompe (2026-07-28):
#   1. Melonn nos devuelve 429 → _fetch_api muere y retorna vacío
#   2. al retornar vacío, el caché NO se actualiza → sigue stale
#   3. cada visita a la página ve caché stale y vuelve a llamar acá
#   4. → otro martilleo de ~60s a Melonn, que vuelve a dar 429
# Nunca salía solo: mientras más se usaba la app, más se saturaba. Por eso
# "autorizar despacho" dejó de funcionar — no quedaba cuota para el POST.
_BG_LOCK_PATH = Path("/tmp/maledenim-melonn-bg.lock")
_BG_CLAIM_SEC     = 180    # un refresh no debería tardar más que esto
_BG_COOLDOWN_SEC  = 900    # 15 min de tregua a Melonn tras un fallo


def _bg_bloqueado() -> tuple[bool, str]:
    """(True, motivo) si otro worker está refrescando o venimos de un fallo."""
    try:
        estado, hasta = _BG_LOCK_PATH.read_text().strip().split(":", 1)
        restante = float(hasta) - time.time()
    except FileNotFoundError:
        return False, ""
    except Exception:
        return False, ""      # candado corrupto → no bloquear
    if restante <= 0:
        return False, ""
    return True, f"{estado}, {int(restante)}s restantes"


def _bg_marcar(estado: str, segundos: float) -> None:
    try:
        _BG_LOCK_PATH.write_text(f"{estado}:{time.time() + segundos:.0f}")
    except Exception as e:
        log.debug(f"[bg] no se pudo escribir el candado: {e}")


def _bg_liberar() -> None:
    try:
        _BG_LOCK_PATH.unlink()
    except Exception:
        pass


def _refresh_background():
    """
    Lanza un fetch completo en un hilo daemon.
    No lanza otro si ya hay uno en curso (en ESTE worker o en cualquier otro),
    ni si venimos de un fallo reciente por saturación de Melonn.
    Actualiza Supabase cuando termina → próxima sesión carga datos frescos.
    """
    global _bg_running
    bloqueado, motivo = _bg_bloqueado()
    if bloqueado:
        log.info(f"[bg] Skip: {motivo}")
        return
    with _bg_lock:
        if _bg_running:
            log.info("[bg] Skip: ya hay un refresh en curso")
            return
        _bg_running = True
    _bg_marcar("refrescando", _BG_CLAIM_SEC)

    def _run():
        global _bg_running
        t0 = time.time()
        try:
            pedidos = _fetch_api()
            elapsed = time.time() - t0
            if pedidos:
                _cache_guardar(pedidos)
                _bg_liberar()
                log.info(f"[bg] OK: {len(pedidos)} pedidos guardados en Supabase · {elapsed:.1f}s")
            else:
                # Casi siempre es 429. Darle tregua a Melonn en vez de volver a
                # intentar en la siguiente visita a la página.
                _bg_marcar("cooldown tras fallo", _BG_COOLDOWN_SEC)
                log.warning(
                    f"[bg] _fetch_api retornó vacío después de {elapsed:.1f}s "
                    f"— pausando refreshes {_BG_COOLDOWN_SEC}s"
                )
        except Exception as e:
            elapsed = time.time() - t0
            _bg_marcar("cooldown tras error", _BG_COOLDOWN_SEC)
            log.error(f"[bg] ERROR después de {elapsed:.1f}s: {e}", exc_info=True)
        finally:
            with _bg_lock:
                _bg_running = False

    threading.Thread(target=_run, daemon=True).start()
    log.info("[bg] Refresh iniciado en segundo plano")


# Enriquecimiento con datos de cliente desde Shopify
try:
    import shopify_enricher as _enricher
    _SHOPIFY_ENRICHER_OK = True
except ImportError:
    _SHOPIFY_ENRICHER_OK = False

# ── Config ─────────────────────────────────────────────────────────────────────
_BASE_URL    = "https://api.orbita.melonn.com"
_TIMEOUT     = 45         # antes 20s — API Melonn responde lento en horas pico
_CONNECT_TO  = 8          # timeout de conexión separado
# 100 por página (antes 25). Con ~535 pedidos activos, el sync horario pasa de
# ~22 peticiones a ~6: cuatro veces menos consumo de cuota Melonn, que es el
# recurso escaso. Antes estaba en 25 buscando respuestas más rápidas, pero con
# la cuota agotada el número de peticiones pesa mucho más que la latencia de
# cada una. Si Melonn topa el per_page en otro valor, la paginación lo detecta
# sola y sigue funcionando — ver `tam_pagina` en _fetch_api.
_PAGE_SIZE   = 100
_MAX_PAGES   = 60         # 100 × 60 = 6000 pedidos, techo de seguridad
_CACHE_TTL   = 1800       # 30 min — caché Supabase
_CACHE_HARD_TTL = 86400   # 24h — pasado esto, fuerza refresh aunque haya datos

# Rate limiting — Melonn permite EXACTAMENTE 1 req/s (doc oficial Postman).
# Usamos 0.5 RPS (2s entre requests) para tener margen contra:
#   - Múltiples procesos (Railway puede levantar réplicas)
#   - Bursts durante sync_completo
#   - Latencia entre cliente y servidor
_MAX_RPS           = 0.5
_MIN_INTERVAL      = 1.0 / _MAX_RPS   # 2.0s entre requests
_MIN_REFRESH_SECS  = 60               # 1 min mínimo entre syncs
_RETRY_MAX         = 3
_RETRY_BACKOFF     = [3, 8, 20]       # antes 5,15,30 — más rápido para no congelar UI
_CACHE_TTL_NOVEDAD = 1800             # igual que TTL principal


# ── Cuota de la API agotada (distinto de un throttle pasajero) ─────────────────
# La API de Melonn corre sobre AWS API Gateway, que devuelve DOS 429 distintos:
#   {"message": "Too Many Requests"} -> throttle por rate/burst. Reintentar SIRVE.
#   {"message": "Limit Exceeded"}    -> cuota del usage plan agotada. Reintentar
#                                       NO sirve hasta que resetee la ventana o
#                                       Melonn amplíe el plan.
# Verificado 2026-07-28: UNA petición aislada, desde fuera de la app y sin nada
# más corriendo, ya devolvía 429 {"message":"Limit Exceeded"}. O sea que no era
# nuestro volumen. Antes tratábamos los dos igual, así que el botón "Autorizar"
# se comía ~86s de reintentos condenados y terminaba en un error que le echaba
# la culpa a la saturación.
_QUOTA_MSG           = "Limit Exceeded"
_QUOTA_COOLDOWN_SEC  = 300
_quota_agotada_hasta = 0.0

_ERROR_CUOTA = (
    "La cuota de la API de Melonn está agotada (no es saturación pasajera: "
    "reintentar no sirve). Hay que pedirle a Melonn que amplíe el plan, o "
    "esperar a que reinicie la cuota."
)


def _es_cuota_agotada(r) -> bool:
    """True si el 429 es por cuota del plan, no por ráfaga."""
    try:
        return (r.json() or {}).get("message") == _QUOTA_MSG
    except Exception:
        return False


def _marcar_cuota_agotada() -> None:
    global _quota_agotada_hasta
    _quota_agotada_hasta = time.time() + _QUOTA_COOLDOWN_SEC


def cuota_agotada() -> bool:
    """Para que la UI/health pueda decir por qué no hay datos frescos."""
    return time.time() < _quota_agotada_hasta


class _RateLimiter:
    """Token bucket simplificado — garantiza <= _MAX_RPS requests/s."""
    def __init__(self):
        self._lock      = threading.Lock()
        self._last_call = 0.0

    def wait(self):
        with self._lock:
            now   = time.monotonic()
            delta = now - self._last_call
            if delta < _MIN_INTERVAL:
                time.sleep(_MIN_INTERVAL - delta)
            self._last_call = time.monotonic()


_rate_limiter = _RateLimiter()

_DB_PATH        = Path(__file__).parent.parent / "data" / "db" / "maledenim.db"
_JSON_BOOTSTRAP = Path(__file__).parent.parent / "data" / "logistica" / "bootstrap.json"
_SB_TABLA       = "melonn_cache"    # tabla en Supabase
# Fila 1 = el caché de pedidos. Fila 2 = SOLO la hora del último fetch real al
# listado de Melonn. Son dos relojes distintos y confundirlos era el bug:
# `fetched_at` de la fila 1 se actualiza con CADA webhook (porque el webhook
# reescribe el caché completo), así que el caché nunca parecía viejo y el
# refresh programado se saltaba por el guard de _MIN_REFRESH_SECS. Resultado:
# el listado casi nunca se volvía a pedir y los estados quedaban congelados en
# lo último que dijo un webhook. Medido 2026-08-01: el tablero mostraba 74
# pedidos en código 29 y Melonn tenía 17; 56 en código 2 y Melonn tenía 0.
# Usar una fila aparte en vez de una columna nueva evita migración: si el
# esquema cambiara bajo nuestros pies, el módulo entero dejaría de leer caché.
_SB_FILA_API    = 2

# Campos que se enriquecen desde Shopify/detail y que NO deben re-consultarse
# ni borrarse: se heredan del caché entre syncs (traer-y-guardar) y se
# preservan cuando un webhook actualiza el estado del pedido.
_CAMPOS_ENRIQUECIDOS = (
    "tienda", "nombre_comprador", "telefono_comprador",
    "ciudad_destino", "region_destino", "email_comprador",
    "sku", "producto", "variante", "imagen_producto",
    "precio_unitario", "cantidad", "line_items",
    "fecha_despacho", "fecha_despacho_confiable", "fecha_promesa", "fecha_entrega",
    # Ventana prometida por Melonn + intentos de entrega. Vienen de
    # sell_order_attempt (?fields=sell_order_promises) y son caros de traer,
    # así que no se pueden perder en cada webhook.
    "promesa_entrega_min", "promesa_entrega_max", "intentos_entrega",
    "guia_real", "carrier_real", "link_guia", "external_order_id",
    # Marca de "ya le pedimos el detalle a Melonn". Tiene que sobrevivir a los
    # webhooks, si no volvemos al bucle infinito de re-consultas. Ver
    # _detalle_ya_intentado().
    "_detalle_melonn_intentado_en",
    # Despacho que VIMOS ocurrir (transición de estado). Es un dato que no se
    # puede volver a calcular: si se pierde, no hay forma de recuperarlo porque
    # la transición ya pasó. Ver _marcar_despacho_observado().
    "fecha_despacho_observada", "fecha_despacho_origen",
    # Fecha de entrega del portal + la marca de "ya pregunté". Sin la marca en
    # esta lista se re-consultaría el portal en CADA ciclo, para siempre.
    "fecha_entrega_origen", "_portal_entrega_intentado",
)

# Cada cuánto vale la pena volver a pedirle a Melonn el detalle de un pedido
# que ya consultamos y que no nos dio lo que buscábamos.
_REINTENTO_DETALLE_HORAS = 24

# Estados de los que ya no se espera novedad: se pregunta UNA vez y se archiva.
# Sin esto, incluir a los entregados en el enriquecedor costaría ~600 peticiones
# diarias para siempre.
_ESTADOS_TERMINALES = ("entregado", "resuelto", "cancelado", "devuelto")


def _limpiar_nombre_estado(nombre: str) -> str:
    """El DETALLE de Melonn devuelve el nombre del estado duplicado:
    "Ready For PackingReady For Packing". Si la cadena es exactamente su
    primera mitad repetida, la colapsa. Verificado contra la API 2026-07-29.
    """
    n = (nombre or "").strip()
    if n and len(n) % 2 == 0:
        mitad = len(n) // 2
        # Mínimo 3 caracteres por mitad: sin esto, un nombre legítimo de dos
        # letras como "aa" se colapsaría a "a". Los estados reales de Melonn
        # son largos ("Ready For Packing"), así que el piso no estorba.
        if mitad >= 3 and n[:mitad] == n[mitad:]:
            return n[:mitad]
    return n


def _estado_de(obj: dict) -> tuple:
    """(código, nombre) del estado, tolerando las DOS formas que usa Melonn.

    EL BUG QUE ESTO ARREGLA (verificado contra la API 2026-07-29): el LISTADO
    y el DETALLE devuelven el estado con nombres de campo distintos.

        LISTADO:  {"code": 28, "name": "Ready For Packing"}
        DETALLE:  {"id":   28, "name": "Ready For PackingReady For Packing"}

    Leíamos solo `code`. En el detalle no existe, así que daba 0 — y el camino
    del webhook usa el detalle. Resultado: cada refresco por webhook dejaba el
    pedido con código de estado 0 y lo sacaba de su clasificación real
    (pendiente / en tránsito / entregado). Encima el nombre venía duplicado.
    """
    st = obj.get("sell_order_state") or obj.get("state") or {}
    if not isinstance(st, dict):
        return 0, ""
    code = st.get("code")
    if code is None:
        code = st.get("id")      # el detalle lo llama `id`
    try:
        code = int(code or 0)
    except (TypeError, ValueError):
        code = 0
    return code, _limpiar_nombre_estado(str(st.get("name") or ""))


def _detalle_ya_intentado(p: dict) -> bool:
    """True si ya le pedimos el detalle de este pedido hace menos de 24h.

    EL BUG QUE ESTO ARREGLA (encontrado 2026-07-28): _enriquecer_desde_melonn
    seleccionaba todo pedido en tránsito sin `fecha_despacho_confiable`, y ese
    flag solo se marca si el detalle de Melonn trae `dispatch_date`. Melonn NO
    lo está devolviendo — 0 de 535 pedidos lo tenían. Resultado: los 130
    pedidos en tránsito se re-consultaban en CADA ciclo, para siempre, por una
    respuesta que nunca llegaba. Era el mayor consumidor de cuota de toda la
    integración y venía corriendo desde el 8 de julio.

    Ahora se pregunta una vez al día por pedido, no una vez por ciclo.
    """
    ts = p.get("_detalle_melonn_intentado_en")
    if not ts:
        return False
    # ESTADO TERMINAL = SE PREGUNTA UNA SOLA VEZ, NUNCA MÁS.
    # Un pedido entregado ya no va a cambiar: si Melonn no nos dio su
    # ship_timestamp cuando preguntamos, no lo va a dar mañana tampoco.
    # Reintentarlo a diario recrearía el "bucle de las 130" pero mucho peor
    # (~600 peticiones diarias eternas, ver el docstring de arriba).
    if (p.get("sub_estado_logistico") or "") in _ESTADOS_TERMINALES:
        return True
    try:
        transcurrido = (datetime.now() - _parse_iso_naive(str(ts))).total_seconds()
    except Exception:
        return False          # marca ilegible → dejar que se reintente
    return 0 <= transcurrido < _REINTENTO_DETALLE_HORAS * 3600


def _campo_vacio(v) -> bool:
    if v is None:
        return True
    if isinstance(v, str):
        return not v.strip()
    if isinstance(v, (int, float)):
        return v == 0
    if isinstance(v, (list, dict)):
        return len(v) == 0
    return False


def _clave_pedido(p: dict) -> str:
    """Clave estable de un pedido: prioriza orden_melonn, cae a orden_tienda."""
    om = (p.get("orden_melonn") or "").lstrip("Mm")
    if om:
        return f"M{om}"
    return f"T{p.get('orden_tienda') or ''}"


# ── Fecha de despacho PROPIA ─────────────────────────────────────────────────
# Melonn es una fuente pobre para esto: `ship_timestamp` solo llega si se pide el
# detalle, y de vez en cuando trae fechas imposibles. Medido el 2026-07-30: solo
# el 12% de los entregados tenía fecha, así que el "días en tránsito" de la
# mayoría salía del contador de Melonn y no de un cálculo auditable.
#
# La solución que NO depende de ellos: mirar el cambio de estado. Cuando un
# pedido pasa de "no despachado" a "despachado", ESE es el momento del despacho,
# y lo sabemos porque lo vimos pasar. Se anota una vez y no se vuelve a tocar.
#
# Límite honesto: solo sirve de aquí en adelante. Para lo ya despachado no hay
# transición que observar — eso depende del backfill de Melonn.
_NO_DESPACHADO = ("pendiente_despacho", "pendiente", "por_despachar")
_YA_DESPACHADO = ("en_transito", "novedad", "entregado", "resuelto", "devuelto")


def _marcar_despacho_observado(p: dict, prev: dict) -> bool:
    """Anota la fecha de despacho si ACABAMOS DE VER la transición.

    Devuelve True si se anotó. No pisa una fecha propia ya existente: el
    despacho pasa una sola vez, y si el pedido vuelve a "en tránsito" tras una
    novedad eso no es un despacho nuevo.
    """
    if p.get("fecha_despacho_observada"):
        return False
    antes = prev.get("sub_estado_logistico") or ""
    ahora = p.get("sub_estado_logistico") or ""
    if antes not in _NO_DESPACHADO or ahora not in _YA_DESPACHADO:
        return False
    from datetime import datetime as _dt
    try:
        from zoneinfo import ZoneInfo
        hoy = _dt.now(ZoneInfo("America/Bogota")).date().isoformat()
    except Exception:
        hoy = _dt.now().date().isoformat()
    p["fecha_despacho_observada"] = hoy
    # Si no había fecha fiable, esta manda: la vimos nosotros.
    if not p.get("fecha_despacho_confiable"):
        p["fecha_despacho"] = hoy
        p["fecha_despacho_confiable"] = True
        p["fecha_despacho_origen"] = "transicion_observada"
    return True


# ── Fecha de ENTREGA desde el portal de tracking ─────────────────────────────
# Estaba vacía en el 100% de los pedidos: 0 de 749 entregados la tenían, así que
# no se podía medir cuánto tardó NINGUNA entrega, y nada lo decía (lo destapó el
# reporte de auditoría). La Sellers API no la da en el listado y su detalle es
# caro; el portal público SÍ la trae en `detailedDeliveredDate`.
#
# POR QUÉ ACÁ Y NO EN tracking_enricher: hay que escribirla en el CACHÉ, no en
# pedido_overrides — esa tabla no tiene columna de fecha y añadirla exige una
# migración que solo Sebastián puede correr. `fecha_entrega` ya existe y ya está
# en las dos listas de herencia, así que llenarla acá no necesita nada nuevo.
#
# COSTO: otro host (api.melonn.com), NO gasta la cuota de 10.000/día de la
# Sellers API. Se pregunta UNA vez por pedido: un entregado no cambia.
_PORTAL_MAX_POR_CICLO = 80
_PORTAL_PAUSA_SEG = 0.5


def _enriquecer_fecha_entrega(pedidos: list, max_pedidos: int = _PORTAL_MAX_POR_CICLO) -> list:
    """Rellena fecha_entrega de los entregados preguntándole al portal."""
    try:
        import melonn_tracking as mt
    except Exception as e:
        log.warning(f"[entrega] no pude importar melonn_tracking: {e}")
        return pedidos

    candidatos = [
        i for i, p in enumerate(pedidos)
        if p.get("sub_estado_logistico") == "entregado"
        and not p.get("fecha_entrega")
        and p.get("orden_melonn")
        # Marca propia: si ya se preguntó y el portal no la dio, no se insiste.
        # Un entregado es terminal; volver a preguntar a diario es el "bucle de
        # las 130" otra vez.
        and not p.get("_portal_entrega_intentado")
    ]
    if not candidatos:
        return pedidos

    # Los más recientes primero: son los que alguien va a mirar.
    def _num(i: int) -> int:
        ot = str(pedidos[i].get("orden_tienda", "")).split("-")[0]
        return int(ot) if ot.isdigit() else 0
    candidatos.sort(key=_num, reverse=True)
    candidatos = candidatos[:max_pedidos]

    import time as _t
    llenados = 0
    for i in candidatos:
        p = pedidos[i]
        try:
            r = mt.consultar(p["orden_melonn"])
        except Exception:
            r = None
        _t.sleep(_PORTAL_PAUSA_SEG)
        # Se marca SIEMPRE que se preguntó, con dato o sin él.
        p["_portal_entrega_intentado"] = True
        if not r:
            continue
        entrega = (r.get("entregado_el") or "").strip()
        recogida = (r.get("recogido_el") or "").strip()
        if entrega:
            p["fecha_entrega"] = entrega
            p["fecha_entrega_origen"] = "portal_entregado"
            llenados += 1
        elif recogida:
            # Recogida en punto: cierra el pedido igual, pero se marca distinto
            # para no mezclar "entrega a domicilio" con "el cliente fue por él".
            p["fecha_entrega"] = recogida
            p["fecha_entrega_origen"] = "portal_recogido_por_cliente"
            llenados += 1
    if llenados:
        log.info(f"[entrega] {llenados} de {len(candidatos)} entregados "
                 f"recibieron fecha de entrega del portal")
    return pedidos


def _heredar_enriquecidos(frescos: list) -> list:
    """Copia los campos enriquecidos del caché anterior a los pedidos frescos
    de Melonn, para no re-consultar Shopify lo que ya trajimos. Solo rellena
    campos vacíos del pedido fresco — el estado/logística fresco manda.

    Acá también se detecta el DESPACHO: es el único punto del código donde
    conviven el estado anterior y el nuevo del mismo pedido.
    """
    try:
        hit = _cache_leer(ignorar_ttl=True)
    except Exception:
        hit = None
    if not hit:
        return frescos
    viejos = hit[0] or []
    idx = {_clave_pedido(p): p for p in viejos}
    heredados = 0
    despachos = 0
    for p in frescos:
        prev = idx.get(_clave_pedido(p))
        if not prev:
            continue
        # OJO EL ORDEN: la transición se evalúa ANTES de heredar, porque heredar
        # copiaría la fecha vieja y el estado anterior dejaría de ser visible.
        if _marcar_despacho_observado(p, prev):
            despachos += 1
        for c in _CAMPOS_ENRIQUECIDOS:
            if _campo_vacio(p.get(c)) and not _campo_vacio(prev.get(c)):
                p[c] = prev[c]
                if c == "nombre_comprador":
                    heredados += 1
    if heredados:
        log.info(f"[enrich] {heredados} pedidos heredaron datos del caché (sin re-consultar Shopify)")
    if despachos:
        log.info(f"[despacho] {despachos} pedido(s) pasaron a despachado en este ciclo "
                 f"— fecha anotada por observación propia")
    return frescos

# ── Clasificación de estados ───────────────────────────────────────────────────
#
# Fuente: documentación oficial API Melonn (31 estados definidos)
#
# Lógica de inclusión:
#   COD  → pendiente_despacho | en_transito | novedad | resuelto (estado 6)
#   Prepago → solo novedad
#
# Excluidos siempre: 8 (Delivered), 9 (Invalid), 15 (Canceled), 17/18/19 (Cancel process)
#

# ── Filtro por CÓDIGO numérico (más fiable que el nombre) ─────────────────────
#
# Nunca mostrar — terminales, cancelados, entregados, proceso interno Melonn
#
# Excluidos siempre (terminal / cancelado):
#   8  Delivered, 9  Invalid, 15 Canceled
#   16 Return pickup, 17/18/19 Cancelation process
#
# Excluidos porque son proceso INTERNO de Melonn — el seller no puede actuar:
#   1  Received-valid, 2  Reserved-ready, 3  Picking, 4  Picked, 5  Packed
#   10 Fixed-valid, 12 Processing, 22 Packing, 24 Prepared-dispatch
#   25 Selected-prep, 27 Pre-packing-VAS, 28 Ready-for-packing
#
# Excluidos siempre (terminales / cancelados / devolución)
# Nota: código 8 y 6 YA NO están aquí — ahora se muestran como "entregado" para COD
CODIGOS_EXCLUIR = {9, 15, 16, 17, 18, 19}

# Proceso interno puro — el seller no puede actuar, nunca se muestra
# (5=Packed, 24=Prepared for dispatch, 28=Ready for packing se INCLUYEN ahora
#  en el tab Tránsito para no perder visibilidad de órdenes activas)
CODIGOS_PROCESO_INTERNO = {3, 4, 10, 12, 22, 25, 27}

# ── Whitelist por código ───────────────────────────────────────────────────────
#   Pendiente seller → 26, 29      "Alistamiento en espera · Seller"
#   En preparación   → 1,2,5,24,28 "En bodega de Melonn, todavía NO salió"
#   En tránsito      → 7           "Con la transportadora, en la calle"
#   Entregado        → 6, 8        "Picked-up by buyer" / "Delivered to buyer"
#   Novedades ext.   → 20 + NOMBRE (código no confirmado en API docs)
#
# CORREGIDO 2026-07-31. `en_transito` incluía 5 (Packed), 24 (Prepared for
# dispatch) y 28 (Ready For Packing) — estados de BODEGA. Se metieron ahí a
# propósito "para no perder visibilidad", pero la etiqueta miente y arrastra
# consecuencias: esos pedidos empezaban a acumular días de SLA sin haber salido,
# y en la tabla se leían como si fueran en la calle. Medido: 60 de 176 "en
# tránsito" estaban en la bodega, y 36 de 38 "novedades" eran código 2
# (ready for fulfillment), que no es ninguna novedad.
#
# La partición correcta YA EXISTÍA en el frontend: /contraentrega y /envios
# agrupan por código crudo con proceso=[1,2,5,24,28] y transito=[7]. Esto pone
# el campo grueso de acuerdo con ellos, en vez de tener dos verdades.
CODIGOS_PENDIENTE_DESPACHO = {26, 29}
# 23 = "Packed - on hold": empacada y retenida en bodega. Estaba fuera de TODOS
# los conjuntos, así que caía en "otro" y el pedido DESAPARECÍA del tablero sin
# dejar rastro. Encontrado 2026-08-01 con el pedido #61358, contraentrega,
# invisible desde el 30 de julio.
CODIGOS_EN_PREPARACION     = {1, 2, 5, 23, 24, 28}
CODIGOS_EN_TRANSITO        = {7}
CODIGOS_ENTREGADO          = {6, 8}
CODIGOS_NOVEDAD            = {20}
CODIGOS_RESUELTO           = set()
CODIGOS_ACTIVOS            = (
    CODIGOS_PENDIENTE_DESPACHO
    | CODIGOS_EN_PREPARACION
    | CODIGOS_EN_TRANSITO
    | CODIGOS_ENTREGADO
    | CODIGOS_NOVEDAD
)
# Códigos OPERATIVOS — excluye entregados (6,8) del criterio de paginación.
# Las páginas con solo entregados no cuentan como "activas" y detienen el loop.
CODIGOS_ACTIVOS_OPERATIVO  = CODIGOS_ACTIVOS - CODIGOS_ENTREGADO

# ── Nombres de estado ─────────────────────────────────────────────────────────
# Excluidos por nombre (cancelados / devolución)
ESTADOS_EXCLUIR = {
    "Received - invalid fixable",                           # 9
    "Canceled",                                             # 15
    "Picked-up by courier for return",                      # 16
    "On Cancelation Process - to be unpacked & relocated",  # 17
    "On Cancelation Process - to be received from courier", # 18
    "In transit - Cancelation requested",                   # 19
    # Español
    "Cancelada",
    "Recogida por transportadora para devolución",
    "En proceso de cancelación",
    "En tránsito - cancelación solicitada",
}

# Novedades externas — código 20 y 29 (confirmados en producción)
# También se detectan por nombre como fallback para variantes futuras
ESTADOS_NOVEDAD_EXTERNA = {
    "Delivery not posible",   # 20 — transportadora no pudo entregar
}

# Entregados COD — códigos 6 y 8
ESTADOS_ENTREGADO = {
    "Picked-up by buyer",         "Recogida por el comprador",    # 6
    "Delivered to buyer",         "Entregada al comprador",       # 8
    "Entregada - pendiente de cobro",                             # 8 variante
}

# Pendiente despacho — códigos 26 y 29
# Ambos muestran "Alistamiento en espera" en la UI de Melonn
# 26 = hold del seller (requiere autorización)
# 29 = hold por condiciones externas (requiere gestión)
ESTADOS_PENDIENTE_DESPACHO = {
    "All items reserved - fulfillment on hold",                    # 26
    "Alistamiento en espera - Seller",                             # 26 español
    "All items reserved - fulfillment on hold - ext. conditionals",# 29
}

# En tránsito — códigos 5, 7, 24, 28
#   7  = con la transportadora (en ruta)
#   5  = Empacada · lista para salir
#   24 = Preparada para despacho
#   28 = Lista para empaque · en bodega
# SOLO el 7. Los nombres de bodega se movieron a ESTADOS_EN_PREPARACION: seguían
# acá y hacían que un pedido empacado se clasificara "en tránsito" POR NOMBRE
# aunque su código ya no estuviera en CODIGOS_EN_TRANSITO. Lo cazó la prueba de
# clasificación, no la lectura del código.
ESTADOS_EN_TRANSITO = {
    "Shipped - in transit", "Despachada - en tránsito", "En tránsito",  # 7
}

# En la bodega de Melonn: NO ha salido. Antes vivían repartidos entre
# ESTADOS_EN_TRANSITO (5, 24, 28) y ESTADOS_NOVEDAD_PREPAGO (1, 2).
ESTADOS_EN_PREPARACION = {
    "Received - valid", "Recibida - valida",                             # 1
    "All items reserved - ready for fulfillment",                        # 2
    "Recibida - valida - lista para alistamiento",                       # 2
    "Packed", "Empacada",                                                # 5
    "Packed - on hold", "Empacada - retenida",                           # 23
    "Prepared for dispatch", "Preparada para despacho",                  # 24
    "Ready For Packing", "Lista para empaque",                           # 28
}

# Proceso interno puro — nunca se muestra (alistado, picking, packing interno)
ESTADOS_PROCESO_INTERNO = {
    "Picking", "Picked", "Fixed & valid - to be processed",
    "Processing Requested", "Packing",
    "Selected for dispatch preparation", "Pre Packing - Vas Pending",
    "Alistando", "Alistada", "Empacando",
    "Seleccionada para preparación de despacho",
}

# Aliases para compatibilidad con caché antiguo
# Los códigos 1 y 2 YA NO son novedad (eran 36 de 38 "novedades" del tablero:
# pedidos esperando alistamiento, no incidencias). Ahora viven en preparación.
ESTADOS_NOVEDAD   = ESTADOS_NOVEDAD_EXTERNA
ESTADOS_RESUELTO  = set()
ESTADOS_RESUELTOS = ESTADOS_EXCLUIR
ESTADOS_ACTIVOS   = (
    ESTADOS_PENDIENTE_DESPACHO | ESTADOS_EN_PREPARACION | ESTADOS_EN_TRANSITO
    | ESTADOS_NOVEDAD | ESTADOS_ENTREGADO
)


def _config_hash() -> str:
    """
    Hash combinado de CODIGOS_ACTIVOS + lógica de clasificación.
    Cubre tanto qué códigos se traen como cómo se clasifican.
    Si cambia CUALQUIER conjunto → caché invalidado automáticamente.
    """
    key = (
        str(sorted(CODIGOS_ACTIVOS))
        + str(sorted(CODIGOS_PENDIENTE_DESPACHO))
        + str(sorted(CODIGOS_EN_TRANSITO))
        + str(sorted(CODIGOS_NOVEDAD))
        + str(sorted(CODIGOS_ENTREGADO))
    )
    return hashlib.md5(key.encode()).hexdigest()[:8]


# ── Credenciales ───────────────────────────────────────────────────────────────
def _api_key() -> Optional[str]:
    try:
        import streamlit as st
        return st.secrets.get("MELONN_API_KEY") or None
    except Exception:
        import os
        return os.getenv("MELONN_API_KEY")


def credenciales_ok() -> bool:
    return bool(_api_key())


# ── SQLite helper ─────────────────────────────────────────────────────────────
def _conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(_DB_PATH), timeout=10)
    c.row_factory = sqlite3.Row
    return c


# ── Supabase (caché primaria — persiste entre deployments) ────────────────────
#
# Formato del campo pedidos_json en Supabase (envelope v2):
#   { "v":2, "fuente":"api_live", "config_hash":"xxxxxxxx", "pedidos":[...] }
#
# El campo total se guarda aparte en la columna total.
# Si el JSON es una lista plana (v1 / formato antiguo) se descarta como inválido.

from functools import lru_cache as _lru_cache

@_lru_cache(maxsize=1)
def _sb():
    """Cliente Supabase singleton. None si las credenciales no están configuradas."""
    try:
        from supabase import create_client
        try:
            import streamlit as st
            u = st.secrets.get("SUPABASE_URL","") or __import__("os").getenv("SUPABASE_URL","")
            k = st.secrets.get("SUPABASE_KEY","") or __import__("os").getenv("SUPABASE_KEY","")
        except Exception:
            import os
            u = os.getenv("SUPABASE_URL","")
            k = os.getenv("SUPABASE_KEY","")
        if u and k:
            return create_client(u, k)
    except Exception:
        pass
    return None


def _sb_ok() -> bool:
    return _sb() is not None


def _parse_iso_naive(value) -> datetime:
    """Parsea un timestamp ISO tolerando CUALQUIER precisión de fracción de
    segundo y la zona horaria. Devuelve datetime naive (a nivel de segundo),
    suficiente para el TTL.

    Necesario porque Postgres (columna timestamptz) recorta los ceros finales
    de la fracción — p.ej. escribimos '...19.142540' y al leer vuelve
    '...19.14254+00:00' (5 dígitos). datetime.fromisoformat en Python < 3.11
    solo acepta 3 o 6 dígitos, así que reventaba y la caché se descartaba
    entera (logística salía vacía). Extraemos solo hasta el segundo con regex,
    que funciona en todas las versiones."""
    s = str(value or "")
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})", s)
    if m:
        y, mo, d, h, mi, sec = (int(x) for x in m.groups())
        return datetime(y, mo, d, h, mi, sec)
    # Último recurso: intento directo sin zona (puede lanzar, y el caller ya
    # atrapa la excepción).
    return datetime.fromisoformat(s.replace("Z", "").split("+")[0].split(".")[0])


def _sb_cache_leer(ignorar_ttl: bool = False) -> Optional[tuple]:
    """Lee caché desde Supabase. Retorna (pedidos, fetched_at, fresco, fuente) o None."""
    try:
        sb = _sb()
        if not sb:
            return None
        rows = sb.table(_SB_TABLA).select("fetched_at,pedidos_json,total").eq("id", 1).execute().data
        if not rows:
            return None
        row = rows[0]

        envelope = json.loads(row["pedidos_json"])
        if not isinstance(envelope, dict) or envelope.get("v") != 2:
            log.info("Supabase cache: formato v1 o inválido — descartando")
            return None

        # config_hash distinto = la clasificación cambió en un deploy. ANTES se
        # devolvía None acá, y eso dejaba el tablero EN CERO hasta que terminara
        # un fetch nuevo (visto en producción el 2026-08-01). Ahora cuenta como
        # "viejo", no como "ilegible": se sirve el dato y se refresca en segundo
        # plano. Es seguro porque _enriquecer_y_filtrar re-deriva el sub_estado,
        # la contraentrega y la whitelist en CADA lectura, así que la
        # clasificación nueva ya se aplica sobre los pedidos guardados.
        stored_hash = envelope.get("config_hash", "")
        hash_ok = stored_hash == _config_hash()
        if not hash_ok:
            log.info(f"Supabase cache: config_hash cambió "
                     f"({stored_hash} → {_config_hash()}) — sirvo y refresco")

        # fetched_at viene como string ISO desde Supabase (Postgres puede
        # recortar la fracción de segundo → parser tolerante).
        fetched_at = _parse_iso_naive(row["fetched_at"])
        # La frescura se mide contra Melonn, NO contra la última escritura del
        # caché: cada webhook reescribe la fila y adelantaba este reloj, así que
        # el caché se veía fresco para siempre y el listado no se volvía a pedir.
        fresco     = hash_ok and not _caduco_vs_melonn()
        if not fresco and not ignorar_ttl:
            return None

        pedidos = envelope.get("pedidos", [])
        fuente  = envelope.get("fuente","api_live")
        return pedidos, fetched_at, fresco, fuente
    except Exception as e:
        log.warning(f"Supabase cache leer error: {e}")
        return None


def _sb_cache_guardar(pedidos: list, fuente: str = "api_live"):
    """Guarda caché en Supabase (upsert single row id=1)."""
    try:
        sb = _sb()
        if not sb:
            return
        envelope = json.dumps({
            "v":           2,
            "fuente":      fuente,
            "config_hash": _config_hash(),
            "pedidos":     pedidos,
        }, default=str)
        sb.table(_SB_TABLA).upsert({
            "id":          1,
            "fetched_at":  datetime.utcnow().isoformat(),
            "pedidos_json": envelope,
            "total":       len(pedidos),
        }).execute()
        log.info(f"Supabase cache guardado: {len(pedidos)} pedidos, fuente={fuente}")
    except Exception as e:
        log.warning(f"Supabase cache guardar error: {e}")


def _sb_limpiar():
    try:
        sb = _sb()
        if sb:
            sb.table(_SB_TABLA).delete().in_("id", [1, _SB_FILA_API]).execute()
    except Exception as e:
        log.warning(f"Supabase limpiar error: {e}")


# ── El reloj del ÚLTIMO FETCH REAL al listado ─────────────────────────────────
#
# Distinto del `fetched_at` de la fila 1, que cambia con cada webhook. Ver el
# comentario de _SB_FILA_API. Se guarda en su propia fila para poder leerlo sin
# arrastrar el blob de pedidos (son ~1.200 pedidos en un solo JSON).

def _marcar_fetch_api() -> None:
    """Sella "acabamos de pedirle el listado completo a Melonn"."""
    ahora = datetime.utcnow().isoformat()
    try:
        sb = _sb()
        if sb:
            sb.table(_SB_TABLA).upsert({
                "id":           _SB_FILA_API,
                "fetched_at":   ahora,
                "pedidos_json": "{}",
                "total":        0,
            }).execute()
    except Exception as e:
        log.warning(f"No pude sellar la hora del fetch: {e}")
    try:
        # Tabla propia y no la fila 2 de melonn_pedidos_cache: esa tabla tiene
        # CHECK (id = 1) y el insert fallaría en silencio.
        with _conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS melonn_fetch_marca ("
                      "id INTEGER PRIMARY KEY CHECK (id = 1), fetched_at TEXT NOT NULL)")
            c.execute("INSERT OR REPLACE INTO melonn_fetch_marca (id, fetched_at) "
                      "VALUES (1, ?)", (ahora,))
            c.commit()
    except Exception as e:
        log.debug(f"SQLite marca fetch: {e}")


def _edad_fetch_api() -> Optional[float]:
    """Segundos desde el último fetch real al listado. None si nunca hubo uno.

    None se trata como "hay que refrescar": es el estado del primer arranque
    después de este cambio, y también el de un caché escrito solo por webhooks.
    """
    for leer in (_edad_fetch_api_sb, _edad_fetch_api_sq):
        try:
            v = leer()
            if v is not None:
                return v
        except Exception:
            continue
    return None


_memo_edad: dict = {"ts": 0.0, "valor": None}
_MEMO_EDAD_SEG = 5


def _edad_fetch_api_memo() -> Optional[float]:
    """_edad_fetch_api con memo corto: se consulta en cada lectura de caché y
    /pedidos se pide muchas veces por minuto. 5s no cambia ninguna decisión
    (el TTL es de 30 min) y ahorra una consulta por request."""
    ahora = time.time()
    if (ahora - _memo_edad["ts"]) < _MEMO_EDAD_SEG:
        base = _memo_edad["valor"]
        return None if base is None else base + (ahora - _memo_edad["ts"])
    v = _edad_fetch_api()
    _memo_edad["ts"], _memo_edad["valor"] = ahora, v
    return v


def _caduco_vs_melonn(ttl: int = _CACHE_TTL) -> bool:
    """True si hay que volver a pedirle el listado completo a Melonn.

    Mide contra el reloj del último fetch REAL, no contra el del caché: el caché
    lo reescribe cada webhook y por eso nunca parecía vencido. None (nunca hubo
    fetch, o solo hubo webhooks) cuenta como vencido.

    Una edad NEGATIVA también cuenta como vencido. Significa que los relojes no
    concuerdan (marca en UTC, comparación en hora local), y si se dejara pasar
    como "recién sincronizado" el listado no se volvería a pedir NUNCA — el mismo
    bug de los estados congelados, otra vez y en silencio. Ante un reloj que no se
    entiende, refrescar.
    """
    edad = _edad_fetch_api_memo()
    if edad is None:
        return True
    if edad < -60:
        log.error(f"Reloj del fetch inconsistente: edad {edad:.0f}s (negativa). "
                  f"Trato el caché como vencido para no congelar los estados.")
        return True
    return edad > ttl


def _edad_fetch_api_sb() -> Optional[float]:
    sb = _sb()
    if not sb:
        return None
    rows = (sb.table(_SB_TABLA).select("fetched_at")
              .eq("id", _SB_FILA_API).execute()).data
    if not rows:
        return None
    # utcnow y no now(): la marca se escribe con datetime.utcnow(). En Railway el
    # contenedor va en UTC y da igual, pero corriendo esto en un portátil en hora
    # de Bogotá la resta daba −272 minutos, o sea "sincronizado en el futuro" →
    # el caché se habría visto fresco para siempre.
    return (datetime.utcnow()
            - _parse_iso_naive(rows[0]["fetched_at"])).total_seconds()


def _edad_fetch_api_sq() -> Optional[float]:
    with _conn() as c:
        c.execute("CREATE TABLE IF NOT EXISTS melonn_fetch_marca ("
                  "id INTEGER PRIMARY KEY CHECK (id = 1), fetched_at TEXT NOT NULL)")
        row = c.execute("SELECT fetched_at FROM melonn_fetch_marca WHERE id=1").fetchone()
    if not row:
        return None
    # utcnow: _marcar_fetch_api escribe la misma marca UTC en los dos lados.
    return (datetime.utcnow() - _parse_iso_naive(row["fetched_at"])).total_seconds()


# ── SQLite (caché local / fallback) ───────────────────────────────────────────

def _init_tabla():
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS melonn_pedidos_cache (
                id           INTEGER PRIMARY KEY CHECK (id = 1),
                fetched_at   TEXT NOT NULL,
                pedidos_json TEXT NOT NULL,
                total        INTEGER NOT NULL DEFAULT 0,
                fuente       TEXT DEFAULT 'api_live',
                config_hash  TEXT DEFAULT ''
            )
        """)
        for col, default in [("fuente", "'api_live'"), ("config_hash", "''")]:
            try:
                c.execute(f"ALTER TABLE melonn_pedidos_cache ADD COLUMN {col} TEXT DEFAULT {default}")
            except Exception:
                pass
        c.commit()


def _sq_cache_leer(ignorar_ttl: bool = False) -> Optional[tuple]:
    """Lee caché desde SQLite local."""
    try:
        _init_tabla()
        with _conn() as c:
            row = c.execute(
                "SELECT fetched_at, pedidos_json, fuente, config_hash "
                "FROM melonn_pedidos_cache WHERE id=1"
            ).fetchone()
        if not row:
            return None
        # Igual que en Supabase: hash distinto = viejo, no ilegible. Ver allá.
        stored_hash = row["config_hash"] or ""
        hash_ok = stored_hash == _config_hash()
        if not hash_ok:
            log.info("SQLite cache: config_hash cambió — sirvo y refresco")
        fetched_at = _parse_iso_naive(row["fetched_at"])
        fresco = hash_ok and not _caduco_vs_melonn()   # ver _caduco_vs_melonn
        if not fresco and not ignorar_ttl:
            return None
        pedidos = json.loads(row["pedidos_json"])
        fuente  = row["fuente"] or "api_live"
        return pedidos, fetched_at, fresco, fuente
    except Exception as e:
        log.warning(f"SQLite cache leer error: {e}")
        return None


def _sq_cache_guardar(pedidos: list, fuente: str = "api_live"):
    try:
        _init_tabla()
        with _conn() as c:
            c.execute("""
                INSERT OR REPLACE INTO melonn_pedidos_cache
                    (id, fetched_at, pedidos_json, total, fuente, config_hash)
                VALUES (1, ?, ?, ?, ?, ?)
            """, (datetime.now().isoformat(), json.dumps(pedidos, default=str),
                  len(pedidos), fuente, _config_hash()))
            c.commit()
    except Exception as e:
        log.warning(f"SQLite cache guardar error: {e}")


# ── API pública de caché (Supabase → SQLite fallback) ─────────────────────────

def _cache_leer(ignorar_ttl: bool = False) -> Optional[tuple]:
    """Supabase primero, SQLite como fallback."""
    result = _sb_cache_leer(ignorar_ttl)
    if result is not None:
        return result
    return _sq_cache_leer(ignorar_ttl)


# Cuánto puede encogerse el caché de un guardado a otro sin que se considere un
# accidente. 0.40 = si el nuevo tiene menos del 40% del anterior, se bloquea.
# El caso real que esto habría atajado: 1.208 pedidos → 3 (0,2%), el 2026-08-01,
# cuando un webhook reescribió el caché entero con un solo pedido y el tablero de
# Envíos apareció en cero. Un encogimiento legítimo grande —arreglar la ventana
# de 90 días bajó 2.126 → 1.158, o sea 54%— pasa sin problema.
_CAIDA_MAXIMA = 0.40
_MINIMO_ABSOLUTO = 50        # por debajo de esto no hay tablero que valga


def _total_en_cache() -> int:
    """Cuántos pedidos tiene el caché HOY. Lee solo el contador, no el blob."""
    try:
        sb = _sb()
        if sb:
            rows = (sb.table(_SB_TABLA).select("total").eq("id", 1).execute()).data
            if rows:
                return int(rows[0].get("total") or 0)
    except Exception:
        pass
    return 0


def _cache_guardar(pedidos: list, fuente: str = "api_live", forzar: bool = False):
    """Escribe en Supabase Y en SQLite (redundancia).

    CON CANDADO: rechaza un guardado que borraría la mayor parte del tablero.
    Antes cualquier ruta podía dejar el caché en tres pedidos y nadie se enteraba
    hasta abrir la app. `forzar=True` es para los casos donde encoger es la
    intención (cargar un CSV, limpiar a mano).
    """
    nuevos = len(pedidos)
    if not forzar:
        antes = _total_en_cache()
        demasiado_chico = (
            antes >= _MINIMO_ABSOLUTO
            and (nuevos < _MINIMO_ABSOLUTO or nuevos < antes * _CAIDA_MAXIMA)
        )
        if demasiado_chico:
            log.error(
                f"GUARDADO BLOQUEADO: el caché pasaría de {antes} a {nuevos} "
                f"pedidos (fuente={fuente}). Eso no es un cambio de datos, es "
                f"una pérdida. Se conserva el caché anterior; revisar por qué "
                f"llegó una lista tan corta."
            )
            _CANDADO_CACHE.update({
                "ts": datetime.now().isoformat(timespec="seconds"),
                "antes": antes, "intento": nuevos, "fuente": fuente,
            })
            return
    _sb_cache_guardar(pedidos, fuente)
    _sq_cache_guardar(pedidos, fuente)


# Último guardado que el candado rechazó. Lo lee el chequeo de salud: un bloqueo
# significa que algo intentó vaciar el tablero y hay que mirar por qué.
_CANDADO_CACHE: dict = {"ts": None, "antes": 0, "intento": 0, "fuente": ""}


def ultimo_guardado_bloqueado() -> dict:
    return dict(_CANDADO_CACHE)


def stock_por_warehouse(warehouse_code: str = "MED-2") -> dict[str, int]:
    """
    Trae el stock REAL por SKU desde Melonn (GET /stock?warehouse_code=X).
    Pagina automáticamente (Melonn usa per_page con default 10).

    Retorna {sku: qty_available}. Cache en memoria limitado a 1 ejecución
    por proceso — el caller hace su propio caching.
    """
    out: dict[str, int] = {}
    page = 1
    per_page = 250
    max_paginas = 50  # 50 * 250 = 12500 SKUs, suficiente
    while page <= max_paginas:
        try:
            r = _get(f"stock?warehouse_code={warehouse_code}&page={page}&per_page={per_page}")
        except Exception as e:
            log.warning(f"stock_por_warehouse error page {page}: {e}")
            break
        if not r:
            break
        items = r.get("data", []) or []
        if not items:
            break
        for it in items:
            sku = (it.get("sku") or "").strip()
            if sku:
                out[sku] = int(it.get("qty_available") or 0)
        # Si la página vino con menos items que per_page, no hay más
        if len(items) < per_page:
            break
        page += 1
    return out


def refrescar_un_pedido(identificador: str) -> dict:
    """
    Refresca UN solo pedido en el caché desde Melonn detail endpoint.
    Usado por el webhook receiver — evita refrescar toda la lista cada
    vez que cambia un pedido.

    `identificador`: external_order_number (orden_tienda) o internal_order_number
                     (orden_melonn, con o sin "M").

    Retorna {ok, encontrado, accion, orden}.
    """
    if not identificador:
        return {"ok": False, "error": "Sin identificador"}

    # Normalizar candidatos: probar el ID tal cual, sin "M", y como string
    candidatos = []
    raw = str(identificador).strip()
    if raw:
        candidatos.append(raw)
    sin_m = raw.lstrip("Mm").strip()
    if sin_m and sin_m != raw:
        candidatos.append(sin_m)

    # Llamar detail endpoint con cada candidato hasta que uno funcione
    detail = None
    usado = ""
    for c in candidatos:
        try:
            d = _get(f"sell-orders/{c}")
            if d:
                detail = d
                usado = c
                break
        except Exception:
            continue

    if not detail:
        return {"ok": False, "error": f"Pedido no encontrado en Melonn: {identificador}", "candidatos": candidatos}

    # Normalizar el detail al schema interno del caché.
    # Reusamos la lógica del list normalizer si el detail tiene los campos.
    def _merge_webhook(viejo: dict, actualizado: dict) -> dict:
        """Fusiona una actualización de webhook sobre el pedido en caché sin
        borrar los campos enriquecidos desde Shopify (cliente/ciudad/producto/
        guía). Regla: el webhook solo pisa un campo enriquecido si trae valor;
        si viene vacío, se conserva el del caché."""
        ENRIQUECIDOS = {
            "tienda", "nombre_comprador", "telefono_comprador",
            "ciudad_destino", "region_destino", "email_comprador",
            "sku", "producto", "variante", "imagen_producto",
            "precio_unitario", "cantidad", "line_items",
            "fecha_despacho", "fecha_promesa", "fecha_entrega",
            # OJO: esta lista se había quedado atrás respecto a
            # _CAMPOS_ENRIQUECIDOS. Le faltaba `fecha_despacho_confiable`, así
            # que un webhook la borraba y el pedido volvía a calificar para
            # re-consulta — realimentando el bucle que arreglamos hoy. Y le
            # faltaban las promesas, que son caras de traer.
            "fecha_despacho_confiable",
            # El despacho observado NO se puede recalcular: la transición ya
            # pasó. Un webhook que lo borre lo pierde para siempre.
            "fecha_despacho_observada", "fecha_despacho_origen",
            "fecha_entrega_origen", "_portal_entrega_intentado",
            "promesa_entrega_min", "promesa_entrega_max", "intentos_entrega",
            "_detalle_melonn_intentado_en",
            "guia_real", "carrier_real", "link_guia", "external_order_id",
        }
        def _vacio(v):
            if v is None:
                return True
            if isinstance(v, str):
                return not v.strip()
            if isinstance(v, (int, float)):
                return v == 0
            if isinstance(v, (list, dict)):
                return len(v) == 0
            return False
        merged = dict(viejo)
        for k, v in actualizado.items():
            if k in ENRIQUECIDOS and _vacio(v):
                continue  # no borrar dato enriquecido con un vacío del webhook
            merged[k] = v
        # EL DESPACHO LLEGA POR ACÁ, NO POR EL SYNC (corregido 2026-07-31).
        # La detección se puso primero solo en _heredar_enriquecidos y en 14 h
        # no anotó NADA: el webhook de Melonn actualiza el caché en tiempo real,
        # así que cuando el sync horario corría, el estado "anterior" del caché
        # ya era el nuevo y la transición era invisible. Este es el único punto
        # donde el cambio se ve llegar. Se deja también en el sync como respaldo
        # por si los webhooks se caen (ya ha pasado).
        try:
            _marcar_despacho_observado(merged, viejo)
        except Exception as e:
            log.warning(f"[despacho] no pude evaluar la transición: {str(e)[:120]}")
        return merged

    try:
        nuevo = _normalizar(detail)
    except Exception:
        # Fallback: estructura mínima
        nuevo = {
            "orden_melonn":   f"M{detail.get('internal_order_number') or usado}",
            "orden_tienda":   detail.get("external_order_number") or usado,
            # Doblemente equivocado antes: leía `state` (el detalle usa
            # `sell_order_state`) y `code` (el detalle usa `id`).
            "estado_melonn":      _estado_de(detail)[1],
            "estado_melonn_code": _estado_de(detail)[0],
            "_raw": True,
        }

    # Mezclar con caché actual
    hit = _cache_leer(ignorar_ttl=True)
    if not hit:
        # NO escribir. Antes se guardaba [nuevo] "raro pero válido", y BORRABA el
        # tablero entero: cuando el caché queda ilegible —el caso típico es que
        # cambió `config_hash` en un deploy— el primer webhook que llegaba dejaba
        # el caché con UN pedido. Pasó en producción el 2026-08-01: 1.208 pedidos
        # → 3, y Sebastián vio Envíos en cero.
        # El pedido no se pierde: el refresh del listado lo vuelve a traer.
        log.warning("[webhook] caché ilegible o vacío — NO lo sobrescribo con un "
                    "solo pedido; lanzo el refresh del listado completo")
        try:
            _refresh_background()
        except Exception as e:
            log.warning(f"[webhook] no pude lanzar el refresh: {str(e)[:120]}")
        return {"ok": True, "accion": "sin_cache_refresh_lanzado",
                "orden": nuevo.get("orden_tienda")}

    pedidos, _ft, _ts, fuente = hit
    encontrado = False
    nuevo_om = (nuevo.get("orden_melonn") or "").lstrip("Mm")
    nuevo_ot = nuevo.get("orden_tienda") or ""
    for i, p in enumerate(pedidos):
        p_om = (p.get("orden_melonn") or "").lstrip("Mm")
        p_ot = p.get("orden_tienda") or ""
        if (nuevo_om and p_om == nuevo_om) or (nuevo_ot and p_ot == nuevo_ot):
            # MERGE (no reemplazo): el webhook trae estado/logística frescos
            # pero NO trae los campos enriquecidos desde Shopify (cliente,
            # ciudad, producto, guía…). Reemplazar el pedido completo borraba
            # esos datos → el pedido aparecía sin cliente/ciudad tras cada
            # cambio de estado. Preservamos lo enriquecido si el webhook viene
            # vacío en ese campo.
            pedidos[i] = _merge_webhook(p, nuevo)
            encontrado = True
            break

    accion = "actualizado"
    if not encontrado:
        pedidos.append(nuevo)
        accion = "creado"

    _cache_guardar(pedidos, fuente=fuente or "webhook")
    return {"ok": True, "encontrado": encontrado, "accion": accion, "orden": nuevo.get("orden_tienda")}


def limpiar_cache():
    """Limpia ambas cachés."""
    _sb_limpiar()
    try:
        _init_tabla()
        with _conn() as c:
            c.execute("DELETE FROM melonn_pedidos_cache WHERE id=1")
            c.commit()
    except Exception as e:
        log.warning(f"SQLite limpiar error: {e}")


def cache_info() -> Optional[dict]:
    """Info de la caché activa (Supabase si disponible, si no SQLite)."""
    # Intentar Supabase
    try:
        sb = _sb()
        if sb:
            rows = sb.table(_SB_TABLA).select("fetched_at,total,pedidos_json").eq("id",1).execute().data
            if rows:
                row        = rows[0]
                envelope   = json.loads(row["pedidos_json"])
                fuente     = envelope.get("fuente","api_live") if isinstance(envelope, dict) else "api_live"
                cfg_hash   = envelope.get("config_hash","") if isinstance(envelope, dict) else ""
                fetched_at = _parse_iso_naive(row["fetched_at"])
                age        = (datetime.now() - fetched_at).total_seconds()
                hash_ok    = cfg_hash == _config_hash()
                # Dos edades, a propósito:
                #   age_s     → hace cuánto se escribió el caché (lo mueve el webhook)
                #   api_age_s → hace cuánto le pedimos el listado a Melonn
                # `stale` mira la SEGUNDA: es la que dice si los estados pueden
                # estar viejos. Confundirlas era el bug.
                api_age    = _edad_fetch_api_memo()
                return {
                    "fetched_at":  fetched_at,
                    "age_s":       age,
                    "api_age_s":   api_age,
                    "total":       row["total"],
                    "fresco":      (not _caduco_vs_melonn()) and hash_ok,
                    "stale":       _caduco_vs_melonn() or not hash_ok,
                    "fuente":      fuente,
                    "config_hash": cfg_hash,
                    "hash_ok":     hash_ok,
                    "backend":     "supabase",
                }
    except Exception:
        pass
    # Fallback SQLite
    try:
        _init_tabla()
        with _conn() as c:
            row = c.execute(
                "SELECT fetched_at,total,fuente,config_hash FROM melonn_pedidos_cache WHERE id=1"
            ).fetchone()
        if not row:
            return None
        fetched_at = _parse_iso_naive(row["fetched_at"])
        age        = (datetime.now() - fetched_at).total_seconds()
        fuente     = row["fuente"] or "api_live"
        hash_ok    = (row["config_hash"] or "") == _config_hash()
        return {
            "fetched_at":  fetched_at,
            "age_s":       age,
            "api_age_s":   _edad_fetch_api_memo(),
            "total":       row["total"],
            "fresco":      (not _caduco_vs_melonn()) and hash_ok,
            "stale":       _caduco_vs_melonn() or not hash_ok,
            "fuente":      fuente,
            "config_hash": row["config_hash"],
            "hash_ok":     hash_ok,
            "backend":     "sqlite",
        }
    except Exception:
        return None


# ── Melonn API ─────────────────────────────────────────────────────────────────
def _get(path: str, params: dict = None) -> Optional[dict]:
    """
    GET con rate limiting y retry/backoff automático en 429/503.

    Aplica el token-bucket antes de cada intento.

    OJO CON EL LÍMITE REAL: la documentación de Melonn dice textualmente "All
    endpoints have a request limit of 1 request per second". El comentario que
    estaba acá decía 10 req/s — estaba mal, y era una trampa: alguien podía
    subir _MAX_RPS confiando en ese margen inexistente.

    _MAX_RPS = 0.5 (una petición cada 2s) queda por debajo del tope, pero el
    limitador es POR PROCESO y corren 4 workers de Uvicorn: en el peor caso, si
    los cuatro piden a la vez, el ritmo combinado llega a 2 req/s y Melonn
    responde 429. No se baja más porque penalizaría las acciones del usuario
    (autorizar despacho esperaría hasta 4s); en la práctica solo el worker líder
    hace tráfico sostenido, así que el ritmo real se mantiene bajo 1 req/s.

    Además hay DOS 429 distintos y no significan lo mismo — ver _es_cuota_agotada.
    """
    # Si ya sabemos que la cuota está agotada, no gastar ni la petición ni los
    # reintentos. OJO: este corto solo aplica a los GET (sincronización,
    # background). Los POST (acciones del usuario, como autorizar despacho) SÍ
    # intentan siempre — son una sola petición y así el usuario se entera en el
    # momento en que la cuota vuelva, sin esperar a que expire el cooldown.
    if cuota_agotada():
        log.info(f"Skip GET {path}: cuota Melonn agotada")
        return None

    url = f"{_BASE_URL}/{path.lstrip('/')}"
    # OJO: NO dormir acá. Cada `continue` de abajo ya durmió lo suyo (el
    # Retry-After de Melonn, o el backoff). Antes se dormía en los dos lados,
    # así que un solo GET con 429 costaba ~90s en vez de ~50s: 20 (Retry-After)
    # + 3 (backoff) + 20 + 8 + 20 + 20. Eso hacía que _fetch_api muriera entero
    # en un par de llamadas y el caché nunca se refrescara.
    for attempt in range(_RETRY_MAX + 1):
        _rate_limiter.wait()  # respeta el techo de _MAX_RPS req/s

        try:
            r = requests.get(
                url,
                headers={"x-api-key": _api_key(), "Accept": "application/json"},
                params=params,
                timeout=(_CONNECT_TO, _TIMEOUT),
            )

            if r.status_code in (429, 503):
                if _es_cuota_agotada(r):
                    # Reintentar es tiempo tirado. Cortar de una.
                    _marcar_cuota_agotada()
                    log.error(f"CUOTA Melonn agotada (Limit Exceeded) en {path} — sin reintentos")
                    return None
                if attempt >= _RETRY_MAX:
                    log.warning(f"HTTP {r.status_code} en {path} — reintentos agotados")
                    return None
                # Respeta Retry-After si la API lo devuelve
                retry_after = int(r.headers.get("Retry-After", _RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF)-1)]))
                log.warning(
                    f"HTTP {r.status_code} en {path} — esperando {retry_after}s "
                    f"(intento {attempt+1}/{_RETRY_MAX+1})"
                )
                time.sleep(retry_after)
                continue

            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict) and data.get("message") == "Limit Exceeded":
                log.warning("Limit Exceeded (respuesta JSON)")
                if attempt < _RETRY_MAX:
                    time.sleep(_RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF)-1)])
                    continue
                return None
            return data

        except requests.HTTPError as e:
            log.warning(f"HTTP {e.response.status_code} en {url}")
            return None
        except Exception as e:
            log.warning(f"Request error en {url}: {e}")
            return None

    return None


def _post(path: str, body: dict = None) -> tuple:
    """
    POST con rate limiting + retry agresivo en 429/503.

    Para acciones del usuario (autorizar despacho, etc.) ampliamos el
    presupuesto de reintentos: hasta ~60s con backoffs progresivos. Si
    Melonn está saturado un momento, el botón "Autorizar" igual triunfa.

    NO disparamos cooldown del scheduler por un solo POST 429 — eso era
    desproporcionado (pausaba 30 min de polling porque un click falló).
    Solo registramos el contador para detectar saturación SOSTENIDA.

    Retorna (ok: bool, data: dict | None, error_msg: str).
    """
    url = f"{_BASE_URL}/{path.lstrip('/')}"
    # Presupuesto ampliado: 5 intentos con backoff progresivo (~62s total).
    # Vale la pena esperar — la acción del usuario es crítica.
    post_backoff = [3, 8, 15, 25, 35]

    # Mismo bug que en _get: acá también se dormía arriba Y en la rama del 429,
    # así que el botón "Autorizar" podía quedarse >2 min girando antes de
    # rendirse. Ahora cada rama duerme una sola vez, explícitamente.
    for attempt in range(len(post_backoff) + 1):
        _rate_limiter.wait()
        try:
            r = requests.post(
                url,
                headers={
                    "x-api-key":     _api_key(),
                    "Accept":        "application/json",
                    "Content-Type":  "application/json",
                },
                json=body or {},
                timeout=_TIMEOUT,
            )
            if r.status_code in (200, 201, 204):
                data = r.json() if r.content else {}
                _registrar_429(False)
                return True, data, ""

            # Rate limit / temporal: reintentar
            if r.status_code in (429, 503):
                if _es_cuota_agotada(r):
                    # Cuota del plan agotada: los 5 reintentos que seguían eran
                    # ~86s de espera para un fracaso garantizado. Fallar ya, y
                    # decirle al usuario la verdad de por qué.
                    _marcar_cuota_agotada()
                    _registrar_429(True)
                    log.error(f"CUOTA Melonn agotada (Limit Exceeded) en POST {path} — sin reintentos")
                    return False, None, _ERROR_CUOTA
                retry_after_hdr = r.headers.get("Retry-After")
                if retry_after_hdr and retry_after_hdr.isdigit() and int(retry_after_hdr) <= 60:
                    wait = int(retry_after_hdr)
                else:
                    wait = post_backoff[min(attempt, len(post_backoff)-1)]
                log.warning(f"POST {url} → HTTP {r.status_code}: esperando {wait}s (intento {attempt+1}/{len(post_backoff)+1})")
                if attempt < len(post_backoff):
                    time.sleep(wait)
                    continue
                # Tras agotar TODOS los reintentos: registrar el 429 sostenido.
                # SOLO si vemos >5 fallos en 5 min, ahí sí pausamos scheduler
                # (no por una sola acción del usuario).
                _registrar_429(True)
                return False, None, (
                    "Melonn está saturado en este momento. "
                    "Espera ~2 minutos y vuelve a intentar — debería liberar pronto."
                )

            try:
                msg = r.json().get("message") or r.text[:200]
            except Exception:
                msg = r.text[:200]
            log.warning(f"POST {url} → HTTP {r.status_code}: {msg}")
            return False, None, f"HTTP {r.status_code}: {msg}"
        except Exception as e:
            log.warning(f"POST {url} error: {e}")
            if attempt < len(post_backoff):
                # Antes este `continue` no dormía: se apoyaba en el sleep del
                # tope del loop, que ya no está. Dormimos acá explícitamente.
                time.sleep(post_backoff[attempt])
                continue
            return False, None, str(e)


# Tracker de 429 sostenidos. Si vemos >5 en 5 min → ahí sí cooldown.
_recent_429: list[float] = []
_RECENT_429_WINDOW = 300  # 5 min
_RECENT_429_THRESHOLD = 5


def _registrar_429(fallido: bool):
    """Registra un POST resultado. Si vemos saturación sostenida, pausa scheduler."""
    global _recent_429
    now = time.time()
    _recent_429 = [t for t in _recent_429 if now - t < _RECENT_429_WINDOW]
    if fallido:
        _recent_429.append(now)
        if len(_recent_429) >= _RECENT_429_THRESHOLD:
            log.warning(f"{len(_recent_429)} POSTs fallidos en {_RECENT_429_WINDOW}s → pausando scheduler")
            try:
                from backend.core import scheduler as _sched
                _sched.trigger_cooldown(15 * 60)  # 15 min, no 30
            except Exception:
                pass
            _recent_429 = []  # reset

    return False, None, "POST agotó reintentos"


def release_hold_fulfillment(orden: str, shipping_method_code: str = None) -> tuple:
    """
    Libera el hold de fulfillment — autoriza despacho.

    IMPORTANTE: el endpoint Melonn requiere external_order_number
    (= orden_tienda), NO internal_order_number (M-id). Si recibimos
    M-id, hacemos un lookup en el detail para encontrar el external.

    POST /sell-orders/{external_order_number}/release-hold-fulfillment

    Retorna (ok: bool, mensaje: str).
    """
    if not orden:
        return False, "Número de orden no disponible"

    # Si nos pasaron un M-id, traducir a external_order_number
    if orden.startswith("M") and orden[1:].isdigit():
        log.info(f"release: traduciendo M-id {orden} a external_order_number...")
        detail = _get(f"sell-orders/{orden}")
        if not detail:
            # El detail con M-id falla — buscar en cache para obtener orden_tienda
            cache_hit = _cache_leer(ignorar_ttl=True)
            if cache_hit:
                pedidos, _, _, _ = cache_hit
                for p in pedidos:
                    if p.get("orden_melonn") == orden:
                        orden = p.get("orden_tienda") or orden
                        break
        else:
            ext = detail.get("external_order_number")
            if ext:
                orden = str(ext)

    body = {}
    if shipping_method_code:
        body["shipping_method_code"] = shipping_method_code

    ok, data, err = _post(
        f"sell-orders/{orden}/release-hold-fulfillment",
        body=body,
    )

    if ok:
        log.info(f"Despacho autorizado: {orden}")
        melonn_msg = (data or {}).get("message", "Order released successfully")
        return True, f"{melonn_msg} · Orden {orden}"
    return False, err or "Error desconocido al autorizar despacho"


def obtener_documentos_entrega(orden: str) -> Optional[dict]:
    """Trae la guía de envío + evidencia de entrega (POD) de una orden.

    GET /sell-orders/{external_order_number}/delivery-documents

    Devuelve un dict con URLs/base64 de:
      - shipping label (PDF/imagen de guía)
      - proof of delivery (firma, foto al cliente)
      - cualquier otro archivo de evidencia que Melonn tenga

    Si nos pasan un M-id, se traduce a external_order_number igual que
    en release_hold_fulfillment.
    """
    if not orden:
        return None

    if orden.startswith("M") and orden[1:].isdigit():
        detail = _get(f"sell-orders/{orden}")
        if detail:
            ext = detail.get("external_order_number")
            if ext:
                orden = str(ext)
        else:
            cache_hit = _cache_leer(ignorar_ttl=True)
            if cache_hit:
                pedidos, _, _, _ = cache_hit
                for p in pedidos:
                    if p.get("orden_melonn") == orden:
                        orden = p.get("orden_tienda") or orden
                        break

    return _get(f"sell-orders/{orden}/delivery-documents")


def _parsear_fecha(valor) -> Optional[date]:
    if not valor:
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    try:
        return datetime.strptime(str(valor)[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def _fecha_corte() -> date:
    """
    Ventana de datos: últimos 90 días.
    Cubre pedidos activos creados hace hasta 3 meses (prepago en tránsito largo,
    COD con novedad, etc.) sin procesar historial completo.
    """
    from datetime import timedelta
    return date.today() - timedelta(days=90)


_ESTADOS_DESCONOCIDOS: set[str] = set()


def _sub_estado_logistico(estado: str, codigo: int = 0, es_cod: bool = False) -> str:
    """
    Clasifica el estado Melonn en las categorías operativas del dashboard.
    Códigos confirmados en producción (corregido 2026-07-31):
      pendiente_despacho → 26, 29   esperando que el seller libere
      en_preparacion     → 1,2,5,24,28  en la bodega de Melonn, NO salió
      en_transito        → 7        con la transportadora, en la calle
      novedad            → 20 + novedades externas por nombre
      entregado          → 6, 8

    OJO: "en_transito" es SOLO el 7. Antes incluía 5/24/28 (estados de bodega) y
    el 1/2 caían en "novedad" para prepago, lo que llenaba el tablero de
    novedades que no eran novedades. Ver el bloque de CODIGOS_* arriba.
    """
    if codigo in CODIGOS_NOVEDAD or estado in ESTADOS_NOVEDAD_EXTERNA:
                                                  return "novedad"
    if codigo in CODIGOS_ENTREGADO or estado in ESTADOS_ENTREGADO:
                                                  return "entregado"
    if codigo in CODIGOS_EN_TRANSITO or estado in ESTADOS_EN_TRANSITO:
                                                  return "en_transito"
    if codigo in CODIGOS_EN_PREPARACION:          return "en_preparacion"
    if codigo in CODIGOS_PENDIENTE_DESPACHO or estado in ESTADOS_PENDIENTE_DESPACHO:
                                                  return "pendiente_despacho"
    # "otro" = el pedido se cae del tablero y NADIE se entera. Pasó con el código
    # 23 ("Packed - on hold"): un pedido contraentrega llevaba dos días invisible.
    # Un estado nuevo de Melonn vuelve a abrir el mismo hueco, así que acá queda
    # el aviso. `_ESTADOS_DESCONOCIDOS` evita repetir el log por cada pedido.
    #
    # Los excluidos A PROPÓSITO (cancelados, proceso interno) también caen en
    # "otro" y NO son un hallazgo: sin este filtro el log se llenaría con los
    # ~270 cancelados de cada sync y el aviso real se perdería entre ellos.
    excluido_a_proposito = (
        codigo in CODIGOS_EXCLUIR or codigo in CODIGOS_PROCESO_INTERNO
        or estado in ESTADOS_EXCLUIR or estado in ESTADOS_PROCESO_INTERNO
    )
    if (codigo or estado) and not excluido_a_proposito:
        clave = f"{codigo}|{estado}"
        if clave not in _ESTADOS_DESCONOCIDOS:
            _ESTADOS_DESCONOCIDOS.add(clave)
            log.warning(
                f"[estado desconocido] código {codigo} '{estado}' no está en "
                f"ningún conjunto — el pedido NO aparecerá en el tablero. "
                f"Clasificarlo en CODIGOS_* de melonn_client.py"
            )
    return "otro"


def _normalizar(raw: dict) -> dict:
    """
    Normaliza un pedido del endpoint GET /sell-orders (list).

    ⚠️  El endpoint de lista solo devuelve 12 campos por pedido:
        id, internal_order_number, external_order_number, external_order_id,
        melonn_tracking_link, payment_on_delivery_amount, payment_on_delivery_type,
        is_b2b, creation_date, shipping_method{code,name}, warehouse{code,name},
        sell_order_state{code,name}

    Los campos de cliente (buyer, shipping_info, line_items) y fechas de despacho
    (dispatch_date, promise_date, delivery_date) NO están en este endpoint.
    → Cliente y fechas de despacho se enriquecen desde Shopify en shopify_enricher.
    """
    # _normalizar se usa TANTO con items del listado como con el detalle
    # (refrescar_un_pedido). Cada uno nombra el campo distinto — ver _estado_de.
    estado_code, estado = _estado_de(raw)
    metodo    = str((raw.get("shipping_method") or {}).get("name") or "")
    valor_cod = raw.get("payment_on_delivery_amount")
    pay_type  = raw.get("payment_on_delivery_type") or {}
    es_b2b    = bool(raw.get("is_b2b"))

    # COD si tiene monto > 0  O  si payment_on_delivery_type tiene código activo
    _monto = float(str(valor_cod).replace(",", ".") or 0) if valor_cod else 0.0
    _tipo  = int(pay_type.get("code", 0)) if isinstance(pay_type, dict) else 0
    es_cod = _monto > 0 or _tipo > 0

    return {
        # ── Identificadores ──────────────────────────────────────────────────
        "orden_melonn":           str(raw.get("internal_order_number") or raw.get("id") or ""),
        "orden_tienda":           str(raw.get("external_order_number") or "").lstrip("#"),
        "external_order_id":      str(raw.get("external_order_id") or ""),
        # ── Estado ───────────────────────────────────────────────────────────
        "estado_melonn":          estado,
        "estado_melonn_code":     estado_code,
        "sub_estado_logistico":   _sub_estado_logistico(estado, estado_code, es_cod),
        # ── Canal / bodega ────────────────────────────────────────────────────
        "canal_venta":            "B2B" if es_b2b else "D2C",
        "es_b2b":                 es_b2b,
        "warehouse_code":         str((raw.get("warehouse") or {}).get("code") or ""),
        "warehouse_name":         str((raw.get("warehouse") or {}).get("name") or ""),
        # ── Cliente (vacío — se llena desde Shopify) ─────────────────────────
        "tienda":                 "",
        "nombre_comprador":       "",
        "telefono_comprador":     "",
        "ciudad_destino":         "",
        "region_destino":         "",
        # ── Logística ────────────────────────────────────────────────────────
        "transportadora":         metodo,
        "shipping_method_code":   str((raw.get("shipping_method") or {}).get("code") or ""),
        "link_guia":              str(raw.get("melonn_tracking_link") or ""),
        # ── Fechas (vacías — se llenan desde Shopify fulfillments) ───────────
        # dispatch_date / promise_date / delivery_date NO están en el list endpoint
        "fecha_creacion":         _parsear_fecha(raw.get("creation_date")),
        "fecha_despacho":         None,   # ← Shopify fulfillments[0].created_at
        "fecha_promesa":          None,   # ← calculado: fecha_despacho + SLA zona
        "fecha_entrega":          None,   # ← solo en pedidos entregados (excluidos)
        # ── Producto (vacío — se llena desde Shopify) ────────────────────────
        "sku":                    "",
        "producto":               "",
        "variante":               "",
        "cantidad":               1,
        "precio_unitario":        0.0,
        # ── COD ──────────────────────────────────────────────────────────────
        "valor_cod_raw":          str(valor_cod or 0),
        "payment_on_delivery_type": str(raw.get("payment_on_delivery_type") or ""),
        "tipo_recaudo":           "Contraentrega" if es_cod else "Prepago",
        "es_contraentrega":       es_cod,
        # ── Flags de estado ───────────────────────────────────────────────────
        "dias_en_transito":       0,   # calculado dinámicamente en shared._dias_reales()
        "esta_en_transito":       estado in ESTADOS_EN_TRANSITO,
        "entregado":              estado in ESTADOS_EXCLUIR,
        "incidencia":             "NINGUNO",
        "promesa_vencida":        False,
    }


def _fetch_api() -> list:
    """
    Trae todos los pedidos D2C activos paginando inteligentemente.

    Estrategia de parada:
      - Si una página completa (50 ítems) no contiene ninguna orden activa
        → detenemos: lo que sigue son solo históricos terminales.
      - Si la página viene incompleta (<50) → es la última página.
      - Límite de seguridad: _MAX_PAGES páginas.
    """
    return _fetch_api_filtrado()


def _fetch_api_raw(max_pages: int = _MAX_PAGES) -> list:
    """TODO lo que devuelve el listado de Melonn, sin filtrar y SIN el corte
    anticipado de paginación. Es la verdad contra la cual comparar el tablero.

    Existe para poder responder "¿por qué no aparece el pedido X?": el fetch
    normal descarta por seis reglas distintas y además puede detenerse antes de
    la última página si encuentra una completa sin pedidos operativos. Si esa
    heurística se equivoca, pierde pedidos sin dejar rastro — acá se ve.

    Solo para diagnóstico: pagina hasta el final, así que gasta más cuota.
    """
    out: list = []
    page = 0
    tam = None
    while page < max_pages:
        resp = _get("sell-orders", params={"per_page": _PAGE_SIZE, "page": page})
        if resp is None:
            break
        items = resp.get("data") or []
        if not items:
            break
        if tam is None:
            tam = len(items)
        out.extend(items)
        if len(items) < tam:
            break
        page += 1
    log.info(f"[diagnostico] listado crudo: {len(out)} pedidos en {page + 1} página(s)")
    return out


# Radiografía del último fetch al listado. La lee el chequeo de salud para poder
# responder "¿el tablero está completo?" sin adivinar. Es de proceso, no
# compartida entre workers: el chequeo la complementa con el reloj de Supabase.
_ULTIMO_FETCH: dict = {
    "ts": None, "paginas": 0, "pedidos_en_ventana": 0,
    "motivo_fin": "nunca_corrio", "completo": False,
}


def ultimo_fetch() -> dict:
    """Cómo terminó el último fetch del listado, para el chequeo de salud."""
    return dict(_ULTIMO_FETCH)


def _fetch_api_filtrado() -> list:
    corte       = _fecha_corte()
    pedidos_raw = []
    page        = 0
    # Tamaño de página EFECTIVO, aprendido de la primera respuesta.
    #
    # OJO — por qué no se compara contra _PAGE_SIZE: si Melonn topa el per_page
    # que pedimos (le pedimos 100 y devuelve 50), `len(items) < _PAGE_SIZE`
    # daría verdadero en la PRIMERA página y cortaríamos ahí, creyendo que ya
    # no hay más. Perderíamos cientos de pedidos en silencio, sin ningún error.
    # Aprendiendo el tope real de la primera página, subir _PAGE_SIZE es seguro
    # incluso si la API lo limita a otro valor.
    tam_pagina = None
    # Se inicializa acá y no dentro del while: si la primera página falla (cuota
    # agotada), el loop no corre y el log de abajo la leería sin existir.
    activos_en_pagina = 0

    motivo_fin = "tope_paginas"

    while page < _MAX_PAGES:
        resp = _get("sell-orders", params={"per_page": _PAGE_SIZE, "page": page})
        if resp is None:
            # Un GET fallido (cuota agotada, 5xx, timeout) cortaba la paginación
            # SIN DEJAR RASTRO, y lo que se había alcanzado a traer se guardaba
            # como si fuera el listado completo. Así fue como el 2026-08-01 medí
            # 1.310 pedidos "crudos" y creí que Melonn no tenía más: la lista
            # estaba cortada a la mitad y yo comparé el tablero contra ella.
            motivo_fin = f"fallo_get_pagina_{page}"
            break
        items = resp.get("data") or []
        if not items:
            motivo_fin = "sin_mas_datos"
            break
        if tam_pagina is None:
            tam_pagina = len(items)
            if tam_pagina < _PAGE_SIZE:
                log.info(
                    f"Melonn topó per_page: pedimos {_PAGE_SIZE}, devuelve {tam_pagina}"
                )

        activos_en_pagina = 0
        for item in items:
            fc       = _parsear_fecha(item.get("creation_date"))
            estado_c = int((item.get("sell_order_state") or {}).get("code") or 0)
            estado_n = str((item.get("sell_order_state") or {}).get("name") or "")
            # ¿Sigue ABIERTO? (pendiente, en preparación, en tránsito, novedad)
            # Entregado NO cuenta: un pedido entregado está cerrado.
            sigue_abierto = (estado_c in CODIGOS_ACTIVOS_OPERATIVO
                             or estado_n in ESTADOS_NOVEDAD_EXTERNA)

            # La ventana de 90 días solo se salta para los que siguen abiertos.
            # ANTES la excepción era `es_activo`, que INCLUYE entregado (6 y 8),
            # así que la ventana no cortaba ni un entregado por viejo que fuera.
            # Con el corte anticipado de paginación eso no se notaba —la
            # paginación moría antes de llegar al historial—; al quitarlo, el
            # tablero se llenó con TODA la historia de entregas: 1.709 entregados
            # y 2.126 pedidos en total, contra ~1.150 que debía tener.
            if fc and fc < corte and not sigue_abierto:
                continue

            pedidos_raw.append(item)
            if sigue_abierto:
                activos_en_pagina += 1

        # SE QUITÓ EL CORTE ANTICIPADO (2026-08-01). Antes se cortaba acá en
        # cuanto una página completa no traía ningún pedido operativo, asumiendo
        # que lo que seguía era solo historial. La apuesta depende de que Melonn
        # devuelva el listado del más nuevo al más viejo, y eso no está
        # documentado ni garantizado: si algún día ordena al revés, o si se
        # acumulan 100 entregados seguidos, el corte se come los pedidos nuevos
        # y no queda ni un error en los logs. Hoy son 14 páginas — 28s cada
        # media hora, ~670 peticiones al día sobre una cuota de 10.000. Pagar
        # eso es más barato que perder un pedido en silencio.
        if len(items) < tam_pagina:
            motivo_fin = "ultima_pagina"
            break
        page += 1

    # ── ¿El listado quedó COMPLETO? ──────────────────────────────────────────
    # Solo dos finales son buenos: la última página vino incompleta, o Melonn
    # devolvió una página vacía. Cualquier otro final significa que faltan
    # pedidos, y un listado incompleto NO puede reemplazar el caché: pisaría
    # datos buenos con datos parciales, que es justo lo que no se puede notar
    # a simple vista.
    completo = motivo_fin in ("ultima_pagina", "sin_mas_datos")
    _ULTIMO_FETCH.update({
        "ts": datetime.now().isoformat(timespec="seconds"),
        "paginas": page + 1,
        "pedidos_en_ventana": len(pedidos_raw),
        "motivo_fin": motivo_fin,
        "completo": completo,
    })
    log.info(f"Melonn API: {len(pedidos_raw)} pedidos en ventana "
             f"({page + 1} página(s), fin={motivo_fin})")

    if not completo:
        # Devolver vacío es lo correcto: obtener_pedidos_activos conserva el
        # caché anterior cuando el fetch viene vacío. Mejor datos de hace un rato
        # que un tablero al que le faltan pedidos sin avisar.
        log.error(f"FETCH INCOMPLETO ({motivo_fin}) — se descartan los "
                  f"{len(pedidos_raw)} pedidos traídos y se conserva el caché "
                  f"anterior. El tablero queda viejo, pero no mutilado.")
        return []

    # Sellar el reloj del listado SOLO si de verdad trajimos algo. Si la cuota
    # está agotada, _get devuelve None, pedidos_raw queda vacío y NO se sella:
    # así el próximo tick vuelve a intentar en vez de esperar otros 30 minutos.
    if pedidos_raw:
        _marcar_fetch_api()

    resultado = []
    for item in pedidos_raw:
        estado_obj  = item.get("sell_order_state") or {}
        estado_nombre = str(estado_obj.get("name") or "")
        estado_codigo = int(estado_obj.get("code") or 0)

        # ── Whitelist: código en CODIGOS_ACTIVOS O nombre en ESTADOS_NOVEDAD_EXTERNA
        #    Las novedades externas no tienen código documentado → se detectan por nombre
        if (estado_codigo not in CODIGOS_ACTIVOS
                and estado_nombre not in ESTADOS_NOVEDAD_EXTERNA):
            log.debug(f"Excluido código {estado_codigo} ({estado_nombre})")
            continue

        # Doble check por nombre — cancelados y proceso interno
        if estado_nombre in ESTADOS_EXCLUIR or estado_nombre in ESTADOS_PROCESO_INTERNO:
            log.debug(f"Excluido por nombre: {estado_nombre}")
            continue

        try:
            p = _normalizar(item)
        except Exception:
            continue

        # Excluir pedidos B2B — este dashboard es solo para D2C
        if p.get("es_b2b"):
            log.debug(f"Excluido B2B: {p.get('orden_tienda')}")
            continue

        sub = p["sub_estado_logistico"]

        # Incluir todas las órdenes activas D2C
        # OJO: si falta un estado acá, esos pedidos DESAPARECEN del tablero.
        # Al separar "en_preparacion" de "en_transito" habrían quedado fuera 96.
        if sub in ("pendiente_despacho", "en_preparacion", "en_transito",
                   "novedad", "entregado"):
            resultado.append(p)

    # Traer-y-guardar: heredar del caché anterior los campos ya enriquecidos
    # (cliente, ciudad, producto, guía) para NO volver a consultarlos en
    # Shopify. El enricher salta los pedidos que ya tienen nombre_comprador,
    # así que solo consulta los NUEVOS o los que aún no se enriquecieron.
    resultado = _heredar_enriquecidos(resultado)

    # Fecha de ENTREGA desde el portal (gratis, otro host). Va DESPUÉS de heredar
    # para no re-preguntar por lo que ya trae fecha del ciclo anterior.
    try:
        resultado = _enriquecer_fecha_entrega(resultado)
    except Exception as e:
        log.warning(f"[entrega] enriquecimiento falló (sigue el sync): {e}")

    # Enriquecer con datos de cliente y fechas desde Shopify (solo faltantes)
    if _SHOPIFY_ENRICHER_OK and resultado:
        try:
            resultado = _enricher.enriquecer(resultado)
        except Exception as e:
            log.warning(f"Shopify enricher error: {e}")

    return resultado


def _lazy_enrich(pedidos: list, max_pedidos: int = 30) -> list:
    """
    Enriquece con Shopify los pedidos en caché sin datos de cliente.

    Estrategia rápida (default):
      - Solo procesa máximo `max_pedidos` por llamada (no bloquea la UI)
      - Prioriza pedidos más recientes (mayor orden_tienda numérica)
      - Los faltantes se completan en llamadas siguientes o vía sync_completo()

    Para enriquecimiento exhaustivo, usar sync_completo().
    """
    if not _SHOPIFY_ENRICHER_OK:
        return pedidos

    # Identificar pedidos que necesitan enriquecimiento
    indices_pendientes = [
        i for i, p in enumerate(pedidos)
        if not p.get("nombre_comprador") and (
            p.get("external_order_id")
            or str(p.get("orden_tienda", "")).split("-")[0].isdigit()
        )
    ]
    if not indices_pendientes:
        return pedidos

    # Limitar batch — prioriza por orden_tienda descendente (más recientes primero)
    def _key(i: int) -> int:
        ot = str(pedidos[i].get("orden_tienda", "")).split("-")[0]
        return int(ot) if ot.isdigit() else 0

    indices_pendientes.sort(key=_key, reverse=True)
    indices_a_procesar = indices_pendientes[:max_pedidos]

    log.info(
        f"Lazy enrich: {len(indices_a_procesar)}/{len(indices_pendientes)} "
        f"pedidos procesados (límite {max_pedidos})"
    )

    # Construir sublista a enriquecer, manteniendo refs
    sublista = [pedidos[i] for i in indices_a_procesar]
    try:
        enriquecidos = _enricher.enriquecer(sublista)
    except Exception as e:
        log.warning(f"Lazy Shopify enricher error: {e}")
        enriquecidos = sublista

    # Merge de vuelta al array original por índice
    resultado = list(pedidos)
    for idx, p_enr in zip(indices_a_procesar, enriquecidos):
        resultado[idx] = p_enr

    # Segundo paso: pedidos manuales sin external_order_id → Melonn detail endpoint
    # Aumentado a 60 para reducir backlog de pedidos sin datos
    resultado = _enriquecer_desde_melonn(resultado, max_pedidos=max(60, max_pedidos))

    return resultado


def _verificar_estados_stale(pedidos: list, max_check: int = 50) -> list:
    """
    Para pedidos que llevan mucho tiempo en tránsito, llama al detail
    endpoint de Melonn para verificar si el estado real cambió.

    Útil cuando el LIST endpoint reporta estado viejo (Shipped - in transit)
    pero el pedido ya está entregado/cobrado según el DETAIL endpoint.

    Solo verifica pedidos que cumplen TODOS:
    - sub_estado_logistico == "en_transito"
    - dias_en_transito > 5 (umbral conservador)
    - tienen orden_tienda (necesario para el detail endpoint)

    Actualiza estado_melonn / estado_melonn_code / sub_estado_logistico
    si el detail responde un estado diferente.
    """
    candidatos = []
    for i, p in enumerate(pedidos):
        if p.get("sub_estado_logistico") != "en_transito":
            continue
        if int(p.get("dias_en_transito") or 0) < 5:
            continue
        if not p.get("orden_tienda"):
            continue
        candidatos.append(i)

    if not candidatos:
        return pedidos

    # Priorizar pedidos más antiguos (mayor riesgo de stale)
    candidatos.sort(key=lambda i: int(pedidos[i].get("dias_en_transito") or 0), reverse=True)
    candidatos = candidatos[:max_check]

    log.info(f"Verificación estados stale: {len(candidatos)} pedidos a re-chequear")
    resultado = list(pedidos)
    actualizados = 0

    for idx in candidatos:
        p = pedidos[idx]
        ext = p.get("orden_tienda")
        try:
            detail = _get(f"sell-orders/{ext}")
        except Exception:
            continue
        if not detail:
            continue

        new_state = detail.get("sell_order_state") or {}
        new_code  = int(new_state.get("id") or 0)
        new_name  = str(new_state.get("name") or "")

        if new_code and new_code != int(p.get("estado_melonn_code") or 0):
            es_cod = p.get("es_contraentrega", False)
            new_sub = _sub_estado_logistico(new_name, new_code, es_cod)
            p_new = dict(p)
            p_new["estado_melonn"]        = new_name
            p_new["estado_melonn_code"]   = new_code
            p_new["sub_estado_logistico"] = new_sub
            p_new["esta_en_transito"]     = new_name in ESTADOS_EN_TRANSITO
            p_new["entregado"]            = new_name in ESTADOS_ENTREGADO

            # Actualizar fecha_entrega si vino en detail
            del_date = detail.get("delivery_date")
            if del_date and not p_new.get("fecha_entrega"):
                p_new["fecha_entrega"] = str(del_date).split("T")[0]

            resultado[idx] = p_new
            actualizados += 1

    if actualizados:
        log.info(f"Verificación estados stale: {actualizados} pedidos actualizados")
    return resultado


def _enriquecer_desde_melonn(pedidos: list, max_pedidos: int = 30) -> list:
    """
    Para pedidos cargados MANUALMENTE en Melonn (sin external_order_id y sin
    datos de cliente), llama GET /sell-orders/{id} para obtener el detalle
    completo (buyer, shipping_info, line_items).

    Limita batch a `max_pedidos` por llamada para no bloquear la UI.
    """
    # Identificar pedidos manuales sin datos.
    # IMPORTANTE: el endpoint GET /sell-orders/{X} usa el external_order_number
    # (= orden_tienda en nuestro modelo), no el internal_order_number.
    indices = []
    for i, p in enumerate(pedidos):
        if not p.get("orden_tienda"):
            continue
        # (a) pedidos manuales sin datos de cliente
        falta_cliente = not p.get("nombre_comprador")
        # (b) pedidos YA DESPACHADOS sin fecha de despacho fiable.
        #     La de Shopify es la fecha del registro del fulfillment, no la del
        #     despacho real, e inflaba los días en tránsito disparando RIESGO
        #     falso. La única fuente buena es `ship_timestamp` del detalle.
        #
        #     ANTES ESTO ERA SOLO `== "en_transito"`, y ahí estaba el hueco de
        #     fondo (medido 2026-07-30): a los ENTREGADOS nunca se les preguntaba,
        #     así que solo tenían fecha los que alcanzaron a consultarse mientras
        #     iban en tránsito — 90 de 727 (12%), contra 101 de 148 (68%) en
        #     tránsito. Sin fecha de despacho no se puede medir cuánto tardó una
        #     entrega, que es justo el SLA que interesa.
        #
        #     Cuota: son ~750 pedidos de atraso, a 60 por ciclo horario se
        #     drenan en medio día; el tope diario de Melonn es 10.000 y hoy se
        #     usan ~500. Y NO se repite: los terminales se preguntan una sola vez
        #     (ver _ESTADOS_TERMINALES en _detalle_ya_intentado).
        falta_despacho = (
            p.get("sub_estado_logistico") in ("en_transito", "entregado", "novedad")
            and not p.get("fecha_despacho_confiable"))
        if not (falta_cliente or falta_despacho):
            continue
        # No volver a preguntar por algo que ya preguntamos hoy. Sin esto, los
        # pedidos en tránsito se consultaban en cada ciclo indefinidamente.
        if _detalle_ya_intentado(p):
            continue
        indices.append(i)

    if not indices:
        return pedidos

    # PRIMERO LOS VIVOS. Con el atraso de entregados (~750) los pedidos EN
    # TRÁNSITO quedarían al final de la cola, y son justo los que se están
    # vigilando en vivo: su SLA importa hoy, el del entregado es historia.
    # Dentro de cada grupo, los más recientes primero.
    _PRIORIDAD = {"en_transito": 0, "novedad": 1}

    def _key(i: int):
        p = pedidos[i]
        ot = str(p.get("orden_tienda", "")).split("-")[0]
        num = int(ot) if ot.isdigit() else 0
        prio = _PRIORIDAD.get(p.get("sub_estado_logistico") or "", 2)
        # num negativo = descendente, sin invertir todo el criterio
        return (prio, -num)

    indices.sort(key=_key)
    indices = indices[:max_pedidos]

    log.info(f"Melonn detail enricher: consultando {len(indices)} pedidos manuales")

    resultado = list(pedidos)
    completados = 0

    for idx in indices:
        p = pedidos[idx]
        # Probar primero external_order_number; si falla, probar internal
        # (orden_melonn sin "M") — útil para órdenes manuales con códigos
        # cortos como "0031" que el external no resuelve.
        ext = p.get("orden_tienda")
        internal = str(p.get("orden_melonn") or "").lstrip("Mm").strip()

        detail = None
        for candidato in [ext, internal]:
            if not candidato:
                continue
            try:
                # ?fields=sell_order_promises trae el bloque sell_order_attempt
                # con las fechas REALES (ship_timestamp, delivery_timestamp) y
                # las ventanas prometidas. SIN este parámetro esos campos NO
                # vienen — y eso era la causa del bucle infinito: buscábamos
                # `dispatch_date`, que no existe en ninguna respuesta.
                detail = _get(f"sell-orders/{candidato}",
                              params={"fields": "sell_order_promises"})
                if detail:
                    break
            except Exception as e:
                log.debug(f"detail {candidato}: {e}")
                continue

        # Registrar el intento ANTES de mirar el resultado. Si el detalle no
        # llega, o llega sin `dispatch_date`, igual no queremos volver a
        # preguntar hasta mañana: marcar solo el caso exitoso dejaría el bucle
        # infinito vivo justo para los pedidos que Melonn no resuelve, que son
        # precisamente los que lo causaban.
        p = dict(p)
        p["_detalle_melonn_intentado_en"] = datetime.now().isoformat()
        resultado[idx] = p

        if not detail:
            log.warning(f"Sin detalle Melonn para {ext} / {internal}")
            continue

        # Schema real Melonn API:
        #   buyer.full_name, buyer.phone_number, buyer.email
        #   shipping_info.full_name, phone_number, city, region,
        #                 address_l1, address_l2, postal_code
        #   warehouse.city, warehouse.region (origen, no destino)
        buyer = detail.get("buyer") or {}
        ship  = detail.get("shipping_info") or {}

        # Prioridad: nombre del comprador (buyer) > recipient (shipping)
        nombre = (
            (buyer.get("full_name") or "").strip()
            or (ship.get("full_name") or "").strip()
        )

        telefono = (
            (buyer.get("phone_number") or "").strip()
            or (ship.get("phone_number") or "").strip()
        )

        ciudad = ((ship.get("city") or "").strip().upper())
        region = (ship.get("region") or "")

        email = (buyer.get("email") or "").strip()
        direccion = " ".join(filter(None, [
            (ship.get("address_l1") or "").strip(),
            (ship.get("address_l2") or "").strip(),
        ]))

        # Productos si vienen
        items = detail.get("line_items") or detail.get("items") or []
        if items:
            nombres = [str(i.get("name") or i.get("title") or "")[:40] for i in items]
            if nombres and not p.get("producto"):
                p["producto"] = " / ".join([n for n in nombres if n])
            if items and not p.get("sku"):
                p["sku"] = str(items[0].get("sku") or "")
            # Lista completa (multi-producto). Melonn solo da sku+cantidad.
            if not p.get("items"):
                p["items"] = [
                    {
                        "sku":      str(i.get("sku") or ""),
                        "titulo":   str(i.get("name") or i.get("title") or ""),
                        "variante": "",
                        "cantidad": int(i.get("quantity") or 1),
                        "precio":   0.0,
                        "imagen":   "",
                    }
                    for i in items
                ]

        if nombre and not p.get("nombre_comprador"):
            p["nombre_comprador"] = nombre
        if telefono and not p.get("telefono_comprador"):
            p["telefono_comprador"] = telefono
        if ciudad and not p.get("ciudad_destino"):
            p["ciudad_destino"] = ciudad
        if region and not p.get("region_destino"):
            p["region_destino"] = region
        if email and not p.get("email_comprador"):
            p["email_comprador"] = email
        if direccion and not p.get("direccion"):
            p["direccion"] = direccion

        # ── Fechas reales, desde sell_order_attempt ──────────────────────────
        # ANTES leía `dispatch_date`, `delivery_date` y `promise_date`. NINGUNO
        # DE LOS TRES EXISTE en las respuestas de Melonn — verificado volcando
        # todas las claves de pedidos reales en varios estados. Por eso
        # `fecha_despacho_confiable` nunca se marcaba y los pedidos en tránsito
        # se re-consultaban en cada ciclo, para siempre (el bucle de las 130).
        #
        # Los campos de verdad viven en sell_order_attempt[], que SOLO llega si
        # se pide ?fields=sell_order_promises (arriba). Cada attempt es un
        # intento de entrega; `current: true` marca el vigente.
        attempts = detail.get("sell_order_attempt") or []
        if isinstance(attempts, list) and attempts:
            act = next((a for a in attempts
                        if isinstance(a, dict) and a.get("current")), None)
            if act is None:
                act = attempts[-1] if isinstance(attempts[-1], dict) else {}

            def _dia(v) -> str:
                return str(v).split("T")[0] if v else ""

            def _despacho_plausible(dia: str, pedido: dict) -> bool:
                """¿Esta fecha de despacho puede ser cierta?

                Dos imposibles: despachar antes de que el pedido exista, y
                despachar en el futuro. Ante cualquier duda de parseo devuelve
                True (no se descarta un dato por no poder leer la fecha de
                creación) — el que filtra de verdad es el caso claro.
                """
                try:
                    d = date.fromisoformat(dia[:10])
                except Exception:
                    return False
                if d > date.today():
                    return False
                creado = str(pedido.get("fecha_creacion") or "")[:10]
                if creado:
                    try:
                        if d < date.fromisoformat(creado):
                            return False
                    except Exception:
                        pass
                return True

            # Despacho real: la fuente autoritativa. Shopify da la fecha del
            # registro del fulfillment, no la del despacho, y por eso inflaba
            # los días en tránsito.
            envio = _dia(act.get("ship_timestamp"))
            # CORDÓN SANITARIO (2026-07-30): un despacho no puede ser anterior a
            # la creación del pedido ni estar en el futuro. Melonn manda basura
            # acá de vez en cuando y el valor se HEREDA entre sincronizaciones
            # (está en _CAMPOS_ENRIQUECIDOS), así que un dato malo se queda
            # pegado para siempre. Caso real: el 61360 se creó el 30-jul y traía
            # ship_timestamp del 12-jun → la app mostraba 48 días de tránsito de
            # un pedido despachado ese mismo día. Si la fecha no tiene sentido no
            # se guarda, y sobre todo NO se marca confiable.
            if envio and not _despacho_plausible(envio, p):
                log.warning(
                    f"{p.get('orden_tienda')}: ship_timestamp {envio} imposible "
                    f"(creado {str(p.get('fecha_creacion'))[:10]}) — se ignora")
                envio = ""
            if envio:
                p["fecha_despacho"] = envio
                p["fecha_despacho_confiable"] = True
                # PROCEDENCIA: de dónde salió esta fecha. Sin esto no se puede
                # auditar un número — solo creerle.
                p["fecha_despacho_origen"] = "melonn_ship_timestamp"

            # Solo rellenar si faltan: no pisar lo que ya trajo el listado.
            entrega = _dia(act.get("delivery_timestamp")) or _dia(act.get("pickup_timestamp"))
            if entrega and not p.get("fecha_entrega"):
                p["fecha_entrega"] = entrega

            # Ventana prometida de entrega. Es dato NUEVO: permite decir "se
            # pasó de lo que Melonn prometió" en vez de solo contar días.
            promesa = _dia(act.get("delivery_promise_max")) or _dia(act.get("pickup_promise_max"))
            if promesa and not p.get("fecha_promesa"):
                p["fecha_promesa"] = promesa
            pmin = act.get("delivery_promise_min") or act.get("pickup_promise_min")
            if pmin and not p.get("promesa_entrega_min"):
                p["promesa_entrega_min"] = _dia(pmin)
            if act.get("delivery_promise_max") and not p.get("promesa_entrega_max"):
                p["promesa_entrega_max"] = _dia(act["delivery_promise_max"])
            p["intentos_entrega"] = len(attempts)

        if nombre or telefono or ciudad:
            completados += 1

        resultado[idx] = p

    if completados > 0:
        log.info(f"Melonn detail enricher: {completados} pedidos completados")

    return resultado


def sync_completo() -> dict:
    """
    Pasada exhaustiva de enriquecimiento sobre TODO el caché.
    Lento (~30-90s según volumen) — solo invocar manualmente.
    """
    if not _SHOPIFY_ENRICHER_OK:
        return {"ok": False, "error": "Shopify enricher no disponible"}

    hit = _cache_leer(ignorar_ttl=True)
    if not hit:
        return {"ok": False, "error": "Sin caché para enriquecer"}

    pedidos, fetched_at, _, fuente = hit
    pedidos = _enriquecer_y_filtrar(pedidos)
    antes = sum(1 for p in pedidos if p.get("nombre_comprador"))
    total = len(pedidos)

    try:
        pedidos = _enricher.enriquecer(pedidos)
    except Exception as e:
        log.warning(f"Shopify enricher en sync_completo: {e}")

    # Pasada de Melonn detail para pedidos manuales — limitado a 50 por ciclo
    # para conservar cuota de la API. Eventualmente se completan en próximos runs.
    try:
        pedidos = _enriquecer_desde_melonn(pedidos, max_pedidos=50)
    except Exception as e:
        log.warning(f"Melonn detail enricher en sync_completo: {e}")

    # Verificar estados stale — solo 25 más antiguos por ciclo (preserva cuota)
    try:
        pedidos = _verificar_estados_stale(pedidos, max_check=25)
    except Exception as e:
        log.warning(f"Verificación estados stale en sync_completo: {e}")

    despues = sum(1 for p in pedidos if p.get("nombre_comprador"))
    try:
        _cache_guardar(pedidos, fuente=fuente)
    except Exception as e:
        log.warning(f"sync_completo no pudo guardar caché: {e}")

    return {
        "ok":       True,
        "total":    total,
        "antes":    antes,
        "despues":  despues,
        "completados": despues - antes,
    }


def _enriquecer_y_filtrar(pedidos: list) -> list:
    """
    Re-aplica la lógica de clasificación vigente a pedidos ya normalizados.

    Re-deriva SIEMPRE:
      • es_contraentrega  → desde valor_cod_raw + payment_on_delivery_type
      • sub_estado_logistico → desde estado_melonn_code + estado_melonn

    Esto garantiza que cambios en la lógica de clasificación surtan efecto
    en el caché existente sin necesitar un refresh manual.
    """
    resultado = []
    for p in pedidos:
        p = dict(p)  # no mutar el original

        # ── Re-derivar es_contraentrega desde campos guardados ────────────────
        # Cubre: fix de payment_on_delivery_type, cambios de lógica futuros
        valor_cod = p.get("valor_cod_raw", "0") or "0"
        pay_type  = p.get("payment_on_delivery_type") or {}
        try:
            _monto = float(str(valor_cod).replace(",", "."))
        except Exception:
            _monto = 0.0
        _tipo = int(pay_type.get("code", 0)) if isinstance(pay_type, dict) else 0
        p["es_contraentrega"] = _monto > 0 or _tipo > 0
        p["tipo_recaudo"]     = "Contraentrega" if p["es_contraentrega"] else "Prepago"

        estado_guardado     = p.get("estado_melonn", "")
        estado_cod_guardado = int(p.get("estado_melonn_code") or 0)
        p["sub_estado_logistico"] = _sub_estado_logistico(
            estado_guardado, estado_cod_guardado, p.get("es_contraentrega", False)
        )

        # Normalizar campo tipo_recaudo / es_contraentrega para formatos viejos
        if "es_contraentrega" not in p:
            p["es_contraentrega"] = p.get("tipo_recaudo", "") == "Contraentrega"

        sub = p["sub_estado_logistico"]

        # Excluir pedidos B2B
        if p.get("es_b2b"):
            continue

        # Whitelist: código activo O nombre en novedades externas
        if (estado_cod_guardado
                and estado_cod_guardado not in CODIGOS_ACTIVOS
                and estado_guardado not in ESTADOS_NOVEDAD_EXTERNA):
            continue

        # Doble check por nombre — cancelados y proceso interno
        if estado_guardado in ESTADOS_EXCLUIR or estado_guardado in ESTADOS_PROCESO_INTERNO:
            continue

        # Incluir todas las órdenes activas D2C
        # OJO: si falta un estado acá, esos pedidos DESAPARECEN del tablero.
        # Al separar "en_preparacion" de "en_transito" habrían quedado fuera 96.
        if sub in ("pendiente_despacho", "en_preparacion", "en_transito",
                   "novedad", "entregado"):
            resultado.append(p)

    # ── Deduplicar por orden_tienda ──────────────────────────────────────
    # Un mismo external_order_number puede tener varias órdenes Melonn
    # (devolución/reposición/segundo envío). Nos quedamos con UNA por
    # orden_tienda — la más relevante:
    #   1) Si hay una activa (no entregado) y otra entregada/cerrada,
    #      gana la activa.
    #   2) Si todas están en el mismo bucket, gana la más reciente por
    #      fecha_creacion (la M-id más nueva refleja el envío vigente).
    # Esto arregla casos donde el pedido más viejo (ya entregado meses
    # atrás) aparecía marcado como crítico por tener muchos días.
    def _rank(p: dict) -> tuple:
        # Mayor = mejor. Activos sobre entregados, recientes sobre viejos.
        sub = p.get("sub_estado_logistico")
        activo = 0 if sub == "entregado" else 1
        fc = p.get("fecha_creacion")
        # Comparamos como str ISO para no romper si viene de cache JSON.
        fc_key = str(fc) if fc else ""
        return (activo, fc_key)

    por_orden: dict[str, dict] = {}
    sin_orden: list[dict] = []
    for p in resultado:
        ot = p.get("orden_tienda") or ""
        if not ot:
            sin_orden.append(p)
            continue
        existente = por_orden.get(ot)
        if existente is None or _rank(p) > _rank(existente):
            por_orden[ot] = p

    return list(por_orden.values()) + sin_orden


def _cache_novedad_vencido() -> bool:
    """
    Retorna True si el caché de novedades debe considerarse vencido.
    Usa un TTL más corto (_CACHE_TTL_NOVEDAD = 1h) para novedades prepago,
    de modo que los pedidos entregados desaparezcan más rápido del dashboard.
    """
    info = cache_info()
    if not info:
        return True
    return info.get("age_s", _CACHE_TTL_NOVEDAD + 1) > _CACHE_TTL_NOVEDAD


def _bootstrap_json() -> list:
    """Carga JSON pre-generado del repo — cero dependencias."""
    if not _JSON_BOOTSTRAP.exists():
        return []
    try:
        with open(_JSON_BOOTSTRAP, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log.warning(f"Error leyendo bootstrap.json: {e}")
        return []


# ── Punto de entrada ───────────────────────────────────────────────────────────
def obtener_pedidos_activos(dias: int = 30, forzar_refresh: bool = False) -> tuple:
    """
    Retorna (pedidos, omitidos, meta).

    Orden normal  (sin forzar_refresh):
      1. SQLite fresco (<4h)  → instantáneo, 0 requests
      2. SQLite stale         → datos viejos en disco
      3. JSON bootstrap       → datos del repo, siempre disponibles

    Cuando forzar_refresh=True (botón ↻):
      1. API Melonn           → fetch real, guarda en SQLite
      2. SQLite stale         → si API falla
      3. JSON bootstrap       → último recurso

    La API solo se llama cuando el usuario presiona ↻ — nunca en carga automática.
    Esto evita esperas innecesarias cuando la cuota está agotada.
    """
    omitidos = {"resuelto": 0, "sin_datos": 0}

    if forzar_refresh:
        # Protección multi-usuario: si otro usuario ya sincronizó hace <5 min,
        # reutilizamos ese caché en lugar de volver a golpear la API.
        info_actual = cache_info()
        if info_actual and not info_actual.get("stale") and info_actual.get("fuente") == "api_live":
            # OJO: api_age_s, NO age_s. Con age_s este guard bloqueaba el refresh
            # del scheduler casi siempre: cada webhook dejaba el caché con menos
            # de 60s de edad, así que "ya sincronizó alguien hace poco" era
            # verdad para el caché y mentira para Melonn. El listado se dejó de
            # pedir y los estados se congelaron (medido: 74 pedidos en código 29
            # contra 17 reales). api_age_s = None → nunca hubo fetch → sí refresca.
            age = info_actual.get("api_age_s")
            if age is not None and age < _MIN_REFRESH_SECS:
                pedidos, fetched_at, _, fuente_hit = _cache_leer(ignorar_ttl=True)
                log.info(f"Refresh bloqueado — caché api_live tiene {int(age)}s (<{_MIN_REFRESH_SECS}s)")
                return pedidos, omitidos, {
                    "fuente": fuente_hit, "stale": False,
                    "fetched_at": fetched_at,
                    "refresh_bloqueado": True,
                }

        # NO limpiamos caché aún — solo después de fetch exitoso.
        # Si limpiáramos primero y la API fallara, dejaríamos todo vacío.

        # — Intentar API real —
        pedidos_api = _fetch_api()
        if pedidos_api:
            # Solo aquí, con datos frescos confirmados, reemplazamos caché
            _cache_guardar(pedidos_api)
            return pedidos_api, omitidos, {
                "fuente": "api_live", "stale": False, "fetched_at": datetime.now()
            }

        # API falló → mantener caché existente como stale
        stale = _cache_leer(ignorar_ttl=True)
        if stale:
            pedidos, fetched_at, _, fuente_stale = stale
            pedidos = _enriquecer_y_filtrar(pedidos)
            log.warning("forzar_refresh: API falló, devuelvo caché stale")
            return pedidos, omitidos, {"fuente": fuente_stale, "stale": True, "fetched_at": fetched_at}

        pedidos_boot = _enriquecer_y_filtrar(_bootstrap_json())
        if pedidos_boot:
            _cache_guardar(pedidos_boot, fuente="csv_bootstrap")
            return pedidos_boot, omitidos, {
                "fuente": "csv_bootstrap", "stale": True, "fetched_at": datetime.now()
            }
        return [], omitidos, {"fuente": "sin_datos", "stale": False}

    # ── Carga normal: stale-while-revalidate ─────────────────────────────────
    # 1. Mostrar datos frescos del caché → instantáneo
    # Skip _lazy_enrich del path normal: solo corre en refresh forzado.
    # En cache normal los datos ya están enriquecidos desde el último fetch.
    hit = _cache_leer(ignorar_ttl=False)
    if hit:
        pedidos, fetched_at, _, fuente_hit = hit
        pedidos = _enriquecer_y_filtrar(pedidos)
        # NO ejecutamos _lazy_enrich aquí — bloquearía cada page load con
        # llamadas externas a Shopify/Melonn (~30s). El enriquecimiento
        # se hace explícitamente vía sync_completo() (botón "Sincronizar
        # datos") o cuando el caché expira (force_refresh).
        return pedidos, omitidos, {"fuente": fuente_hit, "stale": False, "fetched_at": fetched_at}

    # 2. Caché existe pero expiró → comportamiento depende de cuán viejo está
    stale = _cache_leer(ignorar_ttl=True)
    if stale:
        pedidos, fetched_at, _, fuente_stale = stale
        edad = (datetime.now() - fetched_at).total_seconds() if fetched_at else 999999

        # ── HARD TTL (24h): forzar fetch sincrónico aunque sea lento ─────────
        # Background refresh puede estar fallando silenciosamente — si llevamos
        # >24h con datos viejos, intentamos refresh real ahora.
        if edad > _CACHE_HARD_TTL:
            log.warning(f"Cache stale >24h ({edad/3600:.1f}h) — forzando fetch sincrónico")
            try:
                pedidos_fresh = _fetch_api()
                if pedidos_fresh:
                    _cache_guardar(pedidos_fresh)
                    return pedidos_fresh, omitidos, {
                        "fuente": "api_live", "stale": False,
                        "fetched_at": datetime.now(),
                    }
            except Exception as e:
                log.error(f"Fetch sincrónico falló: {e}")

        # Mostrar stale + refrescar en background (sin enrich — más rápido)
        pedidos = _enriquecer_y_filtrar(pedidos)
        _refresh_background()
        return pedidos, omitidos, {
            "fuente": fuente_stale, "stale": True,
            "fetched_at": fetched_at, "bg_refresh": True,
        }

    # 3. Sin caché → lanzar background y devolver vacío (primera vez)
    _refresh_background()
    return [], omitidos, {"fuente": "sin_datos", "stale": False, "bg_refresh": True}


def cargar_desde_csv(pedidos: list) -> dict:
    """
    Guarda pedidos ya normalizados (provenientes de un CSV cargado manualmente)
    como caché activo. Fuente = 'csv_upload' para distinguirlos de datos de API.
    """
    if not pedidos:
        return {"ok": False, "msg": "Sin pedidos válidos"}
    # forzar: acá encoger el caché ES la intención (alguien subió un CSV a mano).
    _cache_guardar(pedidos, fuente="csv_upload", forzar=True)
    return {"ok": True, "total": len(pedidos)}


def estado() -> dict:
    info = cache_info()
    return {
        "credenciales_ok": credenciales_ok(),
        "ultima_sync":     info["fetched_at"].strftime("%d/%m/%Y %H:%M") if info else None,
        "desactualizado":  info is None or info.get("stale", False),
    }
