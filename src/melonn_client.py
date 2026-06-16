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

def _refresh_background():
    """
    Lanza un fetch completo en un hilo daemon.
    Si ya hay uno en curso, no lanza otro.
    Actualiza Supabase cuando termina → próxima sesión carga datos frescos.
    """
    global _bg_running
    with _bg_lock:
        if _bg_running:
            log.info("[bg] Skip: ya hay un refresh en curso")
            return
        _bg_running = True

    def _run():
        global _bg_running
        t0 = time.time()
        try:
            pedidos = _fetch_api()
            elapsed = time.time() - t0
            if pedidos:
                _cache_guardar(pedidos)
                log.info(f"[bg] OK: {len(pedidos)} pedidos guardados en Supabase · {elapsed:.1f}s")
            else:
                log.warning(f"[bg] _fetch_api retornó vacío después de {elapsed:.1f}s")
        except Exception as e:
            elapsed = time.time() - t0
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
_PAGE_SIZE   = 25         # antes 50 — páginas más pequeñas = response time más rápido
_MAX_PAGES   = 60         # 25 × 60 = 1500 pedidos, suficiente para ventana 90d
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
#   Pendiente seller → 26          "Alistamiento en espera · Seller"
#   En tránsito      → 5,7,24,28  "En bodega lista" + "Con transportadora"
#   Entregado        → 6, 8        "Picked-up by buyer" / "Delivered to buyer"
#   Prepago novedad  → 1, 2        (se muestra en tab Pedidos Pagos)
#   Novedades ext.   → por NOMBRE  (código no confirmado en API docs)
CODIGOS_PENDIENTE_DESPACHO = {26, 29}
CODIGOS_EN_TRANSITO        = {5, 7, 24, 28}
CODIGOS_ENTREGADO          = {6, 8}
CODIGOS_NOVEDAD            = {20}
CODIGOS_RESUELTO           = set()
CODIGOS_ACTIVOS            = (
    CODIGOS_PENDIENTE_DESPACHO
    | CODIGOS_EN_TRANSITO
    | CODIGOS_ENTREGADO
    | CODIGOS_NOVEDAD
    | {1, 2}
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
ESTADOS_EN_TRANSITO = {
    "Shipped - in transit", "Despachada - en tránsito", "En tránsito",  # 7
    "Packed", "Empacada",                                                # 5
    "Prepared for dispatch", "Preparada para despacho",                  # 24
    "Ready For Packing", "Lista para empaque",                           # 28
}

# Novedades prepago — códigos 1 y 2 (se muestran en tab Pedidos Pagos)
ESTADOS_NOVEDAD_PREPAGO = {
    "Received - valid",                              # 1 inglés
    "Recibida - valida",                             # 1 español
    "All items reserved - ready for fulfillment",    # 2 inglés
    "Recibida - valida - lista para alistamiento",   # 2 español
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
ESTADOS_NOVEDAD   = ESTADOS_NOVEDAD_EXTERNA | ESTADOS_NOVEDAD_PREPAGO
ESTADOS_RESUELTO  = set()
ESTADOS_RESUELTOS = ESTADOS_EXCLUIR
ESTADOS_ACTIVOS   = (
    ESTADOS_PENDIENTE_DESPACHO | ESTADOS_EN_TRANSITO
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

        stored_hash = envelope.get("config_hash","")
        if stored_hash != _config_hash():
            log.info(f"Supabase cache: config_hash cambió ({stored_hash} → {_config_hash()}) — invalidando")
            return None

        # fetched_at viene como string ISO desde Supabase
        fa_raw     = row["fetched_at"]
        fetched_at = datetime.fromisoformat(fa_raw.replace("Z","+00:00").replace("+00:00",""))
        age        = (datetime.now() - fetched_at).total_seconds()
        fresco     = age <= _CACHE_TTL
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
            sb.table(_SB_TABLA).delete().eq("id", 1).execute()
    except Exception as e:
        log.warning(f"Supabase limpiar error: {e}")


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
        stored_hash = row["config_hash"] or ""
        if stored_hash != _config_hash():
            log.info("SQLite cache: config_hash cambió — invalidando")
            return None
        fetched_at = datetime.fromisoformat(row["fetched_at"])
        age    = (datetime.now() - fetched_at).total_seconds()
        fresco = age <= _CACHE_TTL
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


def _cache_guardar(pedidos: list, fuente: str = "api_live"):
    """Escribe en Supabase Y en SQLite (redundancia)."""
    _sb_cache_guardar(pedidos, fuente)
    _sq_cache_guardar(pedidos, fuente)


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
    try:
        nuevo = _normalizar(detail)
    except Exception:
        # Fallback: estructura mínima
        nuevo = {
            "orden_melonn":   f"M{detail.get('internal_order_number') or usado}",
            "orden_tienda":   detail.get("external_order_number") or usado,
            "estado_melonn":  ((detail.get("state") or {}).get("name") or ""),
            "estado_melonn_code": int(((detail.get("state") or {}).get("code") or 0)),
            "_raw": True,
        }

    # Mezclar con caché actual
    hit = _cache_leer(ignorar_ttl=True)
    if not hit:
        # No hay caché — guardamos solo este pedido (raro pero válido)
        _cache_guardar([nuevo], fuente="webhook")
        return {"ok": True, "accion": "creado", "orden": nuevo.get("orden_tienda")}

    pedidos, _ft, _ts, fuente = hit
    encontrado = False
    nuevo_om = (nuevo.get("orden_melonn") or "").lstrip("Mm")
    nuevo_ot = nuevo.get("orden_tienda") or ""
    for i, p in enumerate(pedidos):
        p_om = (p.get("orden_melonn") or "").lstrip("Mm")
        p_ot = p.get("orden_tienda") or ""
        if (nuevo_om and p_om == nuevo_om) or (nuevo_ot and p_ot == nuevo_ot):
            pedidos[i] = nuevo
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
                fa_raw     = row["fetched_at"]
                fetched_at = datetime.fromisoformat(fa_raw.replace("Z","+00:00").replace("+00:00",""))
                age        = (datetime.now() - fetched_at).total_seconds()
                hash_ok    = cfg_hash == _config_hash()
                return {
                    "fetched_at":  fetched_at,
                    "age_s":       age,
                    "total":       row["total"],
                    "fresco":      age <= _CACHE_TTL and hash_ok,
                    "stale":       age > _CACHE_TTL or not hash_ok,
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
        fetched_at = datetime.fromisoformat(row["fetched_at"])
        age        = (datetime.now() - fetched_at).total_seconds()
        fuente     = row["fuente"] or "api_live"
        hash_ok    = (row["config_hash"] or "") == _config_hash()
        return {
            "fetched_at":  fetched_at,
            "age_s":       age,
            "total":       row["total"],
            "fresco":      age <= _CACHE_TTL and hash_ok,
            "stale":       age > _CACHE_TTL or not hash_ok,
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

    Aplica el token-bucket antes de cada intento para nunca superar
    los 10 req/s que permite la API de Melonn.
    """
    url = f"{_BASE_URL}/{path.lstrip('/')}"
    for attempt, backoff in enumerate([0] + _RETRY_BACKOFF):
        if backoff:
            log.warning(f"Melonn rate-limit — esperando {backoff}s (intento {attempt+1}/{_RETRY_MAX+1})")
            time.sleep(backoff)

        _rate_limiter.wait()  # respeta el techo de _MAX_RPS req/s

        try:
            r = requests.get(
                url,
                headers={"x-api-key": _api_key(), "Accept": "application/json"},
                params=params,
                timeout=(_CONNECT_TO, _TIMEOUT),
            )

            if r.status_code in (429, 503):
                # Respeta Retry-After si la API lo devuelve
                retry_after = int(r.headers.get("Retry-After", _RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF)-1)]))
                log.warning(f"HTTP {r.status_code} — Retry-After: {retry_after}s")
                if attempt < _RETRY_MAX:
                    time.sleep(retry_after)
                    continue
                return None  # agotados los reintentos

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

    for attempt, backoff in enumerate([0] + post_backoff):
        if backoff:
            log.warning(f"POST rate-limit — esperando {backoff}s (intento {attempt+1}/{len(post_backoff)+1})")
            time.sleep(backoff)

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


def _sub_estado_logistico(estado: str, codigo: int = 0, es_cod: bool = False) -> str:
    """
    Clasifica el estado Melonn en las categorías operativas del dashboard.
    Códigos confirmados en producción (junio 2026):
      pendiente_despacho → 26
      en_transito        → 5, 7, 24, 28
      novedad COD        → 20 únicamente (Delivery not posible)
      novedad prepago    → 1, 2 + 20, 29
      entregado          → 6, 8
    """
    if codigo in CODIGOS_NOVEDAD or estado in ESTADOS_NOVEDAD_EXTERNA:
                                                  return "novedad"
    if codigo in CODIGOS_ENTREGADO or estado in ESTADOS_ENTREGADO:
                                                  return "entregado"
    if codigo in CODIGOS_EN_TRANSITO or estado in ESTADOS_EN_TRANSITO:
                                                  return "en_transito"
    if codigo in CODIGOS_PENDIENTE_DESPACHO or estado in ESTADOS_PENDIENTE_DESPACHO:
                                                  return "pendiente_despacho"
    # Códigos 1 y 2 solo se muestran como novedad en prepago — no en COD
    if not es_cod and estado in ESTADOS_NOVEDAD_PREPAGO:
                                                  return "novedad"
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
    estado    = str((raw.get("sell_order_state") or {}).get("name") or "")
    estado_code = int((raw.get("sell_order_state") or {}).get("code") or 0)
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
    corte       = _fecha_corte()
    pedidos_raw = []
    page        = 0

    while page < _MAX_PAGES:
        resp = _get("sell-orders", params={"per_page": _PAGE_SIZE, "page": page})
        if resp is None:
            break
        items = resp.get("data") or []
        if not items:
            break

        activos_en_pagina = 0
        for item in items:
            fc       = _parsear_fecha(item.get("creation_date"))
            estado_c = int((item.get("sell_order_state") or {}).get("code") or 0)
            estado_n = str((item.get("sell_order_state") or {}).get("name") or "")
            es_activo          = (estado_c in CODIGOS_ACTIVOS
                                  or estado_n in ESTADOS_NOVEDAD_EXTERNA)
            # Entregados (6,8) se recogen pero NO cuentan para decidir si
            # hay más páginas relevantes — evita paginar historial de entregas
            es_activo_operativo = (estado_c in CODIGOS_ACTIVOS_OPERATIVO
                                   or estado_n in ESTADOS_NOVEDAD_EXTERNA)

            if fc and fc < corte and not es_activo:
                continue

            pedidos_raw.append(item)
            if es_activo_operativo:
                activos_en_pagina += 1

        # Página completa sin activos operativos → solo hay entregados/terminales
        if len(items) == _PAGE_SIZE and activos_en_pagina == 0:
            log.info(f"Paginación detenida en página {page}: sin activos operativos")
            break

        if len(items) < _PAGE_SIZE:
            break   # última página
        page += 1

    log.info(f"Melonn API: {len(pedidos_raw)} pedidos ({page+1} página(s))")

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
        if sub in ("pendiente_despacho", "en_transito", "novedad", "entregado"):
            resultado.append(p)

    # Enriquecer con datos de cliente y fechas desde Shopify (batch)
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
        if p.get("nombre_comprador"):
            continue
        if p.get("orden_tienda"):
            indices.append(i)

    if not indices:
        return pedidos

    # Priorizar por número de orden descendente (más recientes primero)
    def _key(i: int) -> int:
        ot = str(pedidos[i].get("orden_tienda", "")).split("-")[0]
        return int(ot) if ot.isdigit() else 0

    indices.sort(key=_key, reverse=True)
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
                detail = _get(f"sell-orders/{candidato}")
                if detail:
                    break
            except Exception as e:
                log.debug(f"detail {candidato}: {e}")
                continue

        if not detail:
            log.warning(f"Sin detalle Melonn para {ext} / {internal}")
            continue

        p = dict(p)

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

        # Fechas (formato ISO YYYY-MM-DD)
        for src_key, dst_key in [
            ("dispatch_date",  "fecha_despacho"),
            ("delivery_date",  "fecha_entrega"),
            ("promise_date",   "fecha_promesa"),
        ]:
            raw = detail.get(src_key) or ""
            if raw and not p.get(dst_key):
                try:
                    p[dst_key] = str(raw).split("T")[0]
                except Exception:
                    pass

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
        if sub in ("pendiente_despacho", "en_transito", "novedad", "entregado"):
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
            age = info_actual.get("age_s", _MIN_REFRESH_SECS + 1)
            if age < _MIN_REFRESH_SECS:
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
    _cache_guardar(pedidos, fuente="csv_upload")
    return {"ok": True, "total": len(pedidos)}


def estado() -> dict:
    info = cache_info()
    return {
        "credenciales_ok": credenciales_ok(),
        "ultima_sync":     info["fetched_at"].strftime("%d/%m/%Y %H:%M") if info else None,
        "desactualizado":  info is None or info.get("stale", False),
    }
