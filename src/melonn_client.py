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
_PAGE_SIZE  = 50
_MAX_PAGES  = 2      # máximo 2 requests por sync (100 pedidos) — cuida la cuota
_CACHE_TTL  = 14400  # 4 horas

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
                total        INTEGER NOT NULL DEFAULT 0,
                fuente       TEXT DEFAULT 'api_live'
            )
        """)
        # Migración: agrega columna fuente si la tabla ya existía sin ella
        try:
            c.execute("ALTER TABLE melonn_pedidos_cache ADD COLUMN fuente TEXT DEFAULT 'api_live'")
        except Exception:
            pass  # columna ya existe — normal
        c.commit()


def _cache_leer(ignorar_ttl: bool = False) -> Optional[tuple]:
    """Retorna (pedidos, fetched_at, fresco, fuente) o None si no hay datos."""
    try:
        _init_tabla()
        with _conn() as c:
            row = c.execute(
                "SELECT fetched_at, pedidos_json, fuente FROM melonn_pedidos_cache WHERE id=1"
            ).fetchone()
        if not row:
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
    try:
        _init_tabla()
        with _conn() as c:
            c.execute("""
                INSERT OR REPLACE INTO melonn_pedidos_cache (id, fetched_at, pedidos_json, total, fuente)
                VALUES (1, ?, ?, ?, ?)
            """, (datetime.now().isoformat(), json.dumps(pedidos, default=str), len(pedidos), fuente))
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
                "SELECT fetched_at, total, fuente FROM melonn_pedidos_cache WHERE id=1"
            ).fetchone()
        if not row:
            return None
        fetched_at = datetime.fromisoformat(row["fetched_at"])
        age    = (datetime.now() - fetched_at).total_seconds()
        fuente = row["fuente"] if row["fuente"] else "api_live"
        return {
            "fetched_at": fetched_at,
            "age_s":      age,
            "total":      row["total"],
            "fresco":     age <= _CACHE_TTL,
            "stale":      age > _CACHE_TTL,
            "fuente":     fuente,
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
    """Trae hasta _MAX_PAGES páginas de pedidos para no agotar la cuota de la API."""
    pedidos, page = [], 0
    while page < _MAX_PAGES:
        resp = _get("sell-orders", params={"per_page": _PAGE_SIZE, "page": page})
        if resp is None:
            break
        items       = resp.get("data") or []
        meta        = resp.get("meta_data") or {}
        total_count = meta.get("total_count") or 0
        pedidos.extend(items)
        if not items or len(pedidos) >= total_count:
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
            return pedidos, omitidos, {"fuente": fuente_stale, "stale": True, "fetched_at": fetched_at}

        pedidos_boot = _bootstrap_json()
        if pedidos_boot:
            _cache_guardar(pedidos_boot, fuente="csv_bootstrap")
            return pedidos_boot, omitidos, {
                "fuente": "csv_bootstrap", "stale": True, "fetched_at": datetime.now()
            }
        return [], omitidos, {"fuente": "sin_datos", "stale": False}

    # — Carga normal: SQLite → bootstrap (sin tocar la API) —

    # 1. SQLite fresco
    hit = _cache_leer(ignorar_ttl=False)
    if hit:
        pedidos, fetched_at, _, fuente_hit = hit
        return pedidos, omitidos, {"fuente": fuente_hit, "stale": False, "fetched_at": fetched_at}

    # 2. SQLite stale
    stale = _cache_leer(ignorar_ttl=True)
    if stale:
        pedidos, fetched_at, _, fuente_stale = stale
        return pedidos, omitidos, {"fuente": fuente_stale, "stale": True, "fetched_at": fetched_at}

    # 3. JSON bootstrap → guarda en SQLite para próximas cargas
    pedidos_boot = _bootstrap_json()
    if pedidos_boot:
        _cache_guardar(pedidos_boot, fuente="csv_bootstrap")
        return pedidos_boot, omitidos, {
            "fuente": "csv_bootstrap", "stale": True, "fetched_at": datetime.now()
        }

    return [], omitidos, {"fuente": "sin_datos", "stale": False}


def estado() -> dict:
    info = cache_info()
    return {
        "credenciales_ok": credenciales_ok(),
        "ultima_sync":     info["fetched_at"].strftime("%d/%m/%Y %H:%M") if info else None,
        "desactualizado":  info is None or info.get("stale", False),
    }
