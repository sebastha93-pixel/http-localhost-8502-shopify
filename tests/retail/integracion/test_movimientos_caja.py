"""Plata que entra o sale del cajón sin ser una venta.

POR QUÉ ESTO IMPORTA MÁS DE LO QUE PARECE. El agregado tenía `registrar_retiro`,
`registrar_gasto` y `registrar_ingreso` desde el principio, con sus pruebas de
dominio — y ningún endpoint que los llamara. Así que en la práctica no existían.

Y sin ellos el cierre se rompe TODOS LOS DÍAS: sale plata para un domiciliario
o para bolsas, no hay dónde anotarlo, y el arqueo lo lee como faltante. La
cajera termina justificando y buscando un supervisor por algo rutinario. Un
control que salta con lo normal deja de mirarse en una semana — y entonces ya
no sirve para lo que sí importa.
"""
from __future__ import annotations

import asyncio
import os

import pytest
import pytest_asyncio

pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

URL = os.environ.get("RETAIL_TEST_DATABASE_URL", "").strip()
pytestmark = pytest.mark.skipif(not URL, reason="Sin RETAIL_TEST_DATABASE_URL")

SESION = "01JQ8X4T5N6P001R8S9V0W1X2Y"
UBICACION = "tienda:florida"
BASE = 20000000          # $200.000


def _mov(n: int) -> str:
    return "01JQ8X4T5N7M%03dR8S9V0W1X2Y" % n


@pytest_asyncio.fixture()
async def entorno():
    from backend.core.security import CurrentUser, get_current_user
    from backend.modules.retail.interfaces.http import dependencias
    from backend.modules.retail.interfaces.http.router import router
    from backend.modules.retail.migraciones.runner import aplicar, revertir

    revertir(URL)
    aplicar(URL)
    os.environ["RETAIL_DATABASE_URL"] = URL
    dependencias.reiniciar()

    motor = create_async_engine(URL)
    semillas = [
        ("INSERT INTO retail.tiendas (id,nombre,base_caja) "
         "VALUES ('florida','Florida',:b)", {"b": BASE}),
        ("INSERT INTO retail.cajas (id,tienda_id,nombre,prefijo_factura) "
         "VALUES ('florida_caja1','florida','Caja 1','FV-20')", {}),
        ("INSERT INTO retail.ubicaciones (id,tipo,nombre,tienda_id) "
         "VALUES (:u,'tienda','Florida','florida')", {"u": UBICACION}),
        ("INSERT INTO retail.medios_pago (id,nombre,tipo,siigo_forma_pago_id) "
         "VALUES ('efectivo','Efectivo','efectivo',12243)", {}),
        # Laura puede mover la caja; María no.
        ("INSERT INTO retail.permisos_pos "
         "(usuario_id,nombre,tiendas,puede_mover_caja,puede_ver_esperado) "
         "VALUES ('laura','Laura M.','{florida}',true,true)", {}),
        ("INSERT INTO retail.permisos_pos (usuario_id,nombre,tiendas) "
         "VALUES ('maria','María R.','{florida}')", {}),
    ]
    async with motor.begin() as c:
        for sql, p in semillas:
            await c.execute(text(sql), p)

    app = FastAPI()
    app.include_router(router)

    def entrar_como(uid: str, nombre: str):
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            id=uid, email=f"{uid}@male.com", nombre=nombre, rol="user",
            permisos={"retail": ["ver", "modificar"]})

    entrar_como("maria", "María R.")

    with TestClient(app) as c:
        r = c.post("/api/retail/caja/turno", json={
            "sesion_id": SESION, "tienda_id": "florida",
            "caja_id": "florida_caja1"})
        assert r.status_code == 200, r.text
        yield c, motor, entrar_como

    await motor.dispose()
    dependencias.reiniciar()
    revertir(URL)


def _mover(c, n: int, tipo: str, monto: int, motivo="motivo suficiente"):
    return c.post("/api/retail/caja/movimientos", json={
        "movimiento_id": _mov(n), "sesion_id": SESION, "tipo": tipo,
        "monto_centavos": monto, "motivo": motivo})


def _esperado(c) -> int:
    d = c.get("/api/retail/caja/cierre/resumen",
              params={"sesion_id": SESION}).json()
    return d["esperado_por_medio"]["efectivo"]


# ── El permiso ──────────────────────────────────────────────────────────────

def test_sin_permiso_no_se_saca_plata(entorno):
    """María cobra, pero no vacía el cajón. Es la operación que más se parece a
    un robo cuando no queda rastro de quién y por qué."""
    c, _, _ = entorno
    r = _mover(c, 1, "retiro", 5000000)
    assert r.status_code == 403
    d = r.json()["detail"]
    assert d["error"] == "sin_permiso_caja"
    assert d["accion_sugerida"] == "entrar_con_otro_usuario"


def test_con_permiso_si(entorno):
    c, _, entrar_como = entorno
    entrar_como("laura", "Laura M.")
    assert _mover(c, 2, "retiro", 5000000).status_code == 200


def test_meter_plata_no_necesita_permiso(entorno):
    """Un ingreso —traer sencillo— no es la operación de la que hay que
    protegerse. Exigir permiso para eso sólo consigue que nadie lo registre."""
    c, _, _ = entorno
    assert _mover(c, 3, "ingreso", 5000000).status_code == 200


# ── El efecto sobre el arqueo, que es el punto ──────────────────────────────

def test_un_retiro_BAJA_el_efectivo_esperado(entorno):
    """Lo que arregla el cierre roto: sin esto, esos $50.000 aparecían como
    faltante y exigían justificación y supervisor."""
    c, _, entrar_como = entorno
    entrar_como("laura", "Laura M.")
    assert _esperado(c) == BASE
    _mover(c, 4, "retiro", 5000000)
    assert _esperado(c) == BASE - 5000000


def test_un_ingreso_lo_sube(entorno):
    c, _, entrar_como = entorno
    entrar_como("laura", "Laura M.")
    _mover(c, 5, "ingreso", 3000000)
    assert _esperado(c) == BASE + 3000000


def test_un_gasto_tambien_baja(entorno):
    c, _, entrar_como = entorno
    entrar_como("laura", "Laura M.")
    _mover(c, 6, "gasto", 1200000)
    assert _esperado(c) == BASE - 1200000


def test_el_cierre_cuadra_contando_lo_que_QUEDA(entorno):
    """La prueba de que todo esto sirve: se saca plata, se cuenta lo que queda,
    y el arqueo da CERO — no un faltante."""
    c, _, entrar_como = entorno
    entrar_como("laura", "Laura M.")
    _mover(c, 7, "retiro", 5000000)
    _mover(c, 8, "gasto", 800000)

    r = c.post("/api/retail/caja/cierre", json={
        "sesion_id": SESION,
        "conteos": [{"medio_pago_id": "efectivo",
                     "contado_centavos": BASE - 5000000 - 800000}]})
    assert r.status_code == 200, r.text
    assert r.json()["diferencia_centavos"] == 0
    assert r.json()["cuadro"] is True


# ── INV-C6: no se saca lo que no hay ────────────────────────────────────────

def test_no_se_puede_sacar_mas_de_lo_que_hay(entorno):
    """Dejar el libro en negativo hace que el arqueo pida contar una cantidad
    imposible, y a partir de ahí ningún cierre vuelve a cuadrar."""
    c, _, entrar_como = entorno
    entrar_como("laura", "Laura M.")
    r = _mover(c, 9, "retiro", BASE + 1)
    assert r.status_code == 400
    assert "no hay" in r.json()["detail"]["mensaje"].lower()
    assert _esperado(c) == BASE, "el intento fallido movió el saldo"


# ── El rastro ───────────────────────────────────────────────────────────────

def test_sacar_plata_exige_motivo_escrito(entorno):
    c, _, entrar_como = entorno
    entrar_como("laura", "Laura M.")
    r = c.post("/api/retail/caja/movimientos", json={
        "movimiento_id": _mov(10), "sesion_id": SESION, "tipo": "retiro",
        "monto_centavos": 100000, "motivo": ""})
    assert r.status_code == 422       # lo frena el contrato, antes de la base


def test_el_monto_llega_SIEMPRE_POSITIVO(entorno):
    """El signo lo pone el tipo. Aceptar negativos deja convertir un retiro en
    un ingreso con un guion de más."""
    c, _, entrar_como = entorno
    entrar_como("laura", "Laura M.")
    r = c.post("/api/retail/caja/movimientos", json={
        "movimiento_id": _mov(11), "sesion_id": SESION, "tipo": "retiro",
        "monto_centavos": -5000000, "motivo": "intento de colarse"})
    assert r.status_code == 422


def test_queda_como_CRITICO_en_la_auditoria(entorno):
    c, motor, entrar_como = entorno
    entrar_como("laura", "Laura M.")
    _mover(c, 12, "retiro", 5000000, motivo="sangría a la caja fuerte")

    async def leer():
        async with motor.connect() as cn:
            return (await cn.execute(text("""
                SELECT evento, severidad, payload FROM retail.auditoria
                 WHERE evento LIKE 'caja.%' AND evento <> 'caja.abierta'
            """))).mappings().all()

    filas = asyncio.get_event_loop().run_until_complete(leer())
    assert len(filas) == 1
    assert filas[0]["evento"] == "caja.retiro"
    assert filas[0]["severidad"] == "critico"
    assert filas[0]["payload"]["motivo"] == "sangría a la caja fuerte"


def test_un_ingreso_es_aviso_no_critico(entorno):
    """Meter plata no merece la misma alarma que sacarla. Si todo es crítico,
    nada lo es."""
    c, motor, entrar_como = entorno
    entrar_como("laura", "Laura M.")
    _mover(c, 13, "ingreso", 2000000)

    async def leer():
        async with motor.connect() as cn:
            return (await cn.execute(text("""
                SELECT severidad FROM retail.auditoria WHERE evento='caja.ingreso'
            """))).scalar()

    assert asyncio.get_event_loop().run_until_complete(leer()) == "aviso"


def test_el_movimiento_queda_listado_con_su_motivo(entorno):
    c, motor, entrar_como = entorno
    entrar_como("laura", "Laura M.")
    _mover(c, 14, "gasto", 900000, motivo="bolsas y cinta")

    async def leer():
        from backend.modules.retail.infrastructure.persistencia.unidad_de_trabajo import (
            UnidadDeTrabajoSQL, crear_fabrica,
        )
        async with UnidadDeTrabajoSQL(crear_fabrica(motor)) as t:
            return await t.turnos.movimientos_manuales(SESION)

    movs = asyncio.get_event_loop().run_until_complete(leer())
    assert len(movs) == 1
    assert movs[0]["tipo"] == "gasto"
    assert movs[0]["motivo"] == "bolsas y cinta"
    assert movs[0]["quien"] == "Laura M."
    # Guardado CON SIGNO: negativo porque salió del cajón.
    assert movs[0]["monto"] == -900000
