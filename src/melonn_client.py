"""
Cliente Melonn API — MALE'DENIM

Estrategia de caché (simple y robusta):
  1. SQLite local  → si hay datos frescos (<4h), retorna sin tocar la API
  2. Melonn API    → si el caché venció o se forzó refresh
  3. SQLite stale  → si la API falla, usa datos viejos del disco
  4. JSON bootstrap→ si no hay nada en disco, carga datos pre-generados del repo
"""

import json
import logging
import sqlite3
import time
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import requests

log = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────
_BASE_URL  = "https://api.orbita.melonn.com"
_TIMEOUT   = 20
_PAGE_SIZE = 50
_CACHE_TTL = 14400   # 4 horas

_DB_PATH        = Path(__file__).parent.parent / "data" / "db" / "maledenim.db"
_JSON_BOOTSTRAP = Path(__file__).parent.parent / "data" / "logistica" / "bootstrap.json"

# ── Estados ────────────────────────────────────────────────────────────────────
ESTADOS_EN_TRANSITO = {
    "Shipped - in transit", "Delivery not posible", "Packed",
    "Packed - on hold", "Prepared for dispatch",
    "All items reserved - ready for fulfillment",
    "All items reserved - fulfillment on hold - ext. conditionals",
    "on stand by - not able to fulfil - no stock",
}
ESTADOS_RESUELTOS = {"Delivered to buyer", "Picked-up by buyer", "Canceled"}


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
                total        INTEGER NOT NULL DEFAULT 0
            )
        """)
        c.commit()


def _cache_leer(ignorar_ttl: bool = False) -> Optional[tuple]:
    """Retorna (pedidos, fetched_at, fresco) o None si no hay datos."""
    try:
        _init_tabla()
        with _conn() as c:
            row = c.execute(
                "SELECT fetched_at, pedidos_json FROM melonn_pedidos_cache WHERE id=1"
            ).fetchone()
        if not row:
            return None
        fetched_at = datetime.fromisoformat(row["fetched_at"])
        age   = (datetime.now() - fetched_at).total_seconds()
        fresco = age <= _CACHE_TTL
        if not fresco and not ignorar_ttl:
            return None
        pedidos = json.loads(row["pedidos_json"])
        return pedidos, fetched_at, fresco
    except Exception as e:
        log.warning(f"Error leyendo SQLite cache: {e}")
        return None


def _cache_guardar(pedidos: list):
    try:
        _init_tabla()
        with _conn() as c:
            c.execute("""
                INSERT OR REPLACE INTO melonn_pedidos_cache (id, fetched_at, pedidos_json, total)
                VALUES (1, ?, ?, ?)
            """, (datetime.now().isoformat(), json.dumps(pedidos, default=str), len(pedidos)))
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
                "SELECT fetched_at, total FROM melonn_pedidos_cache WHERE id=1"
            ).fetchone()
        if not row:
            return None
        fetched_at = datetime.fromisoformat(row["fetched_at"])
        age = (datetime.now() - fetched_at).total_seconds()
        return {
            "fetched_at": fetched_at,
            "age_s":      age,
            "total":      row["total"],
            "fresco":     age <= _CACHE_TTL,
            "stale":      age > _CACHE_TTL,
        }
    except Exception:
        return None


# ── Melonn API ─────────────────────────────────────────────────────────────────
def _get(path: str, params: dict = None) -> Optional[dict]:
    url = f"{_BASE_URL}/{path.lstrip('/')}"
    try:
        r = requests.get(
            url,
            headers={"x-api-key": _api_key(), "Accept": "application/json"},
            params=params,
            timeout=_TIMEOUT,
        )
        if r.status_code == 429 or r.status_code == 503:
            log.warning(f"Rate limit {r.status_code}")
            return None
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict) and data.get("message") == "Limit Exceeded":
            log.warning("Limit Exceeded")
            return None
        return data
    except requests.HTTPError as e:
        log.warning(f"HTTP {e.response.status_code}")
        return None
    except Exception as e:
        log.warning(f"Request error: {e}")
        return None


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


def _normalizar(raw: dict) -> dict:
    estado    = str((raw.get("sell_order_state") or {}).get("name") or "")
    buyer     = raw.get("buyer") or {}
    dest      = raw.get("shipping_info") or {}
    items     = raw.get("line_items") or []
    fi        = items[0] if items else {}
    metodo    = str((raw.get("shipping_method") or {}).get("name") or "")
    valor_cod = raw.get("payment_on_delivery_amount")

    fd = _parsear_fecha(raw.get("dispatch_date")) or _parsear_fecha(raw.get("creation_date"))
    fe = _parsear_fecha(raw.get("delivery_date"))

    return {
        "orden_melonn":       str(raw.get("internal_order_number") or raw.get("id") or ""),
        "orden_tienda":       str(raw.get("external_order_number") or "").lstrip("#"),
        "estado_melonn":      estado,
        "tienda":             "",
        "canal_venta":        str((raw.get("fulfillment_type") or {}).get("order_type") or "D2C"),
        "nombre_comprador":   str(buyer.get("full_name") or ""),
        "telefono_comprador": str(buyer.get("phone_number") or ""),
        "ciudad_destino":     str(dest.get("city") or "").upper().strip(),
        "region_destino":     str(dest.get("region") or ""),
        "transportadora":     metodo,
        "link_guia":          str(raw.get("melonn_tracking_link") or ""),
        "fecha_despacho":     fd,
        "fecha_entrega":      fe,
        "fecha_promesa":      _parsear_fecha(raw.get("promise_date")),
        "fecha_creacion":     _parsear_fecha(raw.get("creation_date")),
        "sku":                str(fi.get("sku") or ""),
        "producto":           ", ".join(str(i.get("sku","")) for i in items if i.get("sku")),
        "variante":           "",
        "cantidad":           int(fi.get("quantity") or 1),
        "precio_unitario":    0.0,
        "valor_cod_raw":      str(valor_cod or 0),
        "tipo_recaudo":       "Contraentrega" if valor_cod else "Prepago",
        "es_contraentrega":   bool(valor_cod and float(str(valor_cod).replace(",",".") or 0) > 0),
        "dias_en_transito":   max(0, ((fe or date.today()) - fd).days) if fd else 0,
        "esta_en_transito":   estado in ESTADOS_EN_TRANSITO,
        "entregado":          estado in ESTADOS_RESUELTOS,
        "incidencia":         "NINGUNO",
        "promesa_vencida":    False,
    }


def _fetch_api() -> list:
    pedidos, page = [], 0
    while True:
        resp = _get("sell-orders", params={"per_page": _PAGE_SIZE, "page": page})
        if resp is None:
            break
        items       = resp.get("data") or []
        meta        = resp.get("meta_data") or {}
        total_count = meta.get("total_count") or 0
        pedidos.extend(items)
        if not items or (total_count > 0 and len(pedidos) >= total_count):
            break
        page += 1
        time.sleep(0.3)

    activos = []
    for item in pedidos:
        if str((item.get("sell_order_state") or {}).get("name") or "") in ESTADOS_RESUELTOS:
            continue
        try:
            activos.append(_normalizar(item))
        except Exception:
            pass
    return activos


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

    Orden:
    1. SQLite fresco   → instantáneo
    2. API Melonn      → si cache vencido o forzar_refresh
    3. SQLite stale    → si API falla pero hay datos en disco
    4. JSON bootstrap  → si no hay nada en disco
    """
    omitidos = {"resuelto": 0, "sin_datos": 0}

    if forzar_refresh:
        limpiar_cache()

    # 1 — SQLite fresco
    if not forzar_refresh:
        hit = _cache_leer(ignorar_ttl=False)
        if hit:
            pedidos, fetched_at, _ = hit
            return pedidos, omitidos, {"fuente": "cache", "stale": False, "fetched_at": fetched_at}

    # 2 — API Melonn
    pedidos_api = _fetch_api()
    if pedidos_api:
        _cache_guardar(pedidos_api)
        return pedidos_api, omitidos, {"fuente": "api_live", "stale": False, "fetched_at": datetime.now()}

    # 3 — SQLite stale (datos viejos pero algo)
    stale = _cache_leer(ignorar_ttl=True)
    if stale:
        pedidos, fetched_at, _ = stale
        return pedidos, omitidos, {"fuente": "stale", "stale": True, "fetched_at": fetched_at}

    # 4 — JSON bootstrap (datos del repo, siempre disponibles)
    pedidos_boot = _bootstrap_json()
    if pedidos_boot:
        _cache_guardar(pedidos_boot)   # guarda en SQLite para la próxima carga
        return pedidos_boot, omitidos, {"fuente": "csv_bootstrap", "stale": True, "fetched_at": datetime.now()}

    return [], omitidos, {"fuente": "sin_datos", "stale": False}


def estado() -> dict:
    info = cache_info()
    return {
        "credenciales_ok": credenciales_ok(),
        "ultima_sync":     info["fetched_at"].strftime("%d/%m/%Y %H:%M") if info else None,
        "desactualizado":  info is None or info.get("stale", False),
    }
