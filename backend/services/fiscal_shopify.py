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


_Q_VARIANTE_MAS_CARA = """
query($q: String!) {
  productVariants(first: 20, query: $q) {
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
    data = clientes._shopify_graphql(_Q_VARIANTE_MAS_CARA,
                                     {"q": f"price:>{umbral_con_iva:.0f}"})
    if not isinstance(data, dict) or data.get("errors"):
        return None
    edges = (((data.get("data") or {}).get("productVariants") or {}).get("edges") or [])
    for e in edges:
        n = e.get("node") or {}
        sku = (n.get("sku") or "").strip()
        if not sku or sku == excluir_sku:
            continue
        try:
            con_iva = float(n.get("price"))
        except (TypeError, ValueError):
            continue
        if con_iva <= umbral_con_iva:
            continue
        return {"sku": sku, "precio_con_iva": con_iva,
                "precio_base": F.base_desde_precio_con_iva(con_iva)}
    return None
