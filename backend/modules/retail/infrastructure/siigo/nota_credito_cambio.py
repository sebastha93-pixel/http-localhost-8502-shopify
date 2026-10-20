"""Armar la nota crédito de un CAMBIO: sólo las prendas que volvieron. Puro.

Se diferencia de la de anulación (`nota_credito_venta.py`) en tres cosas:

  · ES PARCIAL. Acredita las prendas devueltas y sus cantidades, no la
    factura entera. Concepto DIAN 1, «devolución parcial de los bienes».
  · DEJA UN ANTICIPO. No reversa los pagos de la factura: la plata no se
    devuelve, queda como saldo a favor de la clienta (ANTICIPO CLIENTES). Es
    el anticipo contra el que se cruza la factura de la prenda nueva.
  · LA PRENDA ENTRA A LA TIENDA QUE LA RECIBE, no a la bodega de donde salió:
    una compra de la página devuelta en Florida queda en Florida.

LOS ÍTEMS SE COPIAN DE LA FACTURA, con su precio base y su descuento, igual
que la de anulación. El valor del anticipo es lo que Siigo va a calcular para
esas líneas: si no cuadra al centavo, Siigo rechaza el documento.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, Optional

from backend.modules.retail.infrastructure.siigo.factura_venta import (
    IVA_19_ID,
    FacturaInvalida,
)
from backend.modules.retail.infrastructure.siigo.nota_credito_venta import (
    _descuento_plano,
    _numero_plano,
)

__all__ = ["construir_nota_credito_cambio", "marca_cambio_de",
           "ANTICIPO_CLIENTES_ID", "MOTIVO_DEVOLUCION_PARCIAL"]

#  La forma de pago que deja saldo a favor. La misma de Postventa.
ANTICIPO_CLIENTES_ID = 8316
MOTIVO_DEVOLUCION_PARCIAL = 1

_CENT = Decimal("0.01")


def _c(v) -> Decimal:
    return Decimal(str(v)).quantize(_CENT, rounding=ROUND_HALF_UP)


def marca_cambio_de(devolucion_id: str, numero_venta: str) -> str:
    """El rastro para reencontrarla si el envío se corta. Lleva la DEVOLUCIÓN:
    una venta puede tener varias, cada una con su nota crédito."""
    return f"POS CAMBIO {numero_venta} · {devolucion_id}"


def _precio_y_descuento(it: dict):
    """El precio base y el porcentaje que se mandan para ese ítem.

    Siigo GUARDA el porcentaje redondeado pero el valor exacto: la segunda
    prenda a $1.000 de la página quedó como «99 %» con un descuento que en
    realidad es 99,33 %. Copiar el 99 daba una línea de $1.499 contra un
    anticipo de $1.000, y Siigo rechazaba la nota crédito (FE-67957, 18-oct).
    Cuando el porcentaje no explica el valor, va el precio YA REBAJADO y sin
    descuento, que es lo que la factura de venta hace en ese mismo caso.
    """
    precio = Decimal(str(it.get("price") or 0))
    d = it.get("discount")
    pct = _descuento_plano(d)
    if isinstance(d, dict) and d.get("value") not in (None, "") and pct:
        cant = Decimal(str(it.get("quantity") or 1)) or Decimal("1")
        valor = Decimal(str(d["value"]))
        if abs(_c(precio * cant * Decimal(str(pct)) / 100) - _c(valor)) > _CENT:
            return _c(precio - valor / cant), None
    return precio, pct


def _total_de(it: dict, cantidad: int) -> Decimal:
    """Lo que Siigo calcula para `cantidad` unidades de ese ítem.

    Con la cantidad completa es el total que la factura ya trae. Con menos
    —devolvió una de dos— se recalcula como lo hace Siigo: descuento sobre el
    bruto, IVA sobre el subtotal, cada uno redondeado al centavo.
    """
    if cantidad == int(float(it.get("quantity") or 0)) and it.get("total") is not None:
        return _c(it["total"])
    precio, pct = _precio_y_descuento(it)
    bruto = precio * cantidad
    descuento = _c(bruto * Decimal(str(pct or 0)) / 100)
    subtotal = bruto - descuento
    tasa = sum((Decimal(str(t.get("percentage") or 0))
                for t in (it.get("taxes") or [])), Decimal("0")) \
        or Decimal("19")
    return _c(subtotal) + _c(subtotal * tasa / 100)


def construir_nota_credito_cambio(*, factura: dict, devueltas: Dict[str, int],
                                  documento_id: int, fecha: str, marca: str,
                                  bodega_id: Optional[int] = None,
                                  estampar: bool = False) -> dict:
    """El cuerpo de `POST /credit-notes` por las prendas devueltas.

    `devueltas`: `{código: cantidad}`. `factura`: `GET /invoices/{id}`.
    """
    if not factura or not factura.get("id"):
        raise FacturaInvalida("no hay factura que acreditar")
    sello = factura.get("stamp") or {}
    if sello and str(sello.get("status") or "").strip().lower() != "accepted":
        # Siigo no acredita una factura que la DIAN no ha validado, y lo dice
        # con un `invalid_document` que no explica nada.
        raise FacturaInvalida(
            f"la DIAN todavía no valida la factura {factura.get('name', '')}")
    faltan = {str(k).upper(): int(v) for k, v in devueltas.items() if int(v) > 0}
    if not faltan:
        raise FacturaInvalida("la devolución no trae prendas")

    lineas, total = [], Decimal("0")
    for it in factura.get("items") or []:
        codigo = str(it.get("code") or "").upper()
        tiene = int(float(it.get("quantity") or 0))
        if codigo not in faltan or tiene <= 0:
            continue
        cantidad = min(faltan[codigo], tiene)
        faltan[codigo] -= cantidad
        if not faltan[codigo]:
            del faltan[codigo]
        precio, pct = _precio_y_descuento(it)
        linea = {
            "code": it.get("code"),
            "description": it.get("description") or "",
            "quantity": cantidad,
            "price": float(precio),
            "taxes": ([{"id": t.get("id")} for t in (it.get("taxes") or [])
                       if t.get("id")] or [{"id": IVA_19_ID}]),
        }
        # Sólo lo que la factura sacó de una bodega vuelve a una. El flete
        # («13», un SERVICIO) no tiene bodega, y mandársela es «The warehouse
        # cannot be used» (FE-65713, 14-oct).
        if it.get("warehouse"):
            bodega = _numero_plano(bodega_id if bodega_id is not None
                                   else it.get("warehouse"))
            if bodega is not None:
                linea["warehouse"] = bodega
        if pct is not None:
            linea["discount"] = pct
        lineas.append(linea)
        total += _total_de(it, cantidad)
    if faltan:
        # No se acredita «lo que se pueda»: una nota crédito por menos de lo
        # devuelto dejaría un saldo a favor que Siigo no respalda.
        raise FacturaInvalida(
            "la factura no trae lo que se devolvió: "
            + ", ".join(f"{n}× {c}" for c, n in sorted(faltan.items())))

    cliente = factura.get("customer") or {}
    cuerpo = {
        "document": {"id": int(documento_id)},
        "date": fecha,
        "invoice": factura["id"],
        "customer": {"identification": cliente.get("identification"),
                     "branch_office": cliente.get("branch_office", 0)},
        "items": lineas,
        "payments": [{"id": ANTICIPO_CLIENTES_ID, "value": float(total),
                      "due_date": fecha}],
        "reason": MOTIVO_DEVOLUCION_PARCIAL,
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
