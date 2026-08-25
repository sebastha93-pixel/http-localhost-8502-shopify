"""Catálogo agrupado por REFERENCIA, con sus tallas.

VIENE DEL DISEÑO. El handoff pone una tarjeta por referencia con una fila de
chips de talla adentro, no una tarjeta por talla. Es mejor de lo que yo había
dibujado: en denim la foto de cinco tallas es la misma foto, así que separarlas
sólo multiplica tarjetas y scroll. La cajera toca la talla donde ya está
mirando.

Eso cambia la forma del dato: la rejilla necesita una fila por referencia con
sus tallas anidadas, no una fila por variante.

DOS COSAS QUE EL PROTOTIPO NO PODÍA SABER:

**Las tallas no son cinco fijas.** El diseño dibuja 24/26/28/30/32; los SKU
reales de MALE parsean a 4, 6, 8, 10, 12 (`92611-1T10` → talla 10). La
consulta devuelve las que existan, en su orden numérico, y la rejilla se
adapta.

**Agotado no se esconde.** Viene con `disponible: 0` para que el chip se pinte
deshabilitado, tal como pide el handoff. Ocultarlo haría creer que esa talla
no existe, cuando lo que pasa es que hoy no hay.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["ListarReferencias", "Referencia", "TallaDisponible"]


@dataclass(frozen=True)
class TallaDisponible:
    variante_id: str
    sku: str
    talla: str
    disponible: int
    precio_con_iva_centavos: int
    tasa_iva: str


@dataclass(frozen=True)
class Referencia:
    referencia: str
    nombre: str
    color: str
    categoria: str
    precio_con_iva_centavos: int
    tasa_iva: str
    tallas: List[TallaDisponible]


class ListarReferencias:
    def __init__(self, sesion: AsyncSession) -> None:
        self._s = sesion

    async def ejecutar(self, *, ubicacion_id: str, texto: str = "",
                       categoria: str = "", limite: int = 60) -> List[Referencia]:
        condiciones = ["v.activa"]
        params: dict = {"u": ubicacion_id, "n": min(limite, 120)}

        if categoria and categoria.lower() not in ("todo", "todas"):
            condiciones.append("c.categoria = :cat")
            params["cat"] = categoria

        for i, token in enumerate([t for t in texto.lower().split() if t][:6]):
            condiciones.append(f"c.texto_busqueda LIKE :t{i}")
            params[f"t{i}"] = f"%{token}%"

        filas = (await self._s.execute(text(f"""
            SELECT v.referencia, v.nombre, v.color, v.categoria, v.sku, v.id,
                   v.talla, v.precio_con_iva, v.tasa_iva,
                   coalesce(s.cantidad - s.reservado, 0) AS disponible
              FROM retail.catalogo_busqueda c
              JOIN retail.variantes v ON v.id = c.variante_id
              LEFT JOIN retail.stock_ubicacion s
                     ON s.variante_id = v.id AND s.ubicacion_id = :u
             WHERE {' AND '.join(condiciones)}
             ORDER BY v.referencia,
                   -- la talla 4 antes que la 10: como texto saldría al revés
                   nullif(regexp_replace(v.talla, '\\D', '', 'g'), '')::int NULLS LAST,
                   v.talla
        """), params)).mappings().all()

        # Se agrupa en Python y no con un JSON_AGG en SQL: la consulta plana
        # aprovecha el índice de categoría y el ORDER BY que ya ordena las
        # tallas numéricamente. Agrupar en la base obligaría a un subquery que
        # ese índice no cubre.
        agrupadas: dict = {}
        orden: List[str] = []
        for f in filas:
            ref = f["referencia"]
            if ref not in agrupadas:
                if len(orden) >= params["n"]:
                    continue
                orden.append(ref)
                agrupadas[ref] = Referencia(
                    referencia=ref, nombre=f["nombre"], color=f["color"],
                    categoria=f["categoria"],
                    precio_con_iva_centavos=int(f["precio_con_iva"]),
                    tasa_iva=str(f["tasa_iva"]), tallas=[],
                )
            agrupadas[ref].tallas.append(TallaDisponible(
                variante_id=f["id"], sku=f["sku"], talla=f["talla"],
                disponible=int(f["disponible"]),
                precio_con_iva_centavos=int(f["precio_con_iva"]),
                tasa_iva=str(f["tasa_iva"]),
            ))
        return [agrupadas[r] for r in orden]

    async def categorias(self) -> List[str]:
        """Las que existen, para los chips. No una lista fija en el código:
        el día que entre 'Vestidos' aparece sola."""
        filas = (await self._s.execute(text("""
            SELECT DISTINCT categoria FROM retail.catalogo_busqueda
             ORDER BY categoria
        """))).scalars().all()
        return list(filas)
