"""
Cliente Melonn API — MALE'DENIM

Estrategia definitiva anti-rate-limit:
  • Solo el endpoint de listado GET /sell-orders (1-3 requests totales)
  • Cache SQLite persistente con TTL configurable
  • En reinicios de Streamlit: datos desde disco en <100ms
  • En caché vencida: 1-3 requests HTTP, luego guarda en disco
  • Nunca hace fetches individuales por orden
"""

import json
import logging
import os
import sqlite3
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import requests

log = logging.getLogger(__name__)

# ── Configuración ──────────────────────────────────────────────────────────────
_BASE_URL    = "https://api.orbita.melonn.com"
_TIMEOUT     = 30
_MAX_RETRIES = 3
_RETRY_WAIT  = 3          # segundos base entre reintentos
_PAGE_SIZE   = 50         # conservador — evita límites de la API
_CACHE_TTL   = 14400      # segundos (4 horas) — el cache nunca se invalida solo; refresh es manual

# Ruta del SQLite (misma BD que el resto de la app)
_DB_PATH = Path(__file__).parent.parent / "data" / "db" / "maledenim.db"

# ── Estados Melonn ─────────────────────────────────────────────────────────────
ESTADOS_EN_TRANSITO = {
    "Shipped - in transit",
    "Delivery not posible",
    "Packed",
    "Packed - on hold",
    "Prepared for dispatch",
    "All items reserved - ready for fulfillment",
    "All items reserved - fulfillment on hold - ext. conditionals",
    "on stand by - not able to fulfil - no stock",
}
ESTADOS_RESUELTOS = {
    "Delivered to buyer",
    "Picked-up by buyer",
    "Canceled",
}


# ── Credenciales ───────────────────────────────────────────────────────────────
def _api_key() -> Optional[str]:
    try:
        import streamlit as st
        return st.secrets.get("MELONN_API_KEY") or os.getenv("MELONN_API_KEY")
    except Exception:
        return os.getenv("MELONN_API_KEY")


def credenciales_ok() -> bool:
    return bool(_api_key())


def _headers() -> dict:
    return {
        "x-api-key":    _api_key(),
        "Content-Type": "application/json",
        "Accept":       "application/json",
    }


# ── Cache SQLite ───────────────────────────────────────────────────────────────
def _get_conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _init_cache():
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS melonn_pedidos_cache (
                id          INTEGER PRIMARY KEY CHECK (id = 1),
                fetched_at  TEXT NOT NULL,
                pedidos_json TEXT NOT NULL,
                total        INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.commit()


def _leer_cache(ignorar_ttl: bool = False) -> Optional[tuple]:
    """
    Retorna (pedidos: list, fetched_at: datetime, fresco: bool).
    Si ignorar_ttl=True devuelve datos aunque estén vencidos (modo stale fallback).
    Retorna None solo si no existe ningún dato en cache.
    """
    try:
        _init_cache()
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT fetched_at, pedidos_json FROM melonn_pedidos_cache WHERE id = 1"
            ).fetchone()
        if not row:
            return None
        fetched_at = datetime.fromisoformat(row["fetched_at"])
        age = (datetime.now() - fetched_at).total_seconds()
        fresco = age <= _CACHE_TTL
        if not fresco and not ignorar_ttl:
            log.info(f"Cache vencido ({age:.0f}s > {_CACHE_TTL}s) — se puede usar stale")
            return None
        pedidos = json.loads(row["pedidos_json"])
        log.info(f"Cache {'hit' if fresco else 'STALE'}: {len(pedidos)} pedidos ({age:.0f}s)")
        return pedidos, fetched_at, fresco
    except Exception as e:
        log.warning(f"Error leyendo cache: {e}")
        return None


def _guardar_cache(pedidos: list):
    try:
        _init_cache()
        with _get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO melonn_pedidos_cache (id, fetched_at, pedidos_json, total)
                VALUES (1, ?, ?, ?)
            """, (datetime.now().isoformat(), json.dumps(pedidos, default=str), len(pedidos)))
            conn.commit()
        log.info(f"Cache guardado: {len(pedidos)} pedidos")
    except Exception as e:
        log.warning(f"Error guardando cache: {e}")


def limpiar_cache():
    """Fuerza re-fetch en la próxima llamada. Llama esto desde el botón de refresh."""
    try:
        _init_cache()
        with _get_conn() as conn:
            conn.execute("DELETE FROM melonn_pedidos_cache WHERE id = 1")
            conn.commit()
        log.info("Cache Melonn limpiado — próxima carga hará re-fetch")
    except Exception as e:
        log.warning(f"Error limpiando cache: {e}")


def cache_info() -> Optional[dict]:
    """Retorna metadata del cache para mostrar en el sidebar."""
    try:
        _init_cache()
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT fetched_at, total FROM melonn_pedidos_cache WHERE id = 1"
            ).fetchone()
        if not row:
            return None
        fetched_at = datetime.fromisoformat(row["fetched_at"])
        age = (datetime.now() - fetched_at).total_seconds()
        return {
            "fetched_at": fetched_at,
            "age_s": age,
            "total": row["total"],
            "fresco": age <= _CACHE_TTL,
            "stale": age > _CACHE_TTL,
        }
    except Exception:
        return None


# ── HTTP helper ────────────────────────────────────────────────────────────────
def _get(path: str, params: dict = None) -> Optional[dict]:
    """GET con reintentos y backoff exponencial."""
    url = f"{_BASE_URL}/{path.lstrip('/')}"
    for intento in range(_MAX_RETRIES):
        try:
            r = requests.get(url, headers=_headers(), params=params, timeout=_TIMEOUT)

            # Rate limit — esperar y reintentar
            if r.status_code in (429, 503):
                wait = _RETRY_WAIT * (2 ** intento)
                log.warning(f"Rate limit HTTP {r.status_code} — esperando {wait}s...")
                time.sleep(wait)
                continue

            r.raise_for_status()
            data = r.json()

            # Detectar "Limit Exceeded" en el cuerpo (patrón de Melonn)
            if isinstance(data, dict) and data.get("message") == "Limit Exceeded":
                wait = _RETRY_WAIT * (2 ** intento)
                log.warning(f"Limit Exceeded en {path} — esperando {wait}s...")
                time.sleep(wait)
                continue

            return data

        except requests.HTTPError as e:
            status = e.response.status_code
            log.warning(f"HTTP {status} en {url} (intento {intento+1})")
            if status in (401, 403):
                log.error("API key inválido o sin permisos — verifica MELONN_API_KEY")
                return None   # no reintentar en auth errors
        except requests.RequestException as e:
            log.warning(f"Request error: {e} (intento {intento+1})")

        if intento < _MAX_RETRIES - 1:
            time.sleep(_RETRY_WAIT)

    log.error(f"Fallaron {_MAX_RETRIES} intentos para {path}")
    return None


# ── Normalización ──────────────────────────────────────────────────────────────
def _parsear_fecha(valor) -> Optional[date]:
    if not valor:
        return None
    if isinstance(valor, date) and not isinstance(valor, datetime):
        return valor
    if isinstance(valor, datetime):
        return valor.date()
    texto = str(valor).strip()
    try:
        return datetime.strptime(texto[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _es_contraentrega(valor) -> bool:
    if valor is None:
        return False
    try:
        return float(str(valor).replace(",", ".")) > 0
    except (ValueError, TypeError):
        return False


def _calcular_dias(fecha_despacho: Optional[date], fecha_entrega: Optional[date]) -> int:
    if not fecha_despacho:
        return 0
    fin = fecha_entrega if fecha_entrega else date.today()
    return max(0, (fin - fecha_despacho).days)


def _normalizar_pedido(raw: dict) -> Optional[dict]:
    """Convierte un item del listado Melonn al esquema interno de la app."""
    estado = str((raw.get("sell_order_state") or {}).get("name") or "")

    buyer  = raw.get("buyer") or {}
    nombre = str(buyer.get("full_name") or "")
    tel    = str(buyer.get("phone_number") or "")

    dest   = raw.get("shipping_info") or {}
    ciudad = str(dest.get("city") or "").upper().strip()
    region = str(dest.get("region") or "")

    metodo = str((raw.get("shipping_method") or {}).get("name") or "")

    items      = raw.get("line_items") or []
    first_item = items[0] if items else {}
    sku        = str(first_item.get("sku") or "")
    cantidad   = int(first_item.get("quantity") or 1)
    producto   = ", ".join(str(i.get("sku", "")) for i in items if i.get("sku"))

    fecha_creacion = _parsear_fecha(raw.get("creation_date"))
    fecha_despacho = _parsear_fecha(raw.get("dispatch_date")) or fecha_creacion
    fecha_entrega  = _parsear_fecha(raw.get("delivery_date"))
    fecha_promesa  = _parsear_fecha(raw.get("promise_date"))

    valor_cod = raw.get("payment_on_delivery_amount")
    tipo_recaudo = str(
        (raw.get("payment_on_delivery_type") or {}).get("name") or
        ("Contraentrega" if valor_cod else "Prepago")
    )

    return {
        "orden_melonn":       str(raw.get("internal_order_number") or raw.get("id") or ""),
        "orden_tienda":       str(raw.get("external_order_number") or "").lstrip("#"),
        "estado_melonn":      estado,
        "tienda":             "",
        "canal_venta":        str((raw.get("fulfillment_type") or {}).get("order_type") or "D2C"),
        "nombre_comprador":   nombre,
        "telefono_comprador": tel,
        "ciudad_destino":     ciudad,
        "region_destino":     region,
        "transportadora":     metodo,
        "link_guia":          str(raw.get("melonn_tracking_link") or ""),
        "fecha_despacho":     fecha_despacho,
        "fecha_entrega":      fecha_entrega,
        "fecha_promesa":      fecha_promesa,
        "fecha_creacion":     fecha_creacion,
        "sku":                sku,
        "producto":           producto,
        "variante":           "",
        "cantidad":           cantidad,
        "precio_unitario":    0.0,
        "valor_cod_raw":      str(valor_cod or 0),
        "tipo_recaudo":       tipo_recaudo,
        "es_contraentrega":   _es_contraentrega(valor_cod),
        "dias_en_transito":   _calcular_dias(fecha_despacho, fecha_entrega),
        "esta_en_transito":   estado in ESTADOS_EN_TRANSITO,
        "entregado":          estado in ESTADOS_RESUELTOS,
        "incidencia":         "NINGUNO",
        "promesa_vencida":    False,
    }


# ── Fetch desde API ────────────────────────────────────────────────────────────
def _fetch_de_api() -> tuple:
    """
    Descarga todos los pedidos activos desde la API.
    Solo usa el endpoint de listado — nunca fetches individuales.
    Retorna (pedidos_normalizados, omitidos_dict).
    """
    omitidos = {"resuelto": 0, "sin_datos": 0}
    todos    = []
    page     = 0

    while True:
        resp = _get("sell-orders", params={"per_page": _PAGE_SIZE, "page": page})
        if resp is None:
            log.error("API no disponible — abortando fetch")
            break

        items       = resp.get("data") or []
        meta        = resp.get("meta_data") or {}
        total_count = meta.get("total_count") or 0

        todos.extend(items)
        log.info(f"Página {page}: {len(items)} items (total_count={total_count}, acumulado={len(todos)})")

        if not items or (total_count > 0 and len(todos) >= total_count):
            break

        page += 1
        time.sleep(0.3)   # pausa mínima entre páginas

    pedidos = []
    for item in todos:
        estado = str((item.get("sell_order_state") or {}).get("name") or "")
        if estado in ESTADOS_RESUELTOS:
            omitidos["resuelto"] += 1
            continue
        p = _normalizar_pedido(item)
        if p:
            pedidos.append(p)
        else:
            omitidos["sin_datos"] += 1

    log.info(f"Fetch completado: {len(pedidos)} activos, {omitidos} omitidos")
    return pedidos, omitidos


# ── Punto de entrada principal ─────────────────────────────────────────────────
def obtener_pedidos_activos(dias: int = 30, forzar_refresh: bool = False) -> tuple:
    """
    Retorna (pedidos: list[dict], omitidos: dict, meta: dict).

    Estrategia anti-rate-limit:
    1. forzar_refresh=True  → limpia cache, intenta fetch; si falla usa datos stale
    2. Cache fresco (<4h)   → retorna directo desde SQLite (0 requests HTTP)
    3. Cache vencido        → intenta fetch; si falla retorna stale con advertencia
    4. Sin cache alguno     → intenta fetch; si falla retorna lista vacía
    """
    _VACIO = ([], {"resuelto": 0, "sin_datos": 0}, {"fuente": "sin_datos", "stale": False})

    if forzar_refresh:
        limpiar_cache()

    # Intentar leer cache fresco
    resultado = _leer_cache(ignorar_ttl=False)
    if resultado is not None:
        pedidos, fetched_at, fresco = resultado
        return pedidos, {"resuelto": 0, "sin_datos": 0}, {
            "fuente": "cache", "stale": False, "fetched_at": fetched_at
        }

    # Cache vencido o vacío → fetch desde API
    pedidos, omitidos = _fetch_de_api()

    if pedidos:
        _guardar_cache(pedidos)
        return pedidos, omitidos, {"fuente": "api_live", "stale": False}

    # Fetch fallido → intentar datos stale antes de retornar vacío
    stale = _leer_cache(ignorar_ttl=True)
    if stale is not None:
        pedidos_stale, fetched_at, _ = stale
        log.warning(f"API no disponible — usando datos stale de {fetched_at}")
        return pedidos_stale, {"resuelto": 0, "sin_datos": 0}, {
            "fuente": "stale", "stale": True, "fetched_at": fetched_at
        }

    return _VACIO


def estado() -> dict:
    info = cache_info()
    if info:
        ultima = info["fetched_at"].strftime("%d/%m/%Y %H:%M")
        age_min = int(info["age_s"] / 60)
        prox_min = max(0, int((_CACHE_TTL - info["age_s"]) / 60))
    else:
        ultima    = None
        age_min   = None
        prox_min  = 0
    return {
        "credenciales_ok": credenciales_ok(),
        "ultima_sync":     ultima,
        "age_min":         age_min,
        "prox_refresh_min": prox_min,
        "intervalo_horas": _CACHE_TTL // 3600 or f"{_CACHE_TTL//60}min",
        "desactualizado":  info is None or not info["fresco"],
    }
