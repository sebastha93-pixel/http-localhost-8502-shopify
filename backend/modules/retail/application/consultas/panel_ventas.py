"""Panel de ventas del día — vista 8 del handoff.

Lo que mira la administradora entre clientas: cómo va el día, a qué horas se
vende y qué se está llevando la gente.

TRES DECISIONES QUE NO SON COSMÉTICAS:

**«Hoy» es el día DE LA TIENDA, no el del servidor.** Colombia está en UTC−5:
con `date_trunc('day', now())` en UTC, todo lo vendido después de las 7 p.m.
caería en el día siguiente. La administradora vería el panel vaciarse a media
tarde y no cuadraría con el arqueo del cierre. Se usa `tiendas.zona_horaria`,
que ya existe en el esquema.

**Las horas del gráfico no son 10–20 fijas.** El prototipo las dibuja así
—horario de centro comercial—, pero una venta a las 21:05 en una tienda que
cerró tarde desaparecería del gráfico sin dejar rastro. La ventana es la unión
del horario habitual y las horas en las que realmente hubo movimiento.

**«Devoluciones» son ANULACIONES.** Devoluciones quedan fuera de esta fase por
alcance. Poner la tarjeta en cero haría creer que el módulo existe y que hoy no
hubo ninguna, que es una afirmación distinta de «no se puede hacer».
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["PanelVentas", "Panel", "BarraHora", "MasVendido", "PorFit",
           "PorDia"]

#  Un año de tope: más que eso es un informe, no un panel.
MAX_DIAS = 366

# El horario habitual de las tiendas. Es el ANCLA del gráfico, no su límite:
# si se vendió antes o después, esas horas se agregan.
HORA_APERTURA = 10
HORA_CIERRE = 20


@dataclass(frozen=True)
class BarraHora:
    hora: int
    etiqueta: str
    ventas_centavos: int
    transacciones: int


@dataclass(frozen=True)
class MasVendido:
    posicion: int
    referencia: str
    nombre: str
    color: str
    unidades: int
    valor_centavos: int


@dataclass(frozen=True)
class PorFit:
    """Lo vendido de un FIT (skinny, wide leg, flare…): la categoría de la
    prenda, que viene del grupo de inventario de Siigo."""
    categoria: str
    unidades: int
    valor_centavos: int
    #  Qué parte de las unidades del periodo fue de este fit, de 0 a 100.
    participacion: int


@dataclass(frozen=True)
class PorDia:
    fecha: str
    ventas_centavos: int
    transacciones: int
    unidades: int


@dataclass
class Panel:
    fecha: str
    tienda_nombre: str
    #  El periodo que de verdad se consultó, y con qué filtros.
    desde: str = ""
    hasta: str = ""
    hora_desde: int = 0
    hora_hasta: int = 23
    categoria: Optional[str] = None
    categorias: List[str] = field(default_factory=list)
    por_fit: List[PorFit] = field(default_factory=list)
    por_dia: List[PorDia] = field(default_factory=list)
    ventas_centavos: int = 0
    transacciones: int = 0
    unidades: int = 0
    anuladas: int = 0
    monto_anulado_centavos: int = 0
    descuentos_centavos: int = 0
    horas: List[BarraHora] = field(default_factory=list)
    mas_vendidos: List[MasVendido] = field(default_factory=list)

    @property
    def ticket_promedio_centavos(self) -> int:
        # Sin ventas el promedio no es cero: no existe. Devolver 0 haría que la
        # tarjeta dijera «ticket promedio $0», que se lee como un mal día.
        if not self.transacciones:
            return 0
        return round(self.ventas_centavos / self.transacciones)


class PanelVentas:
    def __init__(self, sesion: AsyncSession) -> None:
        self._s = sesion

    async def ejecutar(self, *, tienda_id: str,
                       desde: Optional[str] = None, hasta: Optional[str] = None,
                       hora_desde: Optional[int] = None,
                       hora_hasta: Optional[int] = None,
                       categoria: Optional[str] = None) -> Panel:
        """Sin filtros es el panel de HOY, como siempre.

        `desde`/`hasta` (`AAAA-MM-DD`) son días DE LA TIENDA; `hora_desde`/
        `hora_hasta` (0–23) recortan la franja del día; `categoria` deja sólo
        un fit. Con fit, las cifras son las de ESAS PRENDAS —no el tiquete
        entero de quien llevó una—: es lo que responde «cuánto vendí de
        skinny».
        """
        from backend.modules.retail.domain.venta.errores import ReglaDeNegocio

        tienda = (await self._s.execute(text("""
            SELECT nombre, zona_horaria,
                   (now() AT TIME ZONE coalesce(zona_horaria, 'America/Bogota'))::date
                       AS hoy
              FROM retail.tiendas WHERE id = :t
        """), {"t": tienda_id})).mappings().first()
        if tienda is None:
            raise ReglaDeNegocio(f"La tienda {tienda_id!r} no existe.")

        tz = tienda["zona_horaria"] or "America/Bogota"
        hoy: date = tienda["hoy"]
        d1 = _dia(desde) or _dia(hasta) or hoy
        d2 = _dia(hasta) or _dia(desde) or hoy
        if d1 > d2:
            d1, d2 = d2, d1
        if (d2 - d1).days > MAX_DIAS:
            raise ReglaDeNegocio("El periodo no puede pasar de un año.")
        h1 = 0 if hora_desde is None else max(0, min(23, int(hora_desde)))
        h2 = 23 if hora_hasta is None else max(0, min(23, int(hora_hasta)))
        if h1 > h2:
            h1, h2 = h2, h1
        cat = (categoria or "").strip() or None
        if cat and cat.lower() in ("todo", "todas", "todos"):
            cat = None
        params = {"t": tienda_id, "tz": tz, "d1": d1, "d2": d2, "h1": h1,
                  "h2": h2, "cat": cat}

        # El día de la tienda, calculado por Postgres en SU zona horaria. Se
        # hace en la base y no en Python para que el corte del día sea el mismo
        # que usan el arqueo y los informes: dos definiciones de «hoy» que
        # difieren en cinco horas producen dos verdades.
        #
        # `siigo_pos` FUERA: son facturas viejas traídas para hacerles un
        # cambio, con su fecha original. No son ventas de esta caja, y en un
        # rango de fechas se colarían como si lo fueran.
        periodo = """
            v.tienda_id = :t AND v.cerrada_en IS NOT NULL
            AND v.origen <> 'siigo_pos'
            AND (v.cerrada_en AT TIME ZONE :tz)::date BETWEEN :d1 AND :d2
            AND extract(hour FROM (v.cerrada_en AT TIME ZONE :tz))
                BETWEEN :h1 AND :h2
        """
        lineas = f"""
              FROM retail.venta_lineas l
              JOIN retail.ventas v ON v.id = l.venta_id
              JOIN retail.variantes x ON x.id = l.variante_id
             WHERE {periodo}
        """

        if cat is None:
            cab = (await self._s.execute(text(f"""
                SELECT count(*) FILTER (WHERE v.estado = 'cerrada') AS transacciones,
                       coalesce(sum(v.total) FILTER (WHERE v.estado='cerrada'), 0)
                           AS ventas,
                       coalesce(sum(v.descuento_total)
                                FILTER (WHERE v.estado='cerrada'), 0) AS descuentos,
                       count(*) FILTER (WHERE v.estado = 'anulada') AS anuladas,
                       coalesce(sum(v.total) FILTER (WHERE v.estado='anulada'), 0)
                           AS anulado
                  FROM retail.ventas v WHERE {periodo}
            """), params)).mappings().one()
            por_hora = (await self._s.execute(text(f"""
                SELECT extract(hour FROM (v.cerrada_en AT TIME ZONE :tz))::int AS hora,
                       sum(v.total)::bigint AS ventas,
                       count(*)::int        AS transacciones
                  FROM retail.ventas v
                 WHERE {periodo} AND v.estado = 'cerrada'
                 GROUP BY 1 ORDER BY 1
            """), params)).mappings().all()
        else:
            cab = (await self._s.execute(text(f"""
                SELECT count(DISTINCT v.id) FILTER (WHERE v.estado = 'cerrada')
                           AS transacciones,
                       coalesce(sum(l.total_linea)
                                FILTER (WHERE v.estado='cerrada'), 0) AS ventas,
                       coalesce(sum(l.descuento_monto)
                                FILTER (WHERE v.estado='cerrada'), 0) AS descuentos,
                       count(DISTINCT v.id) FILTER (WHERE v.estado = 'anulada')
                           AS anuladas,
                       coalesce(sum(l.total_linea)
                                FILTER (WHERE v.estado='anulada'), 0) AS anulado
                {lineas} AND x.categoria = :cat
            """), params)).mappings().one()
            por_hora = (await self._s.execute(text(f"""
                SELECT extract(hour FROM (v.cerrada_en AT TIME ZONE :tz))::int AS hora,
                       sum(l.total_linea)::bigint  AS ventas,
                       count(DISTINCT v.id)::int   AS transacciones
                {lineas} AND v.estado = 'cerrada' AND x.categoria = :cat
                 GROUP BY 1 ORDER BY 1
            """), params)).mappings().all()

        filtro_fit = "AND x.categoria = :cat" if cat else ""
        unidades = (await self._s.execute(text(f"""
            SELECT coalesce(sum(l.cantidad), 0)
            {lineas} AND v.estado = 'cerrada' {filtro_fit}
        """), params)).scalar() or 0

        vendidos = (await self._s.execute(text(f"""
            SELECT x.referencia, max(x.nombre) AS nombre, max(x.color) AS color,
                   sum(l.cantidad)::int    AS unidades,
                   sum(l.total_linea)::bigint AS valor
            {lineas} AND v.estado = 'cerrada' {filtro_fit}
             GROUP BY x.referencia
             -- Por UNIDADES, no por valor: el panel responde «qué se está
             -- llevando la gente», que es lo que hay que reponer. El de mayor
             -- facturación es otra pregunta y otra tarjeta.
             ORDER BY unidades DESC, valor DESC
             LIMIT :tope
        """), {**params, "tope": 5 if d1 == d2 else 15})).mappings().all()

        # VENTAS POR FIT: todos los fits del periodo, sin el filtro de fit —
        # es la tabla que permite compararlos.
        fits = (await self._s.execute(text(f"""
            SELECT x.categoria, sum(l.cantidad)::int AS unidades,
                   sum(l.total_linea)::bigint AS valor
            {lineas} AND v.estado = 'cerrada'
             GROUP BY x.categoria ORDER BY unidades DESC, valor DESC
        """), params)).mappings().all()

        dias = []
        if d1 != d2:
            dias = (await self._s.execute(text(f"""
                SELECT (v.cerrada_en AT TIME ZONE :tz)::date AS fecha,
                       sum(l.total_linea)::bigint  AS ventas,
                       count(DISTINCT v.id)::int   AS transacciones,
                       sum(l.cantidad)::int        AS unidades
                {lineas} AND v.estado = 'cerrada' {filtro_fit}
                 GROUP BY 1 ORDER BY 1
            """), params)).mappings().all()

        categorias = (await self._s.execute(text("""
            SELECT DISTINCT categoria FROM retail.variantes
             WHERE activa AND categoria IS NOT NULL AND categoria <> ''
             ORDER BY 1
        """))).scalars().all()

        panel = Panel(
            fecha=hoy.isoformat(), tienda_nombre=tienda["nombre"],
            desde=d1.isoformat(), hasta=d2.isoformat(),
            hora_desde=h1, hora_hasta=h2, categoria=cat,
            categorias=list(categorias),
            ventas_centavos=int(cab["ventas"]),
            transacciones=int(cab["transacciones"]),
            unidades=int(unidades),
            anuladas=int(cab["anuladas"]),
            monto_anulado_centavos=int(cab["anulado"]),
            descuentos_centavos=int(cab["descuentos"]),
        )

        movidas = {int(f["hora"]): f for f in por_hora}
        for hora in _ventana(movidas.keys()):
            if not h1 <= hora <= h2:
                continue
            f = movidas.get(hora)
            panel.horas.append(BarraHora(
                hora=hora, etiqueta=f"{hora}h",
                ventas_centavos=int(f["ventas"]) if f else 0,
                transacciones=int(f["transacciones"]) if f else 0,
            ))

        panel.mas_vendidos = [
            MasVendido(posicion=i, referencia=f["referencia"], nombre=f["nombre"],
                       color=f["color"] or "", unidades=int(f["unidades"]),
                       valor_centavos=int(f["valor"]))
            for i, f in enumerate(vendidos, start=1)
        ]
        total_u = sum(int(f["unidades"]) for f in fits) or 1
        panel.por_fit = [
            PorFit(categoria=f["categoria"] or "Sin categoría",
                   unidades=int(f["unidades"]), valor_centavos=int(f["valor"]),
                   participacion=round(int(f["unidades"]) * 100 / total_u))
            for f in fits]
        panel.por_dia = [
            PorDia(fecha=f["fecha"].isoformat(), ventas_centavos=int(f["ventas"]),
                   transacciones=int(f["transacciones"]),
                   unidades=int(f["unidades"])) for f in dias]
        return panel


def _dia(texto: Optional[str]) -> Optional[date]:
    """`AAAA-MM-DD` → fecha. `None` si viene vacío o no es una fecha."""
    if not texto:
        return None
    try:
        return datetime.strptime(str(texto)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _ventana(horas_con_venta) -> List[int]:
    """El horario habitual, más cualquier hora en la que sí hubo movimiento.

    Recortar a 10–20 escondería la venta de las 21:05 de un día de diciembre —y
    justo esas son las que la administradora quiere ver.
    """
    horas = set(range(HORA_APERTURA, HORA_CIERRE + 1)) | set(horas_con_venta)
    return sorted(horas)
