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
    Convierte un pedido JSON de la API al esquema interno de ingest.py.
    Los nombres de campo se actualizan cuando Melonn confirme el contrato.
    """
    # ── Mapeo flexible: acepta camelCase y snake_case ──────────────────────────
    def g(*keys):
        """Busca el primer key que exista en raw."""
        for k in keys:
            if raw.get(k) is not None:
                return raw[k]
        return None

    estado = str(g("orderStatus", "order_status", "estado_orden", "status") or "")

    fecha_despacho = _parsear_fecha(
        g("shippingDate", "shipping_date", "fecha_envio", "fecha_despacho_raw"))
    fecha_entrega  = _parsear_fecha(
        g("deliveryDate", "delivery_date", "fecha_entrega", "fecha_entrega_raw"))
    fecha_promesa  = _parsear_fecha(
        g("promisedDeliveryDate", "promised_delivery_date", "fecha_promesa", "fecha_promesa_raw"))
    fecha_creacion = _parsear_fecha(
        g("createdAt", "created_at", "fecha_creacion", "fecha_creacion_raw"))

    # Sin fecha de despacho = pedido aún en bodega, no es logística activa
    if not fecha_despacho:
        return None

    valor_cod_raw = g("codAmount", "cod_amount", "valor_pago_contraentrega",
                      "valor_cod_raw", "cashOnDelivery") or 0

    ciudad = str(g("destinationCity", "destination_city", "ciudad_destino") or "")
    ciudad = ciudad.upper().strip()

    p = {
        # Identificadores
        "orden_melonn":       str(g("melonnOrderId", "melonn_order_id", "id", "orden_melonn") or ""),
        "orden_tienda":       str(g("storeOrderId", "store_order_id", "orden_shopify", "orden_tienda") or ""),
        "estado_melonn":      estado,
        "tienda":             str(g("store", "tienda") or ""),
        "canal_venta":        str(g("salesChannel", "sales_channel", "canal_venta") or ""),

        # Destinatario
        "nombre_comprador":   str(g("buyerName", "buyer_name", "nombre_comprador") or ""),
        "telefono_comprador": str(g("buyerPhone", "buyer_phone", "telefono_comprador") or ""),
        "ciudad_destino":     ciudad,
        "region_destino":     str(g("destinationRegion", "destination_region", "region_destino") or ""),

        # Logística
        "transportadora":     str(g("carrier", "transportadora") or ""),
        "link_guia":          str(g("trackingUrl", "tracking_url", "link_guia") or ""),

        # Fechas
        "fecha_despacho":     fecha_despacho,
        "fecha_entrega":      fecha_entrega,
        "fecha_promesa":      fecha_promesa,
        "fecha_creacion":     fecha_creacion,

        # Producto
        "sku":                str(g("sku", "SKU") or ""),
        "producto":           str(g("productName", "product_name", "producto") or ""),
        "variante":           str(g("variant", "variante") or ""),
        "cantidad":           int(g("quantity", "cantidad") or 1),
        "precio_unitario":    float(str(g("unitPrice", "unit_price", "precio_unitario") or 0)
                                    .replace(",", ".")),

        # COD
        "valor_cod_raw":      str(valor_cod_raw),
        "tipo_recaudo":       str(g("collectionType", "collection_type", "tipo_recaudo") or ""),

        # Calculados
        "es_contraentrega":   _es_contraentrega(valor_cod_raw),
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
