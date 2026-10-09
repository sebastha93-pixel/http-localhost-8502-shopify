"""Armar la factura de una venta del POS para Siigo. Puro: sin red y sin base.

Aquí vive la traducción entre dos formas de contar la misma plata, y casi
todo lo que puede salir mal en una factura sale de ahí.

**LA FACTURA TIENE QUE DAR EXACTAMENTE LO QUE COBRÓ LA CAJA.** No «casi»: la
DIAN valida el valor que calcule Siigo, y si es $434.710,01 cuando la clienta
pagó $434.710, la factura dice una cosa y la tirilla y el arqueo otra. Pasó
con la primera factura de prueba (`ARRT-1`, 2026-10-09): mandando la base
redondeada a dos decimales, dos jeans de $149.900 dieron $299.800,01.

LA ARITMÉTICA DE SIIGO, verificada contra la API por el Portal Mayoristas
(`lib/siigo/aritmetica.ts`, 2026-08-03) y aquí en ENTEROS por la misma razón
—un centavo decide si la factura entra—:

    base     = precio con IVA / 1,19, a SEIS decimales
    bruto    = cantidad · base
    desc     = redondear(bruto · pct / 100, centavos)
    subtotal = bruto − desc
    iva      = redondear(subtotal · 0,19, centavos)
    total    = redondear(subtotal, centavos) + iva

De ahí salen las tres formas en que viaja una línea:

* **Sin descuento → `taxed_price`**: el precio CON IVA, tal cual la etiqueta.
  Siigo deriva la base con sus seis decimales y el total da `cantidad ×
  precio` exactos.

* **Descuento que es un porcentaje ENTERO → `price` + `discount`**. Siigo sólo
  acepta el porcentaje entero (`25.0000119` → 400), y con el precio de lista
  casi nunca cuadra al centavo. Se BUSCA una base a millonésimas de la
  nominal con la que el total dé exacto — sin que `base × 1,19` deje de ser
  el precio de lista de verdad.

* **Cualquier otro descuento («$20.000 menos») → el precio ya rebajado**, en
  `taxed_price` y sin campo de descuento. La factura dice lo que se cobró,
  que es lo que importa; el descuento queda en el POS, con su motivo.

Lo demás:

* **A Siigo van los pagos NETOS.** Si la clienta entregó $300.000 por
  $299.800, la factura dice $299.800 en efectivo: el vuelto no es un pago.

* **Los pagos suman lo que va a calcular Siigo**, que con lo de arriba es lo
  mismo que cobró la caja. Si alguna vez difieren en centavos, se ajusta el
  pago más grande y queda escrito en el resumen; más de un peso, no se emite.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import List, Optional

__all__ = ["construir_factura", "FacturaInvalida", "CONSUMIDOR_FINAL",
           "IVA_19_ID", "marca_de", "base6_de", "total_linea",
           "base_con_descuento"]

#  El «tercero» de las ventas sin clienta. Existe en la cuenta de Siigo
#  (verificado 2026-10-08: «Consumidor Final», sucursal 0).
CONSUMIDOR_FINAL = "222222222222"
#  Id del impuesto «IVA 19%» en la cuenta. No es el porcentaje: es el id.
IVA_19_ID = 6352

_CENT = Decimal("0.01")

#  Millonésimas de peso por centavo: Siigo guarda `price` con 6 decimales.
_POR_CENTAVO = 10_000
#  Cuánto se puede mover la base buscando el encaje: 0,02 pesos. Con eso
#  `base × 1,19` sigue redondeando al mismo precio de lista.
_VENTANA = 20_000


class FacturaInvalida(Exception):
    """Esta venta no se puede facturar tal como está. No mejora por insistir."""


def _c(valor) -> Decimal:
    return Decimal(str(valor)).quantize(_CENT, rounding=ROUND_HALF_UP)


def _div(n: int, d: int) -> int:
    """División entera con redondeo HALF-UP (positivos)."""
    q, r = divmod(n, d)
    return q + 1 if 2 * r >= d else q


def base6_de(precio_centavos: int) -> int:
    """La base sin IVA que Siigo deriva de un precio con IVA, en millonésimas."""
    return _div(precio_centavos * _POR_CENTAVO * 100, 119)


def total_linea(cantidad: int, base6: int, pct: int = 0) -> int:
    """El total de UNA línea, en centavos, como lo calcula Siigo."""
    bruto = cantidad * base6
    desc = _div(bruto * pct, 100 * _POR_CENTAVO)              # centavos
    subtotal = bruto - desc * _POR_CENTAVO                    # millonésimas
    iva = _div(subtotal * 19, 100 * _POR_CENTAVO)             # centavos
    return _div(subtotal, _POR_CENTAVO) + iva


def base_con_descuento(cantidad: int, precio: int, neto_linea: int,
                       pct: int) -> Optional[int]:
    """Una base (millonésimas) con la que Siigo, aplicando `pct`, calcule
    EXACTAMENTE `neto_linea` centavos. `None` si no hay encaje.

    Se comprueba además que `base × 1,19` siga siendo el precio de lista: el
    documento declara ese `price`, y no puede decirle a la DIAN un precio de
    venta que la marca no tiene.
    """
    nominal = base6_de(precio)
    for paso in range(_VENTANA + 1):
        for signo in ((0,) if paso == 0 else (1, -1)):
            b = nominal + signo * paso
            if b <= 0 or total_linea(cantidad, b, pct) != neto_linea:
                continue
            if _div(b * 119, 100 * _POR_CENTAVO) != precio:
                continue
            return b
    return None


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
                      estampar: bool = False,
                      enviar_correo: bool = False) -> dict:
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

    porcentaje = (tipo_descuento or "").strip().lower() == "percentage"
    items = []
    total_cent = 0
    for l in lineas:
        tasa = Decimal(str(l.get("tasa_iva", "19")))
        if tasa != Decimal("19"):
            # Sólo está mapeado el impuesto del 19 %. Mandar otra tasa con el
            # id del 19 cuadra en todo menos en lo declarado a la DIAN.
            raise FacturaInvalida(
                f"{l['sku']}: IVA del {tasa} % sin impuesto de Siigo asignado")
        cantidad = int(l["cantidad"])
        precio = int(l["precio_unitario"])
        if precio <= 0 or cantidad <= 0:
            raise FacturaInvalida(
                f"{l['sku']}: precio en cero. Un obsequio no se factura así.")
        descuento = int(l.get("descuento_monto") or 0)
        neto = cantidad * precio - descuento
        if neto <= 0:
            raise FacturaInvalida(
                f"{l['sku']}: el descuento se lleva todo el precio. Un "
                f"obsequio no se factura así.")

        def item(cant: int, **precio_kw) -> dict:
            it = {"code": l["sku"],
                  "description": (l.get("descripcion") or l["sku"])[:150],
                  "quantity": cant, **precio_kw,
                  "taxes": [{"id": IVA_19_ID}]}
            if bodega_id is not None:
                # NÚMERO, no `{"id": …}`: mal formado, Siigo lo descarta sin
                # error y el inventario no se mueve.
                it["warehouse"] = int(bodega_id)
            return it

        if descuento == 0:
            items.append(item(cantidad, taxed_price=precio / 100))
            total_cent += total_linea(cantidad, base6_de(precio))
            continue

        # ¿Es un porcentaje entero? Sólo así Siigo acepta el campo `discount`.
        bruto = cantidad * precio
        pct = descuento * 100 // bruto if descuento * 100 % bruto == 0 else 0
        base = (base_con_descuento(cantidad, precio, neto, pct)
                if porcentaje and 0 < pct < 100 else None)
        if base is not None:
            items.append(item(cantidad, price=base / 1_000_000, discount=pct))
            total_cent += total_linea(cantidad, base, pct)
            continue

        # El precio YA REBAJADO, sin campo de descuento. Si no divide exacto
        # entre las unidades, cada unidad va en su línea con su centavo.
        if neto % cantidad == 0:
            reparto = [(cantidad, neto // cantidad)]
        else:
            reparto = [(1, neto // cantidad + (1 if u < neto % cantidad else 0))
                       for u in range(cantidad)]
        for cant, unitario in reparto:
            items.append(item(cant, taxed_price=unitario / 100))
            total_cent += total_linea(cant, base6_de(unitario))

    total_siigo = Decimal(total_cent) / 100

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
    if enviar_correo:
        # Siigo le manda la factura al correo que la clienta tiene en su ficha.
        payload["mail"] = {"send": True}

    # Un peso de diferencia ya no es redondeo: es que se tradujo mal una
    # línea. Mejor no emitir que emitir por otro valor.
    if abs(total_siigo - total_pos) > Decimal("1"):
        raise FacturaInvalida(
            f"el total para Siigo ({total_siigo}) no coincide con el de la "
            f"venta ({total_pos})")
    return payload


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
