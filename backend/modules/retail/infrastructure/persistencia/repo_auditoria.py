"""Auditoría append-only con encadenamiento de hash (ADR-010).

Cada fila guarda el hash de la anterior, así que alterar un evento del pasado
rompe la cadena de todo lo que vino después. No impide que alguien con acceso
a la base edite una fila: hace que se note.

Sirve para lo que realmente importa: un descuento indebido, una anulación, una
reimpresión. Eventos que alguien podría querer que desaparezcan.

SOBRE LA SERIALIZACIÓN. Dos escrituras concurrentes podrían leer el mismo
"último hash" y bifurcar la cadena. Se evita con un advisory lock por tienda:
las auditorías de una misma tienda se serializan dentro de su transacción. A
60 ventas diarias por tienda eso no se siente, y a cambio la cadena es una
sola línea verificable.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.modules.retail.infrastructure.persistencia import tablas as T

__all__ = ["RepositorioAuditoriaSQL", "GENESIS"]

# El primer eslabón. Un valor fijo y reconocible: si aparece en medio de la
# cadena, alguien borró el principio.
GENESIS = "genesis"

_ULTIMO = text("""
    SELECT hash FROM retail.auditoria
     WHERE tienda_id IS NOT DISTINCT FROM :tienda
     ORDER BY ocurrido_en DESC, id DESC
     LIMIT 1
""")


def calcular_hash(hash_anterior: str, payload: dict) -> str:
    """SHA-256 del eslabón anterior más este evento.

    El payload se serializa con `sort_keys` para que el mismo contenido dé
    siempre el mismo hash: sin eso, la verificación fallaría por el orden de
    las claves de un diccionario y nadie sabría por qué.
    """
    canonico = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, default=str)
    return hashlib.sha256(f"{hash_anterior}|{canonico}".encode("utf-8")).hexdigest()


class RepositorioAuditoriaSQL:
    def __init__(self, sesion: AsyncSession) -> None:
        self._s = sesion

    async def registrar(
        self,
        *,
        evento: str,
        ocurrido_en: datetime,
        payload: dict,
        severidad: str = "info",
        tienda_id: Optional[str] = None,
        caja_id: Optional[str] = None,
        sesion_id: Optional[str] = None,
        usuario_id: Optional[str] = None,
        dispositivo_id: Optional[str] = None,
        agregado_tipo: Optional[str] = None,
        agregado_id: Optional[str] = None,
    ) -> str:
        """Añade un eslabón. Devuelve el hash resultante.

        Corre DENTRO de la transacción del caso de uso: si la venta se
        revierte, su auditoría también. Una auditoría de algo que no pasó es
        peor que no tener auditoría.
        """
        # Serializa los apuntes de esta tienda hasta el fin de la transacción.
        await self._s.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:clave))"),
            {"clave": f"retail.auditoria:{tienda_id or '-'}"},
        )

        anterior = (await self._s.execute(_ULTIMO, {"tienda": tienda_id})).scalar()
        anterior = anterior or GENESIS
        h = calcular_hash(anterior, payload)

        await self._s.execute(T.auditoria.insert().values(
            ocurrido_en=ocurrido_en, tienda_id=tienda_id, caja_id=caja_id,
            sesion_id=sesion_id, usuario_id=usuario_id,
            dispositivo_id=dispositivo_id, evento=evento, severidad=severidad,
            agregado_tipo=agregado_tipo, agregado_id=agregado_id,
            payload=payload, hash_anterior=anterior, hash=h,
        ))
        return h

    async def verificar_cadena(self, *, tienda_id: Optional[str] = None) -> dict:
        """Recorre la cadena y dice dónde se rompe. Lo corre el job diario.

        Devuelve el primer eslabón malo, no sólo un booleano: "la auditoría no
        cuadra" sin decir dónde no le sirve a nadie.
        """
        filas = (await self._s.execute(text("""
            SELECT id, ocurrido_en, evento, payload, hash_anterior, hash
              FROM retail.auditoria
             WHERE tienda_id IS NOT DISTINCT FROM :tienda
             ORDER BY ocurrido_en, id
        """), {"tienda": tienda_id})).mappings().all()

        esperado = GENESIS
        for f in filas:
            if f["hash_anterior"] != esperado:
                return {"integra": False, "roto_en": f["id"],
                        "evento": f["evento"], "motivo": "eslabón_no_encadena"}
            if calcular_hash(esperado, f["payload"]) != f["hash"]:
                return {"integra": False, "roto_en": f["id"],
                        "evento": f["evento"], "motivo": "payload_alterado"}
            esperado = f["hash"]

        return {"integra": True, "eventos": len(filas), "ultimo_hash": esperado}


class RepositorioOutboxSQL:
    """Cola de trabajos hacia terceros.

    Se escribe en la MISMA transacción que la venta. Es lo que garantiza que
    no exista una venta cerrada sin su documento fiscal encolado —ni un
    documento encolado de una venta que se revirtió.
    """

    def __init__(self, sesion: AsyncSession) -> None:
        self._s = sesion

    async def encolar(self, *, tipo: str, agregado_tipo: str, agregado_id: str,
                      payload: dict[str, Any]) -> None:
        await self._s.execute(T.outbox.insert().values(
            tipo=tipo, agregado_tipo=agregado_tipo, agregado_id=agregado_id,
            payload=payload, estado="pendiente", intentos=0, max_intentos=8,
        ))
