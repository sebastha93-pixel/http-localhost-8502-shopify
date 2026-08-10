"""Venta — el agregado raíz del módulo retail.

Aquí viven las reglas que protegen la plata. Ninguna de ellas está en un
endpoint, en el frontend ni en un trigger de base de datos: si la pantalla se
salta un paso, el agregado igual se niega.

Las doce invariantes están en docs/retail-pos/02-DOMINIO-DDD.md §3. Las que
gobiernan este archivo:

  INV-V1  una venta cerrada es inmutable
  INV-V2  no se cierra sin al menos una prenda
  INV-V3  no se cierra con menos plata de la debida, y el excedente sólo
          puede venir de efectivo
  INV-V6  un descuento sobre el tope del rol exige firma de quien autoriza
  INV-V7  precio en cero sólo como obsequio autorizado
  INV-V9  cantidad mayor que cero
  INV-V11 anular exige motivo y autorización
  INV-V12 el IVA se calcula por línea

INV-V8 (la venta pertenece a un turno abierto) e INV-V10 (idempotencia) no se
pueden verificar desde aquí: la primera necesita la SesionCaja, la segunda es
un índice único en la base. Se comprueban en la capa de aplicación y en el
esquema, y están documentadas allí.
"""
from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from backend.modules.retail.domain.shared.dinero import Dinero
from backend.modules.retail.domain.shared.sku import Sku
from backend.modules.retail.domain.venta.descuento import Descuento
from backend.modules.retail.domain.venta.errores import (
    ReglaDeNegocio,
    RequiereAutorizacion,
    VentaNoModificable,
)
from backend.modules.retail.domain.venta.estados import EstadoFiscal, EstadoVenta
from backend.modules.retail.domain.venta.eventos import (
    LineaVendida,
    VentaAnulada,
    VentaCerrada,
)
from backend.modules.retail.domain.venta.linea import LineaVenta
from backend.modules.retail.domain.venta.pago import Pago
from backend.modules.retail.domain.venta.politicas import Decision, PoliticaDescuento

__all__ = ["Venta"]

# ULID: 26 caracteres en base32 de Crockford (sin I, L, O, U).
_ULID = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


class Venta:
    """Agregado raíz. Sólo a través de sus métodos se toca una venta."""

    # ── Construcción ────────────────────────────────────────────────────────

    def __init__(
        self,
        *,
        id: str,
        numero: str,
        tienda_id: str,
        caja_id: str,
        sesion_id: str,
        cajera_id: str,
        moneda: str,
        dispositivo_id: Optional[str] = None,
        creada_en: Optional[datetime] = None,
    ) -> None:
        self.id = self._ulid_valido(id, "la venta")
        self.numero = numero
        self.tienda_id = tienda_id
        self.caja_id = caja_id
        self.sesion_id = sesion_id
        self.cajera_id = cajera_id
        self.moneda = moneda
        self.dispositivo_id = dispositivo_id
        self.creada_en = creada_en

        self.estado = EstadoVenta.BORRADOR
        self.estado_fiscal = EstadoFiscal.NO_APLICA
        self.cliente_id: Optional[str] = None
        self.lineas: List[LineaVenta] = []
        self.pagos: List[Pago] = []
        self.cerrada_en: Optional[datetime] = None
        self.anulada_en: Optional[datetime] = None
        self.motivo_anulacion: Optional[str] = None

        self._siguiente_linea = 1
        self._siguiente_pago = 1

    @classmethod
    def abrir(cls, **kw) -> "Venta":
        return cls(**kw)

    @staticmethod
    def _ulid_valido(valor: str, que: str) -> str:
        """El id lo genera el DISPOSITIVO y es la llave de idempotencia.

        Si se acepta cualquier cosa, dos ventas offline distintas pueden
        colisionar —o la misma venta reintentada entrar dos veces (ADR-005).
        """
        if not isinstance(valor, str) or not _ULID.match(valor.strip().upper()):
            raise ReglaDeNegocio(
                f"el identificador de {que} no es un ULID válido: {valor!r}"
            )
        return valor.strip().upper()

    # ── Guardas ─────────────────────────────────────────────────────────────

    def _exigir_borrador(self) -> None:
        """INV-V1. Se emitió un documento fiscal sobre este contenido."""
        if not self.estado.es_mutable():
            raise VentaNoModificable(
                f"La venta {self.numero} ya está {self.estado.value}. "
                f"Para corregirla hay que hacer un documento nuevo, no editarla."
            )

    def _linea(self, numero: int) -> LineaVenta:
        for l in self.lineas:
            if l.numero == numero:
                return l
        raise ReglaDeNegocio(f"la venta no tiene una línea número {numero}")

    def _cero(self) -> Dinero:
        return Dinero.cero(self.moneda)

    # ── Líneas ──────────────────────────────────────────────────────────────

    def agregar_linea(
        self,
        *,
        sku: Sku,
        descripcion: str,
        cantidad: int,
        precio_unitario: Dinero,
        tasa_iva: Decimal,
    ) -> LineaVenta:
        self._exigir_borrador()
        # INV-V5: fuerza la comparación de moneda antes de guardar nada. Sumar
        # dólares con pesos produce un número, y ese es justamente el problema.
        _ = self._cero() + precio_unitario

        linea = LineaVenta(
            numero=self._siguiente_linea,
            sku=sku,
            descripcion=descripcion,
            cantidad=cantidad,
            precio_unitario=precio_unitario,
            tasa_iva=tasa_iva,
        )
        self.lineas.append(linea)
        self._siguiente_linea += 1
        return linea

    def modificar_cantidad(self, numero: int, cantidad: int) -> None:
        """INV-V9. Llevar la cantidad a cero elimina la línea."""
        self._exigir_borrador()
        linea = self._linea(numero)
        if cantidad == 0:
            self.lineas.remove(linea)
            return
        linea.cambiar_cantidad(cantidad)

    def eliminar_linea(self, numero: int) -> None:
        """El número de la línea NO se reutiliza ni se renumera.

        Si se renumerara, un comando en vuelo que apunta a la línea 3
        terminaría modificando otra prenda.
        """
        self._exigir_borrador()
        self.lineas.remove(self._linea(numero))

    # ── Descuentos · INV-V6 ─────────────────────────────────────────────────

    def aplicar_descuento_linea(
        self,
        numero: int,
        descuento: Descuento,
        *,
        tope_de_quien_aplica: Decimal,
        autorizado_por: Optional[str] = None,
        tope_de_quien_autoriza: Optional[Decimal] = None,
    ) -> None:
        """Aplica un descuento, exigiendo firma si supera el tope del rol.

        Autorizar no es un cheque en blanco: si se pasa `tope_de_quien_autoriza`
        y el descuento también lo supera, se rechaza. Sin eso, cualquier
        supervisor podría aprobar el 100%.
        """
        self._exigir_borrador()
        linea = self._linea(numero)
        base = linea.subtotal()

        decision = PoliticaDescuento.evaluar(descuento, base, tope_de_quien_aplica)

        if decision is Decision.REQUIERE_AUTORIZACION:
            if not autorizado_por:
                raise RequiereAutorizacion(
                    PoliticaDescuento.explicar(descuento, base, tope_de_quien_aplica)
                )
            if tope_de_quien_autoriza is not None:
                if PoliticaDescuento.evaluar(
                    descuento, base, tope_de_quien_autoriza
                ) is Decision.REQUIERE_AUTORIZACION:
                    raise ReglaDeNegocio(
                        f"{PoliticaDescuento.explicar(descuento, base, tope_de_quien_autoriza)} "
                        f"Este descuento está por encima de lo que puede aprobar "
                        f"quien lo autorizó."
                    )

        linea.aplicar_descuento(descuento, autorizado_por)

    def quitar_descuento_linea(self, numero: int) -> None:
        self._exigir_borrador()
        self._linea(numero).quitar_descuento()

    def marcar_obsequio(self, numero: int, *, autorizado_por: Optional[str]) -> None:
        """INV-V7. Regalar una prenda siempre lleva firma."""
        self._exigir_borrador()
        if not autorizado_por:
            raise RequiereAutorizacion(
                "Regalar una prenda necesita autorización de un supervisor."
            )
        self._linea(numero).marcar_obsequio(autorizado_por)

    # ── Cliente ─────────────────────────────────────────────────────────────

    def asignar_cliente(self, cliente_id: Optional[str]) -> None:
        """`None` es consumidor final — no un cliente genérico inventado.

        Modelar la ausencia con un registro falso es la raíz de las
        estadísticas de cliente corrompidas.
        """
        self._exigir_borrador()
        self.cliente_id = cliente_id

    # ── Pagos ───────────────────────────────────────────────────────────────

    def registrar_pago(
        self,
        medio_pago_id: str,
        monto: Dinero,
        *,
        es_efectivo: bool,
        referencia: Optional[str] = None,
    ) -> Pago:
        self._exigir_borrador()
        _ = self._cero() + monto  # INV-V5
        pago = Pago(
            numero=self._siguiente_pago,
            medio_pago_id=medio_pago_id,
            monto=monto,
            es_efectivo=es_efectivo,
            referencia=referencia,
        )
        self.pagos.append(pago)
        self._siguiente_pago += 1
        return pago

    def eliminar_pago(self, numero: int) -> None:
        self._exigir_borrador()
        for p in self.pagos:
            if p.numero == numero:
                self.pagos.remove(p)
                return
        raise ReglaDeNegocio(f"la venta no tiene un pago número {numero}")

    # ── Cálculo ─────────────────────────────────────────────────────────────

    def subtotal(self) -> Dinero:
        return sum((l.subtotal() for l in self.lineas), self._cero())

    def descuento_total(self) -> Dinero:
        return sum((l.descuento_monto() for l in self.lineas), self._cero())

    def base_gravable(self) -> Dinero:
        return sum((l.base_gravable() for l in self.lineas), self._cero())

    def iva_total(self) -> Dinero:
        """INV-V12: suma de los IVA de cada línea, nunca el IVA del total."""
        return sum((l.iva() for l in self.lineas), self._cero())

    def total(self) -> Dinero:
        return sum((l.total() for l in self.lineas), self._cero())

    def pagado(self) -> Dinero:
        return sum((p.monto for p in self.pagos), self._cero())

    def efectivo_recibido(self) -> Dinero:
        return sum((p.monto for p in self.pagos if p.es_efectivo), self._cero())

    def saldo(self) -> Dinero:
        """Lo que falta por cobrar. Nunca negativo: el excedente es vuelto."""
        falta = self.total() - self.pagado()
        return falta if falta.es_positivo() else self._cero()

    def vuelto(self) -> Dinero:
        sobra = self.pagado() - self.total()
        return sobra if sobra.es_positivo() else self._cero()

    # ── Cierre ──────────────────────────────────────────────────────────────

    def cerrar(self, ahora: datetime) -> VentaCerrada:
        """El punto de no retorno.

        Después de esto ya se descargó el stock, se afectó la caja y salió el
        ticket. Que el documento fiscal siga en cola es asunto nuestro, no de
        la clienta (ADR-002).
        """
        self._exigir_borrador()

        # INV-V2
        if not self.lineas:
            raise ReglaDeNegocio("No se puede cerrar una venta sin prendas.")

        # INV-V3
        if self.saldo().es_positivo():
            raise ReglaDeNegocio(
                f"Todavía falta cobrar {self.saldo().formateado()}."
            )
        vuelto = self.vuelto()
        if vuelto.es_positivo() and vuelto > self.efectivo_recibido():
            # Un datáfono no da vuelto. Aceptarlo en silencio esconde un error
            # de digitación que reaparece como sobrante en el arqueo, sin saber
            # de qué venta salió.
            raise ReglaDeNegocio(
                f"Se cobraron {self.pagado().formateado()} por una venta de "
                f"{self.total().formateado()}, y el excedente no se puede "
                f"devolver como vuelto porque no entró en efectivo. "
                f"Revisa los medios de pago."
            )

        self.estado = EstadoVenta.CERRADA
        self.cerrada_en = ahora
        self.estado_fiscal = EstadoFiscal.PENDIENTE

        return VentaCerrada(
            ocurrido_en=ahora,
            venta_id=self.id,
            numero=self.numero,
            tienda_id=self.tienda_id,
            caja_id=self.caja_id,
            sesion_id=self.sesion_id,
            cajera_id=self.cajera_id,
            cliente_id=self.cliente_id,
            total=self.total(),
            iva_total=self.iva_total(),
            descuento_total=self.descuento_total(),
            pagado=self.pagado(),
            vuelto=vuelto,
            lineas=self._lineas_del_evento(),
        )

    def anular(self, *, motivo: str, autorizado_por: Optional[str],
               ahora: datetime) -> VentaAnulada:
        """INV-V11. Sólo se anula lo que se cerró, con motivo y con firma."""
        if self.estado is not EstadoVenta.CERRADA:
            raise ReglaDeNegocio(
                f"Sólo se anula una venta cerrada. Ésta está {self.estado.value}; "
                f"un borrador simplemente se descarta."
            )
        if not (motivo or "").strip():
            raise ReglaDeNegocio("Anular una venta exige escribir el motivo.")
        if not autorizado_por:
            raise RequiereAutorizacion(
                "Anular una venta necesita autorización de un supervisor."
            )

        total = self.total()
        lineas = self._lineas_del_evento()

        self.estado = EstadoVenta.ANULADA
        self.anulada_en = ahora
        self.motivo_anulacion = motivo.strip()

        return VentaAnulada(
            ocurrido_en=ahora,
            venta_id=self.id,
            numero=self.numero,
            tienda_id=self.tienda_id,
            motivo=self.motivo_anulacion,
            autorizado_por=autorizado_por,
            total_revertido=total,
            lineas=lineas,
        )

    def descartar(self) -> None:
        """Se abandonó el carrito. No deja rastro fiscal ni de caja."""
        self._exigir_borrador()
        self.estado = EstadoVenta.DESCARTADA

    # ── Auxiliares ──────────────────────────────────────────────────────────

    def _lineas_del_evento(self):
        return tuple(
            LineaVendida(sku=l.sku.codigo, cantidad=l.cantidad, total=l.total())
            for l in self.lineas
        )

    def unidades(self) -> int:
        return sum(l.cantidad for l in self.lineas)

    def __repr__(self) -> str:
        return (f"Venta({self.numero} · {self.estado.value} · "
                f"{len(self.lineas)} líneas · {self.total().formateado()})")
