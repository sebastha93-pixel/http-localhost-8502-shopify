"""Autorización por PIN — la firma de un supervisor sobre una operación.

QUÉ PROTEGE. Un descuento por encima del tope, un obsequio, una anulación, un
cierre con descuadre. Todas tienen algo en común: son operaciones legítimas
que también son la forma de sacar plata, y lo único que las separa es que
quede el nombre de quien las aprobó.

POR QUÉ UN PIN Y NO UNA CONTRASEÑA. Porque ocurre con una clienta enfrente y
la cajera esperando. Una contraseña larga en ese momento se convierte, a la
semana, en un papel pegado debajo del mostrador — que es peor que no tener
control.

QUÉ LO HACE SUFICIENTE. El PIN no vale solo: sólo funciona sobre un
dispositivo registrado (ADR-006), se bloquea a los 5 intentos, y jamás abre
el ERP. Y sobre todo, quien firma sabe que su nombre queda en la auditoría —
que es la mitad del control.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["Autorizador", "ValidarPin", "PinInvalido", "PinBloqueado"]

MAX_INTENTOS = 5
BLOQUEO_MINUTOS = 15


class PinInvalido(Exception):
    """Ningún autorizador activo de esa tienda tiene ese PIN."""


class PinBloqueado(Exception):
    """Demasiados intentos fallidos."""


@dataclass(frozen=True)
class Autorizador:
    usuario_id: str
    nombre: str
    tope_descuento_pct: Decimal


class ValidarPin:
    """Devuelve QUIÉN autorizó, o falla. Nunca dice 'usuario o PIN incorrecto'
    de forma que permita enumerar usuarios: el PIN identifica y autentica a la
    vez, y no se pide un nombre."""

    def __init__(self, sesion: AsyncSession) -> None:
        self._s = sesion

    async def ejecutar(self, *, pin: str, tienda_id: str,
                       ahora: datetime) -> Autorizador:
        if not pin or not pin.strip().isdigit() or not (4 <= len(pin.strip()) <= 6):
            raise PinInvalido("El PIN son 4 a 6 dígitos.")

        candidatos = (await self._s.execute(text("""
            SELECT usuario_id, nombre, pin_hash, tope_descuento_pct,
                   intentos_fallidos, bloqueado_hasta
              FROM retail.permisos_pos
             WHERE activo AND puede_autorizar_descuento
               AND pin_hash IS NOT NULL
               AND (tiendas = '{}' OR :tienda = ANY(tiendas))
        """), {"tienda": tienda_id})).mappings().all()

        import bcrypt

        for c in candidatos:
            if c["bloqueado_hasta"] and c["bloqueado_hasta"] > ahora:
                continue
            if not bcrypt.checkpw(pin.strip().encode(), c["pin_hash"].encode()):
                continue

            await self._s.execute(text("""
                UPDATE retail.permisos_pos
                   SET intentos_fallidos = 0, bloqueado_hasta = NULL
                 WHERE usuario_id = :u
            """), {"u": c["usuario_id"]})
            return Autorizador(
                usuario_id=c["usuario_id"], nombre=c["nombre"],
                tope_descuento_pct=Decimal(c["tope_descuento_pct"]),
            )

        # Ningún PIN coincidió. Se le suma un intento a TODOS los autorizadores
        # de la tienda: no se sabe a quién quiso suplantar, y contar sólo al
        # dueño del PIN correcto delataría cuál existe.
        await self._s.execute(text("""
            UPDATE retail.permisos_pos
               SET intentos_fallidos = intentos_fallidos + 1,
                   bloqueado_hasta = CASE
                       WHEN intentos_fallidos + 1 >= :max THEN :hasta
                       ELSE bloqueado_hasta END
             WHERE activo AND puede_autorizar_descuento
               AND (tiendas = '{}' OR :tienda = ANY(tiendas))
        """), {"tienda": tienda_id, "max": MAX_INTENTOS,
               "hasta": ahora + timedelta(minutes=BLOQUEO_MINUTOS)})

        bloqueados = (await self._s.execute(text("""
            SELECT count(*) FROM retail.permisos_pos
             WHERE activo AND puede_autorizar_descuento
               AND bloqueado_hasta > :ahora
               AND (tiendas = '{}' OR :tienda = ANY(tiendas))
        """), {"ahora": ahora, "tienda": tienda_id})).scalar()

        if bloqueados and not candidatos:
            raise PinBloqueado(
                f"Demasiados intentos. Espera {BLOQUEO_MINUTOS} minutos o "
                f"llama a un administrador."
            )
        raise PinInvalido("Ese PIN no corresponde a nadie que pueda autorizar aquí.")
