"""El calendario de la auditoría no se puede acabar.

EL 2026-10-01 SE ACABÓ. `retail.auditoria` está particionada por mes y la 0001
sembró agosto y septiembre de 2026; a las 00:00 del 1 de octubre, toda
escritura empezó a devolver «no partition of relation "auditoria" found for
row». Y como la constancia va en la MISMA transacción que la venta, eso no
degrada el POS: lo apaga. Ese día las pruebas pasaron de 0 fallos a 72.

Lo que se prueba aquí es que no vuelva a pasar, por dos vías distintas: la red
(partición por defecto, para que una fila fuera de rango no tumbe la caja) y el
plan (crear los meses por delante, que es lo que mantiene la red vacía).
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

pytest.importorskip("sqlalchemy")

from sqlalchemy import text  # noqa: E402

URL = os.environ.get("RETAIL_TEST_DATABASE_URL", "").strip()
pytestmark = pytest.mark.skipif(not URL, reason="Sin RETAIL_TEST_DATABASE_URL")


@pytest_asyncio.fixture()
async def motor():
    from backend.modules.retail.infrastructure.persistencia.unidad_de_trabajo import (
        crear_motor,
    )
    from backend.modules.retail.migraciones.runner import aplicar, revertir

    revertir(URL)
    aplicar(URL)
    m = crear_motor(URL)
    yield m
    await m.dispose()
    revertir(URL)


async def _insertar(m, cuando: datetime) -> int:
    async with m.begin() as c:
        return (await c.execute(text("""
            INSERT INTO retail.auditoria (ocurrido_en, evento, hash)
            VALUES (:t, 'prueba', 'h') RETURNING id
        """), {"t": cuando})).scalar()


async def _tabla_de(m, cuando: datetime) -> str:
    async with m.connect() as c:
        return (await c.execute(text("""
            SELECT c.relname FROM retail.auditoria a
              JOIN pg_class c ON c.oid = a.tableoid
             WHERE a.ocurrido_en = :t
        """), {"t": cuando})).scalar()


def test_un_evento_de_hoy_se_guarda(motor):
    """La prueba que habría avisado. Hoy, no una fecha fija de agosto."""
    ahora = datetime.now(timezone.utc)
    assert asyncio.get_event_loop().run_until_complete(_insertar(motor, ahora))


def test_un_evento_fuera_de_todo_rango_NO_tumba_la_venta(motor):
    """La red. Cae en la partición por defecto en vez de reventar.

    Sin esto, el día que se acaben las particiones la tienda deja de cobrar —
    que es exactamente lo que pasó.
    """
    lejos = datetime(2031, 7, 4, 10, 0, tzinfo=timezone.utc)
    correr = asyncio.get_event_loop().run_until_complete
    assert correr(_insertar(motor, lejos))
    assert correr(_tabla_de(motor, lejos)) == "auditoria_sin_rango"


def test_el_job_crea_los_meses_por_delante_y_no_repite(motor):
    """El plan. Dos pasadas seguidas: la segunda no crea nada."""
    from backend.modules.retail.infrastructure.persistencia.particiones import (
        asegurar_particiones,
    )

    async def ir():
        # Una fecha ya cubierta por la 0021 no da nada que crear; una de 2029,
        # sí. Se usa 2029 para no depender de en qué mes se corran las pruebas.
        async with motor.begin() as c:
            primera = await asegurar_particiones(
                c, datetime(2029, 1, 10, tzinfo=timezone.utc), meses=2)
            segunda = await asegurar_particiones(
                c, datetime(2029, 1, 10, tzinfo=timezone.utc), meses=2)
        return primera, segunda

    primera, segunda = asyncio.get_event_loop().run_until_complete(ir())
    assert primera == ["auditoria_2029_01", "auditoria_2029_02"]
    assert segunda == []

    cuando = datetime(2029, 2, 14, 9, 0, tzinfo=timezone.utc)
    correr = asyncio.get_event_loop().run_until_complete
    correr(_insertar(motor, cuando))
    assert correr(_tabla_de(motor, cuando)) == "auditoria_2029_02"


def test_el_mes_que_viene_ya_tiene_donde_caer(motor):
    """Un turno abierto el último día del mes se cierra al día siguiente."""
    manana = datetime.now(timezone.utc) + timedelta(days=32)
    correr = asyncio.get_event_loop().run_until_complete
    assert correr(_insertar(motor, manana))
    assert correr(_tabla_de(motor, manana)) != "auditoria_sin_rango"
