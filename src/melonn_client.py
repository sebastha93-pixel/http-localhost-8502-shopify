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
_BASE_URL      = "https://api.orbita.melonn.com"
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
    Convierte un pedido JSON de la API Melonn (orbita) al esquema interno.

    Estructura confirmada 2026-05-28 con api.orbita.melonn.com:
      sell_order_state.name  → estado
      buyer.full_name / phone_number
      shipping_info.city / region  → destino (NO warehouse, que es origen)
      payment_on_delivery_amount   → COD
      creation_date                → única fecha disponible en la API
      line_items[].sku / quantity
      melonn_tracking_link
      external_order_number (sin #) → orden_tienda
      internal_order_number         → orden_melonn
    """
    estado = str((raw.get("sell_order_state") or {}).get("name") or "")

    # Comprador
    buyer  = raw.get("buyer") or {}
    nombre = str(buyer.get("full_name") or "")
    tel    = str(buyer.get("phone_number") or "")

    # Destino (shipping_info = dirección del comprador, warehouse = bodega origen)
    dest   = raw.get("shipping_info") or {}
    ciudad = str(dest.get("city") or "").upper().strip()
    region = str(dest.get("region") or "")

    # Método de envío como proxy de transportadora (Melonn no expone carrier directo)
    metodo = str((raw.get("shipping_method") or {}).get("name") or "")

    # Line items
    items      = raw.get("line_items") or []
    first_item = items[0] if items else {}
    sku        = str(first_item.get("sku") or "")
    cantidad   = int(first_item.get("quantity") or 1)
    producto   = ", ".join(str(i.get("sku", "")) for i in items if i.get("sku"))

    # Fechas — la API solo provee creation_date
    fecha_creacion = _parsear_fecha(raw.get("creation_date"))
    fecha_despacho = fecha_creacion   # proxy: días desde creación
    fecha_entrega  = None
    fecha_promesa  = None

    # COD
    valor_cod = raw.get("payment_on_delivery_amount")
    tipo_recaudo = str((raw.get("payment_on_delivery_type") or {}).get("name") or
                       ("Contraentrega" if valor_cod else "Prepago"))

    p = {
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

    return p


# ── Fetch de pedidos ───────────────────────────────────────────────────────────
def obtener_pedido(order_id: str) -> Optional[dict]:
    """Obtiene un pedido individual. Retorna dict normalizado o None."""
    raw = _get(f"sell-orders/{order_id}")
    if raw is None:
        return None
    return _normalizar_pedido(raw)


def _listar_paginas(params_extra: dict = None) -> list[dict]:
    """
    Descarga todas las páginas de sell-orders.
    Paginación confirmada: page 0-indexed, per_page, wrapper {data:[], meta_data:{total_count}}
    """
    todos  = []
    page   = 0
    params_base = {"per_page": _PAGE_SIZE, **(params_extra or {})}

    while True:
        resp = _get("sell-orders", params={**params_base, "page": page})
        if resp is None:
            log.error("Error en sell-orders — verifica el API key")
            break

        # Estructura confirmada: {data: [...], meta_data: {page, per_page, total_count}}
        items       = resp.get("data") or []
        meta        = resp.get("meta_data") or {}
        total_count = meta.get("total_count") or 0

        todos.extend(items)
        log.info(f"Página {page}: {len(items)} items (total: {total_count})")

        # ¿Hay más páginas?
        if not items or len(todos) >= total_count:
            break
        page += 1

    return todos


def obtener_pedidos_activos(dias: int = 30) -> tuple[list, dict]:
    """
    Descarga todos los pedidos activos.

    Estrategia en 2 pasos:
    1. GET /sell-orders?page=N  → listado paginado (campos básicos)
    2. GET /sell-orders/{id}     → detalle completo por cada pedido
       (buyer, fechas de despacho, dirección destino, transportadora)

    Retorna (lista_pedidos_normalizados, dict_omitidos).
    """
    pedidos  = []
    omitidos = {"resuelto": 0, "sin_despacho": 0, "error_detalle": 0}

    # ── Paso 1: listar todos los IDs ──────────────────────────────────────────
    items_lista = _listar_paginas()

    if not items_lista:
        log.warning("sell-orders listado vacío")
        return [], omitidos

    # ── Paso 2: enriquecer con detalle individual ──────────────────────────────
    for item in items_lista:
        estado = str((item.get("sell_order_state") or {}).get("name") or "")

        # Saltar resueltos sin llamar al detalle
        if estado in ESTADOS_RESUELTOS:
            omitidos["resuelto"] += 1
            continue

        # Detalle: external_order_number sin '#' (confirmado con api.orbita.melonn.com)
        order_id = str(item.get("external_order_number") or "").lstrip("#") or str(item.get("id", ""))

        # Intentar enriquecer con detalle (buyer, fechas, dirección)
        detalle = _get(f"sell-orders/{order_id}")
        raw = detalle if detalle else item   # fallback al item del listado

        p = _normalizar_pedido(raw)
        if p is None:
            omitidos["sin_despacho"] += 1
            continue

        pedidos.append(p)

    log.info(f"Total normalizado: {len(pedidos)} pedidos activos")
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
