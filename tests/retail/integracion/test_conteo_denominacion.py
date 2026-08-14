"""Contar la plata al abrir, en vez de suponerla.

EL AGUJERO. La base salía de `tiendas.base_caja` y nadie miraba el cajón. Si
amaneció con $180.000 en vez de $200.000 —alguien sacó vueltas la noche
anterior, el sobre de la caja fuerte venía corto—, ese faltante no
desaparecía: reaparecía ocho horas después en el arqueo de quien cerró. La
persona equivocada, el momento equivocado, y ya sin forma de saber dónde pasó.

`test_lo_contado_al_abrir_es_la_base_QUE_MIDE_EL_CIERRE` es el punto entero de
este archivo. Lo demás lo sostiene.
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

# La tienda tiene base $200.000 y umbral $5.000 (los valores por defecto).
BASE_CONFIGURADA = 20000000
UMBRAL = 500000

# Cajones, en centavos. El de $200.000 cuadra; el de $180.000 está corto por
# $20.000 (supera el umbral); el de $199.000 por $1.000 (no lo supera).
CUADRA = {5000000: 4}
CORTO = {5000000: 3, 2000000: 1, 1000000: 1}
CORTO_POQUITO = {5000000: 3, 2000000: 2, 500000: 1, 100000: 4}


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
    async with motor.begin() as c:
        for sql in (
            "INSERT INTO retail.tiendas (id,nombre) VALUES ('florida','Florida')",
            "INSERT INTO retail.cajas (id,tienda_id,nombre,prefijo_factura) "
            "VALUES ('florida_caja1','florida','Caja 01','FV-20')",
            "INSERT INTO retail.medios_pago (id,nombre,tipo,siigo_forma_pago_id) "
            "VALUES ('efectivo','Efectivo','efectivo',12243)",
            "INSERT INTO retail.permisos_pos (usuario_id,nombre,tiendas) "
            "VALUES ('maria','María R.','{florida}')",
        ):
            await c.execute(text(sql))

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id="maria", email="maria@male.com", nombre="María R.", rol="user",
        permisos={"retail": ["ver", "modificar"]})

    with TestClient(app) as c:
        yield c, motor

    await motor.dispose()
    dependencias.reiniciar()
    revertir(URL)


def abrir(c, conteo=None, justificacion=None, sesion=SESION):
    cuerpo = {"sesion_id": sesion, "tienda_id": "florida",
              "caja_id": "florida_caja1"}
    if conteo is not None:
        cuerpo["conteo_apertura"] = {str(k): v for k, v in conteo.items()}
    if justificacion:
        cuerpo["base_justificacion"] = justificacion
    return c.post("/api/retail/caja/turno", json=cuerpo)


def _correr(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ── EL PUNTO ────────────────────────────────────────────────────────────────

def test_lo_contado_al_abrir_es_la_base_QUE_MIDE_EL_CIERRE(entorno):
    """El faltante de anoche se queda en anoche.

    Se abre con $180.000 contados sobre una base configurada de $200.000, no
    se vende nada, y se cierra contando los mismos $180.000. TIENE QUE CUADRAR.

    Con la conducta vieja —abrir con la base configurada— este cierre saldría
    con -$20.000, a nombre de una cajera que no perdió nada.
    """
    c, _ = entorno
    r = abrir(c, CORTO, justificacion="el sobre de la caja fuerte venía corto")
    assert r.status_code == 200, r.text
    assert r.json()["base_inicial_centavos"] == 18000000

    cierre = c.post("/api/retail/caja/cierre", json={
        "sesion_id": SESION,
        "conteos": [{"medio_pago_id": "efectivo",
                     "piezas": {str(k): v for k, v in CORTO.items()}}]})
    assert cierre.status_code == 200, cierre.text
    assert cierre.json()["diferencia_centavos"] == 0
    assert cierre.json()["cuadro"] is True


# ── El conteo ───────────────────────────────────────────────────────────────

def test_el_total_lo_saca_el_sistema(entorno):
    """La cajera mete cantidades; el total deja de ser un número que se pueda
    escribir de memoria. Es lo que separa contar de declarar."""
    c, _ = entorno
    assert abrir(c, CUADRA).json()["base_inicial_centavos"] == BASE_CONFIGURADA


def test_las_piezas_quedan_guardadas_para_poder_RECONTAR(entorno):
    """El error más común de un arqueo es una fila mal digitada. Con sólo el
    total guardado es irreconstruible; con las piezas, quien revisa ve «declaró
    3 de $50.000» y va a mirar si en el cajón había 4."""
    c, motor = entorno
    abrir(c, CORTO, justificacion="faltaba plata en el sobre")

    async def leer():
        async with motor.connect() as cn:
            return (await cn.execute(text("""
                SELECT valor_centavos, cantidad FROM retail.conteos_denominacion
                 WHERE sesion_id = :s AND momento = 'apertura'
                 ORDER BY valor_centavos DESC
            """), {"s": SESION})).mappings().all()

    filas = _correr(leer())
    assert [(int(f["valor_centavos"]), f["cantidad"]) for f in filas] == [
        (5000000, 3), (2000000, 1), (1000000, 1)]


def test_el_cierre_tambien_deja_sus_piezas(entorno):
    c, motor = entorno
    abrir(c, CUADRA)
    c.post("/api/retail/caja/cierre", json={
        "sesion_id": SESION,
        "conteos": [{"medio_pago_id": "efectivo", "piezas": {"5000000": 4}}]})

    async def leer():
        async with motor.connect() as cn:
            return (await cn.execute(text(
                "SELECT count(*) FROM retail.conteos_denominacion "
                " WHERE sesion_id=:s AND momento='cierre'"), {"s": SESION})).scalar()

    assert _correr(leer()) == 1


# ── La diferencia ───────────────────────────────────────────────────────────

def test_un_cajon_corto_de_verdad_NO_ABRE_sin_explicacion(entorno):
    """No es un bloqueo por el faltante: es que alguien tiene que decir qué
    pasó mientras todavía se acuerda."""
    c, _ = entorno
    r = abrir(c, CORTO)
    assert r.status_code == 400
    assert "faltan" in r.json()["detail"]["mensaje"]
    assert "$20.000" in r.json()["detail"]["mensaje"]


def test_pero_CON_explicacion_abre(entorno):
    """Una tienda que no puede abrir porque le faltan $20.000 no vende en todo
    el día, y eso cuesta más que el faltante."""
    c, _ = entorno
    assert abrir(c, CORTO, justificacion="el sobre venía corto").status_code == 200


def test_unas_monedas_de_menos_no_piden_explicacion(entorno):
    """$1.000 en monedas es la vida real de un cajón. Exigir un escrito cada
    mañana por eso entrena a la gente a escribir «ok» sin leer."""
    c, _ = entorno
    r = abrir(c, CORTO_POQUITO)
    assert r.status_code == 200, r.text
    assert r.json()["base_inicial_centavos"] == 19900000


def test_el_sobrante_tambien_cuenta(entorno):
    """Plata de más en el cajón es plata sin origen: o alguien la dejó, o un
    cierre anterior contó mal. Las dos cosas hay que saberlas."""
    c, _ = entorno
    r = abrir(c, {5000000: 5})          # $250.000 sobre una base de $200.000
    assert r.status_code == 400
    assert "sobran" in r.json()["detail"]["mensaje"]


# ── La auditoría ────────────────────────────────────────────────────────────

def test_el_cajon_corto_queda_CRITICO_con_su_explicacion(entorno):
    c, motor = entorno
    abrir(c, CORTO, justificacion="el sobre de la caja fuerte venía corto")

    async def leer():
        async with motor.connect() as cn:
            return (await cn.execute(text(
                "SELECT severidad, payload FROM retail.auditoria "
                " WHERE evento='caja.abierta'"))).mappings().first()

    a = _correr(leer())
    assert a["severidad"] == "critico"
    assert a["payload"]["base_diferencia"] == -2000000
    assert a["payload"]["base_esperada"] == BASE_CONFIGURADA
    assert "sobre" in a["payload"]["base_justificacion"]


def test_unas_monedas_quedan_como_AVISO_no_como_critico(entorno):
    """Marcar crítico cualquier diferencia llena el log de críticos todas las
    mañanas, y un log que siempre tiene críticos no lo revisa nadie."""
    c, motor = entorno
    abrir(c, CORTO_POQUITO)

    async def leer():
        async with motor.connect() as cn:
            return (await cn.execute(text(
                "SELECT severidad FROM retail.auditoria "
                " WHERE evento='caja.abierta'"))).scalar()

    assert _correr(leer()) == "aviso"


def test_se_lee_en_la_pantalla_de_auditoria(entorno):
    """Si el cajón amaneció corto tiene que verse en el renglón, sin abrir el
    turno para descubrirlo."""
    c, motor = entorno
    abrir(c, CORTO, justificacion="el sobre venía corto")

    async def permitir():
        async with motor.begin() as cn:
            await cn.execute(text("UPDATE retail.permisos_pos "
                                  "SET puede_ver_auditoria=true WHERE usuario_id='maria'"))

    _correr(permitir())
    d = c.get("/api/retail/auditoria", params={"tienda_id": "florida"}).json()
    linea = next(e for e in d["eventos"] if e["evento"] == "caja.abierta")
    assert "faltaban $20.000 al abrir" in linea["resumen"]
    assert "el sobre venía corto" in linea["resumen"]


# ── Que no se cuele basura ──────────────────────────────────────────────────

def test_una_denominacion_dada_de_baja_no_entra(entorno):
    """Una tableta con el catálogo viejo podría declarar 40 monedas de $50
    después de que la tienda las dio de baja, y el total cuadraría contra una
    moneda que ya nadie recibe."""
    c, _ = entorno
    r = abrir(c, {5000000: 4, 5000: 40})       # la de $50 nace apagada
    assert r.status_code == 400
    assert "no tiene activas" in r.json()["detail"]["mensaje"]


def test_mandar_piezas_Y_total_es_ambiguo(entorno):
    """Dos representaciones del mismo dinero que no se obligan a coincidir son
    el origen exacto de un descuadre que nadie puede explicar."""
    c, _ = entorno
    abrir(c, CUADRA)
    r = c.post("/api/retail/caja/cierre", json={
        "sesion_id": SESION,
        "conteos": [{"medio_pago_id": "efectivo", "piezas": {"5000000": 4},
                     "contado_centavos": 19000000}]})
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "conteo_ambiguo"


def test_un_datafono_no_se_cuenta_por_billetes(entorno):
    """Aceptarlo y quedarse sólo con el total descartaría el desglose en
    silencio: la pantalla creería haber guardado un conteo que no existe, y al
    recontar no habría nada que mirar."""
    c, motor = entorno

    async def sembrar():
        async with motor.begin() as cn:
            await cn.execute(text(
                "INSERT INTO retail.medios_pago (id,nombre,tipo,siigo_forma_pago_id)"
                " VALUES ('datafono','Datáfono','tarjeta',12244)"))

    _correr(sembrar())
    abrir(c, CUADRA)
    r = c.post("/api/retail/caja/cierre", json={
        "sesion_id": SESION,
        "conteos": [{"medio_pago_id": "efectivo", "piezas": {"5000000": 4}},
                    {"medio_pago_id": "datafono", "piezas": {"5000000": 1}}]})
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "denominaciones_en_medio_no_efectivo"


def test_no_se_puede_contar_en_negativo(entorno):
    c, _ = entorno
    assert abrir(c, {5000000: -1}).status_code == 400


# ── La vía vieja sigue viva ─────────────────────────────────────────────────

def test_sin_conteo_abre_como_antes(entorno):
    """Una tableta sin actualizar, o una apertura que quedó en la cola offline,
    no puede quedarse sin poder abrir turno porque le falte un campo nuevo."""
    c, _ = entorno
    r = abrir(c)
    assert r.status_code == 200
    assert r.json()["base_inicial_centavos"] == BASE_CONFIGURADA


def test_sin_conteo_se_NOTA_que_nadie_miro(entorno):
    """«Cuadró» y «nadie contó» no son lo mismo, y colapsarlos a cero haría
    pasar lo segundo por lo primero."""
    c, motor = entorno
    abrir(c)

    async def leer():
        async with motor.connect() as cn:
            return (await cn.execute(text(
                "SELECT base_esperada FROM retail.sesiones_caja WHERE id=:s"),
                {"s": SESION})).scalar()

    assert _correr(leer()) is None


def test_el_catalogo_viaja_con_el_contexto(entorno):
    """Contar el cajón es justo lo que se hace al encender la tableta, cuando
    puede que todavía no haya red. El catálogo va con lo que ya se guarda."""
    c, _ = entorno
    d = c.get("/api/retail/caja/contexto",
              params={"caja_id": "florida_caja1"}).json()
    valores = [x["valor_centavos"] for x in d["denominaciones"]]
    assert valores == sorted(valores, reverse=True)   # se cuenta de mayor a menor
    assert 5000 not in valores                        # la de $50 no circula
    assert d["denominaciones"][0]["tipo"] == "billete"
