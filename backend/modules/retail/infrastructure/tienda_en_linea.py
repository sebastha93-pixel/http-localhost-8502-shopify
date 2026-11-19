"""Lo que la tienda en línea (Shopify) tiene para vender HOY, y a cuánto.

Es de donde sale lo que una caja puede vender CON ENVÍO: la prenda no está en
la tienda, está en la bodega de la tienda en línea (Melonn), y la existencia
de verdad de esa bodega la dice Shopify —no la bodega MELONN de Siigo, que va
desfasada: el 2026-11-13, para 25626-1T6, Siigo decía 3 y Shopify y Melonn
decían 0—.

DOS DIFERENCIAS CON `precios_tienda_en_linea.py`, y son a propósito:

**El precio es el que la web cobra HOY** (`price`), no el de lista. Allá se
toma el tachado porque la promoción de la web no es de la tienda física; aquí
la clienta está comprando lo de la web, y Sebastián decidió (2026-11-17) que
lleve el mismo precio que vería comprando ella misma. El de lista viaja
también, para mostrar la rebaja.

**FALLA CERRADO.** Aquel módulo nunca lanza: si Shopify no contesta, no hay
respaldo y ya. Aquí una respuesta vacía se leería como «no hay existencia» o,
peor, dejaría cobrar sin haber comprobado nada. Si Shopify no contesta, lanza
`TiendaEnLineaNoDisponible` y la venta con envío no se hace.

LA EXISTENCIA ES LA DE LA BODEGA DE MELONN, no la suma de la tienda: Shopify
tiene otras sucursales (una tienda, la oficina) y lo que hay ahí no lo
despacha Melonn.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Dict, List

log = logging.getLogger("retail.envio")

__all__ = ["TiendaEnLineaNoDisponible", "buscar", "consultar"]

#  La sucursal de Shopify que es el espejo de la bodega de Melonn.
_SUCURSAL_MELONN = "gid://shopify/Location/99023749440"

_CAMPOS = """
    sku title price compareAtPrice
    product { title status }
    inventoryItem {
      inventoryLevel(locationId: $loc) {
        quantities(names: ["available"]) { quantity }
      }
    }
"""

_POR_SKU = """
query($q: String!, $loc: ID!) {
  productVariants(first: 100, query: $q) { nodes { %s } }
}""" % _CAMPOS

_POR_TEXTO = """
query($q: String!, $loc: ID!, $n: Int!) {
  products(first: $n, query: $q) {
    nodes { title variants(first: 40) { nodes { %s } } }
  }
}""" % _CAMPOS


class TiendaEnLineaNoDisponible(Exception):
    """Shopify no contestó o contestó con error: no se sabe qué hay."""


def _sucursal() -> str:
    return (os.environ.get("SHOPIFY_LOCATION_MELONN") or "").strip() \
        or _SUCURSAL_MELONN


def _pedir(consulta: str, variables: dict) -> dict:
    try:
        from backend.services.clientes import _shopify_graphql
        r = _shopify_graphql(consulta, variables)
    except Exception as e:  # noqa: BLE001 — red, token, lo que sea
        raise TiendaEnLineaNoDisponible(str(e)[:200]) from e
    if not isinstance(r, dict) or r.get("errors") or "data" not in r:
        detalle = (r or {}).get("errors") if isinstance(r, dict) else r
        raise TiendaEnLineaNoDisponible(str(detalle)[:200])
    return r["data"] or {}


def _centavos(valor) -> int:
    try:
        return int(round(float(valor or 0) * 100))
    except (TypeError, ValueError):
        return 0


def _variante(n: dict, titulo_producto: str = "") -> dict:
    nivel = ((n.get("inventoryItem") or {}).get("inventoryLevel") or {})
    disponible = sum(int(q.get("quantity") or 0)
                     for q in (nivel.get("quantities") or []))
    precio = _centavos(n.get("price"))
    lista = _centavos(n.get("compareAtPrice"))
    producto = n.get("product") or {}
    return {
        "sku": (n.get("sku") or "").strip(),
        "nombre": (producto.get("title") or titulo_producto or "").strip(" ."),
        "talla": _talla(n.get("title") or ""),
        "precio_centavos": precio,
        # El tachado sólo cuenta si de verdad es mayor: hay productos con el
        # `compareAtPrice` igual o por debajo del precio, y eso no es rebaja.
        "precio_lista_centavos": lista if lista > precio else precio,
        "disponible": max(disponible, 0),
        "activo": (producto.get("status") or "ACTIVE") == "ACTIVE",
    }


def _talla(titulo: str) -> str:
    """`TALLA 6` → `6`. Lo que no tenga esa forma, tal cual."""
    m = re.match(r"^\s*talla\s+(.+?)\s*$", titulo, re.IGNORECASE)
    return (m.group(1) if m else titulo).strip()


def consultar(skus: List[str]) -> Dict[str, dict]:
    """`{SKU en mayúsculas: variante}` para los que la tienda en línea conoce.

    Es la comprobación de ANTES DE COBRAR: precio y existencia de este
    instante. Lanza `TiendaEnLineaNoDisponible` si no se pudo preguntar.
    """
    pedidos = sorted({s.strip().upper() for s in skus if s and s.strip()})
    salida: Dict[str, dict] = {}
    for i in range(0, len(pedidos), 25):
        lote = pedidos[i:i + 25]
        datos = _pedir(_POR_SKU, {
            "q": " OR ".join(f'sku:"{s}"' for s in lote),
            "loc": _sucursal()})
        for n in ((datos.get("productVariants") or {}).get("nodes") or []):
            v = _variante(n)
            # El filtro de Shopify es por tokens: `sku:"92633-1T6"` también
            # trae `92633-1T60`. Sólo vale el que es EXACTAMENTE el pedido.
            if v["sku"].upper() in lote and v["activo"]:
                salida[v["sku"].upper()] = v
    return salida


def buscar(texto: str, limite: int = 12) -> List[dict]:
    """Productos de la tienda en línea que casan con `texto` (nombre o
    código), con sus tallas. Sólo publicados. Lanza
    `TiendaEnLineaNoDisponible` si no se pudo preguntar.

    Devuelve `[{nombre, variantes: [variante…]}]`, con las que tienen
    existencia primero dentro de cada producto.
    """
    texto = re.sub(r'[^\w\s\-.áéíóúñÁÉÍÓÚÑ]', " ", texto or "").strip()
    if len(texto) < 2:
        return []
    datos = _pedir(_POR_TEXTO, {
        # `inventory_total:>0`: sin él, el catálogo viejo —publicado y en
        # cero— llena los resultados (medido 2026-11-19: «jean» daba 25
        # productos y ninguno con existencia).
        "q": f"{texto} status:active inventory_total:>0", "loc": _sucursal(),
        "n": max(1, min(int(limite), 25))})
    salida = []
    for p in ((datos.get("products") or {}).get("nodes") or []):
        variantes = [_variante(n, p.get("title") or "")
                     for n in ((p.get("variants") or {}).get("nodes") or [])]
        variantes = [v for v in variantes if v["sku"]]
        if variantes:
            salida.append({"nombre": (p.get("title") or "").strip(" ."),
                           "variantes": variantes})
    # Lo que se puede vender, arriba: la vendedora busca para vender.
    salida.sort(key=lambda p: -sum(v["disponible"] for v in p["variantes"]))
    return salida
