"""Repositorio de inventario: la reserva atómica y el libro mayor.

La reserva es UNA sentencia. No hay `SELECT` previo, así que no hay ventana en
la que dos cajas lean el mismo saldo y las dos crean que alcanza. Es la
diferencia entre "no debería sobrevender" y "no puede".
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.modules.retail.infrastructure.persistencia import tablas as T

__all__ = ["RepositorioInventarioSQL"]

_RESERVAR = text("""
    UPDATE retail.stock_ubicacion
       SET reservado = reservado + :n, actualizado_en = now()
     WHERE ubicacion_id = :ubicacion AND variante_id = :variante
       AND (cantidad - reservado) >= :n
    RETURNING cantidad - reservado AS disponible
""")

_LIBERAR = text("""
    UPDATE retail.stock_ubicacion
       SET reservado = greatest(reservado - :n, 0), actualizado_en = now()
     WHERE ubicacion_id = :ubicacion AND variante_id = :variante
""")

# Confirmar = la reserva se vuelve salida real. Se hace en una sentencia para
# que no exista un instante en el que el stock ya bajó pero sigue reservado.
_CONFIRMAR = text("""
    UPDATE retail.stock_ubicacion
       SET cantidad = cantidad - :n,
           reservado = greatest(reservado - :n, 0),
           actualizado_en = now()
     WHERE ubicacion_id = :ubicacion AND variante_id = :variante
    RETURNING cantidad
""")


class RepositorioInventarioSQL:
    def __init__(self, sesion: AsyncSession) -> None:
        self._s = sesion

    async def reservar(self, *, ubicacion_id: str, variante_id: str,
                       cantidad: int) -> Optional[int]:
        """Disponible tras reservar, o None si no alcanzaba.

        `None` no es un error de programa: es la respuesta legítima de "esta
        talla ya no está". Quien llama decide si advierte o bloquea.
        """
        fila = (await self._s.execute(_RESERVAR, {
            "n": cantidad, "ubicacion": ubicacion_id, "variante": variante_id,
        })).first()
        return None if fila is None else fila.disponible

    async def liberar(self, *, ubicacion_id: str, variante_id: str,
                      cantidad: int) -> None:
        await self._s.execute(_LIBERAR, {
            "n": cantidad, "ubicacion": ubicacion_id, "variante": variante_id})

    async def confirmar_salida(self, *, ubicacion_id: str, variante_id: str,
                               cantidad: int, referencia_id: str,
                               usuario_id: str, motivo: str = "venta") -> int:
        fila = (await self._s.execute(_CONFIRMAR, {
            "n": cantidad, "ubicacion": ubicacion_id, "variante": variante_id,
        })).first()
        if fila is None:
            raise LookupError(
                f"no hay saldo registrado de {variante_id} en {ubicacion_id}")
        saldo = fila.cantidad
        await self._asentar(
            ubicacion_id=ubicacion_id, variante_id=variante_id, delta=-cantidad,
            saldo_despues=saldo, motivo=motivo, referencia_tipo="venta",
            referencia_id=referencia_id, usuario_id=usuario_id)
        return saldo

    async def _asentar(self, **kw) -> None:
        """Asiento del libro mayor. Append-only: la tabla tiene REVOKE
        UPDATE/DELETE, así que corregir es un movimiento contrario."""
        await self._s.execute(T.movimientos_inventario.insert().values(
            detalle=kw.pop("detalle", ""), **kw))

    async def saldo(self, *, ubicacion_id: str, variante_id: str) -> Optional[dict]:
        fila = (await self._s.execute(text("""
            SELECT cantidad, reservado, cantidad - reservado AS disponible
              FROM retail.stock_ubicacion
             WHERE ubicacion_id = :u AND variante_id = :v
        """), {"u": ubicacion_id, "v": variante_id})).mappings().first()
        return dict(fila) if fila else None
