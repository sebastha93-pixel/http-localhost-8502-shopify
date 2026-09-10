"""Registrar una devolución — vista 5 del handoff.

CUATRO COSAS PASAN A LA VEZ, y o pasan todas o no pasa ninguna (ADR-004):

  1. La devolución queda escrita, con sus líneas, su motivo y su firma.
  2. La prenda vuelve al saldo de inventario.
  3. Si el reembolso es en efectivo, la plata sale del arqueo del turno.
  4. Queda como CRÍTICO en la auditoría, y se encola el caso de Postventa.

Si alguna se cayera sola el resultado sería peor que no devolver: prenda de
vuelta en el stock sin registro de por qué, o plata entregada sin rastro.

LA QUINTA COSA NO PASA AQUÍ, Y ES DELIBERADO: **la nota crédito.** La emite
Postventa, que lleva meses en producción emitiendo NC + factura contra Siigo.
Construir aquí un segundo emisor sería tener dos sistemas capaces de anular la
misma factura ante la DIAN, y el día que discrepen no habría forma de saber
cuál manda.

Por eso el caso se ENCOLA en el outbox en vez de llamarse en línea — mismo
criterio que ADR-002 con Siigo: la clienta no puede quedarse esperando en el
mostrador a que responda un sistema de terceros. La devolución queda firme en
el POS; el caso se abre después.

ESTO ADEMÁS CIERRA UN HUECO VIEJO. `backend/services/postventa_caja.py` existe
porque «no hay forma de escribirle al POS (Siigo POS no tiene API)», así que
hoy la cajera SUMA A MANO al arqueo lo que entró por postventa. Nuestro POS sí
tiene API: cuando la devolución nace aquí, el movimiento de caja se escribe
solo y el arqueo cuadra sin que nadie sume nada.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Mapping, Optional

from sqlalchemy import text

from backend.modules.retail.domain.devolucion.devolucion import (
    Devolucion,
    LineaVendida,
)
from backend.modules.retail.domain.devolucion.motivo import MotivoDevolucion
from backend.modules.retail.domain.devolucion.reembolso import Reembolso
from backend.modules.retail.domain.venta.errores import ReglaDeNegocio

__all__ = ["RegistrarDevolucion", "ResultadoDevolucion"]


@dataclass(frozen=True)
class ResultadoDevolucion:
    devolucion_id: str
    numero_venta: str
    total_centavos: int
    unidades: int
    reembolso: str
    #  True si salió plata del cajón. La pantalla lo usa para decir «entrégale
    #  $X en efectivo» en vez de un genérico «devolución registrada».
    salio_del_cajon: bool
    #  El turno que la absorbió. `None` cuando no tocó ningún cajón.
    sesion_id: Optional[str]


class RegistrarDevolucion:
    def __init__(self, uow) -> None:
        self._uow = uow

    async def ejecutar(self, *, devolucion_id: str, venta_id: str,
                       seleccion: Mapping[str, int], motivo: str,
                       reembolso: str, usuario_id: str,
                       ahora: datetime,
                       caja_id: Optional[str] = None) -> ResultadoDevolucion:
        """`caja_id` es la caja DONDE se devuelve; sin ella, la de la venta.

        Con dos tiendas no son la misma: la clienta compra en Florida y
        devuelve en Arrayanes. La plata sale del cajón que la cajera tiene
        delante y la prenda entra al inventario de la tienda donde quedó
        físicamente. Hacerlo contra la venta descuadraría las DOS tiendas: a
        Florida le faltaría plata que nunca entregó y le sobraría una prenda
        que no tiene.
        """
        # Los enums validan ANTES de abrir transacción: un motivo inventado no
        # merece un round-trip a la base.
        try:
            motivo_enum = MotivoDevolucion(motivo)
        except ValueError:
            raise ReglaDeNegocio(
                f"«{motivo}» no es un motivo de devolución válido.")
        try:
            reembolso_enum = Reembolso(reembolso)
        except ValueError:
            raise ReglaDeNegocio(
                f"«{reembolso}» no es una forma de reembolso válida.")

        async with self._uow as t:
            cabecera = (await t.sesion.execute(text("""
                SELECT v.id, v.numero, v.tienda_id, v.caja_id, v.moneda,
                       v.estado,
                       (SELECT m.ubicacion_id
                          FROM retail.movimientos_inventario m
                         WHERE m.referencia_id = v.id AND m.delta < 0
                         LIMIT 1) AS ubicacion_id
                  FROM retail.ventas v
                 WHERE v.id = :i
            """), {"i": venta_id})).mappings().first()
            if cabecera is None:
                raise ReglaDeNegocio(f"No existe la venta {venta_id}.")
            lugar = await self._lugar(t, caja_id, cabecera)

            vendidas, variantes = await self._lineas_vendidas(t, venta_id)
            ya = await self._ya_devuelto(t, venta_id)

            # EL TURNO ABIERTO DE **ESTA CAJA**, no de cualquiera. Una
            # devolución en efectivo sale del cajón que la cajera tiene
            # delante; buscar «alguna sesión abierta» podría cargársela a otra
            # caja de la misma tienda y descuadrar a una compañera.
            sesion_id = (await t.sesion.execute(text("""
                SELECT id FROM retail.sesiones_caja
                 WHERE caja_id = :c AND estado = 'abierta'
                 ORDER BY abierta_en DESC LIMIT 1
            """), {"c": lugar["caja_id"]})).scalar()

            # Todas las guardas viven en el agregado, no aquí.
            devolucion = Devolucion.armar(
                venta_id=venta_id,
                numero=cabecera["numero"],
                lineas_vendidas=vendidas,
                ya_devuelto=ya,
                seleccion=seleccion,
                motivo=motivo_enum,
                reembolso=reembolso_enum,
                moneda=cabecera["moneda"],
                venta_anulada=cabecera["estado"] == "anulada",
                turno_abierto=sesion_id is not None,
            )

            # 1 · La devolución y sus líneas.
            sesion_para_guardar = sesion_id if devolucion.sale_del_cajon else None
            await t.sesion.execute(text("""
                INSERT INTO retail.devoluciones
                    (id, venta_id, numero_venta, tienda_id, caja_id, sesion_id,
                     usuario_id, motivo, reembolso, base_gravable, iva_total,
                     total, unidades, moneda, creada_en)
                VALUES (:id, :venta, :numero, :tienda, :caja, :sesion, :usuario,
                        :motivo, :reembolso, :base, :iva, :total, :unidades,
                        :moneda, :ahora)
            """), {
                "id": devolucion_id, "venta": venta_id,
                "numero": cabecera["numero"], "tienda": lugar["tienda_id"],
                "caja": lugar["caja_id"], "sesion": sesion_para_guardar,
                "usuario": usuario_id, "motivo": motivo_enum.value,
                "reembolso": reembolso_enum.value,
                "base": devolucion.base_gravable.centavos,
                "iva": devolucion.iva.centavos,
                "total": devolucion.total.centavos,
                "unidades": devolucion.unidades,
                "moneda": devolucion.moneda, "ahora": ahora,
            })
            for linea in devolucion.lineas:
                await t.sesion.execute(text("""
                    INSERT INTO retail.devolucion_lineas
                        (devolucion_id, sku, variante_id, cantidad,
                         precio_unitario_con_iva)
                    VALUES (:d, :sku, :variante, :cant, :precio)
                """), {
                    "d": devolucion_id, "sku": linea.sku,
                    "variante": variantes.get(linea.sku),
                    "cant": linea.cantidad,
                    "precio": linea.precio_unitario_con_iva_centavos,
                })

            # 2 · La prenda vuelve al saldo de la tienda DONDE QUEDÓ, que es
            #     la que la tiene en la mano.
            for linea in devolucion.lineas:
                variante = variantes.get(linea.sku)
                if not variante or not lugar["ubicacion_id"]:
                    # Sin ubicación no hay a dónde devolverla. Pasa con ventas
                    # migradas de antes del libro de inventario; el registro de
                    # la devolución sí queda, que es lo que la clienta necesita.
                    continue
                await t.inventario.devolver(
                    ubicacion_id=lugar["ubicacion_id"],
                    variante_id=variante, cantidad=linea.cantidad,
                    referencia_id=devolucion_id, usuario_id=usuario_id,
                    motivo="devolucion", referencia_tipo="devolucion")

            # 3 · La plata sale del cajón, sólo si el método lo mueve.
            #
            # Pasa POR EL AGREGADO y no directo a `anotar_movimiento`, igual
            # que hace la anulación. Dos cosas se pierden si se escribe
            # directo: el `medio_efectivo_id` —sin el cual el movimiento no
            # cuenta para el esperado y el arqueo pide plata que ya se
            # entregó— e INV-C6, que impide prometer un efectivo que no está
            # en el cajón.
            if devolucion.sale_del_cajon and sesion_id:
                sesion = await t.turnos.cargar(sesion_id)
                glosa = f"devolución {cabecera['numero']} · {motivo_enum.value}"
                sesion.registrar_devolucion(
                    devolucion.total, motivo=glosa, usuario_id=usuario_id)
                await t.turnos.anotar_movimiento(
                    # Sin I, L, O ni U: el alfabeto ULID las excluye para que
                    # nadie confunda un 1 con una l leyendo un número en voz alta.
                    movimiento_id=f"{devolucion_id[:23]}DV9"[:26],
                    sesion_id=sesion_id, tipo="devolucion",
                    monto=-devolucion.total.centavos, motivo=glosa,
                    usuario_id=usuario_id,
                    medio_pago_id=sesion.medio_efectivo_id,
                    autorizado_por=usuario_id, ahora=ahora)

            # 4 · Constancia, y el caso que emitirá la nota crédito.
            await t.auditoria.registrar(
                evento="venta.devuelta", ocurrido_en=ahora, severidad="critico",
                tienda_id=lugar["tienda_id"], caja_id=lugar["caja_id"],
                sesion_id=sesion_para_guardar, usuario_id=usuario_id,
                agregado_tipo="devolucion", agregado_id=devolucion_id,
                payload={"numero_venta": cabecera["numero"],
                         "tienda_venta": cabecera["tienda_id"],
                         "motivo": motivo_enum.value,
                         "reembolso": reembolso_enum.value,
                         "total": devolucion.total.centavos,
                         "unidades": devolucion.unidades,
                         "lineas": [{"sku": l.sku, "cantidad": l.cantidad}
                                    for l in devolucion.lineas]})

            await t.outbox.encolar(
                tipo="abrir_caso_postventa", agregado_tipo="devolucion",
                agregado_id=devolucion_id,
                payload={"devolucion_id": devolucion_id,
                         "venta_id": venta_id,
                         "numero_venta": cabecera["numero"],
                         # La tienda que ATIENDE el caso —y a cuya bodega
                         # entra la prenda—; la de la venta va aparte, que
                         # es la que emitió la factura que se anula.
                         "tienda_id": lugar["tienda_id"],
                         "tienda_venta_id": cabecera["tienda_id"],
                         "motivo": motivo_enum.value,
                         "reembolso": reembolso_enum.value,
                         "total": devolucion.total.centavos,
                         "base_gravable": devolucion.base_gravable.centavos,
                         "iva": devolucion.iva.centavos,
                         "lineas": [{"sku": l.sku, "cantidad": l.cantidad,
                                     "precio_unitario_con_iva":
                                         l.precio_unitario_con_iva_centavos}
                                    for l in devolucion.lineas]})

            await t.commit()

        return ResultadoDevolucion(
            devolucion_id=devolucion_id,
            numero_venta=cabecera["numero"],
            total_centavos=devolucion.total.centavos,
            unidades=devolucion.unidades,
            reembolso=reembolso_enum.value,
            salio_del_cajon=devolucion.sale_del_cajon,
            sesion_id=sesion_para_guardar,
        )

    # ── Lecturas ────────────────────────────────────────────────────────────

    @staticmethod
    async def _lugar(t, caja_id: Optional[str], cabecera) -> dict:
        """Dónde se hace la devolución: caja, tienda e inventario.

        Sin caja, el de la venta — lo único que existía con una sola tienda.
        Con caja, el inventario es el de SU tienda; si esa tienda no tiene
        ubicación se usa el de la venta antes que dejar la prenda sin saldo.
        """
        if not caja_id or caja_id == cabecera["caja_id"]:
            return {"caja_id": cabecera["caja_id"],
                    "tienda_id": cabecera["tienda_id"],
                    "ubicacion_id": cabecera["ubicacion_id"]}
        fila = (await t.sesion.execute(text("""
            SELECT c.id, c.tienda_id,
                   (SELECT u.id FROM retail.ubicaciones u
                     WHERE u.tienda_id = c.tienda_id AND u.tipo = 'tienda'
                     LIMIT 1) AS ubicacion_id
              FROM retail.cajas c WHERE c.id = :c
        """), {"c": caja_id})).mappings().first()
        if fila is None:
            raise ReglaDeNegocio(f"No existe la caja {caja_id}.")
        return {"caja_id": fila["id"], "tienda_id": fila["tienda_id"],
                "ubicacion_id": fila["ubicacion_id"] or cabecera["ubicacion_id"]}

    @staticmethod
    async def _lineas_vendidas(t, venta_id: str):
        """Lo que la venta dejó escrito, con su precio y su variante.

        El precio sale de `venta_lineas` y NO del catálogo: es el que la
        clienta pagó. Devolver al precio de hoy sería regalarle plata o
        quitársela, según hacia dónde se haya movido la lista.
        """
        filas = (await t.sesion.execute(text("""
            SELECT sku, variante_id, cantidad,
                   -- El unitario CON IVA que se cobró de verdad, ya con el
                   -- descuento de la línea repartido: es lo que hay que
                   -- devolver, no el precio de lista.
                   CASE WHEN cantidad > 0
                        THEN (total_linea / cantidad)::bigint
                        ELSE 0 END AS unitario
              FROM retail.venta_lineas
             WHERE venta_id = :v
        """), {"v": venta_id})).mappings().all()

        vendidas: List[LineaVendida] = []
        variantes: Dict[str, str] = {}
        for f in filas:
            vendidas.append(LineaVendida(
                sku=f["sku"], cantidad=int(f["cantidad"]),
                precio_unitario_con_iva_centavos=int(f["unitario"])))
            if f["variante_id"]:
                variantes[f["sku"]] = f["variante_id"]
        return vendidas, variantes

    @staticmethod
    async def _ya_devuelto(t, venta_id: str) -> Dict[str, int]:
        """Cuánto se devolvió ya de cada referencia de esta venta.

        Es el dato que sostiene INV-D1. Se consulta SIEMPRE, aunque la venta
        parezca intacta: la segunda visita de una clienta es exactamente el
        caso en el que nadie se acuerda de mirar.
        """
        filas = (await t.sesion.execute(text("""
            SELECT dl.sku, sum(dl.cantidad) AS n
              FROM retail.devolucion_lineas dl
              JOIN retail.devoluciones d ON d.id = dl.devolucion_id
             WHERE d.venta_id = :v
             GROUP BY dl.sku
        """), {"v": venta_id})).mappings().all()
        return {f["sku"]: int(f["n"]) for f in filas}
