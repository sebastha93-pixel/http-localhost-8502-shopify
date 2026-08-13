"""Bloques de consecutivos — lo que hace posible vender sin internet.

EL PROBLEMA QUE RESUELVE. La pantalla numeraba con `Date.now() % 100000`. Eso
**se repite exactamente cada 100 segundos**, y como la base tiene
`ux_venta_numero UNIQUE (caja_id, prefijo, consecutivo)`, dos ventas separadas
por ese intervalo chocan y la segunda falla en el mostrador con la clienta
esperando. Con cien ventas al día la probabilidad de que ocurra en alguna caja
es de ~5 % diario: no es teórico, es cuestión de semanas.

CÓMO FUNCIONA. Al abrir turno la caja arrienda un bloque de números. El
dispositivo numera dentro de su bloque sin volver a preguntar, así que sin
internet sigue emitiendo tiquetes con numeración válida y sin chocar con la
otra caja. Al 80 % consumido pide el siguiente.

LOS HUECOS SON INTENCIONALES. Un bloque que se abandona a medias deja saltos en
la numeración interna. No tiene efecto fiscal: **el consecutivo DIAN lo asigna
Siigo al emitir**, y este número es el del tiquete, no el de la factura. Sin
esa separación, offline sería imposible — no se puede pedir un consecutivo
fiscal sin red.

EL ARRIENDO ES UNA SOLA SENTENCIA. Leer el último bloque y después insertar el
siguiente deja una ventana en la que dos cajas leen lo mismo y arriendan el
mismo rango. Es el mismo razonamiento de ADR-004 con la reserva de stock: la
atomicidad la pone la base, no una comprobación en Python.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.modules.retail.domain.venta.errores import ReglaDeNegocio

__all__ = ["RepositorioConsecutivosSQL", "TAMANO_BLOQUE", "UMBRAL_RENOVACION"]

# 500 números por bloque. Con el ritmo de una tienda —del orden de 100 ventas
# al día— alcanza para varios días sin red, que es de sobra frente al límite de
# 24 h de operación offline. Más grande sólo agranda los huecos al cerrar.
TAMANO_BLOQUE = 500

# Al 80 % se pide el siguiente. No al 100 %: si se espera a agotarlo, la
# petición del bloque nuevo cae justo cuando ya no quedan números, y si en ese
# momento no hay red la caja se queda sin poder vender.
UMBRAL_RENOVACION = 0.8


class RepositorioConsecutivosSQL:
    def __init__(self, sesion: AsyncSession) -> None:
        self._s = sesion

    async def registrar_dispositivo(self, *, dispositivo_id: str, caja_id: str,
                                    nombre: str, usuario_id: str) -> None:
        """El equipo se anota solo la primera vez.

        No autentica nada —de eso se encarga el login del ERP— sólo dice «soy
        este equipo», que es lo que hace falta para que dos tabletas no
        compartan bloque de numeración.
        """
        await self._s.execute(text("""
            INSERT INTO retail.dispositivos
                (id, caja_id, nombre, registrado_por, ultimo_visto_en)
            VALUES (:d, :c, :n, :u, now())
            ON CONFLICT (id) DO UPDATE SET ultimo_visto_en = now()
        """), {"d": dispositivo_id, "c": caja_id, "n": nombre, "u": usuario_id})

    async def vigente(self, caja_id: str) -> Optional[dict]:
        fila = (await self._s.execute(text("""
            SELECT id, caja_id, prefijo, desde, hasta, siguiente, arrendado_en,
                   arrendado_a
              FROM retail.bloques_consecutivo
             WHERE caja_id = :c AND NOT agotado
        """), {"c": caja_id})).mappings().first()
        return dict(fila) if fila else None

    async def arrendar(self, *, caja_id: str, prefijo: str,
                       tamano: int = TAMANO_BLOQUE,
                       dispositivo_id: Optional[str] = None) -> dict:
        """Arrienda un bloque nuevo y da por agotado el anterior.

        Se toma un lock ANTES de mirar nada. Sin él, dos cajas pidiendo bloque
        a la vez leen el mismo máximo y se llevan el mismo rango: es el mismo
        razonamiento de ADR-004 con la reserva de stock — la atomicidad la pone
        la base, no una comprobación en Python.
        """
        if tamano <= 0:
            raise ReglaDeNegocio("Un bloque de consecutivos no puede ser vacío.")

        # EL LOCK ES POR PREFIJO, NO POR CAJA. La numeración se reparte entre
        # todas las cajas que comparten prefijo —el diseño fiscal es «un
        # prefijo por tienda», así que las dos cajas de una tienda comparten
        # secuencia—. Con el lock por caja, dos cajas arrendando a la vez leen
        # el mismo máximo y se llevan el mismo rango.
        await self._s.execute(
            text("SELECT pg_advisory_xact_lock(hashtext('bloque:' || :p))"),
            {"p": prefijo})

        # Dónde termina lo ya repartido PARA ESTE PREFIJO, mirando todas las
        # cajas. Se usa el MÁXIMO histórico y no el bloque vigente: si el
        # vigente se agotó, continuar desde él reasignaría números ya usados.
        ultimo = (await self._s.execute(text("""
            SELECT coalesce(max(hasta), 0) FROM retail.bloques_consecutivo
             WHERE prefijo = :p
        """), {"p": prefijo})).scalar() or 0

        # Y también lo que YA está vendido: si alguien numeró a mano —como
        # hacía la pantalla con `Date.now() % 100000`— hay ventas por encima de
        # cualquier bloque, y arrendar desde ahí chocaría con lo ya escrito.
        vendido = (await self._s.execute(text("""
            SELECT coalesce(max(consecutivo), 0) FROM retail.ventas
             WHERE prefijo = :p
        """), {"p": prefijo})).scalar() or 0

        desde = max(int(ultimo), int(vendido)) + 1
        hasta = desde + tamano - 1

        await self._s.execute(text("""
            UPDATE retail.bloques_consecutivo SET agotado = true
             WHERE caja_id = :c AND NOT agotado
        """), {"c": caja_id})

        fila = (await self._s.execute(text("""
            INSERT INTO retail.bloques_consecutivo
                (caja_id, prefijo, desde, hasta, siguiente, arrendado_a)
            VALUES (:c, :p, :d, :h, :d, :dis)
            RETURNING id, caja_id, prefijo, desde, hasta, siguiente, arrendado_en
        """), {"c": caja_id, "p": prefijo, "d": desde, "h": hasta,
               "dis": dispositivo_id})).mappings().one()
        return dict(fila)

    async def vigente_o_arrendar(self, *, caja_id: str, prefijo: str,
                                 dispositivo_id: Optional[str] = None) -> dict:
        """Lo que pide la apertura de turno: el bloque de esta caja, o uno nuevo.

        Reanudar un turno NO debe consumir un bloque: recargar la pantalla a
        media mañana dejaría huecos de 500 números cada vez.

        PERO SÓLO SE REUSA EL BLOQUE PROPIO. Si el vigente lo tiene otro
        equipo, este recibe uno nuevo: devolverle el ajeno pondría a las dos
        tabletas numerando desde el mismo punto, y saldrían dos tiquetes con el
        mismo número. Es la única forma en que un duplicado puede ocurrir una
        vez que el contador avanza bien.
        """
        actual = await self.vigente(caja_id)
        mismo_equipo = (
            actual is not None
            and (actual["arrendado_a"] is None or dispositivo_id is None
                 or actual["arrendado_a"] == dispositivo_id)
        )
        if actual and mismo_equipo and actual["prefijo"] == prefijo and \
                actual["siguiente"] <= actual["hasta"]:
            return actual
        return await self.arrendar(caja_id=caja_id, prefijo=prefijo,
                                   dispositivo_id=dispositivo_id)

    async def pertenece_a_un_bloque(self, *, caja_id: str, prefijo: str,
                                    consecutivo: int) -> bool:
        """¿Este número salió de un bloque que arrendó ESTA caja?

        El número llega en la petición porque el dispositivo lo asignó sin red.
        Aceptarlo sin comprobar nada deja que un cliente modificado numere
        donde quiera —encima de otra caja, o fuera de todo rango—, y eso se
        descubre meses después cuadrando la numeración.

        No se exige que sea el bloque VIGENTE: una venta hecha offline puede
        llegar cuando la caja ya renovó, y rechazarla ahí sería perder la venta
        que todo el diseño offline existe para no perder.

        Sí se exige que el bloque sea DE ESTA CAJA. Como las cajas de una
        tienda comparten prefijo, sin ese filtro la caja 1 podría emitir con
        números de la caja 2 y las dos numeraciones se entrelazarían.
        """
        return bool((await self._s.execute(text("""
            SELECT 1 FROM retail.bloques_consecutivo
             WHERE caja_id = :c AND prefijo = :p
               AND :n BETWEEN desde AND hasta
             LIMIT 1
        """), {"c": caja_id, "p": prefijo, "n": consecutivo})).scalar())

    async def marcar_consumido(self, *, caja_id: str, consecutivo: int) -> None:
        """Adelanta `siguiente` si la venta usó un número igual o mayor.

        No se usa para ASIGNAR —eso lo hace el dispositivo con su bloque— sino
        para que el servidor sepa por dónde va y pueda decir cuánto queda. Con
        `greatest` una venta offline que llega tarde no retrocede el contador.
        """
        await self._s.execute(text("""
            UPDATE retail.bloques_consecutivo
               SET siguiente = greatest(siguiente, :n + 1)
             WHERE caja_id = :c AND NOT agotado
               AND :n BETWEEN desde AND hasta
        """), {"c": caja_id, "n": consecutivo})
