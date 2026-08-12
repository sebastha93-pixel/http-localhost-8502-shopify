"""CerrarVenta — el caso de uso central del módulo.

Es el punto de no retorno. Después de esto la clienta ya se fue con la prenda
y el ticket, así que todo lo que tenga que quedar registrado tiene que quedar
registrado AQUÍ, o no queda nunca.

LO QUE OCURRE EN UNA SOLA TRANSACCIÓN:

  1. el agregado evalúa sus invariantes  (pagó lo suficiente, hay líneas…)
  2. la venta, sus líneas y sus pagos
  3. las reservas se vuelven salidas reales de inventario
  4. el ingreso entra a la caja del turno
  5. la auditoría, encadenada
  6. el outbox: emitir el documento fiscal, publicar el stock a Shopify
  COMMIT

Y sólo DESPUÉS del commit: imprimir y avisar por WebSocket. Nunca antes —
imprimir un ticket de una venta que después se revierte deja a la clienta con
un papel que no existe en el sistema.

LO QUE ESTE CASO DE USO **NO** HACE: llamar a Siigo. Ni a Shopify. Esas van al
outbox y las despacha el worker (ADR-002). Si esperáramos a Siigo, el cierre
pasaría de 800 ms a lo que Siigo quiera ese día, y la promesa de 30 segundos
por venta se cae.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from backend.modules.retail.domain.venta.errores import ReglaDeNegocio
from backend.modules.retail.domain.venta.eventos import VentaCerrada
from backend.modules.retail.domain.venta.venta import Venta

__all__ = ["CerrarVenta", "ResultadoCierre"]


@dataclass(frozen=True)
class ResultadoCierre:
    venta_id: str
    numero: str
    total_centavos: int
    vuelto_centavos: int
    estado_fiscal: str
    evento: VentaCerrada


class CerrarVenta:
    """Orquesta. No decide reglas de negocio: eso es del agregado."""

    def __init__(self, uow, *, reloj) -> None:
        self._uow = uow
        self._reloj = reloj

    async def ejecutar(
        self,
        venta: Venta,
        *,
        variante_por_sku: dict,
        ubicacion_id: str,
        reservas: Optional[dict] = None,
        usuario_id: str,
    ) -> ResultadoCierre:
        """`reservas` mapea sku → id de reserva, cuando el carrito reservó.

        Sin reservas (una venta que llegó de un dispositivo offline) el stock
        se descuenta igual: la prenda ya se entregó. Puede quedar negativo, se
        alerta, y se corrige en el conteo (INV-I2).
        """
        ahora = self._reloj.ahora()

        # 1. El agregado manda. Si alguna invariante no se cumple, aquí revienta
        #    y no se escribió nada todavía.
        evento = venta.cerrar(ahora)

        async with self._uow as t:
            # 2
            await t.ventas.guardar(venta, variante_por_sku=variante_por_sku)

            # 3
            for linea in venta.lineas:
                variante_id = variante_por_sku[linea.sku.codigo]
                await t.inventario.confirmar_salida(
                    ubicacion_id=ubicacion_id, variante_id=variante_id,
                    cantidad=linea.cantidad, referencia_id=venta.id,
                    usuario_id=usuario_id)

            # 4
            for pago in venta.pagos:
                await t.caja.registrar_cobro(
                    sesion_id=venta.sesion_id, venta_id=venta.id,
                    medio_pago_id=pago.medio_pago_id,
                    monto_centavos=pago.monto.centavos,
                    usuario_id=usuario_id, ahora=ahora)

            # 5. Los descuentos autorizados van aparte y como CRÍTICOS: son los
            #    eventos que alguien querría que desaparezcan.
            await t.auditoria.registrar(
                evento="venta.cerrada", ocurrido_en=ahora,
                tienda_id=venta.tienda_id, caja_id=venta.caja_id,
                sesion_id=venta.sesion_id, usuario_id=usuario_id,
                dispositivo_id=venta.dispositivo_id,
                agregado_tipo="venta", agregado_id=venta.id,
                payload={
                    "numero": venta.numero,
                    "total": venta.total().centavos,
                    "iva": venta.iva_total().centavos,
                    "descuento": venta.descuento_total().centavos,
                    "unidades": venta.unidades(),
                    "cliente_id": venta.cliente_id,
                })

            for linea in venta.lineas:
                if linea.autorizado_por:
                    # DOS SEVERIDADES, no una. Antes este bloque sólo se
                    # disparaba con la firma de un supervisor, así que todo lo
                    # que entraba era excepcional y CRÍTICO estaba bien. Sin
                    # PIN, el nombre de quien aplica va SIEMPRE — y marcar
                    # crítico cada descuento del 5 % llena el log a diario
                    # hasta que nadie lo mira. Regalar una prenda sigue siendo
                    # crítico: es el 100 % y no lo justifica ninguna promoción.
                    await t.auditoria.registrar(
                        evento="descuento.aplicado" if not linea.obsequio
                               else "linea.obsequiada",
                        ocurrido_en=ahora,
                        severidad="critico" if linea.obsequio else "aviso",
                        tienda_id=venta.tienda_id, caja_id=venta.caja_id,
                        sesion_id=venta.sesion_id, usuario_id=usuario_id,
                        agregado_tipo="venta", agregado_id=venta.id,
                        payload={
                            "numero": venta.numero,
                            "sku": linea.sku.codigo,
                            "monto": linea.descuento_monto().centavos,
                            "motivo": (linea.descuento.motivo if linea.descuento
                                       else "obsequio"),
                            "aplicado_por": linea.autorizado_por,
                        })

            # 6
            await t.outbox.encolar(
                tipo="emitir_documento_fiscal", agregado_tipo="venta",
                agregado_id=venta.id,
                payload={"venta_id": venta.id, "tienda_id": venta.tienda_id,
                         "caja_id": venta.caja_id})
            await t.outbox.encolar(
                tipo="publicar_stock_shopify", agregado_tipo="venta",
                agregado_id=venta.id,
                payload={"ubicacion_id": ubicacion_id,
                         "variantes": [variante_por_sku[l.sku.codigo]
                                       for l in venta.lineas]})

            await t.commit()

        return ResultadoCierre(
            venta_id=venta.id,
            numero=venta.numero,
            total_centavos=venta.total().centavos,
            vuelto_centavos=venta.vuelto().centavos,
            estado_fiscal=venta.estado_fiscal.value,
            evento=evento,
        )


class RelojDelSistema:
    """La hora la pone el SERVIDOR, siempre.

    El dominio no lee el reloj (hay una guarda que lo verifica) y el
    dispositivo tampoco decide: una tablet con la hora corrida tres horas
    mandaría ventas al turno que no es (riesgo R7).
    """

    def ahora(self) -> datetime:
        from datetime import timezone
        return datetime.now(timezone.utc)


class RelojFijo:
    """Para las pruebas: la misma hora siempre, y por lo tanto reproducibles."""

    def __init__(self, instante: datetime) -> None:
        self._instante = instante

    def ahora(self) -> datetime:
        return self._instante
