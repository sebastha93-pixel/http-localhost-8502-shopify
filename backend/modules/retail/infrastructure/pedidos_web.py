"""Encontrar la compra de la tienda en línea por lo que la clienta SÍ sabe.

La clienta que compró por la página llega a la tienda con el número del
pedido (`#64429`) o con su nombre. La factura de Siigo no siempre está a su
cédula: hay pedidos facturados al celular puesto en el campo de la cédula, o
a «Cliente Mostrador» (Arrayanes, 2026-10-10, cédula 43180115: tres facturas
a su nombre y ninguna era la que traía). Buscar por cédula no las encuentra.

Dos pasos, y el segundo sólo para el pedido que se elige:

  1. `buscar(q)`: los pedidos de Shopify que casan con el número o el nombre.
     Una sola consulta.
  2. `factura_de(pedido, fecha)`: la factura de Siigo de ESE pedido. Siigo no
     deja filtrar por observaciones, así que se recorren las facturas de la
     tienda en línea desde el día del pedido y se mira cuál dice
     «Orden Nº: 64429». Son varias peticiones: por eso no se hace para toda
     la lista.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta
from typing import List, Optional
from zoneinfo import ZoneInfo

__all__ = ["parece_pedido", "buscar", "factura_de"]

_BOGOTA = ZoneInfo("America/Bogota")
_DOCUMENTO_EN_LINEA = 11810
#  Cuántos días después del pedido se sigue buscando su factura.
_DIAS = 6

_CONSULTA = """
query($q: String!) {
  orders(first: 8, query: $q, sortKey: CREATED_AT, reverse: true) {
    nodes {
      name createdAt cancelledAt
      totalPriceSet { shopMoney { amount } }
      customer { displayName }
      shippingAddress { name }
      lineItems(first: 6) { nodes { sku quantity } }
    }
  }
}
"""


def parece_pedido(q: str) -> Optional[str]:
    """El filtro de Shopify para lo tecleado, o `None` si no es para Shopify.

        #64429, pedido 64429   → name:#64429
        Yenny Ruiz             → el texto, que Shopify busca en el nombre

    Una cédula o un número de factura NO: eso se busca en Siigo.
    """
    crudo = (q or "").strip()
    m = re.fullmatch(r"(?:#|pedido\s*#?\s*|orden\s*#?\s*)(\d{3,7})", crudo, re.I)
    if m:
        return f"name:#{m.group(1)}"
    # Un nombre: letras y espacios, al menos cuatro letras. `ARRT-5` o
    # `FE 67600` llevan dígitos y no entran.
    if re.fullmatch(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ' ]+", crudo) and \
            len(crudo.replace(" ", "")) >= 4:
        return crudo
    return None


def buscar(q: str) -> List[dict]:
    """Los pedidos de la tienda en línea que casan. Vacío si no aplica."""
    filtro = parece_pedido(q)
    if not filtro:
        return []
    from backend.services.clientes import _shopify_graphql

    r = _shopify_graphql(_CONSULTA, {"q": filtro})
    nodos = (((r or {}).get("data") or {}).get("orders") or {}).get("nodes") or []
    salida = []
    for n in nodos:
        if n.get("cancelledAt"):
            continue
        numero = str(n.get("name") or "").lstrip("#")
        if not numero.isdigit():
            continue
        cuando = _fecha(n.get("createdAt"))
        salida.append({
            "pedido": numero,
            "fecha": cuando.date().isoformat() if cuando else "",
            "total": float(((n.get("totalPriceSet") or {}).get("shopMoney")
                            or {}).get("amount") or 0),
            "cliente": ((n.get("customer") or {}).get("displayName")
                        or (n.get("shippingAddress") or {}).get("name") or ""
                        ).strip(),
            "prendas": [i.get("sku") for i in
                        ((n.get("lineItems") or {}).get("nodes") or [])
                        if i.get("sku")],
        })
    return salida


def _fecha(iso: Optional[str]) -> Optional[datetime]:
    if not iso:
        return None
    try:
        return datetime.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=ZoneInfo("UTC")).astimezone(_BOGOTA)
    except ValueError:
        return None


def factura_de(pedido: str, fecha: str, *, paginas: int = 12) -> Optional[dict]:
    """La factura de Siigo del pedido `pedido`, hecho el día `fecha`
    (`AAAA-MM-DD`, hora de Bogotá). `None` si todavía no está facturado."""
    from backend.services.siigo import siigo_get

    pedido = str(pedido).strip().lstrip("#")
    if not pedido.isdigit():
        return None
    desde = datetime.strptime(fecha, "%Y-%m-%d").date()
    marca = re.compile(rf"Orden\s*N\S*\s*:?\s*{pedido}\b", re.I)
    for pagina in range(1, paginas + 1):
        if pagina > 1:
            time.sleep(1.1)        # la cuenta aguanta ~1 petición por segundo
        r = siigo_get("/invoices", {
            "document_id": _DOCUMENTO_EN_LINEA,
            "date_start": desde.isoformat(),
            "date_end": (desde + timedelta(days=_DIAS)).isoformat(),
            "page": pagina, "page_size": 100})
        filas = (r.get("results") or []) if isinstance(r, dict) else []
        for f in filas:
            if marca.search(f.get("observations") or ""):
                return f
        if len(filas) < 100:
            break
    return None
