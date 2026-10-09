"""El precio de lista de un código, según la tienda en línea (Shopify).

SÓLO ES EL RESPALDO. El precio de una prenda del POS es el de Siigo. Esto se
consulta únicamente para los códigos que tienen existencia en una tienda y a
los que Siigo les tiene el precio en $0 — un puñado, no el catálogo.

EL PRECIO DE LISTA, NO EL DE PROMOCIÓN. Si la tienda en línea tiene la prenda
rebajada, el precio «tachado» (`compareAtPrice`) es el de etiqueta; el otro es
la promoción de la web, que la tienda física no tiene por qué dar. Cuando no
hay tachado, el precio es el de lista.
"""
from __future__ import annotations

import logging
from typing import Dict, List

log = logging.getLogger("retail.inventario")

__all__ = ["precios_de_lista"]

_CONSULTA = """
query($q: String!) {
  productVariants(first: 100, query: $q) {
    nodes { sku price compareAtPrice }
  }
}"""


def precios_de_lista(codigos: List[str]) -> Dict[str, int]:
    """`{código: pesos}` para los que la tienda en línea conoce. Nunca lanza:
    si Shopify no contesta, no hay respaldo y esos códigos quedan reportados.
    """
    codigos = sorted({c.strip() for c in codigos if c and c.strip()})
    if not codigos:
        return {}
    try:
        from backend.services.clientes import _shopify_graphql
    except Exception as e:  # noqa: BLE001
        log.warning("[retail-inventario] sin acceso a Shopify: %s", e)
        return {}

    salida: Dict[str, int] = {}
    for i in range(0, len(codigos), 25):
        lote = codigos[i:i + 25]
        filtro = " OR ".join(f'sku:"{c}"' for c in lote)
        try:
            r = _shopify_graphql(_CONSULTA, {"q": filtro})
        except Exception as e:  # noqa: BLE001
            log.warning("[retail-inventario] Shopify no contestó: %s", e)
            continue
        nodos = (((r or {}).get("data") or {}).get("productVariants") or {}
                 ).get("nodes") or []
        pedidos = {c.upper() for c in lote}
        for n in nodos:
            sku = (n.get("sku") or "").strip()
            # El filtro de Shopify es por prefijo/tokens: se comprueba que sea
            # EXACTAMENTE el código pedido.
            if sku.upper() not in pedidos:
                continue
            try:
                precio = float(n.get("compareAtPrice") or n.get("price") or 0)
            except (TypeError, ValueError):
                continue
            if precio > 0:
                salida[sku] = int(round(precio))
    return salida
