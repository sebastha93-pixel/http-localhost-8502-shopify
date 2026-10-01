"""Las particiones de la auditoría, creadas por delante.

POR QUÉ EXISTE ESTO Y NO UN RECORDATORIO EN UN DOCUMENTO. El 1 de octubre de
2026 se acabaron las particiones que sembró la migración 0001 y el POS dejó de
poder vender: la constancia va en la misma transacción que la venta, así que
sin partición no hay venta. Un calendario que se acaba no puede ser una tarea
que alguien recuerda.

Corre con el verificador de auditoría —cada seis horas, con el líder— y crea
los meses que falten de aquí en adelante. Es idempotente: si ya están, no hace
nada y no dice nada.

LA PARTICIÓN POR DEFECTO ES LA RED, NO EL PLAN. Mientras este paso corra, las
filas caen en su mes y la de por defecto se queda vacía. Si alguna vez tiene
filas, es que esto lleva meses sin correr — y entonces crear ese mes falla, con
un mensaje explícito, porque Postgres no deja partir una tabla cuyas filas ya
están en otra parte.
"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import text

log = logging.getLogger("retail.auditoria")

__all__ = ["asegurar_particiones", "MESES_POR_DELANTE"]

#  Tres meses: con el job cada seis horas sobra, y deja margen para que el
#  backend pase un par de meses sin desplegarse sin que nadie lo note.
MESES_POR_DELANTE = 3


def _rango(ano: int, mes: int) -> tuple[str, str, str]:
    sig_ano, sig_mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
    return (f"auditoria_{ano}_{mes:02d}",
            f"{ano}-{mes:02d}-01", f"{sig_ano}-{sig_mes:02d}-01")


async def asegurar_particiones(sesion, ahora: datetime, *,
                               meses: int = MESES_POR_DELANTE) -> list[str]:
    """Crea las particiones mensuales que falten. Devuelve las que creó.

    `sesion` es una conexión async de SQLAlchemy. Cada mes va en su propia
    sentencia y los errores se registran sin cortar el resto: que falte el mes
    de dentro de dos no es razón para no crear el de mañana.
    """
    creadas: list[str] = []
    ano, mes = ahora.year, ahora.month
    for _ in range(max(1, meses)):
        nombre, desde, hasta = _rango(ano, mes)
        existe = (await sesion.execute(text("""
            SELECT 1 FROM pg_class c
              JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'retail' AND c.relname = :t
        """), {"t": nombre})).scalar()
        if not existe:
            try:
                await sesion.execute(text(
                    f"CREATE TABLE retail.{nombre} PARTITION OF "
                    f"retail.auditoria FOR VALUES FROM ('{desde}') TO ('{hasta}')"
                ))
                creadas.append(nombre)
                log.info("[retail-auditoria] partición creada: %s", nombre)
            except Exception as e:  # noqa: BLE001
                # El caso realista: la partición por defecto ya tiene filas de
                # ese mes porque esto llevaba tiempo sin correr.
                log.critical(
                    "[retail-auditoria] no se pudo crear la partición %s: %s. "
                    "Si hay filas en retail.auditoria_sin_rango de ese mes, hay "
                    "que moverlas antes de poder partirlo.", nombre, e)
        ano, mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
    return creadas
