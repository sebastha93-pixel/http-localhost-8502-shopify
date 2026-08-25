"""El consumidor del outbox.

Sin él, `encolar` es escribir en un buzón que nadie abre: la venta queda firme
—que es lo que ADR-002 protege— pero la factura no sale nunca.

Lo que se prueba aquí es sobre todo lo que NO se ve en el camino feliz: el
trabajo que se muere a mitad, el tipo que todavía no tiene manejador, y el
reintento que no puede abrir un segundo caso sobre la misma devolución.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

pytest.importorskip("sqlalchemy")

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

URL = os.environ.get("RETAIL_TEST_DATABASE_URL", "").strip()
pytestmark = pytest.mark.skipif(not URL, reason="Sin RETAIL_TEST_DATABASE_URL")

AHORA = datetime(2026, 8, 25, 15, 0, tzinfo=timezone.utc)


@pytest_asyncio.fixture()
async def uow():
    from backend.modules.retail.infrastructure.persistencia.unidad_de_trabajo import (
        UnidadDeTrabajoSQL, crear_fabrica, crear_motor,
    )
    from backend.modules.retail.migraciones.runner import aplicar, revertir

    revertir(URL)
    aplicar(URL)
    motor = crear_motor(URL)
    yield UnidadDeTrabajoSQL(crear_fabrica(motor)), create_async_engine(URL)
    await motor.dispose()
    revertir(URL)


def _leer(motor, sql, params=None):
    async def ir():
        async with motor.connect() as cn:
            return (await cn.execute(text(sql), params or {})).first()
    return asyncio.get_event_loop().run_until_complete(ir())


def _correr(corutina):
    return asyncio.get_event_loop().run_until_complete(corutina)


async def _encolar(u, tipo: str, payload: dict | None = None,
                   agregado_id: str = "X1") -> int:
    """Encola FIJANDO las dos fechas, en vez de dejar los `default now()`.

    Sin esto la prueba depende del reloj de la máquina: la fila nacía con
    `proximo_intento_en = now()` real y el drenador corre con un `AHORA` fijo
    que queda en el pasado, así que no tomaba nada y los siete casos fallaban
    por la misma razón —que no tenía nada que ver con lo que probaban—.
    """
    import json
    async with u as t:
        fila = (await t.sesion.execute(text("""
            INSERT INTO retail.outbox (tipo, agregado_tipo, agregado_id, payload,
                                       creado_en, proximo_intento_en)
            VALUES (:t, 'prueba', :a, CAST(:p AS jsonb), :c, :c) RETURNING id
        """), {"t": tipo, "a": agregado_id, "p": json.dumps(payload or {}),
               "c": AHORA - timedelta(minutes=1)})).scalar()
        await t.commit()
    return int(fila)


def _drenar(u, manejadores, *, ahora=AHORA, limite=20):
    from backend.modules.retail.application.comandos.drenar_outbox import DrenarOutbox
    return _correr(DrenarOutbox(u, manejadores).ejecutar(ahora=ahora, limite=limite))


# ── El camino feliz ─────────────────────────────────────────────────────────

def test_un_trabajo_con_manejador_se_procesa_y_no_vuelve(uow):
    u, motor = uow
    _correr(_encolar(u, "saludar"))
    vistos = []

    async def manejador(t, payload):
        vistos.append(payload)
        return "listo"

    r = _drenar(u, {"saludar": manejador})
    assert (r.tomados, r.procesados, r.fallidos) == (1, 1, 0)
    assert len(vistos) == 1

    fila = _leer(motor, "SELECT estado, procesado_en FROM retail.outbox")
    assert fila.estado == "procesado"
    assert fila.procesado_en is not None

    # La segunda pasada no lo vuelve a tomar.
    assert _drenar(u, {"saludar": manejador}).tomados == 0


def test_un_trabajo_que_todavia_no_toca_no_se_toma(uow):
    u, motor = uow
    _correr(_encolar(u, "saludar"))
    _correr(_aplazar(u, AHORA + timedelta(hours=2)))
    assert _drenar(u, {"saludar": _ok}).tomados == 0


async def _aplazar(u, cuando):
    async with u as t:
        await t.sesion.execute(text(
            "UPDATE retail.outbox SET proximo_intento_en = :c"), {"c": cuando})
        await t.commit()


async def _ok(t, payload):
    return "ok"


# ── El tipo sin manejador ───────────────────────────────────────────────────

def test_un_tipo_sin_manejador_NO_gasta_intentos(uow):
    """`emitir_factura` se encola desde antes de que exista su manejador.
    Contarlo como fallo lo mandaría a `fallido` en ocho pasadas — o sea, tirar
    un documento fiscal a la basura por una función que no se ha escrito."""
    u, motor = uow
    _correr(_encolar(u, "emitir_factura"))

    # El reloj avanza entre pasadas: sin eso, la segunda no toma nada —el
    # trabajo quedó aplazado una hora— y la prueba pasaría por la razón
    # equivocada, sin llegar a comprobar que los intentos siguen en cero.
    for vuelta in range(3):
        r = _drenar(u, {}, ahora=AHORA + timedelta(hours=2 * vuelta))
        assert r.sin_manejador == 1, f"vuelta {vuelta}"
        assert r.fallidos == 0

    fila = _leer(motor, "SELECT estado, intentos, ultimo_error FROM retail.outbox")
    assert fila.estado == "pendiente"
    assert fila.intentos == 0
    assert "sin manejador" in fila.ultimo_error


def test_cuando_el_manejador_aparece_el_trabajo_viejo_se_ejecuta(uow):
    """La consecuencia de lo anterior, que es lo que de verdad importa: el
    documento encolado hace meses sale solo el día que hay con qué."""
    u, _ = uow
    _correr(_encolar(u, "emitir_factura"))
    _drenar(u, {})                       # sin manejador: se aplaza

    # Pasa una hora y ya existe el manejador.
    r = _drenar(u, {"emitir_factura": _ok}, ahora=AHORA + timedelta(hours=2))
    assert r.procesados == 1


# ── Los fallos ──────────────────────────────────────────────────────────────

def test_un_fallo_reintenta_con_espera_creciente(uow):
    u, motor = uow
    _correr(_encolar(u, "romper"))

    async def revienta(t, payload):
        raise RuntimeError("Siigo no responde")

    r = _drenar(u, {"romper": revienta})
    assert (r.reintentos, r.fallidos) == (1, 0)

    fila = _leer(motor, "SELECT estado, intentos, ultimo_error, proximo_intento_en "
                        "  FROM retail.outbox")
    assert fila.estado == "pendiente"
    assert fila.intentos == 1
    assert "Siigo no responde" in fila.ultimo_error
    # Y no se vuelve a intentar de inmediato.
    assert fila.proximo_intento_en > AHORA


def test_agotados_los_intentos_queda_fallido(uow):
    u, motor = uow
    _correr(_encolar(u, "romper"))
    _correr(_poner_intentos(u, 7))       # max_intentos por defecto = 8

    async def revienta(t, payload):
        raise RuntimeError("otra vez no")

    r = _drenar(u, {"romper": revienta})
    assert (r.fallidos, r.reintentos) == (1, 0)
    assert _leer(motor, "SELECT estado FROM retail.outbox").estado == "fallido"


async def _poner_intentos(u, n):
    async with u as t:
        await t.sesion.execute(text("UPDATE retail.outbox SET intentos = :n"),
                               {"n": n})
        await t.commit()


def test_un_trabajo_envenenado_no_tumba_a_los_demas(uow):
    """Cada trabajo va en SU transacción. Una cola donde uno malo revierte a
    los otros diecinueve es una cola que no avanza nunca."""
    u, motor = uow
    _correr(_encolar(u, "bien", agregado_id="A"))
    _correr(_encolar(u, "mal", agregado_id="B"))
    _correr(_encolar(u, "bien", agregado_id="C"))

    async def revienta(t, payload):
        raise RuntimeError("no")

    r = _drenar(u, {"bien": _ok, "mal": revienta})
    assert (r.procesados, r.reintentos) == (2, 1)

    n = _leer(motor, "SELECT count(*) AS n FROM retail.outbox "
                     " WHERE estado='procesado'").n
    assert n == 2


# ── El trabajo varado ───────────────────────────────────────────────────────

def test_lo_varado_en_procesando_vuelve_a_la_cola(uow):
    """Si el proceso se muere a mitad, la fila queda reservada para siempre y
    NUNCA da error: sencillamente esa factura no se emite y nadie se entera."""
    u, motor = uow
    _correr(_encolar(u, "saludar"))
    _correr(_varar(u, AHORA - timedelta(hours=1)))

    r = _drenar(u, {"saludar": _ok})
    assert r.rescatados == 1
    assert r.procesados == 1
    assert _leer(motor, "SELECT estado FROM retail.outbox").estado == "procesado"


def test_lo_que_lleva_poco_en_procesando_NO_se_rescata(uow):
    """Rescatar demasiado pronto es el problema contrario: dos procesos con el
    mismo trabajo, y dos notas crédito de la misma devolución."""
    u, _ = uow
    _correr(_encolar(u, "saludar"))
    _correr(_varar(u, AHORA - timedelta(minutes=2)))
    assert _drenar(u, {"saludar": _ok}).rescatados == 0


async def _varar(u, creado_en):
    async with u as t:
        await t.sesion.execute(text(
            "UPDATE retail.outbox SET estado='procesando', creado_en=:c"),
            {"c": creado_en})
        await t.commit()


# ── La traducción a Postventa ───────────────────────────────────────────────

def test_el_motivo_talla_NO_se_inventa_pequena_ni_grande():
    """Postventa separa pequeña de grande y el POS no lo pregunta. Elegir una
    sería inventarse la mitad de los casos — y es justo el dato que sirve para
    saber si una referencia está mal escalada."""
    from backend.modules.retail.infrastructure.postventa.caso_devolucion import (
        motivo_postventa,
    )
    assert motivo_postventa("talla") == "otro"
    assert motivo_postventa("defecto") == "producto_defectuoso"
    assert motivo_postventa("no_le_gusto") == "no_le_gusto_como_quedo"
    assert motivo_postventa("cambio_modelo") == "cambio_por_otro"


def test_el_tipo_sale_del_REEMBOLSO_no_del_motivo():
    """`cambio_talla` y `cambio_ref` nacen APROBADOS y ponen en marcha un
    reemplazo. Aquí la clienta no se lleva otra prenda: se le devuelve la
    plata. Marcarlo como cambio dispararía un despacho que nadie va a mandar."""
    from backend.modules.retail.infrastructure.postventa.caso_devolucion import (
        tipo_postventa,
    )
    assert tipo_postventa("efectivo") == "reembolso"
    assert tipo_postventa("metodo_original") == "reembolso"
    assert tipo_postventa("credito_tienda") == "bono"


def test_si_la_devolucion_YA_tiene_caso_no_se_abre_otro():
    """EL RIESGO REAL DEL REINTENTO. Si el caso se creó pero el proceso se
    murió antes de marcar la fila del outbox, la siguiente pasada abriría un
    SEGUNDO caso sobre la misma devolución — y con él una segunda nota crédito
    sobre la misma factura ante la DIAN.

    Se prueba sin base ni Supabase a propósito: lo que hay que verificar es que
    la guarda corta ANTES de llamar a `crear_caso`, y eso se ve mejor con un
    doble que estalla si lo llaman.
    """
    from backend.modules.retail.infrastructure.postventa.caso_devolucion import (
        abrir_caso_postventa,
    )

    class _Resultado:
        @staticmethod
        def scalar():
            return "PV-2026-0042"

    class _Sesion:
        async def execute(self, *_a, **_k):
            return _Resultado()

    class _T:
        sesion = _Sesion()

    import backend.services.postventa as svc
    original = svc.crear_caso

    def estalla(**_):
        raise AssertionError("no debió llamarse: la devolución ya tenía caso")

    svc.crear_caso = estalla
    try:
        # `asyncio.run` y no el `_correr` de arriba: esta prueba no pide la
        # fixture `uow`, así que no hay bucle de eventos que reutilizar.
        nota = asyncio.run(abrir_caso_postventa(_T(), {"devolucion_id": "D1"}))
    finally:
        svc.crear_caso = original

    assert "ya tenía el caso PV-2026-0042" in nota


def test_los_valores_traducidos_EXISTEN_en_postventa():
    """La prueba que evita el fallo silencioso: `crear_caso` valida contra sus
    propias listas y lanza `ValueError`. Si alguien añade un motivo al POS y
    olvida el mapa, esto lo dice aquí y no en producción con la clienta
    delante."""
    from backend.services import postventa_logic as L
    from backend.modules.retail.domain.devolucion.motivo import MotivoDevolucion
    from backend.modules.retail.domain.devolucion.reembolso import Reembolso
    from backend.modules.retail.infrastructure.postventa.caso_devolucion import (
        motivo_postventa, tipo_postventa,
    )

    for m in MotivoDevolucion:
        assert L.validar_motivo(motivo_postventa(m.value)), m
    for r in Reembolso:
        assert L.validar_tipo(tipo_postventa(r.value)), r
