"""
backend.services.fiscal_shopify — Precio de una referencia nueva en Shopify.

Para la factura del reemplazo cuando la clienta cambia por OTRA referencia:
el precio sale de Shopify (viene CON IVA) y se convierte a base. Reutiliza el
cliente GraphQL de backend.services.clientes.
"""
from __future__ import annotations

import logging
from typing import Optional

from backend.services import clientes
from backend.services import fiscal_logic as F

log = logging.getLogger("fiscal_shopify")

_QUERY = """
query($q: String!) {
  productVariants(first: 1, query: $q) {
    edges { node { sku price displayName } }
  }
}
"""


def precio_con_iva_variante(sku: str) -> Optional[float]:
    """Precio de venta (CON IVA) de la variante con ese SKU. None si no existe."""
    sku = (sku or "").strip()
    if not sku:
        return None
    data = clientes._shopify_graphql(_QUERY, {"q": f"sku:{sku}"})
    if not isinstance(data, dict) or data.get("errors"):
        log.warning(f"[fiscal_shopify] error consultando sku {sku}: "
                    f"{str(data.get('errors'))[:200] if isinstance(data, dict) else data}")
        return None
    edges = (((data.get("data") or {}).get("productVariants") or {}).get("edges") or [])
    if not edges:
        return None
    precio = (edges[0].get("node") or {}).get("price")
    try:
        return float(precio)
    except (TypeError, ValueError):
        return None


def precio_base_variante(sku: str) -> Optional[float]:
    """Precio SIN IVA de la variante (para el ítem de la factura Siigo)."""
    con_iva = precio_con_iva_variante(sku)
    if con_iva is None:
        return None
    return F.base_desde_precio_con_iva(con_iva)


# Sin filtro de precio en el query: la sintaxis `price:>N` de Shopify resultó
# frágil (devolvía vacío). Se traen variantes disponibles y se filtra en
# Python, que es predecible y no depende de la gramática de búsqueda.
_Q_VARIANTES = """
query($n: Int!) {
  productVariants(first: $n, query: "inventory_quantity:>0") {
    edges { node { sku price displayName availableForSale } }
  }
}
"""


def variante_mas_cara_que(precio_base_min: float, *, excluir_sku: str = "") -> Optional[dict]:
    """Una variante cuyo precio (CON IVA) supere el equivalente de
    `precio_base_min` (SIN IVA). Sirve para probar el excedente: la clienta
    cambia por una prenda más cara y debe pagar la diferencia.

    Devuelve {'sku', 'precio_con_iva', 'precio_base'} o None.
    """
    umbral_con_iva = F.total_con_iva(precio_base_min)
    data = clientes._shopify_graphql(_Q_VARIANTES, {"n": 100})
    if not isinstance(data, dict) or data.get("errors"):
        log.warning(f"[fiscal_shopify] variantes: {str(data)[:200]}")
        return None
    edges = (((data.get("data") or {}).get("productVariants") or {}).get("edges") or [])

    candidatas = []
    for e in edges:
        n = e.get("node") or {}
        sku = (n.get("sku") or "").strip()
        if not sku or sku == excluir_sku:
            continue
        try:
            con_iva = float(n.get("price"))
        except (TypeError, ValueError):
            continue
        if con_iva > umbral_con_iva:
            candidatas.append((con_iva, sku))
    if not candidatas:
        return None
    # La más barata que aun así supera el umbral: diferencia realista, no
    # un salto absurdo de precio.
    con_iva, sku = min(candidatas)
    return {"sku": sku, "precio_con_iva": con_iva,
            "precio_base": F.base_desde_precio_con_iva(con_iva)}


_Q_DX_SIMPLE = """
query { productVariants(first: 5) { edges { node { sku price displayName } } } }
"""

_Q_DX_STOCK = """
query { productVariants(first: 5, query: "inventory_quantity:>0") {
  edges { node { sku price displayName } } } }
"""


def diagnostico_variantes(precio_base_ref: float = 125966.39) -> dict:
    """Qué devuelve Shopify al pedir variantes. Para dejar de adivinar por qué
    `variante_mas_cara_que` no encuentra nada. Solo lectura."""
    umbral = F.total_con_iva(precio_base_ref)

    sin_filtro = clientes._shopify_graphql(_Q_DX_SIMPLE)
    con_filtro = clientes._shopify_graphql(_Q_DX_STOCK)

    def resumir(data):
        if not isinstance(data, dict):
            return {"_error": "respuesta_no_dict", "crudo": str(data)[:300]}
        if data.get("errors"):
            return {"_error": str(data["errors"])[:400]}
        edges = (((data.get("data") or {}).get("productVariants") or {})
                 .get("edges") or [])
        return {"cantidad": len(edges),
                "muestra": [{"sku": (e.get("node") or {}).get("sku"),
                             "price": (e.get("node") or {}).get("price")}
                            for e in edges[:5]]}

    return {
        "umbral_con_iva_buscado": umbral,
        "sin_filtro": resumir(sin_filtro),
        "con_filtro_inventory": resumir(con_filtro),
        "resultado_funcion": variante_mas_cara_que(precio_base_ref),
    }
