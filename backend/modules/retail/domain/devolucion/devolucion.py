"""Devolución — el agregado de la vista 5 del handoff.

UNA DEVOLUCIÓN NO ES UNA ANULACIÓN, y la diferencia decide dónde vive cada
cosa:

  · **Anulación** (INV-V11, `AnularVenta`) deshace una venta del turno EN
    CURSO. La plata vuelve del mismo arqueo que la recibió y no hace falta
    documento fiscal, porque muchas veces todavía no se emitió ninguno.

  · **Devolución** (esto) llega días después. La factura ya salió y el arqueo
    de ese día está cerrado y firmado, así que hace falta NOTA CRÉDITO — y la
    nota crédito la emite POSTVENTA, que es donde vive el motor fiscal desde
    hace meses y en producción. Construir aquí un segundo emisor sería tener
    dos sistemas capaces de anular la misma factura.

Entonces, ¿qué protege este agregado, si lo fiscal es de otro? Justo lo que
Postventa no puede saber, porque no tiene el libro de ventas del POS:

    cuánto se vendió, cuánto se devolvió ya, y si lo que la cajera está
    pidiendo cabe dentro de eso.

Ésa es la regla que evita pagar dos veces la misma prenda, y no se puede
comprobar ni en la pantalla ni en Postventa.

LAS INVARIANTES:

  INV-D1  no se devuelve más de lo vendido, descontando lo ya devuelto
  INV-D2  al menos un artículo, y en cantidad mayor que cero
  INV-D3  una venta anulada no se devuelve
  INV-D4  el reembolso en efectivo exige un turno abierto
  INV-D5  motivo y método son valores cerrados (ver `motivo.py`)
  INV-D6  el IVA se deriva por línea del precio de vitrina, nunca del total

INV-D6 es la misma regla que INV-V12 y por la misma razón: sumar y después
partir mete un peso de diferencia que a fin de mes nadie sabe explicar. Aquí
además importa el doble, porque ese número va en una nota crédito ante la DIAN.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Mapping

from backend.modules.retail.domain.devolucion.motivo import MotivoDevolucion
from backend.modules.retail.domain.devolucion.reembolso import Reembolso
from backend.modules.retail.domain.shared.dinero import Dinero
from backend.modules.retail.domain.shared.impuestos import separar_iva
from backend.modules.retail.domain.venta.errores import ReglaDeNegocio

__all__ = ["Devolucion", "LineaVendida", "LineaDevuelta"]


@dataclass(frozen=True)
class LineaVendida:
    """Lo que la venta original dejó escrito. Sólo lectura."""

    sku: str
    cantidad: int
    precio_unitario_con_iva_centavos: int


@dataclass(frozen=True)
class LineaDevuelta:
    """Lo que vuelve.

    Lleva su PROPIO precio unitario, copiado de la venta y no consultado al
    catálogo: si la referencia subió de precio desde que se vendió, devolver
    al precio de hoy sería regalarle plata a la clienta — o quitársela.
    """

    sku: str
    cantidad: int
    precio_unitario_con_iva_centavos: int

    @property
    def total_centavos(self) -> int:
        return self.cantidad * self.precio_unitario_con_iva_centavos


class Devolucion:
    def __init__(self, *, venta_id: str, numero: str,
                 lineas: List[LineaDevuelta], motivo: MotivoDevolucion,
                 reembolso: Reembolso, moneda: str) -> None:
        self.venta_id = venta_id
        self.numero = numero
        self.lineas = lineas
        self.motivo = motivo
        self.reembolso = reembolso
        self.moneda = moneda

    # ── Construcción con todas las guardas ──────────────────────────────────

    @classmethod
    def armar(cls, *, venta_id: str, numero: str,
              lineas_vendidas: List[LineaVendida],
              ya_devuelto: Mapping[str, int],
              seleccion: Mapping[str, int],
              motivo: MotivoDevolucion,
              reembolso: Reembolso,
              moneda: str,
              venta_anulada: bool,
              turno_abierto: bool) -> "Devolucion":
        """El ÚNICO camino para crear una devolución.

        No hay `__init__` público útil: si alguien pudiera construir el objeto
        saltándose esto, las cinco invariantes serían decoración. Por eso todas
        las guardas están aquí y no repartidas por el endpoint.
        """
        # INV-D3 primero: si la venta ya se deshizo entera, no hay nada más
        # que comprobar y el mensaje correcto es ése, no «no se vendieron
        # tantas».
        if venta_anulada:
            raise ReglaDeNegocio(
                f"La venta {numero} está anulada: su plata ya volvió por el "
                f"arqueo. No se puede devolver otra vez.")

        vendidas: Dict[str, LineaVendida] = {l.sku: l for l in lineas_vendidas}

        lineas: List[LineaDevuelta] = []
        for sku, cantidad in seleccion.items():
            if cantidad == 0:
                # No es un error: es una casilla sin marcar. Se ignora y, si
                # al final no quedó ninguna, cae en la guarda de INV-D2.
                continue
            if cantidad < 0:
                raise ReglaDeNegocio(
                    f"La cantidad a devolver de {sku} tiene que ser mayor que cero.")

            original = vendidas.get(sku)
            if original is None:
                raise ReglaDeNegocio(
                    f"La referencia {sku} no está en la venta {numero}.")

            # INV-D1. El saldo, no la cantidad vendida: es lo que impide pagar
            # dos veces la misma prenda cuando la clienta vuelve por segunda vez.
            devuelto = int(ya_devuelto.get(sku, 0))
            saldo = original.cantidad - devuelto
            if saldo <= 0:
                raise ReglaDeNegocio(
                    f"De {sku} ya se devolvió completa la cantidad vendida.")
            if cantidad > saldo:
                if devuelto:
                    raise ReglaDeNegocio(
                        f"De {sku} se vendieron {original.cantidad} y ya se "
                        f"devolvieron {devuelto}: queda {saldo}.")
                raise ReglaDeNegocio(
                    f"De {sku} se vendieron {original.cantidad}, no se pueden "
                    f"devolver {cantidad}.")

            lineas.append(LineaDevuelta(
                sku=sku, cantidad=cantidad,
                precio_unitario_con_iva_centavos=(
                    original.precio_unitario_con_iva_centavos)))

        # INV-D2
        if not lineas:
            raise ReglaDeNegocio(
                "Marca al menos un artículo para devolver.")

        # INV-D4. Va al final porque es la única que la cajera puede resolver
        # sin cambiar nada de lo que eligió: basta con abrir el turno.
        if reembolso.sale_del_cajon and not turno_abierto:
            raise ReglaDeNegocio(
                "Para devolver en efectivo hace falta un turno abierto: la "
                "plata sale de un cajón y tiene que quedar anotada en su arqueo.")

        return cls(venta_id=venta_id, numero=numero, lineas=lineas,
                   motivo=motivo, reembolso=reembolso, moneda=moneda)

    # ── Lo que el agregado calcula ──────────────────────────────────────────

    @property
    def total(self) -> Dinero:
        return Dinero(sum(l.total_centavos for l in self.lineas), self.moneda)

    @property
    def unidades(self) -> int:
        return sum(l.cantidad for l in self.lineas)

    @property
    def base_gravable(self) -> Dinero:
        """INV-D6. Línea por línea, nunca partiendo el total."""
        return Dinero(
            sum(separar_iva(l.total_centavos)[0] for l in self.lineas),
            self.moneda)

    @property
    def iva(self) -> Dinero:
        return Dinero(
            sum(separar_iva(l.total_centavos)[1] for l in self.lineas),
            self.moneda)

    @property
    def sale_del_cajon(self) -> bool:
        """Si esta devolución mueve el arqueo del turno en curso."""
        return self.reembolso.sale_del_cajon
