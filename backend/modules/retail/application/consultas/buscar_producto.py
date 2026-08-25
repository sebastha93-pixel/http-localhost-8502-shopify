"""BuscarProducto — la consulta que define la sensación del POS.

La cajera escribe `92611 azul 10` y tiene que ver la prenda **antes de
terminar de escribir**. Este es el respaldo del servidor; en operación normal
la búsqueda ocurre contra IndexedDB y no viaja a la red (ADR-009).

Aun así el servidor tiene que ser rápido, porque es lo que usa el dispositivo
en su primer arranque y cuando su copia local todavía no está lista.

TRES DECISIONES:

**Se busca por tokens, no por la frase completa.** `92611 azul 10` son tres
condiciones que se cumplen todas, no un texto literal. Nadie escribe el nombre
del producto tal como está en el catálogo.

**El código de barras gana siempre.** Si lo que llega coincide exacto con un
código, se devuelve esa variante sola: es un escaneo, no una búsqueda, y
mostrar «resultados» ahí obligaría a un clic que arruina los 30 segundos.

**El orden es exacto → prefijo → parecido.** Quien escribe una referencia
completa la quiere primera, no sepultada entre las que se le parecen.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["BuscarProducto", "Resultado"]

_MAX = 60


@dataclass(frozen=True)
class Resultado:
    variante_id: str
    sku: str
    referencia: str
    talla: str
    color: str
    nombre: str
    precio_con_iva_centavos: int
    tasa_iva: str
    codigo_barras: Optional[str]
    disponible: int
    es_escaneo: bool = False


class BuscarProducto:
    def __init__(self, sesion: AsyncSession) -> None:
        self._s = sesion

    async def ejecutar(self, texto: str, *, ubicacion_id: str,
                       limite: int = 24) -> List[Resultado]:
        consulta = (texto or "").strip()
        if not consulta:
            return []

        exacto = await self._por_codigo_de_barras(consulta, ubicacion_id)
        if exacto:
            return [exacto]

        tokens = [t for t in consulta.lower().split() if t][:6]
        if not tokens:
            return []

        # Un AND de LIKEs sobre el texto ya normalizado. El índice GIN de
        # trigramas lo resuelve sin recorrer la tabla.
        condiciones = " AND ".join(
            f"v.texto_busqueda LIKE :t{i}" for i in range(len(tokens)))
        params = {f"t{i}": f"%{t}%" for i, t in enumerate(tokens)}
        params.update({"u": ubicacion_id, "n": min(limite, _MAX),
                       "primero": tokens[0]})

        filas = (await self._s.execute(text(f"""
            SELECT v.variante_id, x.sku, x.referencia, x.talla, x.color,
                   x.nombre, x.precio_con_iva, x.tasa_iva, x.codigo_barras,
                   coalesce(s.cantidad - s.reservado, 0) AS disponible
              FROM retail.catalogo_busqueda v
              JOIN retail.variantes x ON x.id = v.variante_id
              LEFT JOIN retail.stock_ubicacion s
                     ON s.variante_id = v.variante_id AND s.ubicacion_id = :u
             WHERE x.activa AND {condiciones}
             ORDER BY
                   -- exacto primero, luego prefijo, luego el resto
                   (lower(x.sku) = :primero) DESC,
                   (lower(x.referencia) = :primero) DESC,
                   (v.texto_busqueda LIKE :primero || '%') DESC,
                   -- con stock antes que agotado: ofrecer lo que no hay
                   -- obliga a la cajera a descubrirlo tocando
                   (coalesce(s.cantidad - s.reservado, 0) > 0) DESC,
                   x.referencia,
                   -- la talla 4 antes que la 10: como texto saldría al revés
                   nullif(regexp_replace(x.talla, '\\D', '', 'g'), '')::int
                     NULLS LAST,
                   x.talla
             LIMIT :n
        """), params)).mappings().all()

        return [self._a_resultado(f) for f in filas]

    async def _por_codigo_de_barras(self, consulta: str,
                                    ubicacion_id: str) -> Optional[Resultado]:
        fila = (await self._s.execute(text("""
            SELECT x.id AS variante_id, x.sku, x.referencia, x.talla, x.color,
                   x.nombre, x.precio_con_iva, x.tasa_iva, x.codigo_barras,
                   coalesce(s.cantidad - s.reservado, 0) AS disponible
              FROM retail.variantes x
              LEFT JOIN retail.stock_ubicacion s
                     ON s.variante_id = x.id AND s.ubicacion_id = :u
             WHERE x.activa AND (x.codigo_barras = :c OR upper(x.sku) = upper(:c))
             LIMIT 1
        """), {"c": consulta, "u": ubicacion_id})).mappings().first()
        if fila is None:
            return None
        return self._a_resultado(fila, es_escaneo=True)

    @staticmethod
    def _a_resultado(f, es_escaneo: bool = False) -> Resultado:
        return Resultado(
            variante_id=f["variante_id"], sku=f["sku"],
            referencia=f["referencia"], talla=f["talla"], color=f["color"],
            nombre=f["nombre"], precio_con_iva_centavos=int(f["precio_con_iva"]),
            tasa_iva=str(f["tasa_iva"]), codigo_barras=f["codigo_barras"],
            disponible=int(f["disponible"]), es_escaneo=es_escaneo,
        )


class ReconstruirCatalogoBusqueda:
    """Alimenta el read model. Lo dispara un evento del catálogo.

    El texto se normaliza UNA vez al escribir, no en cada búsqueda: es lo que
    permite que la consulta sea un LIKE sobre una columna indexada en vez de
    una función sobre cada fila.

    OJO CON LAS COLUMNAS QUE SE COPIAN. Este INSERT es la ÚNICA vía por la que
    el read model se entera de un cambio del catálogo. `categoria` faltaba: la
    semilla la escribía a mano, así que en local todo se veía bien, pero la
    primera sincronización real habría dejado cada prenda en 'Otros' —el
    default de la columna— y los chips de categoría de la pantalla de venta
    habrían colapsado en uno solo, sin ningún error.
    """

    def __init__(self, sesion: AsyncSession) -> None:
        self._s = sesion

    async def ejecutar(self, *, desde=None) -> int:
        filtro = "WHERE v.actualizado_en > :desde" if desde else ""
        r = await self._s.execute(text(f"""
            INSERT INTO retail.catalogo_busqueda
                (variante_id, texto_busqueda, referencia, talla, color,
                 categoria, precio_con_iva, actualizado_en)
            SELECT v.id,
                   retail.norm(concat_ws(' ', v.sku, v.referencia, v.nombre,
                                         v.color, v.talla, v.codigo_barras)),
                   v.referencia, v.talla, v.color, v.categoria,
                   v.precio_con_iva, now()
              FROM retail.variantes v
              {filtro}
            ON CONFLICT (variante_id) DO UPDATE
                SET texto_busqueda = EXCLUDED.texto_busqueda,
                    referencia     = EXCLUDED.referencia,
                    talla          = EXCLUDED.talla,
                    color          = EXCLUDED.color,
                    categoria      = EXCLUDED.categoria,
                    precio_con_iva = EXCLUDED.precio_con_iva,
                    actualizado_en = now()
        """), {"desde": desde} if desde else {})
        return r.rowcount
