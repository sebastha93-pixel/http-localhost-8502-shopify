"""
Cliente Melonn API — MALE'DENIM

Estrategia de caché en 3 capas (anti-rate-limit + anti-cold-start):
  1. st.session_state    → instantáneo, dura toda la sesión del usuario
  2. Supabase            → persistente en la nube, sobrevive reinicios de Streamlit Cloud
  3. Melonn API          → solo cuando el caché de Supabase tiene >4h o el usuario fuerza refresh

Nunca hace fetches individuales por orden — solo el endpoint de listado.
"""

import json
import logging
import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import requests

# Ruta al CSV de bootstrap (solo se usa si Supabase está vacío y API está caída)
_CSV_BOOTSTRAP = Path(__file__).parent.parent / "data" / "logistica" / "raw" / "melonn_2026-05-12.csv"

log = logging.getLogger(__name__)

# ── Configuración ──────────────────────────────────────────────────────────────
_BASE_URL    = "https://api.orbita.melonn.com"
_TIMEOUT     = 30
_MAX_RETRIES = 3
_RETRY_WAIT  = 5           # segundos base entre reintentos
_PAGE_SIZE   = 50          # conservador — evita límites de la API
_CACHE_TTL   = 14400       # 4 horas en segundos

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


# ── Capa 1: session_state (instantánea, dura la sesión) ───────────────────────
_SESSION_KEY = "_melonn_cache"

def _session_leer() -> Optional[tuple]:
    """Retorna (pedidos, fetched_at) desde session_state si está fresco."""
    try:
        import streamlit as st
        data = st.session_state.get(_SESSION_KEY)
        if not data:
            return None
        fetched_at = data["fetched_at"]
        age = (datetime.now() - fetched_at).total_seconds()
        if age > _CACHE_TTL:
            return None
        return data["pedidos"], fetched_at
    except Exception:
        return None


def _session_escribir(pedidos: list, fetched_at: Optional[datetime] = None):
    try:
        import streamlit as st
        st.session_state[_SESSION_KEY] = {
            "pedidos":    pedidos,
            "fetched_at": fetched_at or datetime.now(),
        }
    except Exception:
        pass


def _session_limpiar():
    try:
        import streamlit as st
        st.session_state.pop(_SESSION_KEY, None)
    except Exception:
        pass


# ── Capa 2: Supabase (persistente en la nube) ──────────────────────────────────
def _supabase_client():
    try:
        from supabase import create_client
        import streamlit as st
        url = st.secrets.get("SUPABASE_URL") or os.getenv("SUPABASE_URL", "")
        key = st.secrets.get("SUPABASE_KEY") or os.getenv("SUPABASE_KEY", "")
        if not url or not key:
            return None
        return create_client(url, key)
    except Exception:
        return None


def _supabase_leer() -> Optional[tuple]:
    """
    Retorna (pedidos, fetched_at, fresco) desde Supabase.
    Retorna stale si hay datos aunque estén vencidos.
    """
    try:
        sb = _supabase_client()
        if sb is None:
            return None
        res = sb.table("melonn_cache").select("fetched_at,pedidos_json,total").eq("id", 1).execute()
        rows = res.data if hasattr(res, "data") else []
        if not rows:
            return None
        row = rows[0]
        fetched_at = datetime.fromisoformat(row["fetched_at"].replace("Z", "+00:00")).replace(tzinfo=None)
        age = (datetime.utcnow() - fetched_at).total_seconds()
        fresco = age <= _CACHE_TTL
        pedidos = json.loads(row["pedidos_json"])
        log.info(f"Supabase cache {'fresco' if fresco else 'stale'}: {len(pedidos)} pedidos ({age/3600:.1f}h)")
        return pedidos, fetched_at, fresco
    except Exception as e:
        log.warning(f"Error leyendo Supabase cache: {e}")
        return None


def _supabase_escribir(pedidos: list):
    """Guarda/actualiza el caché en Supabase (upsert en id=1)."""
    try:
        sb = _supabase_client()
        if sb is None:
            return
        payload = {
            "id":           1,
            "fetched_at":   datetime.utcnow().isoformat(),
            "pedidos_json": json.dumps(pedidos, default=str),
            "total":        len(pedidos),
        }
        sb.table("melonn_cache").upsert(payload).execute()
        log.info(f"Supabase cache guardado: {len(pedidos)} pedidos")
    except Exception as e:
        log.warning(f"Error guardando Supabase cache: {e}")


def _supabase_limpiar():
    try:
        sb = _supabase_client()
        if sb is None:
            return
        # Marcar como muy viejo para forzar re-fetch
        sb.table("melonn_cache").update({"fetched_at": "2000-01-01T00:00:00"}).eq("id", 1).execute()
    except Exception as e:
        log.warning(f"Error limpiando Supabase cache: {e}")


# ── Capa 3: Melonn API ─────────────────────────────────────────────────────────
def _get(path: str, params: dict = None) -> Optional[dict]:
    """GET sin reintentos en rate limit — falla rápido para llegar al fallback de caché."""
    url = f"{_BASE_URL}/{path.lstrip('/')}"
    try:
        r = requests.get(url, headers=_headers(), params=params, timeout=_TIMEOUT)

        # Rate limit → falla inmediato (no esperar — el fallback de Supabase/CSV es mejor)
        if r.status_code in (429, 503):
            log.warning(f"Rate limit {r.status_code} — usando caché fallback")
            return None

        r.raise_for_status()
        data = r.json()

        if isinstance(data, dict) and data.get("message") == "Limit Exceeded":
            log.warning("Limit Exceeded — usando caché fallback")
            return None

        return data

    except requests.HTTPError as e:
        status = e.response.status_code
        if status in (401, 403):
            log.error("API key inválido — verifica MELONN_API_KEY")
        else:
            log.warning(f"HTTP {status} en {url}")
        return None
    except requests.RequestException as e:
        log.warning(f"Request error: {e}")
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
        log.info(f"Página {page}: {len(items)} items (total={total_count}, acumulado={len(todos)})")

        if not items or (total_count > 0 and len(todos) >= total_count):
            break

        page += 1
        time.sleep(0.3)

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

    Flujo de 3 capas:
    1. session_state fresco → retorno instantáneo (0 red, 0 DB)
    2. Supabase fresco       → carga desde nube, guarda en session
    3. API Melonn            → solo si caché vencido o forzar_refresh
       - Si API falla        → retorna datos stale de Supabase con advertencia
    """
    _EMPTY_META = {"fuente": "sin_datos", "stale": False}

    if forzar_refresh:
        _session_limpiar()
        _supabase_limpiar()

    # ── Capa 1: session_state ──────────────────────────────────────────────────
    if not forzar_refresh:
        hit = _session_leer()
        if hit:
            pedidos, fetched_at = hit
            return pedidos, {"resuelto": 0, "sin_datos": 0}, {
                "fuente": "session", "stale": False, "fetched_at": fetched_at
            }

    # ── Capa 2: Supabase ───────────────────────────────────────────────────────
    if not forzar_refresh:
        sb_result = _supabase_leer()
        if sb_result:
            pedidos, fetched_at, fresco = sb_result
            if fresco:
                _session_escribir(pedidos, fetched_at)
                return pedidos, {"resuelto": 0, "sin_datos": 0}, {
                    "fuente": "supabase", "stale": False, "fetched_at": fetched_at
                }
            # Supabase tiene datos pero están vencidos → intentar API primero
            log.info("Supabase cache vencido — intentando refresh de API")

    # ── Capa 3: API Melonn ─────────────────────────────────────────────────────
    try:
        pedidos_api, omitidos = _fetch_de_api()
    except Exception as e:
        log.error(f"_fetch_de_api excepcion: {e}")
        pedidos_api, omitidos = [], {}

    if pedidos_api:
        _supabase_escribir(pedidos_api)
        _session_escribir(pedidos_api)
        return pedidos_api, omitidos, {
            "fuente": "api_live", "stale": False, "fetched_at": datetime.now()
        }

    log.warning("API Melonn no disponible — intentando fallbacks")

    # Capa 3b: Supabase stale (si el cache expiró pero hay datos)
    try:
        sb_stale = _supabase_leer()
    except Exception:
        sb_stale = None

    if sb_stale:
        pedidos_stale, fetched_at, _ = sb_stale
        _session_escribir(pedidos_stale, fetched_at)
        return pedidos_stale, {"resuelto": 0, "sin_datos": 0}, {
            "fuente": "stale", "stale": True, "fetched_at": fetched_at
        }

    # Capa 4: CSV bootstrap — último recurso cuando API y Supabase fallan
    try:
        pedidos_csv = _seed_desde_csv()
    except Exception as e:
        log.error(f"CSV bootstrap excepcion: {e}")
        pedidos_csv = []

    if pedidos_csv:
        _supabase_escribir(pedidos_csv)
        _session_escribir(pedidos_csv)
        log.info(f"Bootstrap CSV: {len(pedidos_csv)} pedidos cargados y guardados en Supabase")
        return pedidos_csv, {"resuelto": 0, "sin_datos": 0}, {
            "fuente": "csv_bootstrap", "stale": True, "fetched_at": datetime.now(),
        }

    return [], {"resuelto": 0, "sin_datos": 0}, _EMPTY_META


def _seed_desde_csv() -> list:
    """
    Lee el CSV de bootstrap y retorna pedidos normalizados.
    Solo se usa cuando Supabase está vacío Y la API no responde.
    """
    if not _CSV_BOOTSTRAP.exists():
        return []
    try:
        from ingest import leer_csv_melonn
        pedidos, _ = leer_csv_melonn(str(_CSV_BOOTSTRAP), solo_activos=True)
        if pedidos:
            log.info(f"Bootstrap desde CSV: {len(pedidos)} pedidos de {_CSV_BOOTSTRAP.name}")
        return pedidos
    except Exception as e:
        log.warning(f"Error leyendo CSV bootstrap: {e}")
        return []


def limpiar_cache():
    """Fuerza re-fetch en la próxima llamada."""
    _session_limpiar()
    _supabase_limpiar()
    log.info("Cache Melonn limpiado — próxima carga hará re-fetch")


def cache_info() -> Optional[dict]:
    """Retorna metadata del caché para mostrar en el sidebar."""
    # Primero session
    hit = _session_leer()
    if hit:
        pedidos, fetched_at = hit
        age = (datetime.now() - fetched_at).total_seconds()
        return {
            "fetched_at": fetched_at,
            "age_s": age,
            "total": len(pedidos),
            "fresco": True,
            "stale": False,
            "fuente": "session",
        }
    # Luego Supabase
    sb_result = _supabase_leer()
    if sb_result:
        pedidos, fetched_at, fresco = sb_result
        age = (datetime.utcnow() - fetched_at).total_seconds()
        return {
            "fetched_at": fetched_at,
            "age_s": age,
            "total": len(pedidos),
            "fresco": fresco,
            "stale": not fresco,
            "fuente": "supabase",
        }
    return None


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
        "credenciales_ok":  credenciales_ok(),
        "ultima_sync":      ultima,
        "age_min":          age_min,
        "prox_refresh_min": prox_min,
        "desactualizado":   info is None or info.get("stale", False),
    }
