"""Repositorio del turno de caja.

INV-C1 —una sola sesion abierta por caja— NO se comprueba aqui con un SELECT
previo: es el indice unico parcial `ux_sesion_abierta` el que lo garantiza.
Comprobarlo en Python dejaria una ventana entre la lectura y el INSERT en la
que dos dispositivos abren turno a la vez, y el arqueo se vuelve imposible.

Por eso `abrir` intenta insertar y traduce el choque del indice a un mensaje
que la cajera entiende, en vez de preguntar antes.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.modules.retail.domain.venta.errores import ReglaDeNegocio

__all__ = ["RepositorioSesionCajaSQL"]


class RepositorioSesionCajaSQL:
    def __init__(self, sesion: AsyncSession) -> None:
        self._s = sesion

    async def abierta_de(self, caja_id: str) -> Optional[dict]:
        fila = (await self._s.execute(text("""
            SELECT s.id, s.numero_turno, s.abierta_por, s.abierta_en,
                   s.base_inicial, s.tienda_id, s.estado,
                   coalesce(p.nombre, s.abierta_por) AS cajera_nombre
              FROM retail.sesiones_caja s
              LEFT JOIN retail.permisos_pos p ON p.usuario_id = s.abierta_por
             WHERE s.caja_id = :c AND s.estado <> 'cerrada'
        """), {"c": caja_id})).mappings().first()
        return dict(fila) if fila else None

    async def abrir(self, *, sesion_id: str, tienda_id: str, caja_id: str,
                    usuario_id: str, base_inicial: int,
                    ahora: datetime) -> dict:
        siguiente = (await self._s.execute(text("""
            SELECT coalesce(max(numero_turno), 0) + 1
              FROM retail.sesiones_caja WHERE caja_id = :c
        """), {"c": caja_id})).scalar()

        try:
            await self._s.execute(text("""
                INSERT INTO retail.sesiones_caja
                    (id, tienda_id, caja_id, numero_turno, estado,
                     base_inicial, abierta_por, abierta_en)
                VALUES (:id, :t, :c, :n, 'abierta', :base, :u, :ts)
            """), {"id": sesion_id, "t": tienda_id, "c": caja_id,
                   "n": siguiente, "base": base_inicial, "u": usuario_id,
                   "ts": ahora})
        except Exception as e:  # noqa: BLE001
            if "ux_sesion_abierta" in str(e):
                raise ReglaDeNegocio(
                    "Esta caja ya tiene un turno abierto. Ciérralo antes de "
                    "abrir otro, o pide a un supervisor que lo cierre."
                ) from e
            raise

        # La base es plata que YA esta en el cajon: entra al arqueo desde el
        # primer minuto o el cierre saldria sobrado por ese monto.
        await self._s.execute(text("""
            INSERT INTO retail.movimientos_caja
                (id, sesion_id, tipo, medio_pago_id, monto, motivo,
                 usuario_id, creado_en)
            VALUES (:id, :s, 'base_inicial', 'efectivo', :base,
                    'base inicial', :u, :ts)
        """), {"id": (sesion_id[:20] + "BASE000000")[:26], "s": sesion_id,
               "base": base_inicial, "u": usuario_id, "ts": ahora})

        return {"id": sesion_id, "numero_turno": siguiente,
                "base_inicial": base_inicial}

    async def base_de_tienda(self, tienda_id: str) -> int:
        base = (await self._s.execute(text("""
            SELECT base_caja FROM retail.tiendas WHERE id = :t
        """), {"t": tienda_id})).scalar()
        if base is None:
            raise ReglaDeNegocio(f"La tienda {tienda_id!r} no existe.")
        return int(base)
