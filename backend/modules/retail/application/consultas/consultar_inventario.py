"""Inventario por referencia y talla — vista 6 del handoff.

Responde la pregunta que hoy obliga a la cajera a salirse del carrito y buscar
a alguien: «¿tienes la 10 en azul?».

TRES DECISIONES QUE EL PROTOTIPO NO PODÍA TOMAR:

**Las tallas no son cinco fijas.** El handoff dibuja columnas T24…T32 —tallaje
de jean americano—. Los SKU reales de MALE parsean a 4, 6, 8, 10, 12
(`92611-1T10` → talla 10). Las columnas salen de los datos, en orden numérico,
y el día que entre una talla nueva aparece sola.

**Hay DOS umbrales y miden cosas distintas.** El de la tienda mira el total
de la referencia, como el prototipo: es el que sirve el primer día, sin
configurar nada. `stock_minimo` mira UNA talla en UNA ubicación, y sólo habla
cuando alguien lo puso a propósito.

Aplicar el umbral de la tienda por talla —que es lo que hice primero— parece
más fino y es peor: con 12 unidades repartidas en cinco tallas, ninguna llega
a 8 y TODAS las referencias salen marcadas. Un aviso que sale siempre no es un
aviso. El número del handoff (8) está pensado para el total, y cambiarle la
unidad sin cambiarle el valor lo rompe.

**Se ve dónde MÁS hay.** Traslados entre tiendas quedan fuera de esta fase por
alcance, pero saber que en la otra tienda quedan tres es la diferencia entre
«no hay» y «te la consigo». La columna informa; no promete un traslado.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["ConsultarInventario", "FilaInventario", "CeldaTalla", "Inventario"]


@dataclass(frozen=True)
class CeldaTalla:
    talla: str
    disponible: int
    #  El mínimo AFINADO para esta talla, o 0 si nadie lo configuró. Viaja para
    #  que la pantalla pueda explicar por qué avisa en vez de sólo pintarlo.
    minimo: int
    es_bajo: bool


@dataclass
class FilaInventario:
    referencia: str
    nombre: str
    color: str
    categoria: str
    precio_con_iva_centavos: int
    tallas: List[CeldaTalla] = field(default_factory=list)
    total: int = 0
    en_otras_ubicaciones: int = 0
    umbral_referencia: int = 0

    @property
    def estado(self) -> str:
        if self.total <= 0:
            return "agotado"
        # El total por debajo del umbral de la tienda, O una talla concreta que
        # alguien marcó como crítica. Lo segundo es lo que permite que la
        # referencia con 40 unidades pero sin la 10 no pase por sana.
        if self.total <= self.umbral_referencia or any(c.es_bajo for c in self.tallas):
            return "bajo"
        return "ok"


@dataclass
class Inventario:
    """Las columnas vienen con los datos: la tabla no las puede suponer."""

    columnas_talla: List[str]
    filas: List[FilaInventario]
    umbral_tienda: int

    @property
    def referencias(self) -> int:
        return len(self.filas)

    @property
    def con_stock_bajo(self) -> int:
        return sum(1 for f in self.filas if f.estado in ("bajo", "agotado"))


class ConsultarInventario:
    def __init__(self, sesion: AsyncSession) -> None:
        self._s = sesion

    async def ejecutar(self, *, ubicacion_id: str, tienda_id: str,
                       texto: str = "", categoria: str = "",
                       solo_bajos: bool = False) -> Inventario:
        umbral = (await self._s.execute(text("""
            SELECT umbral_stock_bajo FROM retail.tiendas WHERE id = :t
        """), {"t": tienda_id})).scalar()
        if umbral is None:
            umbral = 0

        condiciones = ["v.activa"]
        params: dict = {"u": ubicacion_id, "umbral": int(umbral)}

        if categoria and categoria.lower() not in ("todo", "todas"):
            condiciones.append("v.categoria = :cat")
            params["cat"] = categoria

        for i, token in enumerate([t for t in texto.lower().split() if t][:6]):
            condiciones.append(f"c.texto_busqueda LIKE :t{i}")
            params[f"t{i}"] = f"%{token}%"

        # `disponible` descuenta lo RESERVADO: una prenda apartada por otra caja
        # a medio cobrar no está para vender, y ofrecerla produce la peor
        # conversación posible en el mostrador.
        filas = (await self._s.execute(text(f"""
            SELECT v.referencia, v.nombre, v.color, v.categoria,
                   v.precio_con_iva, v.talla,
                   coalesce(s.cantidad - s.reservado, 0)   AS disponible,
                   coalesce(s.stock_minimo, 0)             AS minimo,
                   coalesce(o.otras, 0)                    AS otras
              FROM retail.catalogo_busqueda c
              JOIN retail.variantes v ON v.id = c.variante_id
              LEFT JOIN retail.stock_ubicacion s
                     ON s.variante_id = v.id AND s.ubicacion_id = :u
              LEFT JOIN LATERAL (
                    SELECT sum(s2.cantidad - s2.reservado)::bigint AS otras
                      FROM retail.stock_ubicacion s2
                      JOIN retail.ubicaciones ub ON ub.id = s2.ubicacion_id
                     WHERE s2.variante_id = v.id
                       AND s2.ubicacion_id <> :u
                       AND ub.tipo IN ('tienda', 'bodega')
              ) o ON true
             WHERE {' AND '.join(condiciones)}
             ORDER BY v.referencia,
                   nullif(regexp_replace(v.talla, '\\D', '', 'g'), '')::int
                     NULLS LAST,
                   v.talla
        """), params)).mappings().all()

        agrupadas: dict = {}
        orden: List[str] = []
        tallas_vistas: List[str] = []

        for f in filas:
            ref = f["referencia"]
            if ref not in agrupadas:
                orden.append(ref)
                agrupadas[ref] = FilaInventario(
                    referencia=ref, nombre=f["nombre"], color=f["color"],
                    categoria=f["categoria"],
                    precio_con_iva_centavos=int(f["precio_con_iva"]),
                    umbral_referencia=int(umbral),
                )
            fila = agrupadas[ref]
            disponible = int(f["disponible"])
            minimo = int(f["minimo"])
            fila.tallas.append(CeldaTalla(
                talla=f["talla"], disponible=disponible, minimo=minimo,
                # Sólo avisa por talla si alguien AFINÓ esa talla. Y agotado no
                # es «bajo»: es su propia categoría, y mezclarlas esconde la
                # prenda que todavía se puede reponer a tiempo.
                es_bajo=minimo > 0 and 0 < disponible <= minimo,
            ))
            fila.total += disponible
            fila.en_otras_ubicaciones += int(f["otras"])
            if f["talla"] not in tallas_vistas:
                tallas_vistas.append(f["talla"])

        resultado = [agrupadas[r] for r in orden]
        if solo_bajos:
            resultado = [f for f in resultado if f.estado in ("bajo", "agotado")]

        return Inventario(
            columnas_talla=_ordenar_tallas(tallas_vistas),
            filas=resultado, umbral_tienda=int(umbral),
        )


def _ordenar_tallas(tallas: List[str]) -> List[str]:
    """La 4 antes que la 10. Como texto saldría al revés — y una tabla de
    tallas desordenada se lee mal aunque los números estén bien."""
    def clave(t: str):
        digitos = "".join(ch for ch in t if ch.isdigit())
        return (0, int(digitos), t) if digitos else (1, 0, t)

    return sorted(tallas, key=clave)
