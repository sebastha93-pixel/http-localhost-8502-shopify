"""Armar la nota crédito que anula la factura de una venta del POS. Puro.

UNA VENTA ANULADA CON FACTURA SIGUE VIVA ANTE LA DIAN. Marcarla `anulada` en
el POS devuelve la prenda y la plata, pero el documento electrónico no se
entera: una factura validada sólo se deshace con una nota crédito.

LA NOTA CRÉDITO SE COPIA DE LA FACTURA, NO SE RECALCULA. Los ítems van tal
cual los devuelve Siigo —precio base, impuestos, descuento— para que cuadre
al centavo con el documento que anula. Es la misma regla del motor fiscal de
Postventa (`backend/services/fiscal_logic.py`), que lleva meses emitiendo así.

LOS PAGOS TAMBIÉN SE COPIAN, y ésa es la diferencia con Postventa. Allá la
nota crédito deja un saldo a favor (ANTICIPO CLIENTES); aquí la plata YA SE
DEVOLVIÓ en la caja, por el mismo medio por el que entró. La nota crédito
reversa esas mismas cuentas: el efectivo sale de la caja de la tienda, el
datáfono del datáfono. Los ids de forma de pago son válidos también para
notas crédito (verificado contra `/payment-types?document_type=NC` el
2026-10-08).
"""
from __future__ import annotations

from typing import Optional

from backend.modules.retail.infrastructure.siigo.factura_venta import (
    IVA_19_ID,
    FacturaInvalida,
)

__all__ = ["construir_nota_credito", "marca_nc_de", "MOTIVO_ANULACION"]

#  Concepto DIAN de la nota crédito (`reason`, obligatorio en electrónicas):
#  1 = devolución parcial, **2 = anulación de la factura**. Es el que llevan
#  las notas crédito de anulación que ya hay en la cuenta.
MOTIVO_ANULACION = 2


def marca_nc_de(venta_id: str, numero: str) -> str:
    """El rastro para reencontrarla si el envío se corta. Distinto del de la
    factura a propósito: buscar una no puede traer la otra."""
    return f"POS ANULA {numero} · {venta_id}"


def _numero_plano(valor) -> Optional[int]:
    """El GET devuelve bodega y centro de costo EXPANDIDOS (`{"id": 37, …}`) y
    el POST los quiere como NÚMERO. Con el objeto, Siigo descarta el campo en
    silencio y el inventario no se mueve."""
    if isinstance(valor, dict):
        valor = valor.get("id")
    try:
        return int(valor) if valor not in (None, "") else None
    except (TypeError, ValueError):
        return None


def construir_nota_credito(*, factura: dict, documento_id: int, fecha: str,
                           marca: str, bodega_id: Optional[int] = None,
                           estampar: bool = False) -> dict:
    """El cuerpo de `POST /credit-notes` por el TOTAL de la factura.

    `factura` es la respuesta de `GET /invoices/{id}`.
    """
    if not factura or not factura.get("id"):
        raise FacturaInvalida("no hay factura que acreditar")
    items = factura.get("items") or []
    if not items:
        raise FacturaInvalida("la factura no trae ítems")
    pagos_factura = [p for p in (factura.get("payments") or [])
                     if p.get("id") and float(p.get("value") or 0) > 0]
    if not pagos_factura:
        raise FacturaInvalida("la factura no trae pagos que reversar")

    lineas = []
    for it in items:
        linea = {
            "code": it.get("code"),
            "description": it.get("description") or "",
            "quantity": it.get("quantity") or 1,
            "price": it.get("price"),
            # El GET los trae con nombre y porcentaje; el POST quiere el id.
            "taxes": ([{"id": t.get("id")} for t in (it.get("taxes") or [])
                       if t.get("id")] or [{"id": IVA_19_ID}]),
        }
        # La prenda vuelve a la bodega de la tienda que anula.
        bodega = _numero_plano(bodega_id if bodega_id is not None
                               else it.get("warehouse"))
        if bodega is not None:
            linea["warehouse"] = bodega
        if it.get("discount"):
            linea["discount"] = it["discount"]
        lineas.append(linea)

    cliente = factura.get("customer") or {}
    cuerpo = {
        "document": {"id": int(documento_id)},
        "date": fecha,
        "invoice": factura["id"],
        "customer": {"identification": cliente.get("identification"),
                     "branch_office": cliente.get("branch_office", 0)},
        "items": lineas,
        "payments": [{"id": int(p["id"]), "value": float(p["value"]),
                      "due_date": fecha} for p in pagos_factura],
        "reason": MOTIVO_ANULACION,
        "observations": marca,
    }
    vendedor = _numero_plano(factura.get("seller"))
    if vendedor is not None:
        cuerpo["seller"] = vendedor
    # Se contabiliza DONDE se contabilizó la venta que reversa.
    centro = _numero_plano(factura.get("cost_center"))
    if centro is not None:
        cuerpo["cost_center"] = centro
    if estampar:
        cuerpo["stamp"] = {"send": True}
    return cuerpo
