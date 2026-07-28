"""
backend.services.fiscal_logic — Lógica PURA del motor fiscal.

Sin I/O: extracción del nº de pedido, configuración por modo y armado del
payload de la nota crédito. Todo testeable sin red ni DB.

IDs verificados contra la cuenta Siigo de MALE (ver spec del motor fiscal).
Los montos de la NC se COPIAN de la factura original (no se recalculan del
panel) para que el documento cuadre al centavo con la DIAN.
"""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Optional

# ── IDs de la cuenta ─────────────────────────────────────────────────
NC_ELECTRONICA_ID = 11817     # Nota Crédito Electrónica (va a DIAN)
NC_PROFORMA_ID = 27141        # Nota Crédito Proforma (NoElectronic, modo prueba)
FV_ONLINE_ID = 11810          # Factura de venta online ("Domicilios")
IVA_19_ID = 6352
VENDEDOR_ONLINE_ID = 658
ANTICIPO_CLIENTES_ID = 8316   # Forma de pago de la NC (no toca banco, deja saldo)

# Motivo DIAN de la nota crédito (campo `reason`, obligatorio en electrónicas).
# 1 = Devolución parcial de los bienes / no aceptación parcial del servicio.
# Es el que aplica a un cambio o devolución de prenda.
REASON_DEVOLUCION_PARCIAL = 1

IVA_PORCENTAJE = Decimal("19")

# "Orden Nº: 60112 - Medio de Pago: ..."  → 60112
ORDEN_RE = re.compile(r"orden\s*n[ºo°]?\s*:?\s*(\d+)", re.IGNORECASE)


# ── Extracción del pedido ────────────────────────────────────────────
def extraer_numero_pedido(observations: str) -> Optional[str]:
    """Saca el nº de pedido Shopify del campo observations de la factura."""
    if not observations:
        return None
    m = ORDEN_RE.search(observations)
    return m.group(1) if m else None


def normalizar_numero_pedido(order_name: str) -> str:
    """'#60112' → '60112'. Lo que guarda el caso vs lo que trae Siigo."""
    return (order_name or "").strip().lstrip("#").strip()


# ── Config por modo ──────────────────────────────────────────────────
def config_documentos(modo: str) -> dict:
    """Config de documentos según el modo de operación.

    Siigo EXIGE que la nota crédito tenga el mismo `electronic_type` que la
    factura que acredita (error `invalid_document` si no). Como las ventas
    online se facturan con factura ELECTRÓNICA, la NC debe ser la electrónica
    (11817) en ambos modos — una Proforma no puede aplicarse a una factura
    electrónica.

    La diferencia entre modos es el ESTAMPADO ante la DIAN:
      - 'prueba':     stamp ausente → Siigo lo toma como false → NO va a la DIAN.
                      El documento queda en Siigo, revisable y borrable.
      - 'produccion': stamp true → se envía a la DIAN (irreversible).
    """
    return {
        "nota_credito_id": NC_ELECTRONICA_ID,
        "factura_id": FV_ONLINE_ID,
        "electronico": True,
        "estampar": modo == "produccion",
    }


# ── Montos ───────────────────────────────────────────────────────────
def calcular_iva(valor_sin_iva: float) -> float:
    """IVA 19% sobre un valor SIN iva. Decimal para no arrastrar error float."""
    v = Decimal(str(valor_sin_iva))
    return float((v * IVA_PORCENTAJE / Decimal("100")).quantize(Decimal("0.01")))


def total_con_iva(valor_sin_iva: float) -> float:
    return float(
        (Decimal(str(valor_sin_iva)) + Decimal(str(calcular_iva(valor_sin_iva))))
        .quantize(Decimal("0.01"))
    )


def _total_con_iva_de_lineas(lineas: list[dict]) -> float:
    """Total CON IVA de líneas de factura Siigo (price es base, sin IVA)."""
    subtotal = Decimal("0")
    for it in lineas:
        subtotal += Decimal(str(it.get("price") or 0)) * Decimal(str(it.get("quantity") or 1))
    iva = subtotal * IVA_PORCENTAJE / Decimal("100")
    return float((subtotal + iva).quantize(Decimal("0.01")))


def factura_aceptada_dian(factura: dict) -> bool:
    """True si la DIAN ya aceptó la factura.

    Una nota crédito ELECTRÓNICA solo puede aplicarse a una factura que la
    DIAN ya validó. Las ventas del día suelen estar en proceso, y Siigo las
    rechaza con `invalid_document` en el campo `invoice` — un error que no
    dice la causa real.
    """
    stamp = factura.get("stamp") or {}
    estado = str(stamp.get("status") or "").strip().lower()
    # Siigo devuelve "Accepted" cuando la DIAN la validó. Sin stamp (no
    # electrónica) no aplica esta restricción.
    if not stamp:
        return True
    return estado == "accepted"


def motivo_factura_no_apta(factura: dict) -> str:
    """Explicación legible de por qué no se le puede hacer nota crédito."""
    stamp = factura.get("stamp") or {}
    estado = str(stamp.get("status") or "").strip()
    if not estado:
        return "la factura no tiene sello DIAN"
    return (f"la DIAN aún no acepta la factura {factura.get('name', '')} "
            f"(estado: {estado}). Una nota crédito electrónica solo puede "
            f"aplicarse a facturas ya validadas — normalmente toma unas horas.")


# ── Nota crédito ─────────────────────────────────────────────────────
def items_factura_por_sku(factura: dict, skus: list[str]) -> list[dict]:
    """Ítems de la factura original cuyo `code` está en `skus`.

    Copia el ítem TAL CUAL viene de Siigo (price base, taxes) para que la
    nota crédito cuadre al centavo con la factura. NO recalcula precios.
    """
    objetivo = {s for s in skus if s}
    return [it for it in (factura.get("items") or [])
            if it.get("code") in objetivo]


def construir_payload_nota_credito(*, factura: dict, skus_a_acreditar: list[str],
                                   modo: str, fecha: str,
                                   bodega_destino: Optional[int] = None) -> dict:
    """Arma el cuerpo del POST de la nota crédito. NO emite nada.

    Los montos se COPIAN de la factura original (ítems por SKU), no del panel.
    Forma de pago: ANTICIPO CLIENTES (deja saldo a favor de la clienta).
    """
    if not factura or not factura.get("id"):
        raise ValueError("sin_factura_original")
    # La DIAN debe haber aceptado la factura antes de acreditarla.
    if not factura_aceptada_dian(factura):
        raise ValueError("factura_no_aceptada_dian")
    lineas = items_factura_por_sku(factura, skus_a_acreditar)
    if not lineas:
        raise ValueError("items_no_encontrados")

    cfg = config_documentos(modo)
    cliente = factura.get("customer") or {}
    total = _total_con_iva_de_lineas(lineas)

    payload = {
        "document": {"id": cfg["nota_credito_id"]},
        "date": fecha,
        "invoice": factura["id"],
        "customer": {
            "identification": cliente.get("identification"),
            "branch_office": cliente.get("branch_office", 0),
        },
        "seller": factura.get("seller") or VENDEDOR_ONLINE_ID,
        # bodega_destino: en un cambio EN TIENDA la prenda entra al inventario
        # de esa tienda, no a la bodega de donde salió la venta online. Evita
        # tener que hacer después un traslado manual en Siigo.
        "items": [_linea_nc(it, bodega_destino=bodega_destino) for it in lineas],
        # ANTICIPO CLIENTES maneja vencimiento (due_date: true en /payment-types),
        # así que Siigo exige due_date. Se usa la fecha del documento.
        "payments": [{"id": ANTICIPO_CLIENTES_ID, "value": total,
                      "due_date": fecha}],
        # Motivo DIAN: obligatorio en notas crédito electrónicas.
        "reason": REASON_DEVOLUCION_PARCIAL,
        "observations": f"Postventa — anula ítems de {factura.get('name', '')}",
    }
    # stamp solo en producción: ausente = Siigo lo toma false = NO va a la DIAN.
    if cfg.get("estampar"):
        payload["stamp"] = {"send": True}
    return payload


def _linea_nc(it: dict, *, bodega_destino: Optional[int] = None) -> dict:
    """Convierte un ítem de la factura Siigo en un ítem de nota crédito.

    Copia lo que el POST necesita: code, cantidad, precio base y —crítico para
    que Siigo no rechace— el vendedor, la bodega y los impuestos SOLO por id
    (en el GET vienen expandidos con name/percentage/value; el POST espera {id}).
    """
    taxes = it.get("taxes") or []
    linea = {
        "code": it.get("code"),
        "description": it.get("description") or "",
        "quantity": it.get("quantity") or 1,
        "price": it.get("price"),
        "taxes": ([{"id": t.get("id")} for t in taxes if t.get("id")]
                  or [{"id": IVA_19_ID}]),
    }
    if it.get("seller"):
        linea["seller"] = it["seller"]
    # Bodega: el producto es de inventario (ej. MELONN). Se copia para que la
    # NC devuelva el stock a la misma bodega de la factura.
    if bodega_destino is not None:
        linea["warehouse"] = {"id": int(bodega_destino)}
    else:
        wh = it.get("warehouse")
        if isinstance(wh, dict) and wh.get("id") is not None:
            linea["warehouse"] = {"id": wh["id"]}
        elif isinstance(wh, (int, str)) and wh not in ("", None):
            linea["warehouse"] = {"id": wh}
    if it.get("discount"):
        linea["discount"] = it["discount"]
    return linea


# ── Factura del reemplazo ────────────────────────────────────────────
EXCEDENTE_PAYMENT_ID = 8857   # CUENTAS POR COBRAR — excedente que paga la clienta


def base_desde_precio_con_iva(precio_con_iva: float) -> float:
    """Precio Shopify (CON IVA) → base sin IVA. base = precio / 1.19."""
    v = Decimal(str(precio_con_iva))
    factor = Decimal("1") + IVA_PORCENTAJE / Decimal("100")
    return float((v / factor).quantize(Decimal("0.01")))


def construir_payload_factura_reemplazo(*, factura_original: dict,
                                        item_reemplazo: dict,
                                        credito_con_iva: float,
                                        modo: str, fecha: str,
                                        documento_id: Optional[int] = None,
                                        bodega_id: Optional[int] = None,
                                        pago_excedente_id: Optional[int] = None) -> dict:
    """Arma el POST de la factura del reemplazo. NO emite.

    Regla del fundador:
      - El anticipo (saldo de la NC) cubre hasta el valor de la prenda nueva.
      - Si la nueva vale MÁS, la clienta paga el excedente (cuentas por cobrar).
      - Si vale igual o menos, el anticipo cubre todo (el saldo restante queda
        a favor y se maneja aparte).
    `item_reemplazo.price_base` es SIN IVA (misma ref = precio original exacto;
    otra ref = precio Shopify / 1.19).
    """
    if not item_reemplazo or item_reemplazo.get("price_base") is None:
        raise ValueError("sin_item_reemplazo")

    cfg = config_documentos(modo)
    cliente = factura_original.get("customer") or {}
    price_base = Decimal(str(item_reemplazo["price_base"]))
    qty = Decimal(str(item_reemplazo.get("quantity") or 1))
    total = float((price_base * qty * (Decimal("1") + IVA_PORCENTAJE / Decimal("100")))
                  .quantize(Decimal("0.01")))
    credito = float(Decimal(str(credito_con_iva)).quantize(Decimal("0.01")))

    anticipo_aplicado = round(min(credito, total), 2)
    excedente = round(total - anticipo_aplicado, 2)
    # Ambas formas de pago manejan vencimiento → due_date obligatorio.
    payments = [{"id": ANTICIPO_CLIENTES_ID, "value": anticipo_aplicado,
                 "due_date": fecha}]
    if excedente > 0:
        # En tienda el excedente se cobra ahí mismo (datáfono o caja); online
        # queda como cuenta por cobrar.
        payments.append({"id": int(pago_excedente_id or EXCEDENTE_PAYMENT_ID),
                         "value": excedente, "due_date": fecha})

    linea = {
        "code": item_reemplazo.get("code"),
        "description": item_reemplazo.get("description") or "",
        "quantity": int(qty),
        "price": float(price_base),
        "taxes": [{"id": IVA_19_ID}],
    }
    if item_reemplazo.get("seller"):
        linea["seller"] = item_reemplazo["seller"]
    wh = item_reemplazo.get("warehouse")
    if isinstance(wh, dict) and wh.get("id") is not None:
        linea["warehouse"] = {"id": wh["id"]}

    if bodega_id is not None:
        linea["warehouse"] = {"id": int(bodega_id)}

    payload = {
        # documento_id: el punto de venta que factura (Florida FV-11/FV-12,
        # Arrayanes FV-6). Sin él sale con el prefijo de online.
        "document": {"id": int(documento_id) if documento_id else cfg["factura_id"]},
        "date": fecha,
        "customer": {
            "identification": cliente.get("identification"),
            "branch_office": cliente.get("branch_office", 0),
        },
        "seller": factura_original.get("seller") or VENDEDOR_ONLINE_ID,
        "items": [linea],
        "payments": payments,
        "observations": (f"Postventa — reemplazo de {factura_original.get('name', '')} "
                         f"(anticipo {anticipo_aplicado}"
                         + (f" + excedente {excedente}" if excedente > 0 else "") + ")"),
        "_resumen": {"total": total, "anticipo": anticipo_aplicado,
                     "excedente": excedente},
    }
    # Igual que la NC: sin stamp no se envía a la DIAN (modo prueba).
    if cfg.get("estampar"):
        payload["stamp"] = {"send": True}
    return payload
