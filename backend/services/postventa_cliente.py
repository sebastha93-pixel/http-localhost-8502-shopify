"""
backend.services.postventa_cliente — Buscar las compras de una clienta.

La clienta llega a la tienda (o escribe) y casi nunca recuerda el número de
pedido. Pero siempre tiene la cédula. Siigo indexa las facturas por
`customer_identification`, así que con la cédula se traen TODAS sus compras
—online y de tienda— y la asesora solo elige cuál viene a cambiar.

Solo lectura.
"""
from __future__ import annotations

import logging
from typing import Optional

from backend.services import siigo
from backend.services import fiscal_logic as F
from backend.services import tiendas

log = logging.getLogger("postventa_cliente")

# Prefijo de factura → dónde se hizo la compra.
_CANAL_POR_DOCUMENTO: dict[int, str] = {
    F.FV_ONLINE_ID: "online",
}


def _canal_de(document_id: Optional[int], nombre: str) -> dict:
    """De qué canal es la factura: online o qué punto de venta."""
    if document_id == F.FV_ONLINE_ID:
        return {"canal": "online", "etiqueta": "Tienda online"}
    for clave, t in ((c, tiendas.obtener(c)) for c in
                     [p["clave"] for p in tiendas.listar()]):
        if t and t.get("documento_factura_id") == document_id:
            return {"canal": clave, "etiqueta": t.get("nombre")}
    # Prefijo desconocido: se muestra igual, sin adivinar el punto.
    prefijo = nombre.rsplit("-", 1)[0] if "-" in nombre else nombre
    return {"canal": None, "etiqueta": f"Otro ({prefijo})"}


def compras_por_cedula(cedula: str, *, limite: int = 12) -> dict:
    """Compras de la clienta, de la más reciente a la más antigua.

    Cada una trae sus prendas y si ya se le puede hacer nota crédito (la DIAN
    debe haber aceptado la factura).
    """
    cedula = (cedula or "").strip()
    if not cedula:
        return {"_error": "sin_cedula"}
    if not siigo.siigo_configurado():
        return {"_error": "siigo_no_configurado"}

    try:
        data = siigo.siigo_get("/invoices", {"customer_identification": cedula,
                                             "page_size": max(1, min(limite, 50)),
                                             "page": 1})
    except Exception as e:  # noqa: BLE001
        return {"_error": "siigo_error", "detalle": str(e)[:250]}

    filas = data.get("results", []) if isinstance(data, dict) else []
    compras = []
    for inv in filas:
        if not isinstance(inv, dict):
            continue
        nombre = str(inv.get("name") or "")
        doc_id = (inv.get("document") or {}).get("id")
        canal = _canal_de(doc_id, nombre)
        aceptada = F.factura_aceptada_dian(inv)
        compras.append({
            "factura_id": inv.get("id"),
            "factura": nombre,
            "fecha": inv.get("date"),
            "total": inv.get("total"),
            "canal": canal["canal"],
            "donde": canal["etiqueta"],
            # El nº de pedido solo existe en las ventas online.
            "pedido": (lambda n: f"#{n}" if n else None)(
                F.extraer_numero_pedido(inv.get("observations") or "")),
            "acreditable": aceptada,
            "motivo_no_acreditable": (None if aceptada
                                      else F.motivo_factura_no_apta(inv)),
            "prendas": [{"sku": it.get("code"),
                         "descripcion": it.get("description"),
                         "precio": it.get("price")}
                        for it in (inv.get("items") or [])],
        })

    compras.sort(key=lambda c: c.get("fecha") or "", reverse=True)
    cliente = ((filas[0].get("customer") or {}) if filas else {})
    return {
        "cedula": cedula,
        "cliente": {"identification": cliente.get("identification"),
                    "branch_office": cliente.get("branch_office", 0)},
        "total": len(compras),
        "acreditables": sum(1 for c in compras if c["acreditable"]),
        "compras": compras,
    }
