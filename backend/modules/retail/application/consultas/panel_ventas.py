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
from typing import List

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["PanelVentas", "Panel", "BarraHora", "MasVendido"]

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


@dataclass
class Panel:
    fecha: str
    tienda_nombre: str
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

    async def ejecutar(self, *, tienda_id: str) -> Panel:
        tienda = (await self._s.execute(text("""
            SELECT nombre, zona_horaria FROM retail.tiendas WHERE id = :t
        """), {"t": tienda_id})).mappings().first()
        if tienda is None:
            from backend.modules.retail.domain.venta.errores import ReglaDeNegocio
            raise ReglaDeNegocio(f"La tienda {tienda_id!r} no existe.")

        tz = tienda["zona_horaria"] or "America/Bogota"
        params = {"t": tienda_id, "tz": tz}

        # El día de la tienda, calculado por Postgres en SU zona horaria. Se
        # hace en la base y no en Python para que el corte del día sea el mismo
        # que usan el arqueo y los informes: dos definiciones de «hoy» que
        # difieren en cinco horas producen dos verdades.
        dia = """
            (v.cerrada_en AT TIME ZONE :tz)::date
                = (now() AT TIME ZONE :tz)::date
        """

        cab = (await self._s.execute(text(f"""
            SELECT (now() AT TIME ZONE :tz)::date AS fecha,
                   count(*) FILTER (WHERE v.estado = 'cerrada')     AS transacciones,
                   coalesce(sum(v.total) FILTER (WHERE v.estado='cerrada'), 0)
                       AS ventas,
                   coalesce(sum(v.descuento_total) FILTER (WHERE v.estado='cerrada'), 0)
                       AS descuentos,
                   count(*) FILTER (WHERE v.estado = 'anulada')     AS anuladas,
                   coalesce(sum(v.total) FILTER (WHERE v.estado='anulada'), 0)
                       AS anulado
              FROM retail.ventas v
             WHERE v.tienda_id = :t AND v.cerrada_en IS NOT NULL AND {dia}
        """), params)).mappings().one()

        unidades = (await self._s.execute(text(f"""
            SELECT coalesce(sum(l.cantidad), 0)
              FROM retail.venta_lineas l
              JOIN retail.ventas v ON v.id = l.venta_id
             WHERE v.tienda_id = :t AND v.estado = 'cerrada'
               AND v.cerrada_en IS NOT NULL AND {dia}
        """), params)).scalar() or 0

        por_hora = (await self._s.execute(text(f"""
            SELECT extract(hour FROM (v.cerrada_en AT TIME ZONE :tz))::int AS hora,
                   sum(v.total)::bigint AS ventas,
                   count(*)::int        AS transacciones
              FROM retail.ventas v
             WHERE v.tienda_id = :t AND v.estado = 'cerrada'
               AND v.cerrada_en IS NOT NULL AND {dia}
             GROUP BY 1 ORDER BY 1
        """), params)).mappings().all()

        vendidos = (await self._s.execute(text(f"""
            SELECT x.referencia, max(x.nombre) AS nombre, max(x.color) AS color,
                   sum(l.cantidad)::int    AS unidades,
                   sum(l.total_linea)::bigint AS valor
              FROM retail.venta_lineas l
              JOIN retail.ventas v ON v.id = l.venta_id
              JOIN retail.variantes x ON x.id = l.variante_id
             WHERE v.tienda_id = :t AND v.estado = 'cerrada'
               AND v.cerrada_en IS NOT NULL AND {dia}
             GROUP BY x.referencia
             -- Por UNIDADES, no por valor: el panel responde «qué se está
             -- llevando la gente», que es lo que hay que reponer. El de mayor
             -- facturación es otra pregunta y otra tarjeta.
             ORDER BY unidades DESC, valor DESC
             LIMIT 5
        """), params)).mappings().all()

        panel = Panel(
            fecha=cab["fecha"].isoformat(), tienda_nombre=tienda["nombre"],
            ventas_centavos=int(cab["ventas"]),
            transacciones=int(cab["transacciones"]),
            unidades=int(unidades),
            anuladas=int(cab["anuladas"]),
            monto_anulado_centavos=int(cab["anulado"]),
            descuentos_centavos=int(cab["descuentos"]),
        )

        movidas = {int(f["hora"]): f for f in por_hora}
        for hora in _ventana(movidas.keys()):
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
        return panel


def _ventana(horas_con_venta) -> List[int]:
    """El horario habitual, más cualquier hora en la que sí hubo movimiento.

    Recortar a 10–20 escondería la venta de las 21:05 de un día de diciembre —y
    justo esas son las que la administradora quiere ver.
    """
    horas = set(range(HORA_APERTURA, HORA_CIERRE + 1)) | set(horas_con_venta)
    return sorted(horas)
