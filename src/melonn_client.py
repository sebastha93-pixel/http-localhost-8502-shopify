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

# Enriquecimiento con datos de cliente desde Shopify
try:
    import shopify_enricher as _enricher
    _SHOPIFY_ENRICHER_OK = True
except ImportError:
    _SHOPIFY_ENRICHER_OK = False

# ── Config ─────────────────────────────────────────────────────────────────────
_BASE_URL  = "https://api.orbita.melonn.com"
_TIMEOUT   = 20
_PAGE_SIZE  = 50
_MAX_PAGES  = 5        # hasta 250 pedidos por sync (5 × 50)
_CACHE_TTL  = 1800     # 30 minutos — antes 4h, reducido para mayor frescura

# Rate limiting — Melonn permite MÁXIMO 1 req/s (documentación oficial)
_MAX_RPS           = 0.8
_MIN_INTERVAL      = 1.0 / _MAX_RPS   # 1.25s entre requests
_MIN_REFRESH_SECS  = 60         # 1 min mínimo entre syncs (antes 5 min)
_RETRY_MAX         = 3
_RETRY_BACKOFF     = [5, 15, 30]
_CACHE_TTL_NOVEDAD = 1800       # igual que TTL principal


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
CODIGOS_EXCLUIR = {8, 9, 15, 16, 17, 18, 19}   # 8=Entregado excluido

# Proceso interno — nunca se muestra al seller
# 1=Recibida-válida y 2=Reservada-lista se movieron a NOVEDAD
CODIGOS_PROCESO_INTERNO = {3, 4, 10, 12, 22, 25, 27}

# Whitelist por código
#   Pendiente seller  → 26          "Alistamiento en espera - Seller"
#   En tránsito COD   → 5,6,7,24,28
#   Novedad           → 1,2
#                        1  Recibida · válida
#                        2  Reservada · lista para alistamiento
CODIGOS_PENDIENTE_DESPACHO = {26}
CODIGOS_EN_TRANSITO        = {5, 6, 7, 24, 28}
CODIGOS_NOVEDAD            = {1, 2}
CODIGOS_RESUELTO           = set()
CODIGOS_ACTIVOS            = (
    CODIGOS_PENDIENTE_DESPACHO
    | CODIGOS_EN_TRANSITO
    | CODIGOS_NOVEDAD
)

# ── Nombres de estado (para compatibilidad con caché antiguo y UI) ────────────
# Nunca mostrar — se saltan en fetch y en caché
ESTADOS_EXCLUIR = {
    # Inglés
    "Received - invalid fixable",                          # 9
    "Canceled",                                            # 15
    "Picked-up by courier for return",                     # 16
    "On Cancelation Process - to be unpacked & relocated", # 17
    "On Cancelation Process - to be received from courier",# 18
    "In transit - Cancelation requested",                  # 19
    "Delivered to buyer",                                  # 8 excluido
    # Español
    "Cancelada",                                           # 15 español
    "Recogida por transportadora para devolución",         # 16 español
    "En proceso de cancelación",                           # 17/18 español
    "En tránsito - cancelación solicitada",                # 19 español
    "Entregada al comprador",                              # 8 español excluido
    "Entregada - pendiente de cobro",                      # 8 variante excluida
}

# Código 6 movido a EN_TRANSITO — ya no hay "resueltos" separados
ESTADOS_RESUELTO = set()

# Alias para compatibilidad con bootstrap/caché antiguo
ESTADOS_RESUELTOS = ESTADOS_EXCLUIR | ESTADOS_RESUELTO

# Solo los estados donde el seller DEBE autorizar el despacho (códigos 23 y 26)
# Todo lo demás es proceso interno de Melonn — no se muestra en el dashboard
ESTADOS_PENDIENTE_DESPACHO = {
    # Código 26 únicamente — seller debe autorizar despacho
    "All items reserved - fulfillment on hold",      # 26 inglés
    "Alistamiento en espera - Seller",               # 26 español ← estado real de la cuenta
    # "Packed - on hold" (23) excluido — no aplica para esta cuenta
}

# En tránsito COD — códigos 5, 6, 7, 24, 28
ESTADOS_EN_TRANSITO = {
    # Código 5 — Empacada
    "Packed", "Empacada",
    # Código 6 — Recogida por el comprador (finalizada)
    "Picked-up by buyer", "Recogida por el comprador",
    # Código 7 — Con la transportadora
    "Shipped - in transit", "Despachada - en tránsito", "En tránsito",
    # Código 24 — Preparada para despacho
    "Prepared for dispatch", "Preparada para despacho",
    # Código 28 — Lista para empaque (en bodega)
    "Ready For Packing", "Lista para empaque",
}

# Novedad — códigos 1 y 2 únicamente
ESTADOS_NOVEDAD = {
    # Código 1 — Recibida válida
    "Received - valid",                              # 1 inglés
    "Recibida - valida",                             # 1 español
    # Código 2 — Reservada lista para alistamiento
    "All items reserved - ready for fulfillment",    # 2 inglés
    "Recibida - valida - lista para alistamiento",   # 2 español
}

# Estados de proceso interno — nunca mostrar
# 1 y 2 se movieron a NOVEDAD; 28 se movió a EN_TRANSITO
ESTADOS_PROCESO_INTERNO = {
    # Inglés
    "Picking", "Picked", "Fixed & valid - to be processed",
    "Processing Requested", "Packing",
    "Selected for dispatch preparation", "Pre Packing - Vas Pending",
    # Español
    "Alistando", "Alistada", "Empacando",
    "Seleccionada para preparación de despacho",
}

ESTADOS_ACTIVOS = ESTADOS_PENDIENTE_DESPACHO | ESTADOS_EN_TRANSITO | ESTADOS_NOVEDAD | ESTADOS_RESUELTO


def _config_hash() -> str:
    """
    Hash de 8 chars de CODIGOS_ACTIVOS.
    Cambia automáticamente cada vez que se modifica qué códigos deben cargarse.
    La caché lo compara en cada lectura — si difiere, se descarta y se refetchea.
    """
    return hashlib.md5(str(sorted(CODIGOS_ACTIVOS)).encode()).hexdigest()[:8]


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


# ── SQLite cache ───────────────────────────────────────────────────────────────
def _conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(_DB_PATH), timeout=10)
    c.row_factory = sqlite3.Row
    return c


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
        # Migraciones — añade columnas si la tabla ya existía sin ellas
        for col, default in [("fuente", "'api_live'"), ("config_hash", "''")]:
            try:
                c.execute(f"ALTER TABLE melonn_pedidos_cache ADD COLUMN {col} TEXT DEFAULT {default}")
            except Exception:
                pass
        c.commit()


def _cache_leer(ignorar_ttl: bool = False) -> Optional[tuple]:
    """
    Retorna (pedidos, fetched_at, fresco, fuente) o None.

    Descarta la caché automáticamente si:
      - El TTL de 30 min venció (a menos que ignorar_ttl=True)
      - El config_hash no coincide con el hash actual de CODIGOS_ACTIVOS
        → significa que los códigos a mostrar cambiaron desde el último fetch
    """
    try:
        _init_tabla()
        with _conn() as c:
            row = c.execute(
                "SELECT fetched_at, pedidos_json, fuente, config_hash "
                "FROM melonn_pedidos_cache WHERE id=1"
            ).fetchone()
        if not row:
            return None

        # Invalidar si CODIGOS_ACTIVOS cambió desde que se guardó la caché
        stored_hash  = row["config_hash"] or ""
        current_hash = _config_hash()
        if stored_hash != current_hash:
            log.info(f"config_hash cambió ({stored_hash} → {current_hash}) — caché invalidada")
            return None

        fetched_at = datetime.fromisoformat(row["fetched_at"])
        age    = (datetime.now() - fetched_at).total_seconds()
        fresco = age <= _CACHE_TTL
        if not fresco and not ignorar_ttl:
            return None

        pedidos = json.loads(row["pedidos_json"])
        fuente  = row["fuente"] if row["fuente"] else "api_live"
        return pedidos, fetched_at, fresco, fuente
    except Exception as e:
        log.warning(f"Error leyendo SQLite cache: {e}")
        return None


def _cache_guardar(pedidos: list, fuente: str = "api_live"):
    """Guarda pedidos junto con el hash actual de CODIGOS_ACTIVOS."""
    try:
        _init_tabla()
        with _conn() as c:
            c.execute("""
                INSERT OR REPLACE INTO melonn_pedidos_cache
                    (id, fetched_at, pedidos_json, total, fuente, config_hash)
                VALUES (1, ?, ?, ?, ?, ?)
            """, (
                datetime.now().isoformat(),
                json.dumps(pedidos, default=str),
                len(pedidos),
                fuente,
                _config_hash(),
            ))
            c.commit()
    except Exception as e:
        log.warning(f"Error guardando SQLite cache: {e}")


def limpiar_cache():
    try:
        _init_tabla()
        with _conn() as c:
            c.execute("DELETE FROM melonn_pedidos_cache WHERE id=1")
            c.commit()
    except Exception as e:
        log.warning(f"Error limpiando cache: {e}")


def cache_info() -> Optional[dict]:
    try:
        _init_tabla()
        with _conn() as c:
            row = c.execute(
                "SELECT fetched_at, total, fuente, config_hash "
                "FROM melonn_pedidos_cache WHERE id=1"
            ).fetchone()
        if not row:
            return None
        fetched_at   = datetime.fromisoformat(row["fetched_at"])
        age          = (datetime.now() - fetched_at).total_seconds()
        fuente       = row["fuente"] if row["fuente"] else "api_live"
        hash_ok      = (row["config_hash"] or "") == _config_hash()
        return {
            "fetched_at":  fetched_at,
            "age_s":       age,
            "total":       row["total"],
            "fresco":      age <= _CACHE_TTL and hash_ok,
            "stale":       age > _CACHE_TTL or not hash_ok,
            "fuente":      fuente,
            "config_hash": row["config_hash"],
            "hash_ok":     hash_ok,
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
                timeout=_TIMEOUT,
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
    POST con rate limiting.
    Retorna (ok: bool, data: dict | None, error_msg: str).
    """
    url = f"{_BASE_URL}/{path.lstrip('/')}"
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
            return True, data, ""
        try:
            msg = r.json().get("message") or r.text[:200]
        except Exception:
            msg = r.text[:200]
        log.warning(f"POST {url} → HTTP {r.status_code}: {msg}")
        return False, None, f"HTTP {r.status_code}: {msg}"
    except Exception as e:
        log.warning(f"POST {url} error: {e}")
        return False, None, str(e)


def release_hold_fulfillment(orden_melonn: str, shipping_method_code: str = None) -> tuple:
    """
    Libera el hold de fulfillment de un pedido — autoriza su despacho.

    POST /sell-orders/{orden_melonn}/release-hold-fulfillment
    Body opcional: { "shipping_method_code": "XXX" }

    Retorna (ok: bool, mensaje: str).
    """
    if not orden_melonn:
        return False, "Número de orden Melonn no disponible"

    body = {}
    if shipping_method_code:
        body["shipping_method_code"] = shipping_method_code

    ok, data, err = _post(
        f"sell-orders/{orden_melonn}/release-hold-fulfillment",
        body=body,
    )

    if ok:
        log.info(f"Despacho autorizado: {orden_melonn}")
        melonn_msg = (data or {}).get("message", "Order released successfully")
        return True, f"{melonn_msg} · Orden {orden_melonn}"
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
    Ventana de datos: mes actual completo + hasta 15 días del mes anterior.
    Retorna la más temprana entre: primer día del mes actual y hoy - 15 días.
    Ejemplo: hoy = 5 junio  → min(1 jun, 21 may) = 21 mayo
             hoy = 25 junio → min(1 jun, 10 jun) = 1 junio
    """
    from datetime import timedelta
    hoy = date.today()
    return min(hoy.replace(day=1), hoy - timedelta(days=15))


def _sub_estado_logistico(estado: str) -> str:
    """
    Clasifica el estado Melonn en las 4 categorías operativas del dashboard:
      pendiente_despacho → en bodega, aún no enviado
      en_transito        → despachado, esperando entrega normal
      novedad            → problema activo que requiere gestión
      resuelto           → novedad solucionada / pedido recogido (estado 6)
    """
    if estado in ESTADOS_NOVEDAD:       return "novedad"
    if estado in ESTADOS_EN_TRANSITO:   return "en_transito"
    if estado in ESTADOS_PENDIENTE_DESPACHO: return "pendiente_despacho"
    if estado in ESTADOS_RESUELTO:      return "resuelto"
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
    es_b2b    = bool(raw.get("is_b2b"))

    es_cod = bool(valor_cod and float(str(valor_cod).replace(",", ".") or 0) > 0)

    return {
        # ── Identificadores ──────────────────────────────────────────────────
        "orden_melonn":           str(raw.get("internal_order_number") or raw.get("id") or ""),
        "orden_tienda":           str(raw.get("external_order_number") or "").lstrip("#"),
        "external_order_id":      str(raw.get("external_order_id") or ""),
        # ── Estado ───────────────────────────────────────────────────────────
        "estado_melonn":          estado,
        "estado_melonn_code":     estado_code,
        "sub_estado_logistico":   _sub_estado_logistico(estado),
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
    Trae pedidos dentro de la ventana: mes actual + últimos 15 días.
    Para cuando encuentra un pedido más antiguo que la fecha de corte.

    Inclusión:
      COD     → pendiente_despacho | en_transito | novedad | resuelto (estado 6)
      Prepago → solo novedad
      Excluidos siempre: estados en ESTADOS_EXCLUIR (8,9,15,17,18,19)
    """
    corte       = _fecha_corte()
    pedidos_raw = []
    page        = 0

    while page < _MAX_PAGES:
        resp = _get("sell-orders", params={"per_page": _PAGE_SIZE, "page": page})
        if resp is None:
            break
        items = resp.get("data") or []
        meta  = resp.get("meta_data") or {}

        alcanzado_corte = False
        for item in items:
            fc = _parsear_fecha(item.get("creation_date"))
            if fc and fc < corte:
                alcanzado_corte = True
                break
            pedidos_raw.append(item)

        if alcanzado_corte or not items or len(pedidos_raw) >= (meta.get("total_count") or 0):
            break
        page += 1

    log.info(f"Melonn API: {len(pedidos_raw)} pedidos desde {corte} (ventana: mes + 15d)")

    resultado = []
    for item in pedidos_raw:
        estado_obj  = item.get("sell_order_state") or {}
        estado_nombre = str(estado_obj.get("name") or "")
        estado_codigo = int(estado_obj.get("code") or 0)

        # ── Whitelist por código — solo estados activos (excluye terminales,
        #    cancelados Y proceso interno de Melonn) ──────────────────────────
        if estado_codigo not in CODIGOS_ACTIVOS:
            log.debug(f"Excluido código {estado_codigo} ({estado_nombre})")
            continue

        # Doble check por nombre — proceso interno y estados excluidos
        if estado_nombre in ESTADOS_EXCLUIR or estado_nombre in ESTADOS_PROCESO_INTERNO:
            log.debug(f"Excluido por nombre: {estado_nombre}")
            continue

        try:
            p = _normalizar(item)
        except Exception:
            continue

        sub    = p["sub_estado_logistico"]
        es_cod = p["es_contraentrega"]

        if es_cod:
            # COD: mostrar pendiente, tránsito, novedad y resuelto
            resultado.append(p)
        else:
            # Prepago: solo novedades activas
            if sub == "novedad":
                resultado.append(p)

    # Enriquecer con datos de cliente y fechas desde Shopify (batch)
    if _SHOPIFY_ENRICHER_OK and resultado:
        try:
            resultado = _enricher.enriquecer(resultado)
        except Exception as e:
            log.warning(f"Shopify enricher error: {e}")

    return resultado


def _lazy_enrich(pedidos: list) -> list:
    """
    Enriquece con Shopify los pedidos en caché sin datos de cliente.
    Detecta tres casos:
      1. Tiene external_order_id pero no nombre_comprador  → API data sin enriquecer
      2. Sin external_order_id, sin nombre, con orden_tienda numérico → caché viejo
    """
    if not _SHOPIFY_ENRICHER_OK:
        return pedidos

    necesita = any(
        not p.get("nombre_comprador") and (
            p.get("external_order_id")
            or str(p.get("orden_tienda", "")).split("-")[0].isdigit()
        )
        for p in pedidos
    )
    if not necesita:
        return pedidos

    log.info("Lazy Shopify enricher: detectados pedidos sin datos de cliente en caché")
    try:
        return _enricher.enriquecer(pedidos)
    except Exception as e:
        log.warning(f"Lazy Shopify enricher error: {e}")
        return pedidos


def _enriquecer_y_filtrar(pedidos: list) -> list:
    """
    Aplica la lógica de inclusión a pedidos ya normalizados
    (bootstrap.json, CSV, caché SQLite de versiones anteriores).

    — Añade 'sub_estado_logistico' si el registro no lo tiene todavía.
    — Filtra: COD → todo; Prepago → solo novedades ACTIVAS.

    ⚠️  Re-deriva sub_estado_logistico desde estado_melonn en cada carga
        para que pedidos entregados (estado 8) que quedaron en caché como
        "novedad" sean correctamente excluidos aunque el caché sea viejo.
    """
    resultado = []
    for p in pedidos:
        p = dict(p)  # no mutar el original

        # Siempre re-deriva desde el estado guardado — esto cubre el caso donde
        # el pedido cambió de novedad → entregado pero el caché no se refrescó.
        estado_guardado = p.get("estado_melonn", "")
        estado_cod_guardado = int(p.get("estado_melonn_code") or 0)
        p["sub_estado_logistico"] = _sub_estado_logistico(estado_guardado)

        # Normalizar campo tipo_recaudo / es_contraentrega para formatos viejos
        if "es_contraentrega" not in p:
            p["es_contraentrega"] = p.get("tipo_recaudo", "") == "Contraentrega"

        sub    = p["sub_estado_logistico"]
        es_cod = p["es_contraentrega"]

        # Whitelist por código — excluye terminales, cancelados y proceso interno
        if estado_cod_guardado and estado_cod_guardado not in CODIGOS_ACTIVOS:
            continue

        # Doble check por nombre — proceso interno y excluidos
        if estado_guardado in ESTADOS_EXCLUIR or estado_guardado in ESTADOS_PROCESO_INTERNO:
            continue

        if es_cod:
            # COD: pendiente, tránsito, novedad y resuelto (estado 6)
            resultado.append(p)
        else:
            # Prepago: solo novedades activas
            if sub == "novedad":
                resultado.append(p)

    return resultado


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

        limpiar_cache()

        # — Intentar API real —
        pedidos_api = _fetch_api()
        if pedidos_api:
            _cache_guardar(pedidos_api)
            return pedidos_api, omitidos, {
                "fuente": "api_live", "stale": False, "fetched_at": datetime.now()
            }

        # API falló → stale o bootstrap
        stale = _cache_leer(ignorar_ttl=True)
        if stale:
            pedidos, fetched_at, _, fuente_stale = stale
            pedidos = _enriquecer_y_filtrar(pedidos)
            return pedidos, omitidos, {"fuente": fuente_stale, "stale": True, "fetched_at": fetched_at}

        pedidos_boot = _enriquecer_y_filtrar(_bootstrap_json())
        if pedidos_boot:
            _cache_guardar(pedidos_boot, fuente="csv_bootstrap")
            return pedidos_boot, omitidos, {
                "fuente": "csv_bootstrap", "stale": True, "fetched_at": datetime.now()
            }
        return [], omitidos, {"fuente": "sin_datos", "stale": False}

    # — Carga normal: SQLite → bootstrap (sin tocar la API) —

    # 1. SQLite fresco
    # Si el TTL de novedades venció (>1h), intentar refresh silencioso de la API
    # para que los pedidos entregados desaparezcan sin que el usuario pulse ↻.
    _novedad_vencido = _cache_novedad_vencido()
    if _novedad_vencido:
        log.info("Caché de novedades vencido (>1h) — intentando refresh silencioso")
        pedidos_api = _fetch_api()
        if pedidos_api:
            _cache_guardar(pedidos_api)
            return pedidos_api, omitidos, {
                "fuente": "api_live", "stale": False, "fetched_at": datetime.now()
            }
        # Si la API falla, continuar con caché aunque esté vencido

    hit = _cache_leer(ignorar_ttl=False)
    if hit:
        pedidos, fetched_at, _, fuente_hit = hit
        pedidos = _enriquecer_y_filtrar(pedidos)
        pedidos = _lazy_enrich(pedidos)
        return pedidos, omitidos, {"fuente": fuente_hit, "stale": False, "fetched_at": fetched_at}

    # 2. SQLite stale
    stale = _cache_leer(ignorar_ttl=True)
    if stale:
        pedidos, fetched_at, _, fuente_stale = stale
        pedidos = _enriquecer_y_filtrar(pedidos)
        pedidos = _lazy_enrich(pedidos)
        return pedidos, omitidos, {"fuente": fuente_stale, "stale": True, "fetched_at": fetched_at}

    # 3. JSON bootstrap → guarda en SQLite para próximas cargas
    pedidos_boot = _enriquecer_y_filtrar(_bootstrap_json())
    if pedidos_boot:
        _cache_guardar(pedidos_boot, fuente="csv_bootstrap")
        return pedidos_boot, omitidos, {
            "fuente": "csv_bootstrap", "stale": True, "fetched_at": datetime.now()
        }

    return [], omitidos, {"fuente": "sin_datos", "stale": False}


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
