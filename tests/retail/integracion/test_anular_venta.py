"""Deshacer una venta cerrada.

Cuatro cosas pasan a la vez, y o pasan todas o no pasa ninguna: la venta se
marca, la prenda vuelve al stock, la plata sale del arqueo, y queda constancia.
Si alguna se cayera sola el resultado sería PEOR que no anular — prenda
devuelta al saldo con la venta todavía viva, o plata descontada del arqueo sin
que nadie sepa por qué.

`Venta.anular` estaba en el agregado desde el principio, con la firma por PIN
que ya no existe, y sin ningún endpoint. El panel contaba «anuladas» y nada
podía anular.
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
VENTA = "01JQ8X4T5N7V001R8S9V0W1X2Y"
VARIANTE = "01JQ8X4T5N6P7R8S9V0W1X2Y42"
UBICACION = "tienda:florida"
PRECIO = 16990000
STOCK = 50
BASE = 20000000


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
        ("INSERT INTO retail.variantes "
         "(id,sku,referencia,talla,nombre,precio_con_iva) "
         "VALUES (:v,'92611-1T10','92611-1','10','Jean',:p)",
         {"v": VARIANTE, "p": PRECIO}),
        ("INSERT INTO retail.stock_ubicacion (ubicacion_id,variante_id,cantidad) "
         "VALUES (:u,:v,:c)", {"u": UBICACION, "v": VARIANTE, "c": STOCK}),
        # Laura puede anular; María no.
        ("INSERT INTO retail.permisos_pos "
         "(usuario_id,nombre,tiendas,puede_anular_venta,puede_ver_esperado) "
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
        # Una venta de 2 unidades pagada en efectivo.
        r = c.post("/api/retail/ventas/cerrar", json={
            "venta_id": VENTA, "numero": f"FV-20-{r.json()['consecutivo_siguiente']}",
            "tienda_id": "florida", "caja_id": "florida_caja1",
            "sesion_id": SESION, "ubicacion_id": UBICACION,
            "lineas": [{"sku": "92611-1T10", "cantidad": 2,
                        "precio_unitario_centavos": PRECIO,
                        "descripcion": "Jean · 10"}],
            "pagos": [{"medio_pago_id": "efectivo",
                       "monto_centavos": PRECIO * 2, "es_efectivo": True}]})
        assert r.status_code == 200, r.text
        yield c, motor, entrar_como

    await motor.dispose()
    dependencias.reiniciar()
    revertir(URL)


def _anular(c, motivo="cobrada dos veces por error"):
    return c.post(f"/api/retail/ventas/{VENTA}/anular", json={"motivo": motivo})


def _leer(motor, sql, params=None):
    async def ir():
        async with motor.connect() as cn:
            return (await cn.execute(text(sql), params or {})).first()
    return asyncio.get_event_loop().run_until_complete(ir())


# ── El permiso ──────────────────────────────────────────────────────────────

def test_sin_permiso_no_se_anula(entorno):
    """Anular es la forma limpia de hacer desaparecer una venta cobrada. Sin
    permiso ni rastro sería la vía perfecta para quedarse con la plata."""
    c, _, _ = entorno
    r = _anular(c)
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "sin_permiso_anular"


def test_anular_exige_motivo_de_verdad(entorno):
    c, _, entrar_como = entorno
    entrar_como("laura", "Laura M.")
    assert c.post(f"/api/retail/ventas/{VENTA}/anular",
                  json={"motivo": "x"}).status_code == 422


# ── Las cuatro cosas, juntas ────────────────────────────────────────────────

def test_anular_marca_devuelve_stock_y_saca_la_plata(entorno):
    """La prueba central: las cuatro escrituras ocurren, y coherentes."""
    c, motor, entrar_como = entorno
    entrar_como("laura", "Laura M.")

    antes = _leer(motor, "SELECT cantidad FROM retail.stock_ubicacion "
                         " WHERE ubicacion_id=:u AND variante_id=:v",
                  {"u": UBICACION, "v": VARIANTE}).cantidad
    assert antes == STOCK - 2

    r = _anular(c)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["total_revertido_centavos"] == PRECIO * 2
    assert d["unidades_devueltas"] == 2

    # 1 · la venta
    v = _leer(motor, "SELECT estado, motivo_anulacion, anulada_en "
                     " FROM retail.ventas WHERE id=:i", {"i": VENTA})
    assert v.estado == "anulada"
    assert v.motivo_anulacion == "cobrada dos veces por error"
    assert v.anulada_en is not None

    # 2 · el stock vuelve
    despues = _leer(motor, "SELECT cantidad FROM retail.stock_ubicacion "
                           " WHERE ubicacion_id=:u AND variante_id=:v",
                    {"u": UBICACION, "v": VARIANTE}).cantidad
    assert despues == STOCK, "la prenda no volvió al saldo"

    # 3 · la plata sale del arqueo
    d2 = c.get("/api/retail/caja/cierre/resumen",
               params={"sesion_id": SESION}).json()
    assert d2["esperado_por_medio"]["efectivo"] == BASE

    # 4 · la auditoría
    a = _leer(motor, "SELECT severidad, payload FROM retail.auditoria "
                     " WHERE evento='venta.anulada'")
    assert a.severidad == "critico"
    assert a.payload["motivo"] == "cobrada dos veces por error"


def test_el_libro_de_inventario_es_APPEND_ONLY(entorno):
    """No se borra el asiento de la venta: se escribe el contrario. Un libro
    que se puede editar no sirve para cuadrar nada, porque cualquier diferencia
    se puede hacer desaparecer."""
    c, motor, entrar_como = entorno
    entrar_como("laura", "Laura M.")
    _anular(c)

    async def asientos():
        async with motor.connect() as cn:
            return (await cn.execute(text("""
                SELECT delta, motivo FROM retail.movimientos_inventario
                 WHERE referencia_id = :i ORDER BY id
            """), {"i": VENTA})).mappings().all()

    filas = asyncio.get_event_loop().run_until_complete(asientos())
    assert len(filas) == 2, "debería haber salida y devolución, no una edición"
    assert filas[0]["delta"] == -2
    assert filas[1]["delta"] == 2
    assert filas[1]["motivo"] == "anulacion"


def test_la_anulacion_queda_a_nombre_de_QUIEN_ANULA(entorno):
    """Antes el movimiento de caja se anotaba con `abierta_por`, así que al
    revisar quién deshizo una venta salía siempre la persona que abrió la caja
    esa mañana."""
    c, motor, entrar_como = entorno
    entrar_como("laura", "Laura M.")
    _anular(c)

    m = _leer(motor, "SELECT usuario_id, monto FROM retail.movimientos_caja "
                     " WHERE tipo='anulacion'")
    assert m.usuario_id == "laura"          # no 'maria', que abrió el turno
    assert m.monto == -PRECIO * 2


# ── Lo que NO se puede anular ───────────────────────────────────────────────

def test_no_se_anula_dos_veces(entorno):
    c, _, entrar_como = entorno
    entrar_como("laura", "Laura M.")
    assert _anular(c).status_code == 200
    r = _anular(c)
    assert r.status_code == 400
    assert "cerrada" in r.json()["detail"]["mensaje"].lower()


def test_no_se_anula_una_venta_de_un_turno_YA_CERRADO(entorno):
    """Su plata se contó en un arqueo firmado. Tocarla ahora descuadra un turno
    que ya cuadró — y ese arqueo no se puede volver a hacer."""
    c, motor, entrar_como = entorno
    entrar_como("laura", "Laura M.")

    async def cerrar_turno():
        async with motor.begin() as cn:
            await cn.execute(text(
                "UPDATE retail.sesiones_caja SET estado='cerrada', "
                " cerrada_por='laura', cerrada_en=now() WHERE id=:i"),
                {"i": SESION})

    asyncio.get_event_loop().run_until_complete(cerrar_turno())
    r = _anular(c)
    assert r.status_code == 400
    assert "nota crédito" in r.json()["detail"]["mensaje"].lower()


def test_una_venta_que_no_existe(entorno):
    c, _, entrar_como = entorno
    entrar_como("laura", "Laura M.")
    r = c.post("/api/retail/ventas/01JQ8X4T5N7V999R8S9V0W1X2Y/anular",
               json={"motivo": "prueba de venta inexistente"})
    assert r.status_code == 400


# ── Lo fiscal, que esto NO resuelve ─────────────────────────────────────────

def test_si_la_factura_YA_SALIO_lo_dice(entorno):
    """Anular en el POS no revierte nada ante la DIAN: hace falta nota crédito.
    Callarlo dejaría creer que quedó todo deshecho."""
    c, motor, entrar_como = entorno
    entrar_como("laura", "Laura M.")

    async def emitir():
        async with motor.begin() as cn:
            await cn.execute(text(
                "UPDATE retail.ventas SET estado_fiscal='emitido' WHERE id=:i"),
                {"i": VENTA})

    asyncio.get_event_loop().run_until_complete(emitir())
    r = _anular(c)
    assert r.status_code == 200, r.text
    assert r.json()["exige_nota_credito"] is True

    # Y queda encolada para la Fase 3 en vez de perderse.
    o = _leer(motor, "SELECT tipo FROM retail.outbox "
                     " WHERE tipo='emitir_nota_credito'")
    assert o is not None


def test_sin_factura_emitida_no_exige_nota_credito(entorno):
    c, _, entrar_como = entorno
    entrar_como("laura", "Laura M.")
    assert _anular(c).json()["exige_nota_credito"] is False


# ── Las ventas del turno, para poder llegar a ellas ─────────────────────────

def test_listar_las_ventas_del_turno(entorno):
    """Hasta ahora la tirilla sólo se podía reimprimir mientras la pantalla del
    ticket siguiera abierta: ocho segundos. La clienta que vuelve media hora
    después con el papel borrado no tenía por dónde."""
    c, _, _ = entorno
    r = c.get("/api/retail/caja/ventas", params={"sesion_id": SESION})
    assert r.status_code == 200, r.text
    ventas = r.json()
    assert len(ventas) == 1
    assert ventas[0]["venta_id"] == VENTA
    assert ventas[0]["unidades"] == 2
    assert ventas[0]["total_centavos"] == PRECIO * 2
    assert ventas[0]["estado"] == "cerrada"
    assert len(ventas[0]["hora"]) == 5      # HH:MM en hora de la tienda


def test_la_anulada_sigue_LISTADA_con_su_motivo(entorno):
    """No desaparece: una venta que se esfuma de la lista es indistinguible de
    una que nunca existió, y eso es justo lo que hay que poder revisar."""
    c, _, entrar_como = entorno
    entrar_como("laura", "Laura M.")
    _anular(c)

    ventas = c.get("/api/retail/caja/ventas",
                   params={"sesion_id": SESION}).json()
    assert len(ventas) == 1
    assert ventas[0]["estado"] == "anulada"
    assert ventas[0]["motivo_anulacion"] == "cobrada dos veces por error"
