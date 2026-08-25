"""El consumidor del outbox — quien saca de la cola lo que va hacia terceros.

Sin esto, `encolar` es escribir en un buzón que nadie abre. La venta y la
devolución quedan firmes en el POS —que es lo que ADR-002 protege— pero la
factura y la nota crédito no salen nunca.

TRES TRAMPAS CLÁSICAS DE UN OUTBOX, y cómo se resuelven aquí:

1. **Dos procesos tomando el mismo trabajo.** Pasa en cuanto hay dos réplicas
   del backend, y el resultado son dos notas crédito de la misma devolución.
   Se toma con `FOR UPDATE SKIP LOCKED`: el segundo proceso no espera al
   primero, simplemente se lleva otras filas.

2. **Trabajos varados en `procesando`.** Si el proceso se muere a mitad, la
   fila queda reservada para siempre y nadie la vuelve a mirar. NUNCA da error
   — sencillamente esa factura no se emite y nadie se entera hasta la
   declaración. Por eso lo primero que hace cada pasada es RESCATAR lo que
   lleva demasiado tiempo en `procesando`.

3. **Un tipo sin manejador tratado como un fallo.** `emitir_factura` está
   encolándose desde antes de que exista su manejador. Contarlo como intento
   fallido lo llevaría a `fallido` en ocho pasadas — o sea, tirar un documento
   fiscal a la basura por una función que todavía no se ha escrito. Aquí se
   deja `pendiente`, se aplaza, y NO se cuenta el intento: el día que el
   manejador exista, el trabajo se ejecuta.

CADA TRABAJO VA EN SU PROPIA TRANSACCIÓN. Si uno falla, los demás de la misma
pasada ya están confirmados: una cola donde un trabajo envenenado revierte a
los otros diecinueve es una cola que no avanza.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Awaitable, Callable, Dict, List, Optional

from sqlalchemy import text

__all__ = ["DrenarOutbox", "ResumenDrenaje", "Manejador"]

# Un manejador recibe la sesión abierta (para poder escribir en la MISMA
# transacción que cierra el trabajo) y el payload. Devuelve una nota corta
# para el registro, o None.
Manejador = Callable[..., Awaitable[Optional[str]]]

#  Cuánto puede estar un trabajo en `procesando` antes de darlo por varado.
#  Generoso a propósito: Siigo tarda segundos, no minutos, así que 15 min sólo
#  se alcanza si el proceso murió. Rescatar demasiado pronto sería lo contrario
#  del problema —dos procesos con el mismo trabajo.
VARADO_MINUTOS = 15

#  Espera entre intentos: 1, 2, 4, 8, 16, 32, 60, 60 minutos. Tope de una hora
#  porque un tercero caído se recupera en minutos u horas, no en días, y
#  esperar más sólo alarga el tiempo en que el documento no existe.
def _espera(intentos: int) -> timedelta:
    return timedelta(minutes=min(2 ** max(0, intentos - 1), 60))


#  Un tipo sin manejador se reintenta cada hora. No es un fallo: es una
#  capacidad que todavía no existe.
SIN_MANEJADOR_MINUTOS = 60


@dataclass
class ResumenDrenaje:
    tomados: int = 0
    procesados: int = 0
    reintentos: int = 0
    fallidos: int = 0
    #  Los que esperan a que alguien escriba su manejador. Se cuentan aparte
    #  para que no se lean como errores en el panel: no lo son.
    sin_manejador: int = 0
    rescatados: int = 0
    errores: List[str] = field(default_factory=list)


class DrenarOutbox:
    def __init__(self, uow, manejadores: Dict[str, Manejador]) -> None:
        self._uow = uow
        self._manejadores = manejadores

    async def ejecutar(self, *, ahora: datetime, limite: int = 20) -> ResumenDrenaje:
        resumen = ResumenDrenaje()
        resumen.rescatados = await self._rescatar_varados(ahora)

        for trabajo in await self._tomar(ahora, limite):
            resumen.tomados += 1
            await self._procesar(trabajo, ahora, resumen)

        return resumen

    # ── Paso 0 · rescatar lo varado ─────────────────────────────────────────

    async def _rescatar_varados(self, ahora: datetime) -> int:
        """Devuelve a la cola lo que quedó reservado por un proceso muerto."""
        async with self._uow as t:
            # El texto va como PARÁMETRO, no incrustado: `text()` busca `:algo`
            # también dentro de las comillas, así que un mensaje con dos puntos
            # se convierte en un bind que nadie declaró.
            n = (await t.sesion.execute(text("""
                UPDATE retail.outbox
                   SET estado = 'pendiente',
                       ultimo_error = coalesce(ultimo_error, '') || :nota
                 WHERE estado = 'procesando'
                   AND creado_en < :limite
             RETURNING id
            """), {"nota": f" [rescatado tras {VARADO_MINUTOS} min en procesando]",
                   "limite": ahora - timedelta(minutes=VARADO_MINUTOS)})).rowcount
            await t.commit()
        return int(n or 0)

    # ── Paso 1 · tomar el lote ──────────────────────────────────────────────

    async def _tomar(self, ahora: datetime, limite: int) -> List[dict]:
        """Reserva hasta `limite` trabajos que ya toca intentar.

        `SKIP LOCKED` es lo que hace esto seguro con varias réplicas: el
        segundo proceso NO espera a que el primero suelte la fila —se lleva
        otras—. Sin él, dos réplicas se turnarían el mismo trabajo y la cola
        avanzaría al ritmo de una sola.
        """
        async with self._uow as t:
            filas = (await t.sesion.execute(text("""
                WITH lote AS (
                    SELECT id FROM retail.outbox
                     WHERE estado = 'pendiente'
                       AND proximo_intento_en <= :ahora
                     ORDER BY proximo_intento_en, id
                     LIMIT :n
                       FOR UPDATE SKIP LOCKED
                )
                UPDATE retail.outbox o
                   SET estado = 'procesando'
                  FROM lote
                 WHERE o.id = lote.id
             RETURNING o.id, o.tipo, o.agregado_tipo, o.agregado_id,
                       o.payload, o.intentos, o.max_intentos
            """), {"ahora": ahora, "n": limite})).mappings().all()
            await t.commit()
        return [dict(f) for f in filas]

    # ── Paso 2 · ejecutar, cada uno en su transacción ───────────────────────

    async def _procesar(self, trabajo: dict, ahora: datetime,
                        resumen: ResumenDrenaje) -> None:
        manejador = self._manejadores.get(trabajo["tipo"])

        if manejador is None:
            await self._aplazar_sin_manejador(trabajo, ahora)
            resumen.sin_manejador += 1
            return

        try:
            async with self._uow as t:
                nota = await manejador(t, trabajo["payload"])
                await t.sesion.execute(text("""
                    UPDATE retail.outbox
                       SET estado = 'procesado', procesado_en = :ahora,
                           intentos = intentos + 1, ultimo_error = :nota
                     WHERE id = :i
                """), {"i": trabajo["id"], "ahora": ahora, "nota": nota})
                await t.commit()
            resumen.procesados += 1
        except Exception as e:  # noqa: BLE001 — cualquier fallo del tercero
            # El texto del error se guarda TRUNCADO pero completo en lo que
            # importa: una traza de Siigo entera en una columna hace ilegible
            # la tabla, y lo que se necesita para decidir está al principio.
            detalle = f"{type(e).__name__}: {e}"[:500]
            agotado = await self._marcar_error(trabajo, ahora, detalle)
            if agotado:
                resumen.fallidos += 1
            else:
                resumen.reintentos += 1
            resumen.errores.append(f"#{trabajo['id']} {trabajo['tipo']}: {detalle}")

    async def _aplazar_sin_manejador(self, trabajo: dict,
                                     ahora: datetime) -> None:
        """Vuelve a `pendiente` SIN gastar un intento.

        Es la diferencia entre «esto falló» y «esto todavía no se puede
        hacer». Gastar intentos aquí acabaría marcando `fallido` un documento
        fiscal perfectamente válido porque su manejador aún no existe.
        """
        async with self._uow as t:
            await t.sesion.execute(text("""
                UPDATE retail.outbox
                   SET estado = 'pendiente',
                       proximo_intento_en = :cuando,
                       ultimo_error = :err
                 WHERE id = :i
            """), {"i": trabajo["id"],
                   "cuando": ahora + timedelta(minutes=SIN_MANEJADOR_MINUTOS),
                   "err": f"sin manejador para «{trabajo['tipo']}» todavía"})
            await t.commit()

    async def _marcar_error(self, trabajo: dict, ahora: datetime,
                            detalle: str) -> bool:
        """Anota el fallo y decide si aún quedan intentos. True = se agotaron."""
        intentos = int(trabajo["intentos"]) + 1
        agotado = intentos >= int(trabajo["max_intentos"])
        async with self._uow as t:
            await t.sesion.execute(text("""
                UPDATE retail.outbox
                   SET estado = :estado, intentos = :n, ultimo_error = :err,
                       proximo_intento_en = :cuando
                 WHERE id = :i
            """), {"i": trabajo["id"],
                   "estado": "fallido" if agotado else "pendiente",
                   "n": intentos, "err": detalle,
                   "cuando": ahora + _espera(intentos)})
            await t.commit()
        return agotado
