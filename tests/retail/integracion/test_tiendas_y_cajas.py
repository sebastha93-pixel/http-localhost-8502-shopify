"""Dos tiendas en la misma base: Florida y Arrayanes.

Hasta ahora el POS tenía UNA caja, cableada en variables del frontend, y todo
lo demás se apoyaba en eso: el efectivo era «el» efectivo, y la tienda, la
caja y la ubicación que mandaba el dispositivo se creían sin mirar. Con dos
tiendas eso se vuelve un error silencioso: la plata de Arrayanes en la cuenta
de Florida, o una venta de Arrayanes descontando el stock de Florida.

Lo que se prueba aquí: que la siembra crea las tiendas reales sin pisar lo
corregido a mano, que cada tienda ve SU efectivo, y que el servidor rechaza
una petición que mezcla tiendas.
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

SESION = "01JQ8X4T5N6P003R8S9V0W1X2Y"
VENTA = "01JQ8X4T5N7V003R8S9V0W1X2Y"
VARIANTE = "01JQ8X4T5N6P7R8S9V0W1X2Y44"
PRECIO = 10_000_000
STOCK = 5


def _leer(motor, sql, params=None):
    async def ir():
        async with motor.connect() as cn:
            return (await cn.execute(text(sql), params or {})).all()
    return asyncio.get_event_loop().run_until_complete(ir())


@pytest.fixture()
def base_vacia():
    """Sin asyncio a propósito: la siembra es síncrona, y estas pruebas no
    tienen un bucle de eventos al que colgarse."""
    from sqlalchemy import create_engine
    from backend.modules.retail.migraciones.runner import aplicar, revertir

    revertir(URL)
    aplicar(URL)
    motor = create_engine(URL, future=True)
    yield motor
    motor.dispose()
    revertir(URL)


def _leer_sync(motor, sql, params=None):
    with motor.connect() as cn:
        return cn.execute(text(sql), params or {}).all()


@pytest_asyncio.fixture()
async def entorno():
    from backend.core.security import CurrentUser, get_current_user
    from backend.modules.retail.interfaces.http import dependencias
    from backend.modules.retail.interfaces.http.router import router
    from backend.modules.retail.migraciones.runner import aplicar, revertir
    from backend.modules.retail.sembrar_tiendas import sembrar

    revertir(URL)
    aplicar(URL)
    sembrar(URL, aplicar=True)
    os.environ["RETAIL_DATABASE_URL"] = URL
    dependencias.reiniciar()

    motor = create_async_engine(URL)
    async with motor.begin() as c:
        await c.execute(text(
            "INSERT INTO retail.variantes "
            "(id,sku,referencia,talla,nombre,precio_con_iva) "
            "VALUES (:v,'92611-1T10','92611-1','10','Jean',:p)"),
            {"v": VARIANTE, "p": PRECIO})
        for ubi in ("tienda:florida", "tienda:arrayanes"):
            await c.execute(text(
                "INSERT INTO retail.stock_ubicacion "
                "(ubicacion_id,variante_id,cantidad) VALUES (:u,:v,:c)"),
                {"u": ubi, "v": VARIANTE, "c": STOCK})
        await c.execute(text(
            "INSERT INTO retail.permisos_pos (usuario_id,nombre,tiendas) "
            "VALUES ('maria','María R.','{florida,arrayanes}')"))

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


def _abrir_arrayanes(c, tienda="arrayanes"):
    return c.post("/api/retail/caja/turno", json={
        "sesion_id": SESION, "tienda_id": tienda,
        "caja_id": "arrayanes_caja1"})


def _vender(c, turno, *, ubicacion):
    return c.post("/api/retail/ventas/cerrar", json={
        "venta_id": VENTA,
        "numero": f"{turno['prefijo']}-{turno['consecutivo_siguiente']}",
        "tienda_id": "arrayanes", "caja_id": "arrayanes_caja1",
        "sesion_id": SESION, "ubicacion_id": ubicacion,
        "lineas": [{"sku": "92611-1T10", "cantidad": 1,
                    "precio_unitario_centavos": PRECIO,
                    "descripcion": "Jean · 10"}],
        "pagos": [{"medio_pago_id": "efectivo_arrayanes",
                   "monto_centavos": PRECIO, "es_efectivo": True}]})


def _stock(motor, ubicacion):
    return _leer(motor, "SELECT cantidad FROM retail.stock_ubicacion "
                        "WHERE ubicacion_id=:u AND variante_id=:v",
                 {"u": ubicacion, "v": VARIANTE})[0][0]


# ── La siembra ──────────────────────────────────────────────────────────────

def test_el_ensayo_corre_todo_y_no_deja_nada(base_vacia):
    """El ensayo ejecuta los INSERT de verdad y los revierte: un error de
    columnas tiene que salir aquí, no a mitad de la aplicación en producción."""
    from backend.modules.retail.sembrar_tiendas import sembrar

    r = sembrar(URL)
    assert r["aplicado"] is False
    assert sorted(r["tiendas"]) == ["arrayanes", "florida"]
    assert len(r["cajas"]) == 3 and len(r["ubicaciones"]) == 2
    assert _leer_sync(base_vacia, "SELECT count(*) FROM retail.tiendas")[0][0] == 0


def test_volver_a_sembrar_no_pisa_lo_corregido_a_mano(base_vacia):
    """Subir el consecutivo antes de una jornada es una corrección a mano, y
    es justo la que no se puede perder por volver a correr la siembra."""
    from backend.modules.retail.sembrar_tiendas import sembrar

    sembrar(URL, aplicar=True)

    with base_vacia.begin() as c:
        c.execute(text("UPDATE retail.tiendas SET consecutivo_externo = 1600 "
                       "WHERE id = 'florida'"))

    otra = sembrar(URL, aplicar=True)
    assert otra["tiendas"] == [] and otra["cajas"] == []
    assert _leer_sync(base_vacia, "SELECT consecutivo_externo FROM retail.tiendas "
                             "WHERE id='florida'")[0][0] == 1600


def test_florida_queda_con_los_datos_de_su_tirilla(base_vacia):
    """Las migraciones 0016 y 0018 traían estos datos como UPDATE, y sobre la
    base de producción —nueva— no tocaron ninguna fila."""
    from backend.modules.retail.sembrar_tiendas import sembrar

    sembrar(URL, aplicar=True)
    nit, techo, piso = _leer_sync(base_vacia, """
        SELECT nit, autorizacion_hasta, consecutivo_externo
          FROM retail.tiendas WHERE id = 'florida'""")[0]
    assert (nit, techo, piso) == ("901680460-1", 10000, 1536)
    prefijos = _leer_sync(base_vacia, "SELECT DISTINCT prefijo_factura "
                                 "FROM retail.cajas WHERE tienda_id='florida'")
    assert prefijos == [("FL",)]      # un prefijo por tienda, las dos cajas


# ── Qué ve cada tienda ──────────────────────────────────────────────────────

def test_la_lista_trae_las_cajas_activas(entorno):
    c, motor = entorno
    ids = [x["caja_id"] for x in c.get("/api/retail/cajas").json()]
    assert ids == ["arrayanes_caja1", "florida_caja1", "florida_caja2"]

    async def dar_de_baja():
        async with motor.begin() as cn:
            await cn.execute(text("UPDATE retail.cajas SET activa = false "
                                  "WHERE id = 'florida_caja2'"))
    asyncio.get_event_loop().run_until_complete(dar_de_baja())
    ids = [x["caja_id"] for x in c.get("/api/retail/cajas").json()]
    assert "florida_caja2" not in ids


def test_arrayanes_ve_su_efectivo_y_no_el_de_florida(entorno):
    c, _ = entorno
    d = c.get("/api/retail/caja/contexto",
              params={"caja_id": "arrayanes_caja1"}).json()
    medios = {m["id"] for m in d["medios_pago"]}
    assert {"efectivo_arrayanes", "datafono_arrayanes",
            "transferencia"} <= medios
    assert not medios & {"efectivo_florida", "datafono_florida"}
    assert d["ubicacion_id"] == "tienda:arrayanes"
    assert d["tienda_id"] == "arrayanes"


def test_la_base_de_cada_tienda_entra_a_SU_efectivo(entorno):
    """Si la base se anotara contra el efectivo de la otra tienda, el arqueo
    saldría corto por la base todos los días, sin un error.

    Florida es el caso que discrimina: la consulta vieja —el primer efectivo,
    por orden e id— devolvía `efectivo_arrayanes` para las dos."""
    c, motor = entorno
    florida = "01JQ8X4T5N6P004R8S9V0W1X2Y"
    r = c.post("/api/retail/caja/turno", json={
        "sesion_id": florida, "tienda_id": "florida",
        "caja_id": "florida_caja1"})
    assert r.status_code == 200, r.text
    assert (r.json()["prefijo"], r.json()["consecutivo_siguiente"]) == ("FL", 1537)

    r = _abrir_arrayanes(c)
    assert r.status_code == 200, r.text
    assert r.json()["prefijo"] == "FV-6"
    assert r.json()["consecutivo_siguiente"] == 10704   # sobre el piso

    base = dict(_leer(motor, "SELECT sesion_id, medio_pago_id "
                             "FROM retail.movimientos_caja "
                             "WHERE tipo='base_inicial'"))
    assert base == {florida: "efectivo_florida", SESION: "efectivo_arrayanes"}


# ── Lo que el servidor ya no se cree ────────────────────────────────────────

def test_no_se_abre_turno_con_la_tienda_de_otra_caja(entorno):
    c, motor = entorno
    r = _abrir_arrayanes(c, tienda="florida")
    assert r.status_code == 400, r.text
    assert "arrayanes" in r.json()["detail"]["mensaje"]
    assert _leer(motor, "SELECT count(*) FROM retail.sesiones_caja")[0][0] == 0


def test_no_se_vende_contra_el_inventario_de_otra_tienda(entorno):
    """Una tableta de Arrayanes con un dato viejo no puede descontar el stock
    de Florida. Y con la ubicación correcta, la misma venta sí entra."""
    c, motor = entorno
    turno = _abrir_arrayanes(c).json()

    r = _vender(c, turno, ubicacion="tienda:florida")
    assert r.status_code == 400, r.text
    assert _stock(motor, "tienda:florida") == STOCK

    r = _vender(c, turno, ubicacion="tienda:arrayanes")
    assert r.status_code == 200, r.text
    assert _stock(motor, "tienda:arrayanes") == STOCK - 1
    assert _stock(motor, "tienda:florida") == STOCK


# ── Comprar en una tienda, devolver en la otra ──────────────────────────────

def test_lo_comprado_en_florida_se_devuelve_en_arrayanes(entorno):
    """La plata sale del cajón de ARRAYANES y la prenda entra a SU inventario.

    Hacerlo contra la venta descuadraría las dos tiendas a la vez: a Florida
    le faltaría plata que nunca entregó y le sobraría una prenda que no tiene.
    """
    c, motor = entorno
    florida = "01JQ8X4T5N6P005R8S9V0W1X2Y"
    t = c.post("/api/retail/caja/turno", json={
        "sesion_id": florida, "tienda_id": "florida",
        "caja_id": "florida_caja1"}).json()
    numero = f"{t['prefijo']}-{t['consecutivo_siguiente']}"
    r = c.post("/api/retail/ventas/cerrar", json={
        "venta_id": VENTA, "numero": numero,
        "tienda_id": "florida", "caja_id": "florida_caja1",
        "sesion_id": florida, "ubicacion_id": "tienda:florida",
        "lineas": [{"sku": "92611-1T10", "cantidad": 1,
                    "precio_unitario_centavos": PRECIO,
                    "descripcion": "Jean · 10"}],
        "pagos": [{"medio_pago_id": "efectivo_florida",
                   "monto_centavos": PRECIO, "es_efectivo": True}]})
    assert r.status_code == 200, r.text

    # En Arrayanes todavía no hay turno: el efectivo no se puede ofrecer,
    # aunque Florida —la que vendió— sí tenga el suyo abierto.
    ticket = c.get(f"/api/retail/devoluciones/ticket/{numero}",
                   params={"caja_id": "arrayanes_caja1"}).json()
    assert ticket["puede_efectivo"] is False

    assert _abrir_arrayanes(c).status_code == 200
    ticket = c.get(f"/api/retail/devoluciones/ticket/{numero}",
                   params={"caja_id": "arrayanes_caja1"}).json()
    assert ticket["puede_efectivo"] is True

    r = c.post("/api/retail/devoluciones", json={
        "devolucion_id": "01JQ8X4T5N7D005R8S9V0W1X2Y", "venta_id": VENTA,
        "seleccion": {"92611-1T10": 1}, "motivo": "talla",
        "reembolso": "efectivo", "caja_id": "arrayanes_caja1"})
    assert r.status_code == 200, r.text
    assert r.json()["sesion_id"] == SESION          # el turno de Arrayanes

    assert _stock(motor, "tienda:arrayanes") == STOCK + 1
    assert _stock(motor, "tienda:florida") == STOCK - 1   # la venta, intacta
    salida = _leer(motor, "SELECT sesion_id, medio_pago_id, monto "
                          "FROM retail.movimientos_caja WHERE tipo='devolucion'")
    assert salida == [(SESION, "efectivo_arrayanes", -PRECIO)]
    donde = _leer(motor, "SELECT tienda_id, caja_id FROM retail.devoluciones")
    assert donde == [("arrayanes", "arrayanes_caja1")]
