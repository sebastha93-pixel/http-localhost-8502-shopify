"""
Shopify Enricher — MALE'DENIM
Enriquece pedidos Melonn con datos de cliente, dirección y productos
usando el external_order_id (= Shopify order ID) como clave de unión.

Una sola llamada batch por sync → eficiente y sin rate-limit issues.
"""

import logging
from typing import Optional

import requests

log = logging.getLogger(__name__)

_BATCH_SIZE = 250   # Shopify acepta hasta 250 IDs por request
_TIMEOUT    = 20


def _credenciales() -> Optional[tuple]:
    """Retorna (store, token, version) desde st.secrets o variables de entorno."""
    try:
        import streamlit as st
        store   = st.secrets.get("SHOPIFY_STORE")
        token   = st.secrets.get("SHOPIFY_ACCESS_TOKEN")
        version = st.secrets.get("SHOPIFY_API_VERSION", "2024-01")
        if store and token:
            return store, token, version
    except Exception:
        pass
    import os
    store   = os.getenv("SHOPIFY_STORE")
    token   = os.getenv("SHOPIFY_ACCESS_TOKEN")
    version = os.getenv("SHOPIFY_API_VERSION", "2024-01")
    if store and token:
        return store, token, version
    return None


def _fetch_shopify_orders(order_ids: list[str]) -> dict:
    """
    Hace una o varias llamadas batch a Shopify y devuelve un dict
    { shopify_order_id (str) → order_dict }.
    """
    creds = _credenciales()
    if not creds:
        log.warning("Shopify: credenciales no configuradas — sin enriquecimiento")
        return {}

    store, token, version = creds
    url     = f"https://{store}/admin/api/{version}/orders.json"
    headers = {"X-Shopify-Access-Token": token}
    fields  = "id,name,customer,shipping_address,line_items,total_price"

    resultado = {}
    for i in range(0, len(order_ids), _BATCH_SIZE):
        chunk = order_ids[i : i + _BATCH_SIZE]
        try:
            r = requests.get(
                url,
                headers=headers,
                params={"ids": ",".join(chunk), "status": "any", "fields": fields},
                timeout=_TIMEOUT,
            )
            r.raise_for_status()
            for o in r.json().get("orders", []):
                resultado[str(o["id"])] = o
        except Exception as e:
            log.warning(f"Shopify batch error (chunk {i}): {e}")

    return resultado


def _fetch_by_name(order_name: str, store: str, token: str, version: str) -> Optional[dict]:
    """Busca en Shopify por nombre de orden (ej. #58043) — para reenvíos sin external_order_id."""
    try:
        r = requests.get(
            f"https://{store}/admin/api/{version}/orders.json",
            headers={"X-Shopify-Access-Token": token},
            params={
                "name": f"#{order_name}" if not order_name.startswith("#") else order_name,
                "status": "any",
                "fields": "id,name,customer,shipping_address,line_items,total_price",
            },
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        orders = r.json().get("orders", [])
        return orders[0] if orders else None
    except Exception as e:
        log.warning(f"Shopify lookup by name '{order_name}': {e}")
        return None


def enriquecer(pedidos: list) -> list:
    """
    Recibe la lista de pedidos normalizados de Melonn y añade/rellena:
      nombre_comprador, telefono_comprador, ciudad_destino, region_destino,
      producto, sku, cantidad, precio_unitario, valor_total

    Estrategia de lookup:
      1. Por external_order_id (batch, eficiente) — pedidos normales
      2. Por nombre de orden (#XXXXX) — reenvíos sin external_order_id
    """
    creds = _credenciales()

    # Recopilar IDs de Shopify que faltan datos
    ids_necesarios = [
        str(p["external_order_id"])
        for p in pedidos
        if p.get("external_order_id")
        and not p.get("nombre_comprador")
    ]

    if not ids_necesarios and not creds:
        return pedidos

    log.info(f"Shopify enricher: consultando {len(ids_necesarios)} pedidos por ID")
    shopify_map = _fetch_shopify_orders(ids_necesarios) if ids_necesarios else {}
    # NO retornar si shopify_map está vacío — puede haber pedidos sin external_order_id
    # que necesitan fallback por nombre de orden

    enriquecidos = []
    for p in pedidos:
        sid = str(p.get("external_order_id") or "")
        o   = shopify_map.get(sid)

        # Fallback: buscar por nombre de orden cuando falta external_order_id
        # Cubre: reenvíos ("58043-NUEVO_ENVIO"), caché viejo sin ID, etc.
        if not o and not p.get("nombre_comprador") and creds:
            orden_tienda = str(p.get("orden_tienda") or "")
            base = orden_tienda.split("-")[0].strip()
            if base.isdigit():
                o = _fetch_by_name(base, *creds)
                if o:
                    # Guardar el ID de Shopify para futuros lookups
                    p = dict(p)
                    p["external_order_id"] = str(o.get("id", ""))

        if not o:
            enriquecidos.append(p)
            continue

        p = dict(p)  # copia para no mutar el original

        # ── Cliente ──────────────────────────────────────────────────────────
        cust = o.get("customer") or {}
        ship = o.get("shipping_address") or {}

        nombre = " ".join(filter(None, [
            cust.get("first_name", ""),
            cust.get("last_name", ""),
        ])).strip() or ship.get("name", "")

        telefono = (
            ship.get("phone")
            or cust.get("phone")
            or ""
        )

        # ── Dirección ────────────────────────────────────────────────────────
        ciudad  = (ship.get("city") or "").upper().strip()
        region  = ship.get("province") or ""

        # ── Productos ────────────────────────────────────────────────────────
        items = o.get("line_items") or []
        skus     = [str(i.get("sku") or "") for i in items if i.get("sku")]
        nombres  = [str(i.get("title") or "")[:40] for i in items]
        total    = sum(
            float(i.get("price", 0)) * int(i.get("quantity", 1))
            for i in items
        )
        fi = items[0] if items else {}

        # ── Rellenar campos vacíos ────────────────────────────────────────────
        if nombre:
            p["nombre_comprador"]   = nombre
        if telefono:
            p["telefono_comprador"] = telefono
        if ciudad:
            p["ciudad_destino"]     = ciudad
        if region:
            p["region_destino"]     = region
        if skus:
            p["sku"]      = skus[0]
            p["producto"] = " / ".join(nombres)
        if fi:
            p["cantidad"]        = int(fi.get("quantity") or 1)
            p["precio_unitario"] = float(fi.get("price") or 0)
        if total:
            p["valor_total"] = total

        enriquecidos.append(p)

    enriquecidos_n = sum(
        1 for p in enriquecidos if p.get("nombre_comprador")
    )
    log.info(f"Shopify enricher: {enriquecidos_n}/{len(enriquecidos)} pedidos con datos de cliente")
    return enriquecidos
