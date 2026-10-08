"""Armar la factura de una venta del POS para Siigo. Puro: sin red y sin base.

Aquí vive la traducción entre dos formas de contar la misma plata, y casi
todo lo que puede salir mal en una factura sale de ahí:

* **El POS piensa en precios CON IVA**, que es lo que dice la etiqueta y lo
  que paga la clienta. **Siigo recibe el precio SIN IVA** y calcula el
  impuesto él. $149.900 viaja como $125.966,39.

* **Siigo redondea a centavos, y un centavo rechaza la factura.** Dos jeans
  de $149.900 son $299.800 para el POS; Siigo llega a $299.800,01, porque
  redondea la base de cada línea antes de aplicar el 19 %. Si los pagos suman
  $299.800,00, la factura no entra. Por eso los pagos se cuadran contra el
  total QUE VA A CALCULAR SIIGO (`total_siigo`), no contra el del POS. La
  diferencia es de centavos y queda escrita en el resumen.

* **A Siigo van los pagos NETOS.** Si la clienta entregó $300.000 por
  $299.800, la factura dice $299.800 en efectivo: el vuelto no es un pago.

* **El descuento depende del comprobante.** Unos lo esperan en pesos y otros
  en porcentaje (`discount_type` del tipo de documento). Escribirlo fijo saca
  una factura con el monto equivocado y SIN error. Ante un tipo desconocido
  no se emite: una factura mal descontada ya salió a la DIAN.

Todo se calcula con `Decimal`; los `float` aparecen sólo al final, en el JSON.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import List, Optional

__all__ = ["construir_factura", "FacturaInvalida", "CONSUMIDOR_FINAL",
           "IVA_19_ID", "marca_de"]

#  El «tercero» de las ventas sin clienta. Existe en la cuenta de Siigo
#  (verificado 2026-10-08: «Consumidor Final», sucursal 0).
CONSUMIDOR_FINAL = "222222222222"
#  Id del impuesto «IVA 19%» en la cuenta. No es el porcentaje: es el id.
IVA_19_ID = 6352

_CENT = Decimal("0.01")


class FacturaInvalida(Exception):
    """Esta venta no se puede facturar tal como está. No mejora por insistir."""


def _c(valor) -> Decimal:
    return Decimal(str(valor)).quantize(_CENT, rounding=ROUND_HALF_UP)


def marca_de(venta_id: str, numero: str) -> str:
    """El rastro que deja el POS en la factura, para poder reencontrarla.

    Siigo no tiene llave de idempotencia. Si el envío se corta sin respuesta,
    la única forma de saber si la factura llegó es buscarla — y para eso
    tiene que llevar algo que sólo ella tenga. Va en `observations`.
    """
    return f"POS {numero} · {venta_id}"


def construir_factura(*, venta: dict, lineas: List[dict], pagos: List[dict],
                      documento_id: int, tipo_descuento: Optional[str],
                      vendedor_id: int, fecha: str,
                      identificacion: Optional[str] = None,
                      bodega_id: Optional[int] = None,
                      centro_costo_id: Optional[int] = None,
                      estampar: bool = False) -> dict:
    """El cuerpo de `POST /invoices`. No emite nada.

    `lineas`: sku, descripcion, cantidad, precio_unitario y descuento_monto en
    CENTAVOS CON IVA, y `tasa_iva`.
    `pagos`: `siigo_forma_pago_id` y `neto` en centavos — lo que ENTRÓ por ese
    medio, ya sin el vuelto.

    Devuelve el payload con una clave `_resumen` (que NO se envía) con lo que
    hace falta para auditar la traducción.
    """
    if not lineas:
        raise FacturaInvalida("la venta no tiene líneas")

    items = []
    total_siigo = Decimal("0")
    for l in lineas:
        tasa = Decimal(str(l.get("tasa_iva", "19")))
        if tasa != Decimal("19"):
            # Sólo está mapeado el impuesto del 19 %. Mandar otra tasa con el
            # id del 19 cuadra en todo menos en lo declarado a la DIAN.
            raise FacturaInvalida(
                f"{l['sku']}: IVA del {tasa} % sin impuesto de Siigo asignado")
        factor = Decimal("1") + tasa / Decimal("100")
        cantidad = int(l["cantidad"])

        precio_base = _c(Decimal(int(l["precio_unitario"])) / 100 / factor)
        if precio_base <= 0:
            raise FacturaInvalida(
                f"{l['sku']}: precio en cero. Un obsequio no se factura así.")
        bruto = _c(precio_base * cantidad)
        descuento_base = _c(Decimal(int(l.get("descuento_monto") or 0)) / 100 / factor)
        if descuento_base > bruto:
            raise FacturaInvalida(f"{l['sku']}: el descuento supera el precio")

        item = {
            "code": l["sku"],
            "description": (l.get("descripcion") or l["sku"])[:150],
            "quantity": cantidad,
            "price": float(precio_base),
            "taxes": [{"id": IVA_19_ID}],
        }
        if descuento_base > 0:
            item["discount"] = _descuento(tipo_descuento, bruto, descuento_base,
                                          l["sku"])
        if bodega_id is not None:
            # NÚMERO, no `{"id": …}`: mal formado, Siigo lo descarta sin
            # error y el inventario no se mueve.
            item["warehouse"] = int(bodega_id)
        items.append(item)

        neto = bruto - descuento_base
        total_siigo += neto + _c(neto * tasa / Decimal("100"))

    payments, ajuste = _pagos(pagos, total_siigo, fecha)

    total_pos = Decimal(int(venta["total"])) / 100
    payload = {
        "document": {"id": int(documento_id)},
        "date": fecha,
        "customer": {
            "identification": (identificacion or CONSUMIDOR_FINAL).strip(),
            "branch_office": 0,
        },
        "seller": int(vendedor_id),
        "items": items,
        "payments": payments,
        "observations": marca_de(venta["id"], venta["numero"]),
        "_resumen": {
            "total_pos": float(total_pos),
            "total_siigo": float(total_siigo),
            # Centavos que se movieron en un pago para cuadrar con Siigo.
            "ajuste_centavos": float(ajuste),
        },
    }
    if centro_costo_id is not None:
        payload["cost_center"] = int(centro_costo_id)
    # Sin `stamp`, Siigo guarda el documento y NO lo manda a la DIAN: queda
    # revisable y borrable. Es lo que permite probar sin consecuencias.
    if estampar:
        payload["stamp"] = {"send": True}

    # Un peso de diferencia ya no es redondeo: es que se tradujo mal una
    # línea. Mejor no emitir que emitir por otro valor.
    if abs(total_siigo - total_pos) > Decimal("1"):
        raise FacturaInvalida(
            f"el total para Siigo ({total_siigo}) no coincide con el de la "
            f"venta ({total_pos})")
    return payload


def _descuento(tipo: Optional[str], bruto: Decimal, descuento: Decimal,
               sku: str):
    t = (tipo or "").strip().lower()
    if t == "value":
        return float(descuento)
    if t == "percentage":
        return float((descuento * 100 / bruto).quantize(Decimal("0.0001"),
                                                        rounding=ROUND_HALF_UP))
    raise FacturaInvalida(
        f"{sku}: el comprobante no dice si el descuento va en pesos o en "
        f"porcentaje ({tipo!r}). No se emite a ciegas.")


def _pagos(pagos: List[dict], total_siigo: Decimal, fecha: str):
    """Los pagos, sumando EXACTAMENTE lo que Siigo va a calcular."""
    por_forma: dict = {}
    for p in pagos:
        neto = Decimal(int(p["neto"])) / 100
        if neto <= 0:
            continue
        forma = p.get("siigo_forma_pago_id")
        if forma is None:
            raise FacturaInvalida(
                f"el medio «{p.get('medio_pago_id')}» no tiene forma de pago "
                f"en Siigo")
        por_forma[int(forma)] = por_forma.get(int(forma), Decimal("0")) + neto
    if not por_forma:
        raise FacturaInvalida("la venta no tiene pagos")

    ajuste = total_siigo - sum(por_forma.values())
    if abs(ajuste) > Decimal("1"):
        raise FacturaInvalida(
            f"los pagos ({sum(por_forma.values())}) no cubren el total "
            f"({total_siigo})")
    # Los centavos van al pago más grande: es donde menos se notan y nunca lo
    # dejan en negativo.
    mayor = max(por_forma, key=lambda k: por_forma[k])
    por_forma[mayor] += ajuste

    return ([{"id": forma, "value": float(_c(valor)), "due_date": fecha}
             for forma, valor in por_forma.items()], ajuste)
