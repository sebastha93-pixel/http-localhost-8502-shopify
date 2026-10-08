"""Repositorio de caja: los movimientos del turno.

Sólo lo que `CerrarVenta` necesita hoy. El agregado `SesionCaja` completo se
persistirá cuando se construya la pantalla de arqueo (Fase 5); adelantarlo
ahora sería escribir código para un caso de uso que todavía no existe.
"""
from __future__ import annotations

import hashlib

from datetime import datetime
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.modules.retail.infrastructure.persistencia import tablas as T

__all__ = ["RepositorioCajaSQL"]


class RepositorioCajaSQL:
    def __init__(self, sesion: AsyncSession) -> None:
        self._s = sesion

    async def registrar_cobro(self, *, sesion_id: str, venta_id: str,
                              medio_pago_id: str, monto_centavos: int,
                              usuario_id: str, ahora: datetime) -> None:
        # El id se deriva de la venta y el medio para que reintentar el mismo
        # cierre no sume dos veces la misma plata al arqueo.
        #
        # CON SHA-256, NO CON `hash()`. El `hash()` de Python lleva una sal
        # distinta en cada proceso: el mismo medio daba un id diferente en
        # cada worker y tras cada despliegue, así que el reintento que esto
        # dice impedir habría sumado dos veces. No pasó porque la venta ya se
        # protege por su propia llave — pero el código no hacía lo que afirma.
        huella = int(hashlib.sha256(medio_pago_id.encode()).hexdigest(), 16)
        mov_id = f"{venta_id[:20]}{huella % 10**6:06d}"[:26].upper()
        await self._s.execute(T.movimientos_caja.insert().values(
            id=mov_id, sesion_id=sesion_id, tipo="venta",
            medio_pago_id=medio_pago_id, monto=monto_centavos, motivo="venta",
            venta_id=venta_id, usuario_id=usuario_id, creado_en=ahora,
        ))

    async def esperado_por_medio(self, sesion_id: str) -> dict:
        filas = (await self._s.execute(text("""
            SELECT medio_pago_id, sum(monto)::bigint AS total
              FROM retail.movimientos_caja
             WHERE sesion_id = :s AND medio_pago_id IS NOT NULL
             GROUP BY medio_pago_id
        """), {"s": sesion_id})).mappings().all()
        return {f["medio_pago_id"]: f["total"] for f in filas}

    async def sesion_abierta(self, caja_id: str) -> Optional[dict]:
        """INV-V8 se verifica AQUÍ, no en el agregado: necesita la sesión."""
        fila = (await self._s.execute(text("""
            SELECT id, estado, tienda_id FROM retail.sesiones_caja
             WHERE caja_id = :c AND estado <> 'cerrada'
        """), {"c": caja_id})).mappings().first()
        return dict(fila) if fila else None
