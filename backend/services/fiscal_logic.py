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

    'prueba' usa la NC Proforma (NoElectronic): ejercita todo el flujo
    contra la cuenta real SIN emitir ante la DIAN.
    """
    if modo == "produccion":
        return {"nota_credito_id": NC_ELECTRONICA_ID, "factura_id": FV_ONLINE_ID,
                "electronico": True}
    return {"nota_credito_id": NC_PROFORMA_ID, "factura_id": FV_ONLINE_ID,
            "electronico": False}


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
                                   modo: str, fecha: str) -> dict:
    """Arma el cuerpo del POST de la nota crédito. NO emite nada.

    Los montos se COPIAN de la factura original (ítems por SKU), no del panel.
    Forma de pago: ANTICIPO CLIENTES (deja saldo a favor de la clienta).
    """
    if not factura or not factura.get("id"):
        raise ValueError("sin_factura_original")
    lineas = items_factura_por_sku(factura, skus_a_acreditar)
    if not lineas:
        raise ValueError("items_no_encontrados")

    cfg = config_documentos(modo)
    cliente = factura.get("customer") or {}
    total = _total_con_iva_de_lineas(lineas)

    return {
        "document": {"id": cfg["nota_credito_id"]},
        "date": fecha,
        "invoice": factura["id"],
        "customer": {
            "identification": cliente.get("identification"),
            "branch_office": cliente.get("branch_office", 0),
        },
        "seller": factura.get("seller") or VENDEDOR_ONLINE_ID,
        "items": [_linea_nc(it) for it in lineas],
        "payments": [{"id": ANTICIPO_CLIENTES_ID, "value": total}],
        "observations": f"Postventa — anula ítems de {factura.get('name', '')}",
    }


def _linea_nc(it: dict) -> dict:
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
                                        modo: str, fecha: str) -> dict:
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
    payments = [{"id": ANTICIPO_CLIENTES_ID, "value": anticipo_aplicado}]
    if excedente > 0:
        payments.append({"id": EXCEDENTE_PAYMENT_ID, "value": excedente})

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

    return {
        "document": {"id": cfg["factura_id"]},
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
