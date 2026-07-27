"""
backend.services.postventa_shopify_write — Escritura en Shopify desde postventa.

Dos operaciones, ambas SECUNDARIAS al flujo fiscal:

1. `registrar_retorno` — deja constancia en Shopify de que la prenda volvió
   (returnCreate). NO mueve dinero: la plata se maneja en Siigo con el
   anticipo. Decisión del fundador (opción A) para no contar el reembolso
   dos veces entre los dos sistemas.

2. `reservar_item` — aparta la prenda de reemplazo del inventario disponible
   para que la tienda no la venda mientras llega el cambio.

REGLA DE ORO: si Shopify falla, el caso NO se rompe. La nota crédito ya se
emitió ante la DIAN; un error de inventario no puede revertir eso. Todo
devuelve un dict con `ok` y el motivo, nunca lanza hacia el flujo fiscal.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

from backend.services import clientes

log = logging.getLogger("postventa_shopify_write")

# Versión con las mutaciones de returns estables. Se puede subir con env.
API_VERSION_WRITE = os.environ.get("SHOPIFY_API_VERSION_WRITE", "2024-10")


def _gql(query: str, variables: Optional[dict] = None) -> dict:
    """GraphQL contra la versión de escritura (no la global del OS)."""
    import requests
    from backend.services import shopify_auth

    store = os.environ.get("SHOPIFY_STORE", "").strip()
    if not store:
        return {"errors": [{"message": "SHOPIFY_STORE no configurado"}]}
    try:
        token = shopify_auth.token()
    except Exception as e:  # noqa: BLE001
        return {"errors": [{"message": f"shopify_auth: {str(e)[:120]}"}]}

    r = requests.post(
        f"https://{store}/admin/api/{API_VERSION_WRITE}/graphql.json",
        json={"query": query, "variables": variables or {}},
        headers={"X-Shopify-Access-Token": token,
                 "Content-Type": "application/json"},
        timeout=30,
    )
    return r.json()


def _errores(data: Any, campo: str) -> str:
    """Extrae userErrors de una mutación. '' si todo bien."""
    if not isinstance(data, dict):
        return "respuesta_inesperada"
    if data.get("errors"):
        return str(data["errors"])[:300]
    nodo = (data.get("data") or {}).get(campo) or {}
    errs = nodo.get("userErrors") or []
    if errs:
        return "; ".join(f"{e.get('field')}: {e.get('message')}" for e in errs)[:300]
    return ""


# ── 1. Registrar el retorno ──────────────────────────────────────────
_Q_FULFILLMENTS = """
query($id: ID!) {
  order(id: $id) {
    id
    name
    fulfillments {
      fulfillmentLineItems(first: 50) {
        edges { node { id quantity lineItem { sku title } } }
      }
    }
  }
}
"""

_M_RETURN_CREATE = """
mutation returnCreate($returnInput: ReturnInput!) {
  returnCreate(returnInput: $returnInput) {
    return { id name status }
    userErrors { field message }
  }
}
"""

# Motivos de Shopify ← motivos del caso de postventa.
_RAZON_SHOPIFY = {
    "talla_pequena": "SIZE_TOO_SMALL",
    "talla_grande": "SIZE_TOO_LARGE",
    "no_le_gusto_como_quedo": "STYLE",
    "color_diferente": "COLOR",
    "producto_defectuoso": "DEFECTIVE",
    "producto_equivocado": "WRONG_ITEM",
    "garantia": "DEFECTIVE",
    "arrepentimiento": "UNWANTED",
    "calidad_percibida": "NOT_AS_DESCRIBED",
}


def _fulfillment_line_item(order_gid: str, sku: str) -> Optional[dict]:
    """Encuentra la línea despachada que corresponde al SKU devuelto."""
    data = _gql(_Q_FULFILLMENTS, {"id": order_gid})
    orden = (data.get("data") or {}).get("order")
    if not orden:
        return None
    for f in orden.get("fulfillments") or []:
        for e in ((f.get("fulfillmentLineItems") or {}).get("edges") or []):
            n = e.get("node") or {}
            if ((n.get("lineItem") or {}).get("sku") or "") == sku:
                return {"id": n.get("id"), "quantity": n.get("quantity") or 1}
    return None


def registrar_retorno(*, shopify_order_id: str, sku: str, motivo: str = "",
                      nota: str = "") -> dict:
    """Registra en Shopify que la prenda volvió. No mueve dinero.

    Nunca lanza: devuelve {'ok': bool, 'motivo'|'return_name'}.
    """
    if not shopify_order_id or not sku:
        return {"ok": False, "motivo": "faltan_datos"}

    gid = (shopify_order_id if str(shopify_order_id).startswith("gid://")
           else f"gid://shopify/Order/{shopify_order_id}")
    try:
        linea = _fulfillment_line_item(gid, sku)
        if not linea:
            return {"ok": False, "motivo": "linea_despachada_no_encontrada"}

        variables = {"returnInput": {
            "orderId": gid,
            "returnLineItems": [{
                "fulfillmentLineItemId": linea["id"],
                "quantity": 1,
                "returnReason": _RAZON_SHOPIFY.get(motivo, "OTHER"),
                "returnReasonNote": (nota or "Postventa MALE")[:300],
            }],
            "notifyCustomer": False,
        }}
        data = _gql(_M_RETURN_CREATE, variables)
        err = _errores(data, "returnCreate")
        if err:
            return {"ok": False, "motivo": err}
        ret = ((data.get("data") or {}).get("returnCreate") or {}).get("return") or {}
        return {"ok": True, "return_name": ret.get("name"), "return_id": ret.get("id")}
    except Exception as e:  # noqa: BLE001
        log.warning(f"[shopify_write] retorno fallo: {e}")
        return {"ok": False, "motivo": str(e)[:200]}


# ── 2. Reservar el ítem de reemplazo ─────────────────────────────────
_Q_INVENTORY_ITEM = """
query($q: String!) {
  productVariants(first: 1, query: $q) {
    edges { node {
      sku
      inventoryItem {
        id
        inventoryLevels(first: 5) {
          edges { node { location { id name } quantities(names: ["available"]) { name quantity } } }
        }
      }
    } }
  }
}
"""

_M_ADJUST = """
mutation inventoryAdjustQuantities($input: InventoryAdjustQuantitiesInput!) {
  inventoryAdjustQuantities(input: $input) {
    inventoryAdjustmentGroup { createdAt reason }
    userErrors { field message }
  }
}
"""


def _ajustar_inventario(*, sku: str, delta: int, location_id: str = "") -> dict:
    """Suma o resta `delta` al inventario disponible del SKU.

    delta negativo aparta (reserva), positivo devuelve al disponible.
    Nunca lanza: devuelve {'ok': bool, ...}.
    """
    if not sku:
        return {"ok": False, "motivo": "sin_sku"}
    try:
        data = _gql(_Q_INVENTORY_ITEM, {"q": f"sku:{sku}"})
        edges = (((data.get("data") or {}).get("productVariants") or {})
                 .get("edges") or [])
        if not edges:
            return {"ok": False, "motivo": "sku_no_encontrado"}

        inv = ((edges[0].get("node") or {}).get("inventoryItem") or {})
        inv_id = inv.get("id")
        if not inv_id:
            return {"ok": False, "motivo": "sin_inventory_item"}

        loc = location_id
        if not loc:
            niveles = ((inv.get("inventoryLevels") or {}).get("edges") or [])
            if not niveles:
                return {"ok": False, "motivo": "sin_bodega"}
            loc = ((niveles[0].get("node") or {}).get("location") or {}).get("id")
        if not loc:
            return {"ok": False, "motivo": "sin_bodega"}

        variables = {"input": {
            "reason": "other",
            "name": "available",
            "referenceDocumentUri": "logistics://male/postventa/reserva",
            "changes": [{"delta": int(delta),
                         "inventoryItemId": inv_id,
                         "locationId": loc}],
        }}
        res = _gql(_M_ADJUST, variables)
        err = _errores(res, "inventoryAdjustQuantities")
        if err:
            return {"ok": False, "motivo": err}
        return {"ok": True, "sku": sku, "delta": int(delta), "location_id": loc}
    except Exception as e:  # noqa: BLE001
        log.warning(f"[shopify_write] ajuste de inventario fallo: {e}")
        return {"ok": False, "motivo": str(e)[:200]}


def reservar_item(*, sku: str, cantidad: int = 1, location_id: str = "") -> dict:
    """Aparta la prenda: la resta del disponible para que no se venda."""
    return _ajustar_inventario(sku=sku, delta=-abs(int(cantidad)),
                               location_id=location_id)


def liberar_reserva(*, sku: str, cantidad: int = 1, location_id: str = "") -> dict:
    """Devuelve al disponible lo apartado (caso rechazado o cancelado)."""
    return _ajustar_inventario(sku=sku, delta=abs(int(cantidad)),
                               location_id=location_id)
