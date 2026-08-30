"""El job que comprueba la cadena de auditoría.

`verificar_cadena` llevaba meses con un docstring que decía «lo corre el job
diario», y ese job no existía: la única comprobación pasaba si alguien abría la
pantalla. Una cadena de hashes que nadie verifica es decoración.

Lo que se prueba aquí es que DETECTA, porque una verificación que siempre dice
que sí es peor que ninguna — da confianza sin darla.
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

pytest.importorskip("sqlalchemy")

from sqlalchemy import text  # noqa: E402

URL = os.environ.get("RETAIL_TEST_DATABASE_URL", "").strip()
pytestmark = pytest.mark.skipif(not URL, reason="Sin RETAIL_TEST_DATABASE_URL")

T0 = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)


@pytest_asyncio.fixture()
async def uow():
    from backend.modules.retail.infrastructure.persistencia.unidad_de_trabajo import (
        UnidadDeTrabajoSQL, crear_fabrica, crear_motor,
    )
    from backend.modules.retail.migraciones.runner import aplicar, revertir

    revertir(URL)
    aplicar(URL)
    motor = crear_motor(URL)
    async with motor.begin() as c:
        await c.execute(text(
            "INSERT INTO retail.tiendas (id,nombre,base_caja) "
            "VALUES ('florida','Florida',0)"))
    yield UnidadDeTrabajoSQL(crear_fabrica(motor))
    await motor.dispose()
    revertir(URL)


def _correr(c):
    return asyncio.get_event_loop().run_until_complete(c)


async def _sembrar(u, n=5):
    """`n` eventos encadenados de verdad, por el repositorio."""
    async with u as t:
        for i in range(n):
            await t.auditoria.registrar(
                evento="venta.cerrada", ocurrido_en=T0 + timedelta(minutes=i),
                severidad="info", tienda_id="florida", caja_id=None,
                sesion_id=None, usuario_id="maria",
                agregado_tipo="venta", agregado_id=f"V{i}",
                payload={"numero": f"FV-20-{i}", "total": 1000 * (i + 1)})
        await t.commit()


def _verificar(u):
    """Pide la cadena de 'florida' EXPLÍCITAMENTE.

    Sin el argumento se verifica la cadena de los eventos SIN tienda, que aquí
    está vacía — y la prueba pasaría diciendo «íntegra» sin haber mirado nada.
    Es justo el fallo que tenía el job."""
    async def ir():
        async with u as t:
            return await t.auditoria.verificar_cadena(tienda_id="florida")
    return _correr(ir())


# ── Lo que tiene que decir cuando todo está bien ────────────────────────────

def test_una_cadena_intacta_se_declara_integra(uow):
    _correr(_sembrar(uow, 5))
    v = _verificar(uow)
    assert v["integra"] is True
    assert v["eventos"] == 5


def test_una_auditoria_vacia_es_integra(uow):
    """Cero eventos no es una cadena rota. Parece obvio y no lo es: la
    verificación arranca en GENESIS y no debe confundir «no hay nada» con
    «falta el principio»."""
    v = _verificar(uow)
    assert v["integra"] is True
    assert v["eventos"] == 0


# ── Lo que de verdad importa: que DETECTE ───────────────────────────────────

def test_detecta_un_payload_alterado(uow):
    """El caso para el que existe la cadena: alguien edita el monto de una
    venta en la base para tapar un faltante. El hash guardado ya no
    corresponde al contenido."""
    _correr(_sembrar(uow, 5))

    async def alterar():
        async with uow as t:
            fila = (await t.sesion.execute(text(
                "SELECT id, payload FROM retail.auditoria "
                " ORDER BY ocurrido_en, id OFFSET 2 LIMIT 1"))).mappings().first()
            payload = dict(fila["payload"])
            payload["total"] = 1                       # el faltante, tapado
            await t.sesion.execute(text(
                "UPDATE retail.auditoria SET payload = CAST(:p AS jsonb) "
                " WHERE id = :i"), {"p": json.dumps(payload), "i": fila["id"]})
            await t.commit()
            return fila["id"]

    tocado = _correr(alterar())
    v = _verificar(uow)

    assert v["integra"] is False
    assert v["motivo"] == "payload_alterado"
    assert v["roto_en"] == tocado
    # Y dice CUÁNTOS eslabones aguantaron antes: es por dónde empezar a mirar.
    assert v["eventos"] == 2


def test_detecta_un_eslabon_borrado(uow):
    """Borrar una fila del medio deja al siguiente apuntando a un hash que ya
    no es su predecesor. Es la otra forma de manipular el rastro: en vez de
    cambiar un evento, hacerlo desaparecer."""
    _correr(_sembrar(uow, 5))

    async def borrar():
        async with uow as t:
            fila = (await t.sesion.execute(text(
                "SELECT id FROM retail.auditoria "
                " ORDER BY ocurrido_en, id OFFSET 2 LIMIT 1"))).scalar()
            await t.sesion.execute(text(
                "DELETE FROM retail.auditoria WHERE id = :i"), {"i": fila})
            await t.commit()

    _correr(borrar())
    v = _verificar(uow)
    assert v["integra"] is False
    assert v["motivo"] == "eslabón_no_encadena"


def test_la_verificacion_por_LOTES_da_el_mismo_veredicto(uow):
    """La versión anterior se traía TODAS las filas a memoria, y esto lo llama
    la pantalla en cada carga. Ahora recorre por lotes; el veredicto tiene que
    ser idéntico, incluido cruzar el borde de un lote."""
    from backend.modules.retail.infrastructure.persistencia.repo_auditoria import (
        RepositorioAuditoriaSQL,
    )
    _correr(_sembrar(uow, 7))

    original = RepositorioAuditoriaSQL.LOTE_VERIFICACION
    RepositorioAuditoriaSQL.LOTE_VERIFICACION = 2   # fuerza 4 vueltas
    try:
        v = _verificar(uow)
    finally:
        RepositorioAuditoriaSQL.LOTE_VERIFICACION = original

    assert v["integra"] is True
    assert v["eventos"] == 7


def test_por_lotes_tambien_detecta_la_rotura(uow):
    """La comprobación que hace útil a la anterior: que trocear el recorrido
    no se coma una rotura que cae justo en el corte."""
    from backend.modules.retail.infrastructure.persistencia.repo_auditoria import (
        RepositorioAuditoriaSQL,
    )
    _correr(_sembrar(uow, 7))

    async def alterar():
        async with uow as t:
            fila = (await t.sesion.execute(text(
                "SELECT id, payload FROM retail.auditoria "
                " ORDER BY ocurrido_en, id OFFSET 4 LIMIT 1"))).mappings().first()
            p = dict(fila["payload"]); p["total"] = 0
            await t.sesion.execute(text(
                "UPDATE retail.auditoria SET payload = CAST(:p AS jsonb) "
                " WHERE id = :i"), {"p": json.dumps(p), "i": fila["id"]})
            await t.commit()

    _correr(alterar())
    original = RepositorioAuditoriaSQL.LOTE_VERIFICACION
    RepositorioAuditoriaSQL.LOTE_VERIFICACION = 2
    try:
        v = _verificar(uow)
    finally:
        RepositorioAuditoriaSQL.LOTE_VERIFICACION = original

    assert v["integra"] is False
    assert v["eventos"] == 4


# ── El job ──────────────────────────────────────────────────────────────────

def test_el_job_deja_su_veredicto_donde_se_puede_mirar(uow):
    """Un verificador que sólo escribe en el log es medio verificador: nadie
    mira los logs de un backend hasta que ya pasó algo."""
    from backend.modules.retail.infrastructure import verificador_auditoria as v
    os.environ["RETAIL_DATABASE_URL"] = URL
    from backend.modules.retail.interfaces.http import dependencias
    dependencias.reiniciar()

    _correr(_sembrar(uow, 3))
    _correr(v.verificar_ahora())

    assert v.ultimo["integra"] is True
    assert v.ultimo["eventos"] == 3
    assert v.ultimo["corrio_en"] is not None
    dependencias.reiniciar()


def test_el_job_no_arranca_sin_base_configurada():
    from backend.modules.retail.infrastructure import verificador_auditoria as v

    guardado = os.environ.get("RETAIL_DATABASE_URL")
    os.environ.pop("RETAIL_DATABASE_URL", None)
    try:
        assert v.start() is False
    finally:
        if guardado is not None:
            os.environ["RETAIL_DATABASE_URL"] = guardado


def test_el_job_MIRA_LAS_CADENAS_DE_LAS_TIENDAS(uow):
    """La regresión del fallo que tuvo este job al nacer.

    Hay UNA CADENA POR TIENDA. La primera versión llamaba a `verificar_cadena`
    sin argumento, o sea que comprobaba sólo los eventos sin tienda — y casi
    todos llevan tienda. Habría dicho «íntegra» todos los días mirando una
    cadena vacía, que es el peor resultado posible: da confianza sin darla.

    Si alguien vuelve a quitarle el recorrido por tiendas, esta prueba falla.
    """
    from backend.modules.retail.infrastructure import verificador_auditoria as v
    os.environ["RETAIL_DATABASE_URL"] = URL
    from backend.modules.retail.interfaces.http import dependencias
    dependencias.reiniciar()

    _correr(_sembrar(uow, 4))

    async def alterar():
        async with uow as t:
            fila = (await t.sesion.execute(text(
                "SELECT id, payload FROM retail.auditoria "
                " ORDER BY ocurrido_en, id OFFSET 1 LIMIT 1"))).mappings().first()
            p = dict(fila["payload"]); p["total"] = 7
            await t.sesion.execute(text(
                "UPDATE retail.auditoria SET payload = CAST(:p AS jsonb) "
                " WHERE id = :i"), {"p": json.dumps(p), "i": fila["id"]})
            await t.commit()

    _correr(alterar())
    _correr(v.verificar_ahora())

    assert v.ultimo["integra"] is False, "el job no vio la cadena de la tienda"
    assert v.ultimo["tienda_rota"] == "florida"
    assert v.ultimo["motivo"] == "payload_alterado"
    dependencias.reiniciar()
