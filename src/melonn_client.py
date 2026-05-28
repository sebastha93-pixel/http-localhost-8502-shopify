"""
Cliente Melonn API — MALE'DENIM
Reemplaza la carga manual de CSV por datos en tiempo real.

Endpoint:  GET https://api.melonn.com/prod/api/sell-orders
Auth:      x-api-key header
"""

import os
import time
import threading
import logging
from datetime import date, datetime, timedelta
from typing import Optional

import requests

log = logging.getLogger(__name__)

# ── Configuración ──────────────────────────────────────────────────────────────
_BASE_URL      = "https://api.melonn.com/prod/api"
_TIMEOUT       = 30          # segundos por request
_MAX_RETRIES   = 3
_RETRY_WAIT    = 2           # segundos entre reintentos
_INTERVALO_H   = 2           # horas entre auto-syncs
_PAGE_SIZE     = 100         # pedidos por página (ajustar según API)

# ── Estado global ──────────────────────────────────────────────────────────────
_lock          = threading.Lock()
_ultima_sync:  Optional[datetime] = None
_sync_en_curso = False

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
    """Lee el API key desde Streamlit Secrets o variable de entorno."""
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


# ── HTTP helper ────────────────────────────────────────────────────────────────
def _get(path: str, params: dict = None) -> dict | list | None:
    """GET con reintentos. Retorna el JSON o None si falla."""
    url = f"{_BASE_URL}/{path.lstrip('/')}"
    for intento in range(_MAX_RETRIES):
        try:
            r = requests.get(url, headers=_headers(), params=params, timeout=_TIMEOUT)
            r.raise_for_status()
            return r.json()
        except requests.HTTPError as e:
            log.warning(f"Melonn HTTP {e.response.status_code} en {url} (intento {intento+1})")
            if e.response.status_code in (401, 403):
                log.error("API key inválido o sin permisos — verifica MELONN_API_KEY")
                return None          # no reintentar en errores de auth
        except requests.RequestException as e:
            log.warning(f"Melonn request error: {e} (intento {intento+1})")
        if intento < _MAX_RETRIES - 1:
            time.sleep(_RETRY_WAIT * (intento + 1))
    return None


# ── Normalización de campos ────────────────────────────────────────────────────
def _parsear_fecha(valor) -> Optional[date]:
    """Convierte string ISO o timestamp a date. Retorna None si vacío."""
    if not valor:
        return None
    if isinstance(valor, date) and not isinstance(valor, datetime):
        return valor
    if isinstance(valor, datetime):
        return valor.date()
    texto = str(valor).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(texto[:len(fmt.replace('%', 'XX').replace('X', '00'))], fmt).date()
        except ValueError:
            pass
    # Fallback: tomar los primeros 10 chars
    try:
        return datetime.strptime(texto[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _es_contraentrega(valor) -> bool:
    """True si el valor COD es un número positivo."""
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
    """
    Convierte un pedido JSON de la API Melonn al esquema interno de ingest.py.

    Estructura confirmada (2026-05-28):
    {
      "id": 1732571663793215,
      "internal_order_number": "M...",
      "external_order_number": "SHOPIFY-XXX",
      "external_order_id": null,
      "creation_date": "2024-11-25T21:54:25.000Z",
      "melonn_tracking_link": "https://...",
      "payment_on_delivery_amount": null | 59900,
      "is_b2b": false,
      "sell_order_state": {"id": 2, "name": "All items reserved..."},
      "buyer": {"full_name": "...", "phone_number": "+57...", "email": "..."},
      "line_items": [{"quantity": 1, "sku": "S0001"}],
      "shipping_method": {"code": "MEL-15", "name": "Estándar..."},
      "warehouse": {"city": "Sabaneta", "region": "ANTIOQUIA", ...},
      -- campos que aparecen en órdenes despachadas (pendiente confirmar nombres):
      "delivery_address": {"city": "...", "region": "...", ...},
      "dispatch_date": "...",
      "promise_date": "...",
      "delivery_date": "...",
      "carrier": {"name": "..."}
    }
    """
    # ── Campos base (confirmados) ──────────────────────────────────────────────
    estado = str((raw.get("sell_order_state") or {}).get("name") or "")

    buyer  = raw.get("buyer") or {}
    nombre = str(buyer.get("full_name") or "")
    tel    = str(buyer.get("phone_number") or "")

    # Primer line_item para SKU / cantidad
    items      = raw.get("line_items") or []
    first_item = items[0] if items else {}
    sku        = str(first_item.get("sku") or "")
    cantidad   = int(first_item.get("quantity") or 1)
    # Producto: concatenar todos los SKUs si hay varios
    producto   = ", ".join(str(i.get("sku", "")) for i in items if i.get("sku"))

    fecha_creacion = _parsear_fecha(raw.get("creation_date"))
    valor_cod      = raw.get("payment_on_delivery_amount")

    # ── Campos de despacho (aparecen cuando el pedido está enviado) ────────────
    # Intentar múltiples nombres posibles hasta confirmar con Melonn
    def _f(*keys):
        for k in keys:
            v = raw.get(k)
            if v is not None:
                return v
        return None

    fecha_despacho = _parsear_fecha(
        _f("dispatch_date", "shipping_date", "shipped_date", "dispatched_at"))
    fecha_entrega  = _parsear_fecha(
        _f("delivery_date", "delivered_date", "actual_delivery_date"))
    fecha_promesa  = _parsear_fecha(
        _f("promise_date", "promised_delivery_date", "estimated_delivery_date",
           "max_delivery_date"))

    # ── Destino (aparece cuando el pedido está creado con dirección real) ──────
    dest   = (raw.get("delivery_address") or raw.get("destination")
              or raw.get("shipping_address") or raw.get("buyer_address") or {})
    ciudad = str(dest.get("city") or dest.get("ciudad") or "").upper().strip()
    region = str(dest.get("region") or dest.get("state") or "")

    # ── Transportadora ─────────────────────────────────────────────────────────
    carrier_obj  = raw.get("carrier") or raw.get("courier") or {}
    transportadora = str(
        carrier_obj.get("name") or carrier_obj.get("carrier_name") or
        raw.get("carrier_name") or raw.get("transportadora") or
        (raw.get("shipping_method") or {}).get("name") or ""
    )

    # Sin fecha de despacho = aún en bodega, no es logística activa
    if not fecha_despacho:
        return None

    p = {
        # Identificadores
        "orden_melonn":       str(raw.get("internal_order_number") or raw.get("id") or ""),
        "orden_tienda":       str(raw.get("external_order_number") or raw.get("external_order_id") or ""),
        "estado_melonn":      estado,
        "tienda":             "",
        "canal_venta":        "B2B" if raw.get("is_b2b") else "D2C",

        # Comprador
        "nombre_comprador":   nombre,
        "telefono_comprador": tel,
        "ciudad_destino":     ciudad,
        "region_destino":     region,

        # Logística
        "transportadora":     transportadora,
        "link_guia":          str(raw.get("melonn_tracking_link") or ""),

        # Fechas
        "fecha_despacho":     fecha_despacho,
        "fecha_entrega":      fecha_entrega,
        "fecha_promesa":      fecha_promesa,
        "fecha_creacion":     fecha_creacion,

        # Producto
        "sku":                sku,
        "producto":           producto,
        "variante":           str(first_item.get("variant") or first_item.get("variante") or ""),
        "cantidad":           cantidad,
        "precio_unitario":    float(
            str(first_item.get("unit_price") or first_item.get("price") or 0)
            .replace(",", ".")),

        # COD
        "valor_cod_raw":      str(valor_cod or 0),
        "tipo_recaudo":       "contraentrega" if valor_cod else "prepago",

        # Calculados
        "es_contraentrega":   _es_contraentrega(valor_cod),
        "dias_en_transito":   _calcular_dias(fecha_despacho, fecha_entrega),
        "esta_en_transito":   estado in ESTADOS_EN_TRANSITO,
        "entregado":          estado in ESTADOS_RESUELTOS,
        "incidencia":         "NINGUNO",
    }

    # Promesa vencida
    if p["fecha_promesa"] and not p["entregado"]:
        p["promesa_vencida"] = date.today() > p["fecha_promesa"]
    else:
        p["promesa_vencida"] = False

    return p


# ── Fetch de pedidos ───────────────────────────────────────────────────────────
def obtener_pedido(order_id: str) -> Optional[dict]:
    """Obtiene un pedido individual. Retorna dict normalizado o None."""
    raw = _get(f"sell-orders/{order_id}")
    if raw is None:
        return None
    return _normalizar_pedido(raw)


def obtener_pedidos_activos(dias: int = 30) -> tuple[list, dict]:
    """
    Descarga todos los pedidos activos de los últimos `dias` días.
    Retorna (lista_pedidos_normalizados, dict_omitidos).

    Maneja paginación automáticamente.
    """
    pedidos  = []
    omitidos = {"resuelto": 0, "sin_despacho": 0, "error_parse": 0}

    fecha_desde = (date.today() - timedelta(days=dias)).isoformat()

    page   = 1
    total  = None

    while True:
        params = {
            "page":      page,
            "pageSize":  _PAGE_SIZE,
            "limit":     _PAGE_SIZE,    # algunos APIs usan limit
            "from":      fecha_desde,
            "dateFrom":  fecha_desde,   # variante camelCase
            "status":    "active",      # solo activos (ajustar si la API no lo soporta)
        }

        data = _get("sell-orders", params=params)
        if data is None:
            log.error("Error obteniendo sell-orders — verifica el API key")
            break

        # Normalizar respuesta: puede ser lista directa o paginada {data:[...], total:N}
        if isinstance(data, list):
            items = data
            total = len(data)
        elif isinstance(data, dict):
            items = (data.get("data") or data.get("orders") or
                     data.get("sellOrders") or data.get("items") or [])
            total = data.get("total") or data.get("totalItems") or len(items)
        else:
            log.error(f"Respuesta inesperada de sell-orders: {type(data)}")
            break

        for raw in items:
            estado = str(raw.get("orderStatus") or raw.get("order_status") or
                         raw.get("status") or raw.get("estado_orden") or "")

            if estado in ESTADOS_RESUELTOS:
                omitidos["resuelto"] += 1
                continue

            p = _normalizar_pedido(raw)
            if p is None:
                omitidos["sin_despacho"] += 1
                continue

            pedidos.append(p)

        log.info(f"Página {page}: {len(items)} pedidos, acumulado {len(pedidos)}")

        # Cortar si no hay más páginas
        if len(items) < _PAGE_SIZE or (total and len(pedidos) >= total):
            break
        page += 1

    return pedidos, omitidos


# ── Auto-sync (igual patrón que shopify_scheduler) ─────────────────────────────
def datos_desactualizados() -> bool:
    with _lock:
        if _ultima_sync is None:
            return True
        return (datetime.now() - _ultima_sync).total_seconds() / 3600 >= _INTERVALO_H


def sincronizar_si_necesario(dias: int = 30) -> tuple[bool, str]:
    """
    Sync-on-load: llama esto al inicio de la página de Logística.
    Retorna (ok, mensaje).
    """
    global _sync_en_curso, _ultima_sync

    if not credenciales_ok():
        return False, "MELONN_API_KEY no configurado"

    if not datos_desactualizados():
        return True, "Datos actualizados"

    with _lock:
        if _sync_en_curso:
            return False, "Sync en curso"
        _sync_en_curso = True

    try:
        pedidos, omitidos = obtener_pedidos_activos(dias=dias)
        if not pedidos:
            return False, "Sin pedidos activos o error de API"

        with _lock:
            _ultima_sync = datetime.now()

        return True, f"{len(pedidos)} pedidos sincronizados"
    except Exception as e:
        log.exception("Error en sync Melonn")
        return False, str(e)
    finally:
        with _lock:
            _sync_en_curso = False


def estado() -> dict:
    """Estado actual del cliente para mostrar en el sidebar."""
    return {
        "credenciales_ok": credenciales_ok(),
        "ultima_sync":     _ultima_sync.strftime("%d/%m/%Y %H:%M") if _ultima_sync else None,
        "desactualizado":  datos_desactualizados(),
        "intervalo_horas": _INTERVALO_H,
    }
