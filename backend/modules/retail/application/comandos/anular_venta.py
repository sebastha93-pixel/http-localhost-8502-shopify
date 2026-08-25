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

LO QUE ESTO NO HACE, y hay que decirlo: **no emite nota crédito**. Si la venta
ya tenía factura electrónica emitida, anularla aquí la deja anulada en el POS y
viva ante la DIAN. Eso se resuelve en la Fase 3; mientras tanto se encola en el
outbox y el endpoint avisa.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import text

from backend.modules.retail.domain.shared.dinero import Dinero
from backend.modules.retail.domain.venta.errores import ReglaDeNegocio

__all__ = ["AnularVenta", "ResultadoAnulacion"]


@dataclass(frozen=True)
class ResultadoAnulacion:
    venta_id: str
    numero: str
    total_revertido_centavos: int
    unidades_devueltas: int
    #  True si la venta ya tenía documento fiscal emitido. La anulación en el
    #  POS NO lo revierte: hace falta una nota crédito, que es Fase 3.
    exige_nota_credito: bool


class AnularVenta:
    def __init__(self, uow) -> None:
        self._uow = uow

    async def ejecutar(self, *, venta_id: str, motivo: str, usuario_id: str,
                       ahora: datetime) -> ResultadoAnulacion:
        async with self._uow as t:
            venta = await t.ventas.obtener(venta_id)
            if venta is None:
                raise ReglaDeNegocio(f"No existe la venta {venta_id}.")

            # La ubicación NO está en `ventas`: sale del asiento de inventario
            # que dejó la venta. Es la fuente correcta —la prenda vuelve a
            # DONDE SALIÓ— y no a una ubicación deducida de la tienda, que
            # sería otra cosa el día que una caja despache desde bodega.
            fila = (await t.sesion.execute(text("""
                SELECT v.sesion_id, v.estado_fiscal,
                       s.estado AS estado_sesion,
                       coalesce(p.puede_anular_venta, false) AS puede,
                       (SELECT m.ubicacion_id
                          FROM retail.movimientos_inventario m
                         WHERE m.referencia_id = v.id AND m.delta < 0
                         LIMIT 1) AS ubicacion_id
                  FROM retail.ventas v
                  JOIN retail.sesiones_caja s ON s.id = v.sesion_id
                  LEFT JOIN retail.permisos_pos p
                         ON p.usuario_id = :u AND p.activo
                 WHERE v.id = :i
            """), {"i": venta_id, "u": usuario_id})).mappings().first()

            # INV-V11: sólo del turno EN CURSO. Una venta de ayer no se anula
            # desde la caja: su plata ya se contó en un arqueo cerrado y
            # firmado, y tocarla ahora descuadra un turno que ya cuadró.
            if fila["estado_sesion"] == "cerrada":
                raise ReglaDeNegocio(
                    "Esa venta es de un turno ya cerrado. Su plata está en un "
                    "arqueo firmado; para deshacerla hace falta una nota "
                    "crédito, no una anulación de caja."
                )

            evento = venta.anular(motivo=motivo, usuario_id=usuario_id,
                                  puede_anular=bool(fila["puede"]), ahora=ahora)

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
            for pago in venta.pagos:
                sesion.registrar_anulacion(
                    medio_pago_id=pago.medio_pago_id,
                    monto=Dinero(pago.monto.centavos, venta.moneda),
                    es_efectivo=pago.es_efectivo, venta_id=venta_id,
                    usuario_id=usuario_id)
                await t.turnos.anotar_movimiento(
                    # Sin L: el alfabeto ULID excluye I, L, O y U —para que nadie
                    # confunda un 1 con una l al leer un número en voz alta.
                    movimiento_id=f"{venta_id[:20]}AN9{pago.numero:03d}"[:26],
                    sesion_id=fila["sesion_id"], tipo="anulacion",
                    monto=-pago.monto.centavos, motivo=f"anulación {venta.numero}",
                    usuario_id=usuario_id, medio_pago_id=pago.medio_pago_id,
                    autorizado_por=usuario_id, ahora=ahora)

            exige_nc = fila["estado_fiscal"] == "emitido"

            await t.auditoria.registrar(
                evento="venta.anulada", ocurrido_en=ahora, severidad="critico",
                tienda_id=venta.tienda_id, caja_id=venta.caja_id,
                sesion_id=fila["sesion_id"], usuario_id=usuario_id,
                agregado_tipo="venta", agregado_id=venta_id,
                payload={"numero": venta.numero, "motivo": evento.motivo,
                         "total": evento.total_revertido.centavos,
                         "unidades": unidades,
                         "exige_nota_credito": exige_nc})

            if exige_nc:
                # La factura sigue viva ante la DIAN hasta que salga la nota
                # crédito. Se encola para la Fase 3 en vez de dejarlo al aire.
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
