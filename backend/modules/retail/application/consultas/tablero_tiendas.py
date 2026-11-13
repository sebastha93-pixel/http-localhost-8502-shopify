"""Tablero de las tiendas — cómo van TODAS, lado a lado.

El Panel (`panel_ventas.py`) es de UNA tienda y vive amarrado a la caja del
equipo: sirve a quien vende. Quien administra quiere otra cosa: abrir una
pantalla, sin abrir caja, y ver de un golpe cuál tienda va adelante, cuál se
quedó quieta y si hoy va mejor o peor que antes (Sebastián, 2026-11-13, con la
feria vendiendo desde un iPad y nadie de la oficina allá).

CUATRO DECISIONES QUE NO SON COSMÉTICAS:

**El día es el DE LA TIENDA.** Igual que el Panel: Colombia es UTC−5 y una
venta de las 7 p.m. sigue siendo de hoy. El corte se hace en Postgres con la
zona horaria de cada tienda.

**«Antes» se corta a la misma hora cuando el periodo termina hoy.** Comparar
lo vendido hasta el mediodía con TODO el día de ayer dice «vamos mal» todas
las mañanas. Si el periodo incluye hoy, el periodo anterior se cuenta sólo
hasta esta misma hora de su último día.

**El efectivo va NETO del vuelto.** `venta_pagos` guarda lo que la clienta
entregó (es lo que imprime la tirilla). Paga $300.000 por $299.800 y al cajón
entran $299.800: sumar lo entregado inflaría el efectivo por cada vuelto.

**Las devoluciones se muestran, no se restan.** «Ventas» aquí es lo mismo que
en el Panel y en el cierre: lo cobrado en ventas no anuladas. Restarlas daría
un tercer número que no cuadra con ninguno de los otros dos.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.modules.retail.application.consultas.panel_ventas import (
    HORA_APERTURA,
    HORA_CIERRE,
    MAX_DIAS,
    _dia,
)

__all__ = ["TableroTiendas", "Tablero", "TiendaDelTablero"]

#  Todas las tiendas están en Colombia. «Hoy» y «a esta hora» se calculan
#  aquí; el día de cada venta, con la zona de SU tienda.
ZONA = "America/Bogota"

#  Cuántas referencias caben en «lo más vendido» sin volverse un informe.
TOPE_VENDIDOS = 10


@dataclass
class TiendaDelTablero:
    id: str
    nombre: str
    ventas_centavos: int = 0
    transacciones: int = 0
    unidades: int = 0
    descuentos_centavos: int = 0
    anuladas: int = 0
    monto_anulado_centavos: int = 0
    devoluciones: int = 0
    monto_devuelto_centavos: int = 0
    #  Lo mismo, en el periodo anterior (ver la cabecera: cortado a esta hora).
    ventas_anterior_centavos: int = 0
    transacciones_anterior: int = 0
    #  `AAAA-MM-DD HH:MM`, hora de la tienda. Vacío si no vendió en el periodo.
    ultima_venta: str = ""
    #  Las cajas con turno abierto AHORA: [{caja, abierta_por, desde}].
    turnos_abiertos: List[dict] = field(default_factory=list)
    #  [{nombre, tipo, centavos}] — el efectivo, neto del vuelto.
    medios: List[dict] = field(default_factory=list)
    #  [{nombre, ventas_centavos, transacciones}]
    cajeras: List[dict] = field(default_factory=list)

    @property
    def ticket_promedio_centavos(self) -> int:
        if not self.transacciones:
            return 0
        return round(self.ventas_centavos / self.transacciones)


@dataclass
class Tablero:
    hoy: str
    desde: str
    hasta: str
    anterior_desde: str
    anterior_hasta: str
    #  El periodo anterior se contó sólo hasta esta hora de su último día.
    anterior_cortado: bool
    tiendas: List[TiendaDelTablero] = field(default_factory=list)
    #  Un solo día → por hora; varios → por día. Cada punto:
    #  {etiqueta, tiendas: {tienda_id: centavos}}.
    serie_por: str = "hora"
    serie: List[dict] = field(default_factory=list)
    #  [{referencia, nombre, color, unidades, valor_centavos,
    #    tiendas: {tienda_id: unidades}}]
    mas_vendidos: List[dict] = field(default_factory=list)


class TableroTiendas:
    def __init__(self, sesion: AsyncSession) -> None:
        self._s = sesion

    async def ejecutar(self, *, desde: Optional[str] = None,
                       hasta: Optional[str] = None) -> Tablero:
        """Sin fechas es el tablero de HOY. `desde`/`hasta` son `AAAA-MM-DD`."""
        from backend.modules.retail.domain.venta.errores import ReglaDeNegocio

        hoy: date = (await self._s.execute(text(
            "SELECT (now() AT TIME ZONE :z)::date"), {"z": ZONA})).scalar()
        d1 = _dia(desde) or _dia(hasta) or hoy
        d2 = _dia(hasta) or _dia(desde) or hoy
        if d1 > d2:
            d1, d2 = d2, d1
        if (d2 - d1).days > MAX_DIAS:
            raise ReglaDeNegocio("El periodo no puede pasar de un año.")

        # El periodo anterior: los mismos días, justo antes.
        dias = (d2 - d1).days + 1
        a2 = d1 - timedelta(days=1)
        a1 = a2 - timedelta(days=dias - 1)
        cortado = d2 >= hoy

        #  `siigo_pos` FUERA, como en el Panel: son facturas viejas traídas
        #  para hacerles un cambio, no ventas de la caja.
        dia_venta = ("(v.cerrada_en AT TIME ZONE "
                     f"coalesce(ti.zona_horaria, '{ZONA}'))")
        desde_ventas = """
              FROM retail.ventas v
              JOIN retail.tiendas ti ON ti.id = v.tienda_id
        """
        periodo = f"""
            v.cerrada_en IS NOT NULL AND v.origen <> 'siigo_pos'
            AND {dia_venta}::date BETWEEN :d1 AND :d2
        """
        params = {"d1": d1, "d2": d2}

        tiendas: Dict[str, TiendaDelTablero] = {
            f["id"]: TiendaDelTablero(id=f["id"], nombre=f["nombre"])
            for f in (await self._s.execute(text(
                "SELECT id, nombre FROM retail.tiendas WHERE activa ORDER BY nombre"
            ))).mappings()}

        def de(tienda_id: str, nombre: Optional[str] = None) -> TiendaDelTablero:
            #  Una tienda que se desactivó pero vendió en el periodo no
            #  desaparece del tablero: su plata sigue siendo de ese periodo.
            if tienda_id not in tiendas:
                tiendas[tienda_id] = TiendaDelTablero(
                    id=tienda_id, nombre=nombre or tienda_id)
            return tiendas[tienda_id]

        for f in (await self._s.execute(text(f"""
            SELECT v.tienda_id, max(ti.nombre) AS nombre,
                   count(*) FILTER (WHERE v.estado = 'cerrada') AS transacciones,
                   coalesce(sum(v.total) FILTER (WHERE v.estado = 'cerrada'), 0)
                       AS ventas,
                   coalesce(sum(v.descuento_total)
                            FILTER (WHERE v.estado = 'cerrada'), 0) AS descuentos,
                   count(*) FILTER (WHERE v.estado = 'anulada') AS anuladas,
                   coalesce(sum(v.total) FILTER (WHERE v.estado = 'anulada'), 0)
                       AS anulado,
                   to_char(max({dia_venta}) FILTER (WHERE v.estado = 'cerrada'),
                           'YYYY-MM-DD HH24:MI') AS ultima
            {desde_ventas} WHERE {periodo}
             GROUP BY v.tienda_id
        """), params)).mappings():
            t = de(f["tienda_id"], f["nombre"])
            t.transacciones = int(f["transacciones"])
            t.ventas_centavos = int(f["ventas"])
            t.descuentos_centavos = int(f["descuentos"])
            t.anuladas = int(f["anuladas"])
            t.monto_anulado_centavos = int(f["anulado"])
            t.ultima_venta = f["ultima"] or ""

        for f in (await self._s.execute(text(f"""
            SELECT v.tienda_id, coalesce(sum(l.cantidad), 0) AS unidades
              FROM retail.venta_lineas l
              JOIN retail.ventas v ON v.id = l.venta_id
              JOIN retail.tiendas ti ON ti.id = v.tienda_id
             WHERE {periodo} AND v.estado = 'cerrada'
             GROUP BY v.tienda_id
        """), params)).mappings():
            de(f["tienda_id"]).unidades = int(f["unidades"])

        for f in (await self._s.execute(text(f"""
            SELECT v.tienda_id, count(*) AS transacciones,
                   coalesce(sum(v.total), 0) AS ventas
            {desde_ventas}
             WHERE v.cerrada_en IS NOT NULL AND v.origen <> 'siigo_pos'
               AND v.estado = 'cerrada'
               AND {dia_venta}::date BETWEEN :a1 AND :a2
               AND (NOT :cortado OR {dia_venta}::date < :a2
                    OR {dia_venta}::time <= (now() AT TIME ZONE :z)::time)
             GROUP BY v.tienda_id
        """), {"a1": a1, "a2": a2, "cortado": cortado, "z": ZONA})).mappings():
            t = de(f["tienda_id"])
            t.ventas_anterior_centavos = int(f["ventas"])
            t.transacciones_anterior = int(f["transacciones"])

        for f in (await self._s.execute(text(f"""
            SELECT d.tienda_id, count(*) AS n, coalesce(sum(d.total), 0) AS total
              FROM retail.devoluciones d
              JOIN retail.tiendas ti ON ti.id = d.tienda_id
             WHERE (d.creada_en AT TIME ZONE coalesce(ti.zona_horaria, '{ZONA}'))
                   ::date BETWEEN :d1 AND :d2
             GROUP BY d.tienda_id
        """), params)).mappings():
            t = de(f["tienda_id"])
            t.devoluciones = int(f["n"])
            t.monto_devuelto_centavos = int(f["total"])

        # El vuelto se le quita al efectivo UNA vez por venta: por eso se
        # agrupa primero por venta y después se suma.
        for f in (await self._s.execute(text(f"""
            WITH por_venta AS (
                SELECT v.tienda_id, v.id, m.nombre, m.tipo,
                       sum(p.monto) AS monto, max(v.vuelto) AS vuelto
                  FROM retail.venta_pagos p
                  JOIN retail.ventas v ON v.id = p.venta_id
                  JOIN retail.tiendas ti ON ti.id = v.tienda_id
                  JOIN retail.medios_pago m ON m.id = p.medio_pago_id
                 WHERE {periodo} AND v.estado = 'cerrada'
                 GROUP BY v.tienda_id, v.id, m.nombre, m.tipo
            )
            SELECT tienda_id, nombre, tipo,
                   sum(CASE WHEN tipo = 'efectivo'
                            THEN greatest(monto - vuelto, 0) ELSE monto END)
                       ::bigint AS centavos
              FROM por_venta GROUP BY tienda_id, nombre, tipo
             ORDER BY centavos DESC
        """), params)).mappings():
            if int(f["centavos"]):
                de(f["tienda_id"]).medios.append({
                    "nombre": f["nombre"], "tipo": f["tipo"],
                    "centavos": int(f["centavos"])})

        for f in (await self._s.execute(text(f"""
            SELECT v.tienda_id, coalesce(max(pp.nombre), v.cajera_id) AS nombre,
                   count(*) AS transacciones, sum(v.total)::bigint AS ventas
            {desde_ventas}
              LEFT JOIN retail.permisos_pos pp ON pp.usuario_id = v.cajera_id
             WHERE {periodo} AND v.estado = 'cerrada'
             GROUP BY v.tienda_id, v.cajera_id
             ORDER BY ventas DESC
        """), params)).mappings():
            de(f["tienda_id"]).cajeras.append({
                "nombre": f["nombre"], "ventas_centavos": int(f["ventas"]),
                "transacciones": int(f["transacciones"])})

        for f in (await self._s.execute(text(f"""
            SELECT s.tienda_id, c.nombre AS caja,
                   coalesce(pp.nombre, s.abierta_por) AS abierta_por,
                   to_char(s.abierta_en AT TIME ZONE
                           coalesce(ti.zona_horaria, '{ZONA}'),
                           'YYYY-MM-DD HH24:MI') AS desde
              FROM retail.sesiones_caja s
              JOIN retail.cajas c ON c.id = s.caja_id
              JOIN retail.tiendas ti ON ti.id = s.tienda_id
              LEFT JOIN retail.permisos_pos pp ON pp.usuario_id = s.abierta_por
             WHERE s.estado = 'abierta'
             ORDER BY s.abierta_en
        """))).mappings():
            de(f["tienda_id"]).turnos_abiertos.append({
                "caja": f["caja"], "abierta_por": f["abierta_por"],
                "desde": f["desde"]})

        tablero = Tablero(
            hoy=hoy.isoformat(), desde=d1.isoformat(), hasta=d2.isoformat(),
            anterior_desde=a1.isoformat(), anterior_hasta=a2.isoformat(),
            anterior_cortado=cortado,
            serie_por="hora" if d1 == d2 else "dia",
        )

        if d1 == d2:
            filas = (await self._s.execute(text(f"""
                SELECT v.tienda_id,
                       extract(hour FROM {dia_venta})::int AS punto,
                       sum(v.total)::bigint AS ventas
                {desde_ventas} WHERE {periodo} AND v.estado = 'cerrada'
                 GROUP BY 1, 2
            """), params)).mappings().all()
            por_punto: Dict[int, Dict[str, int]] = {}
            for f in filas:
                por_punto.setdefault(int(f["punto"]), {})[f["tienda_id"]] = \
                    int(f["ventas"])
            # El horario habitual, más cualquier hora en la que sí se vendió.
            horas = set(range(HORA_APERTURA, HORA_CIERRE + 1)) | set(por_punto)
            tablero.serie = [{"etiqueta": f"{h}h", "tiendas": por_punto.get(h, {})}
                             for h in sorted(horas)]
        else:
            filas = (await self._s.execute(text(f"""
                SELECT v.tienda_id, {dia_venta}::date AS punto,
                       sum(v.total)::bigint AS ventas
                {desde_ventas} WHERE {periodo} AND v.estado = 'cerrada'
                 GROUP BY 1, 2
            """), params)).mappings().all()
            por_dia: Dict[date, Dict[str, int]] = {}
            for f in filas:
                por_dia.setdefault(f["punto"], {})[f["tienda_id"]] = \
                    int(f["ventas"])
            # TODOS los días del periodo, también los que no vendieron: un día
            # en cero es un dato, no un hueco que se pueda saltar.
            tablero.serie = [
                {"etiqueta": (d1 + timedelta(days=i)).isoformat(),
                 "tiendas": por_dia.get(d1 + timedelta(days=i), {})}
                for i in range(dias)]

        refs: Dict[str, dict] = {}
        for f in (await self._s.execute(text(f"""
            SELECT x.referencia, v.tienda_id, max(x.nombre) AS nombre,
                   max(x.color) AS color, sum(l.cantidad)::int AS unidades,
                   sum(l.total_linea)::bigint AS valor
              FROM retail.venta_lineas l
              JOIN retail.ventas v ON v.id = l.venta_id
              JOIN retail.tiendas ti ON ti.id = v.tienda_id
              JOIN retail.variantes x ON x.id = l.variante_id
             WHERE {periodo} AND v.estado = 'cerrada'
             GROUP BY x.referencia, v.tienda_id
        """), params)).mappings():
            r = refs.setdefault(f["referencia"], {
                "referencia": f["referencia"], "nombre": f["nombre"],
                "color": f["color"] or "", "unidades": 0, "valor_centavos": 0,
                "tiendas": {}})
            r["unidades"] += int(f["unidades"])
            r["valor_centavos"] += int(f["valor"])
            r["tiendas"][f["tienda_id"]] = int(f["unidades"])
        tablero.mas_vendidos = sorted(
            refs.values(),
            key=lambda r: (-r["unidades"], -r["valor_centavos"], r["referencia"]),
        )[:TOPE_VENDIDOS]

        # La que más vende, primero. El empate lo decide el nombre para que el
        # orden no baile entre una recarga y la siguiente.
        tablero.tiendas = sorted(
            tiendas.values(), key=lambda t: (-t.ventas_centavos, t.nombre))
        return tablero
