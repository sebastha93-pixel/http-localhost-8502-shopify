"""Deshacer una venta que ya se cerró.

CUATRO COSAS PASAN A LA VEZ, y o pasan todas o no pasa ninguna (ADR-004):

  1. La venta queda `anulada`, con motivo y con el nombre de quien la anuló.
  2. La prenda vuelve al saldo de inventario.
  3. La plata sale del arqueo — un movimiento de caja contrario.
  4. Queda como CRÍTICO en la auditoría.

Si alguna se cayera sola, el resultado sería peor que no anular: prenda
devuelta al stock con la venta todavía viva, o plata descontada del arqueo sin
que nadie sepa por qué.

EL LIBRO DE INVENTARIO ES APPEND-ONLY. No se borra el asiento de la venta: se
escribe el contrario. Un libro que se puede editar no sirve para cuadrar nada,
porque cualquier diferencia se puede hacer desaparecer.

LA NOTA CRÉDITO NO SE EMITE AQUÍ, SE ENCOLA. Si la venta ya tenía factura
electrónica, anularla en el POS la deja viva ante la DIAN hasta que salga su
nota crédito: la emite `emisor_nota_credito` desde la cola, con las mismas
garantías que la factura. Si la factura todavía estaba en camino, quien encola
la nota crédito es el emisor de facturas, cuando termina.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import text

from backend.modules.retail.domain.shared.dinero import Dinero
from backend.modules.retail.domain.venta.errores import (
    ReglaDeNegocio,
    RequiereAutorizacion,
)

__all__ = ["AnularVenta", "ResultadoAnulacion"]


@dataclass(frozen=True)
class ResultadoAnulacion:
    venta_id: str
    numero: str
    total_revertido_centavos: int
    unidades_devueltas: int
    #  True si la venta ya tenía documento fiscal emitido: se encoló su nota
    #  crédito.
    exige_nota_credito: bool


class AnularVenta:
    def __init__(self, uow) -> None:
        self._uow = uow

    async def comprobar(self, *, venta_id: str, usuario_id: str,
                        desde_oficina: bool = False) -> None:
        """Lanza lo mismo que lanzaría `ejecutar`, SIN CAMBIAR NADA.

        Para quien tiene que hacer algo irreversible ANTES de anular: una
        venta con envío primero le pide a Melonn que no la despache, y eso no
        se puede pedir para una anulación que después se va a rechazar (turno
        cerrado, sin permiso). Antes pasaba: quedaba la venta cobrada y su
        pedido cancelado.
        """
        async with self._uow as t:
            venta, fila = await self._cargar(t, venta_id, usuario_id)
            self._exigir(venta, fila, desde_oficina)

    @staticmethod
    async def _cargar(t, venta_id: str, usuario_id: str):
        venta = await t.ventas.obtener(venta_id)
        if venta is None:
            raise ReglaDeNegocio(f"No existe la venta {venta_id}.")

        # La ubicación NO está en `ventas`: sale del asiento de inventario
        # que dejó la venta. Es la fuente correcta —la prenda vuelve a
        # DONDE SALIÓ— y no a una ubicación deducida de la tienda, que
        # sería otra cosa el día que una caja despache desde bodega.
        fila = (await t.sesion.execute(text("""
            SELECT v.sesion_id, v.estado_fiscal, v.canal, v.estado,
                   d.estado AS despacho,
                   s.estado AS estado_sesion,
                   coalesce(p.puede_anular_venta, false) AS puede,
                   EXISTS (SELECT 1 FROM retail.devoluciones dv
                            WHERE dv.venta_id = v.id) AS tiene_devoluciones,
                   (SELECT m.ubicacion_id
                      FROM retail.movimientos_inventario m
                     WHERE m.referencia_id = v.id AND m.delta < 0
                     LIMIT 1) AS ubicacion_id
              FROM retail.ventas v
              JOIN retail.sesiones_caja s ON s.id = v.sesion_id
              LEFT JOIN retail.despachos d ON d.venta_id = v.id
              LEFT JOIN retail.permisos_pos p
                     ON p.usuario_id = :u AND p.activo
             WHERE v.id = :i
        """), {"i": venta_id, "u": usuario_id})).mappings().first()
        return venta, fila

    @staticmethod
    def _exigir(venta, fila, desde_oficina: bool) -> None:
        """Todo lo que impide anular. Sin efectos."""
        if fila["estado"] != "cerrada":
            raise ReglaDeNegocio(
                f"Sólo se anula una venta cerrada. Ésta está {fila['estado']}; "
                f"un borrador simplemente se descarta.")
        if desde_oficina and fila["despacho"] is None:
            raise ReglaDeNegocio(
                "Esa venta no es con envío a domicilio: se anula desde su "
                "caja, en su turno.")
        # LO QUE YA SALIÓ NO SE CANCELA. La prenda va en camino o ya está
        # en manos de la clienta: eso es un cambio o una devolución.
        if fila["despacho"] in ("despachado", "entregado"):
            raise ReglaDeNegocio(
                "Ese pedido ya salió de la bodega. No se anula: cuando la "
                "clienta lo reciba se hace el cambio o la devolución.")
        # UNA VENTA CON CAMBIO O DEVOLUCIÓN NO SE ANULA. Anular devuelve TODAS
        # las líneas y TODO lo cobrado, sin restar lo que la devolución ya
        # devolvió: 2 jeans por $300.000, cambio de 1 que deja $150.000 de
        # saldo, anular → salían $300.000 del arqueo, entraban 2 prendas y el
        # saldo seguía vivo. Lo que queda se deshace con otra devolución, que
        # sí lleva la cuenta de lo ya devuelto (auditoría dic-2026, T2).
        if fila["tiene_devoluciones"]:
            raise ReglaDeNegocio(
                "Esa venta ya tuvo un cambio o una devolución, así que no se "
                "anula entera. Para deshacer lo que queda, haz una devolución "
                "de las prendas restantes.")
        # INV-V11: sólo del turno EN CURSO. Una venta de ayer no se anula
        # desde la caja: su plata ya se contó en un arqueo cerrado y
        # firmado, y tocarla ahora descuadra un turno que ya cuadró.
        if fila["estado_sesion"] == "cerrada" and not desde_oficina:
            raise ReglaDeNegocio(
                "Esa venta es de un turno ya cerrado. Su plata está en un "
                "arqueo firmado; para deshacerla hace falta una nota "
                "crédito, no una anulación de caja."
            )
        if not (desde_oficina or fila["puede"]):
            raise RequiereAutorizacion(
                "Anular una venta necesita permiso. Pide que entre alguien "
                "que lo tenga, con su correo y contraseña.")

    async def ejecutar(self, *, venta_id: str, motivo: str, usuario_id: str,
                       ahora: datetime, desde_oficina: bool = False,
                       resolucion: Optional[str] = None) -> ResultadoAnulacion:
        """`desde_oficina` es la cancelación de un PEDIDO CON ENVÍO que hace un
        administrador (Melonn no pudo despachar, la clienta se arrepintió al
        otro día): vale aunque el turno ya esté cerrado y NO toca el arqueo —
        la plata se devuelve por fuera de la caja y `resolucion` dice cómo—.
        Quien llama ya comprobó que Melonn no lo va a despachar
        (`melonn.despacho.cancelar_en_melonn`).
        """
        async with self._uow as t:
            venta, fila = await self._cargar(t, venta_id, usuario_id)
            self._exigir(venta, fila, desde_oficina)

            evento = venta.anular(motivo=motivo, usuario_id=usuario_id,
                                  puede_anular=(desde_oficina or bool(fila["puede"])),
                                  ahora=ahora)

            await t.ventas.marcar_anulada(
                venta_id=venta_id, motivo=evento.motivo,
                anulada_por=usuario_id, ahora=ahora)

            # 2 · La prenda vuelve al saldo.
            unidades = 0
            for linea in venta.lineas:
                if linea.obsequio and linea.cantidad == 0:
                    continue
                variante = (await t.sesion.execute(text("""
                    SELECT variante_id FROM retail.venta_lineas
                     WHERE venta_id = :v AND sku = :s LIMIT 1
                """), {"v": venta_id, "s": linea.sku.codigo})).scalar()
                if not variante or not fila["ubicacion_id"]:
                    continue
                await t.inventario.devolver(
                    ubicacion_id=fila["ubicacion_id"], variante_id=variante,
                    cantidad=linea.cantidad, referencia_id=venta_id,
                    usuario_id=usuario_id)
                unidades += linea.cantidad

            # 3 · La plata sale del arqueo, un movimiento por medio de pago.
            sesion = await t.turnos.cargar(fila["sesion_id"])
            # Se devuelve el NETO, el mismo que entró al cobrar. Si pagó
            # $300.000 por $299.800 se le devuelven $299.800: los otros $200
            # ya se los llevó como vuelto.
            for pago, neto in venta.cobros_netos():
                if neto.es_cero() or desde_oficina:
                    # Desde la oficina la plata NO sale de la caja: se le
                    # devuelve a la clienta por fuera (queda en `resolucion`)
                    # y el arqueo —quizá ya firmado— no se toca.
                    continue
                sesion.registrar_anulacion(
                    medio_pago_id=pago.medio_pago_id,
                    monto=Dinero(neto.centavos, venta.moneda),
                    es_efectivo=pago.es_efectivo, venta_id=venta_id,
                    usuario_id=usuario_id)
                await t.turnos.anotar_movimiento(
                    # Sin L: el alfabeto ULID excluye I, L, O y U —para que nadie
                    # confunda un 1 con una l al leer un número en voz alta.
                    movimiento_id=f"{venta_id[:20]}AN9{pago.numero:03d}"[:26],
                    sesion_id=fila["sesion_id"], tipo="anulacion",
                    monto=-neto.centavos, motivo=f"anulación {venta.numero}",
                    usuario_id=usuario_id, medio_pago_id=pago.medio_pago_id,
                    autorizado_por=usuario_id, ahora=ahora)

            # El saldo a favor que esta venta gastó vuelve a su dueña.
            await t.sesion.execute(text("""
                UPDATE retail.saldos_a_favor s SET usado = s.usado - u.monto
                  FROM retail.saldo_usos u
                 WHERE u.saldo_id = s.id AND u.venta_id = :v
            """), {"v": venta_id})
            await t.sesion.execute(text(
                "DELETE FROM retail.saldo_usos WHERE venta_id = :v"),
                {"v": venta_id})

            if fila["despacho"] is not None:
                # EL DESPACHO SE CANCELA CON LA VENTA, en la misma transacción.
                # Siempre queda «cancelación pedida»: el verificador de la
                # cola mira en Melonn hasta estar seguro de que no sale —
                # incluido el pedido que Melonn pudo crear tarde.
                await t.sesion.execute(text("""
                    UPDATE retail.despachos
                       SET estado = 'cancelado', resuelto_por = :u,
                           resolucion = :r, melonn_estado = 'cancelación pedida',
                           ultimo_error = NULL, actualizado_en = :ahora
                     WHERE venta_id = :v
                """), {"v": venta_id, "u": usuario_id, "ahora": ahora,
                       "r": (resolucion or f"anulada en la caja: {evento.motivo}")[:500]})
                await t.outbox.encolar(
                    tipo="cancelar_despacho_melonn", agregado_tipo="venta",
                    agregado_id=venta_id, payload={"venta_id": venta_id})

            exige_nc = fila["estado_fiscal"] == "emitido"

            await t.auditoria.registrar(
                evento="venta.anulada", ocurrido_en=ahora, severidad="critico",
                tienda_id=venta.tienda_id, caja_id=venta.caja_id,
                sesion_id=fila["sesion_id"], usuario_id=usuario_id,
                agregado_tipo="venta", agregado_id=venta_id,
                payload={"numero": venta.numero, "motivo": evento.motivo,
                         "total": evento.total_revertido.centavos,
                         "unidades": unidades,
                         "exige_nota_credito": exige_nc,
                         "desde_oficina": desde_oficina,
                         "resolucion": resolucion})

            if exige_nc:
                # La factura sigue viva ante la DIAN hasta que salga la nota
                # crédito: se encola aquí, en la misma transacción.
                await t.outbox.encolar(
                    tipo="emitir_nota_credito", agregado_tipo="venta",
                    agregado_id=venta_id,
                    payload={"venta_id": venta_id, "motivo": evento.motivo})

            await t.commit()

        return ResultadoAnulacion(
            venta_id=venta_id, numero=venta.numero,
            total_revertido_centavos=evento.total_revertido.centavos,
            unidades_devueltas=unidades, exige_nota_credito=exige_nc,
        )
