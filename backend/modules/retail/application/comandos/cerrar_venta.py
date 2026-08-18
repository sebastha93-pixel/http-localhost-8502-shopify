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
  6. el outbox: emitir el documento fiscal
  COMMIT

Y sólo DESPUÉS del commit: imprimir y avisar por WebSocket. Nunca antes —
imprimir un ticket de una venta que después se revierte deja a la clienta con
un papel que no existe en el sistema.

LO QUE ESTE CASO DE USO **NO** HACE: llamar a Siigo. Eso va al outbox y lo
despacha el worker (ADR-002). Si esperáramos a Siigo, el cierre pasaría de
800 ms a lo que Siigo quiera ese día, y la promesa de 30 segundos por venta se
cae.

A SHOPIFY NO SE LE DICE NADA, y tampoco es un pendiente: la web vende contra el
inventario de Melonn, no contra el de la tienda. Ver la nota en el paso 6.
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
            # 1b. LA REFERENCIA DE LOS MEDIOS QUE LA EXIGEN.
            #
            # `exige_referencia` existe en la migración 0001 y no lo leía
            # nadie. Es el único hilo que une una línea del POS con una línea
            # del informe de Addi, de Wompi o del datáfono: sin él, cuadrar el
            # día se reduce a comparar dos totales y encogerse de hombros
            # cuando no dan — y la clienta que quiere reclamar un cobro se
            # queda sin el número con el que reclamarlo.
            #
            # Se comprueba contra la BASE, no contra lo que diga el
            # dispositivo: una tableta con el catálogo viejo no sabe que ese
            # medio pasó a exigirla.
            await self._exigir_referencias(t, venta)

            # 2
            await t.ventas.guardar(venta, variante_por_sku=variante_por_sku)

            # El bloque de la caja avanza CON la venta, en la misma
            # transacción. Sin esto el contador del servidor se queda quieto y
            # cada recarga de la pantalla reinicia la numeración desde el
            # principio del bloque: la venta siguiente choca con una ya hecha y
            # la clienta se va con un papel de algo que nunca se registró.
            # (Lo encontré así, con dos ventas distintas numeradas FV-20-1.)
            await t.consecutivos.marcar_consumido(
                caja_id=venta.caja_id, consecutivo=venta.consecutivo)

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
            # NO SE ENCOLA STOCK PARA SHOPIFY, y es a propósito.
            #
            # Shopify vende contra el inventario de MELONN (bodega 32 de
            # Siigo); el stock de la tienda física es un pozo distinto. O sea
            # que lo que se venda en Florida no cambia lo que la web puede
            # vender, y empujarlo a Shopify no arregla nada: lo rompe.
            #
            # Aquí se encolaba `publicar_stock_shopify` con
            # `{ubicacion_id, variantes}` y NUNCA hubo consumidor — ni podía
            # haberlo, porque `retail.ubicaciones` no tiene
            # `shopify_location_id`: no existe el mapeo tienda↔location. La cola
            # sólo acumulaba mensajes inejecutables (16 al quitarlo).
            #
            # Y las dos formas obvias de consumirla habrían hecho daño:
            #   · Cantidad ABSOLUTA: borra del stock de Shopify las ventas web,
            #     porque nada mete esas ventas al inventario del POS.
            #   · DELTA: una cola con reintentos aplica el mismo descuento dos
            #     veces y deja stock fantasma.
            #
            # Si algún día MALE quiere mostrar «disponible en tienda» en la web,
            # esto vuelve — pero con mapeo de ubicación y con una sincronización
            # de ENTRADA, no reactivando este encolado.

            await t.commit()

        return ResultadoCierre(
            venta_id=venta.id,
            numero=venta.numero,
            total_centavos=venta.total().centavos,
            vuelto_centavos=venta.vuelto().centavos,
            estado_fiscal=venta.estado_fiscal.value,
            evento=evento,
        )

    @staticmethod
    async def _exigir_referencias(t, venta) -> None:
        """Que ningún pago que necesite referencia entre sin ella.

        Se pregunta por LOS MEDIOS DE ESTA VENTA y no por todos: una tienda
        puede tener veinte configurados y la consulta iría a buscarlos todos en
        cada cobro.
        """
        from sqlalchemy import text as _t

        ids = sorted({p.medio_pago_id for p in venta.pagos})
        if not ids:
            return
        filas = (await t.sesion.execute(_t("""
            SELECT id, nombre, exige_referencia FROM retail.medios_pago
             WHERE id = ANY(:ids)
        """), {"ids": ids})).mappings().all()
        exigen = {f["id"]: f["nombre"] for f in filas if f["exige_referencia"]}

        # Un medio que no está en la tabla no se deja pasar en silencio: la
        # llave foránea lo rechazaría después con un error de base de datos que
        # en pantalla no dice nada. Así fue como «datafono_florida» —el id
        # quemado en la pantalla— rompía todo cobro con tarjeta.
        desconocidos = sorted(set(ids) - {f["id"] for f in filas})
        if desconocidos:
            raise ReglaDeNegocio(
                f"El equipo mandó un medio de pago que esta tienda no tiene: "
                f"{', '.join(desconocidos)}. Actualiza la pantalla."
            )

        sin = [exigen[p.medio_pago_id] for p in venta.pagos
               if p.medio_pago_id in exigen and not (p.referencia or "").strip()]
        if sin:
            raise ReglaDeNegocio(
                f"Falta el número de aprobación de {', '.join(sorted(set(sin)))}. "
                f"Está en la pantalla del datáfono o en la app, y es lo único "
                f"que después permite cuadrar ese cobro."
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
