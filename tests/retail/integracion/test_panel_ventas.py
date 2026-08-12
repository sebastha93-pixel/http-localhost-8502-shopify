"""Panel de ventas del día — vista 8.

La prueba que justifica este archivo es la de la zona horaria. Colombia está en
UTC−5: una venta de las 7 p.m. es todavía «hoy» en Medellín pero ya es mañana
en UTC. Si el corte se hace mal, el panel se vacía a media tarde y deja de
cuadrar con el arqueo del cierre — dos números distintos para la misma
pregunta, y ninguna forma de saber cuál está mal mirando la pantalla.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

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

SESION = "01JQ8X4T5N6P7R8S9V0W1X2Y3Z"
UBICACION = "tienda:florida"
BOGOTA = timezone(timedelta(hours=-5))


def _var(n: int) -> str:
    return "01JQ8X4T5N6P%03dR8S9V0W1X2Y" % n


def _venta_id(n: int) -> str:
    return "01JQ8X4T5N7P%03dR8S9V0W1X2Y" % n


@pytest_asyncio.fixture()
async def cliente():
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
        ("INSERT INTO retail.tiendas (id,nombre,zona_horaria) "
         "VALUES ('florida','Florida','America/Bogota')", {}),
        ("INSERT INTO retail.cajas (id,tienda_id,nombre) "
         "VALUES ('florida_caja1','florida','Caja 1')", {}),
        ("INSERT INTO retail.ubicaciones (id,tipo,nombre,tienda_id) "
         "VALUES (:u,'tienda','Florida','florida')", {"u": UBICACION}),
        ("INSERT INTO retail.sesiones_caja "
         "(id,tienda_id,caja_id,numero_turno,base_inicial,abierta_por) "
         "VALUES (:s,'florida','florida_caja1',1,20000000,'maria')",
         {"s": SESION}),
        ("INSERT INTO retail.variantes "
         "(id,sku,referencia,talla,nombre,color,precio_con_iva) "
         "VALUES (:v,'92611-1T10','92611-1','10','Jean Skinny','Azul',16990000)",
         {"v": _var(1)}),
        ("INSERT INTO retail.variantes "
         "(id,sku,referencia,talla,nombre,color,precio_con_iva) "
         "VALUES (:v,'93100-2T4','93100-2','4','Falda Midi','Negro',13990000)",
         {"v": _var(2)}),
    ]
    async with motor.begin() as c:
        for sql, p in semillas:
            await c.execute(text(sql), p)

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id="maria", email="m@male.com", nombre="María", rol="user",
        permisos={"retail": ["ver", "modificar"]})

    with TestClient(app) as c:
        yield c, motor

    await motor.dispose()
    dependencias.reiniciar()
    revertir(URL)


async def _vender(motor, n: int, *, cuando: datetime, variante: str,
                  cantidad: int, precio: int, estado: str = "cerrada"):
    """Escribe la venta directamente: aquí se prueba la LECTURA, y el momento
    exacto del cierre es el dato bajo prueba — tiene que poder fijarse."""
    total = precio * cantidad
    # Anular EXIGE motivo: lo impone el esquema, y con razón — una venta que
    # desaparece sin explicación es indistinguible de un robo.
    motivo = "prueba" if estado == "anulada" else None
    async with motor.begin() as c:
        await c.execute(text("""
            INSERT INTO retail.ventas
                (id,numero,prefijo,consecutivo,tienda_id,caja_id,sesion_id,
                 cajera_id,estado,moneda,subtotal,descuento_total,total,pagado,
                 cerrada_en,motivo_anulacion)
            VALUES (:i,:num,'FV-20',:c,'florida','florida_caja1',:s,'maria',
                    :e,'COP',:t,0,:t,:t,:ts,:mot)
        """), {"i": _venta_id(n), "num": f"FV-20-{1400 + n}", "c": 1400 + n,
               "s": SESION, "e": estado, "t": total, "ts": cuando,
               "mot": motivo})
        await c.execute(text("""
            INSERT INTO retail.venta_lineas
                (id,venta_id,orden,variante_id,sku,descripcion,cantidad,
                 precio_unitario,descuento_monto,tasa_iva,base_gravable,
                 iva_monto,total_linea)
            VALUES (:i,:v,1,:var,'X','X',:cant,:p,0,19,:t,0,:t)
        """), {"i": _venta_id(n)[:22] + "0001", "v": _venta_id(n),
               "var": variante, "cant": cantidad, "p": precio, "t": total})


def _panel(c):
    r = c.get("/api/retail/panel", params={"tienda_id": "florida"})
    assert r.status_code == 200, r.text
    return r.json()


def _ahora_bogota() -> datetime:
    return datetime.now(BOGOTA)


# ── LA PRUEBA QUE IMPORTA ───────────────────────────────────────────────────

def test_una_venta_de_las_siete_de_la_noche_sigue_siendo_de_hoy(cliente):
    """Colombia es UTC−5. A las 19:00 de Medellín ya son las 00:00 en UTC.

    Con `date_trunc('day', now())` sin zona horaria, esa venta se contaría en
    el día siguiente: el panel se vaciaría cada tarde y no cuadraría con el
    arqueo del cierre, que sí se hace sobre el turno real.
    """
    c, motor = cliente
    import asyncio

    hoy = _ahora_bogota().date()
    siete_pm = datetime(hoy.year, hoy.month, hoy.day, 19, 30, tzinfo=BOGOTA)
    if siete_pm > _ahora_bogota():
        # Si la prueba corre antes de las 19:30, se usa la de ayer a esa hora
        # y se verifica lo contrario: que NO cuente. Ambas ramas dicen lo
        # mismo —el corte es el de la tienda— y la prueba no depende del reloj.
        anoche = siete_pm - timedelta(days=1)
        asyncio.get_event_loop().run_until_complete(
            _vender(motor, 1, cuando=anoche, variante=_var(1), cantidad=1,
                    precio=16990000))
        assert _panel(c)["transacciones"] == 0, (
            "está contando ventas de ayer como de hoy"
        )
        return

    asyncio.get_event_loop().run_until_complete(
        _vender(motor, 1, cuando=siete_pm, variante=_var(1), cantidad=1,
                precio=16990000))
    d = _panel(c)
    assert d["transacciones"] == 1, "perdió la venta de la tarde por la zona horaria"
    assert d["fecha"] == hoy.isoformat()


def test_lo_de_ayer_no_entra(cliente):
    c, motor = cliente
    import asyncio
    ayer = _ahora_bogota() - timedelta(days=1)
    asyncio.get_event_loop().run_until_complete(
        _vender(motor, 2, cuando=ayer, variante=_var(1), cantidad=3,
                precio=16990000))
    d = _panel(c)
    assert d["transacciones"] == 0
    assert d["ventas_centavos"] == 0
    assert d["unidades"] == 0


def test_la_fecha_que_devuelve_es_la_de_la_tienda(cliente):
    c, _ = cliente
    assert _panel(c)["fecha"] == _ahora_bogota().date().isoformat()


# ── Las cifras ──────────────────────────────────────────────────────────────

def test_las_cuatro_tarjetas(cliente):
    c, motor = cliente
    import asyncio
    ahora = _ahora_bogota()

    async def sembrar():
        await _vender(motor, 10, cuando=ahora, variante=_var(1), cantidad=2,
                      precio=16990000)                       # $339.800
        await _vender(motor, 11, cuando=ahora, variante=_var(2), cantidad=1,
                      precio=13990000)                       # $139.900
        await _vender(motor, 12, cuando=ahora, variante=_var(1), cantidad=1,
                      precio=16990000, estado="anulada")     # no cuenta

    asyncio.get_event_loop().run_until_complete(sembrar())
    d = _panel(c)

    assert d["transacciones"] == 2
    assert d["ventas_centavos"] == 33980000 + 13990000
    assert d["unidades"] == 3, "las unidades salen de las líneas, no de las ventas"
    # La anulada se cuenta aparte, no se resta en silencio de las ventas.
    assert d["anuladas"] == 1
    assert d["monto_anulado_centavos"] == 16990000


def test_el_ticket_promedio(cliente):
    c, motor = cliente
    import asyncio
    ahora = _ahora_bogota()

    async def sembrar():
        await _vender(motor, 20, cuando=ahora, variante=_var(1), cantidad=1,
                      precio=16990000)
        await _vender(motor, 21, cuando=ahora, variante=_var(2), cantidad=1,
                      precio=13990000)

    asyncio.get_event_loop().run_until_complete(sembrar())
    assert _panel(c)["ticket_promedio_centavos"] == round((16990000 + 13990000) / 2)


def test_sin_ventas_el_panel_no_se_rompe(cliente):
    """El primer minuto del día. Dividir por cero aquí dejaría la pantalla en
    blanco justo cuando la administradora abre la tienda."""
    c, _ = cliente
    d = _panel(c)
    assert d["transacciones"] == 0
    assert d["ticket_promedio_centavos"] == 0
    assert d["mas_vendidos"] == []
    # El gráfico existe igual: un día sin ventas es una respuesta, no un vacío.
    assert len(d["horas"]) >= 11


# ── El gráfico por hora ─────────────────────────────────────────────────────

def test_el_grafico_trae_el_horario_habitual_aunque_no_haya_ventas(cliente):
    c, _ = cliente
    horas = [h["hora"] for h in _panel(c)["horas"]]
    assert horas == sorted(horas)
    assert set(range(10, 21)) <= set(horas)


def test_una_venta_fuera_del_horario_NO_desaparece(cliente):
    """El prototipo dibuja 10h–20h fijas. Una venta a las 21:05 de un día de
    diciembre se perdería sin dejar rastro — y justo esas son las que hay que
    poder ver."""
    c, motor = cliente
    import asyncio
    hoy = _ahora_bogota()
    tarde = hoy.replace(hour=21, minute=5, second=0, microsecond=0)
    if tarde > hoy:                       # todavía no son las 21:05
        tarde = hoy.replace(hour=min(hoy.hour, 9), minute=0, second=0,
                            microsecond=0)
    asyncio.get_event_loop().run_until_complete(
        _vender(motor, 30, cuando=tarde, variante=_var(1), cantidad=1,
                precio=16990000))

    d = _panel(c)
    barras = {h["hora"]: h for h in d["horas"]}
    assert tarde.hour in barras, f"la venta de las {tarde.hour}h no aparece"
    assert barras[tarde.hour]["ventas_centavos"] == 16990000
    assert [h["hora"] for h in d["horas"]] == sorted(barras)


def test_las_horas_sin_venta_van_en_cero_no_ausentes(cliente):
    """Un hueco en el gráfico se lee como «no hay dato», no como «no se vendió».
    Son cosas distintas y la segunda es la que importa."""
    c, motor = cliente
    import asyncio
    ahora = _ahora_bogota()
    asyncio.get_event_loop().run_until_complete(
        _vender(motor, 40, cuando=ahora, variante=_var(1), cantidad=1,
                precio=16990000))

    d = _panel(c)
    vacias = [h for h in d["horas"] if h["ventas_centavos"] == 0]
    assert vacias, "no hay barras en cero: el gráfico está omitiendo horas"
    assert all("etiqueta" in h for h in d["horas"])


# ── Más vendidos ────────────────────────────────────────────────────────────

def test_los_mas_vendidos_van_por_UNIDADES(cliente):
    """La pregunta es «qué se está llevando la gente», que es lo que hay que
    reponer. La referencia que más factura es otra pregunta."""
    c, motor = cliente
    import asyncio
    ahora = _ahora_bogota()

    async def sembrar():
        # La falda: 5 unidades a $139.900 = $699.500
        await _vender(motor, 50, cuando=ahora, variante=_var(2), cantidad=5,
                      precio=13990000)
        # El jean: 2 unidades a $169.900 = $339.800 — factura menos.
        await _vender(motor, 51, cuando=ahora, variante=_var(1), cantidad=2,
                      precio=16990000)

    asyncio.get_event_loop().run_until_complete(sembrar())
    top = _panel(c)["mas_vendidos"]

    assert [t["referencia"] for t in top] == ["93100-2", "92611-1"]
    assert top[0]["posicion"] == 1
    assert top[0]["unidades"] == 5
    assert top[0]["nombre"] == "Falda Midi"
    assert top[0]["color"] == "Negro"
    assert top[1]["posicion"] == 2


def test_una_venta_anulada_no_aparece_entre_los_mas_vendidos(cliente):
    """Anular y volver a vender inflaría el ranking al doble."""
    c, motor = cliente
    import asyncio
    ahora = _ahora_bogota()
    asyncio.get_event_loop().run_until_complete(
        _vender(motor, 60, cuando=ahora, variante=_var(1), cantidad=9,
                precio=16990000, estado="anulada"))
    assert _panel(c)["mas_vendidos"] == []


def test_las_tallas_de_una_misma_referencia_se_suman(cliente):
    """La administradora repone por REFERENCIA. Ver el mismo jean tres veces,
    una por talla, oculta que es el más vendido del día."""
    c, motor = cliente
    import asyncio

    async def sembrar():
        async with motor.begin() as cn:
            await cn.execute(text("""
                INSERT INTO retail.variantes
                    (id,sku,referencia,talla,nombre,color,precio_con_iva)
                VALUES (:v,'92611-1T4','92611-1','4','Jean Skinny','Azul',16990000)
            """), {"v": _var(3)})
        ahora = _ahora_bogota()
        await _vender(motor, 70, cuando=ahora, variante=_var(1), cantidad=2,
                      precio=16990000)
        await _vender(motor, 71, cuando=ahora, variante=_var(3), cantidad=3,
                      precio=16990000)

    asyncio.get_event_loop().run_until_complete(sembrar())
    top = _panel(c)["mas_vendidos"]
    assert len(top) == 1
    assert top[0]["referencia"] == "92611-1"
    assert top[0]["unidades"] == 5


def test_una_tienda_que_no_existe_lo_dice(cliente):
    c, _ = cliente
    r = c.get("/api/retail/panel", params={"tienda_id": "no_existe"})
    assert r.status_code == 400
    assert "no_existe" in r.json()["detail"]["mensaje"]
