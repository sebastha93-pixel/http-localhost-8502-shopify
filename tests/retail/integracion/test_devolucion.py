"""Devolver una venta de otro día — vista 5 del handoff.

CUATRO ESCRITURAS Y UNA COLA, en una sola transacción: la devolución queda
escrita, la prenda vuelve al stock, la plata sale del arqueo si el reembolso
es en efectivo, queda constancia crítica, y se encola el caso que emitirá la
NOTA CRÉDITO —que la emite Postventa, no este módulo—.

Lo que se prueba aquí y no en el dominio: que el SQL escribe lo que dice, que
el movimiento de caja lleva el MEDIO DE EFECTIVO (sin él el arqueo pediría
plata que ya se entregó) y que el saldo de lo ya devuelto se lee de verdad de
la base entre dos peticiones distintas — que es el caso de la clienta que
vuelve por segunda vez.
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

SESION = "01JQ8X4T5N6P002R8S9V0W1X2Y"
VENTA = "01JQ8X4T5N7V002R8S9V0W1X2Y"
VARIANTE = "01JQ8X4T5N6P7R8S9V0W1X2Y43"
UBICACION = "tienda:florida"
PRECIO = 10_000_000          # $100.000
STOCK = 50
BASE = 20_000_000
NUMERO = "FV-20-1"


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
        ("INSERT INTO retail.permisos_pos (usuario_id,nombre,tiendas) "
         "VALUES ('maria','María R.','{florida}')", {}),
        # Laura sí puede anular. Hace falta para poder llevar una venta al
        # estado «anulada» y comprobar que ahí ya no se devuelve.
        ("INSERT INTO retail.permisos_pos "
         "(usuario_id,nombre,tiendas,puede_anular_venta) "
         "VALUES ('laura','Laura M.','{florida}',true)", {}),
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
        # Una venta de 3 unidades pagada en efectivo. TRES y no una: lo que
        # hay que poder probar es la devolución PARCIAL, que es donde vive el
        # riesgo de pagar dos veces la misma prenda.
        r = c.post("/api/retail/ventas/cerrar", json={
            "venta_id": VENTA, "numero": NUMERO,
            "tienda_id": "florida", "caja_id": "florida_caja1",
            "sesion_id": SESION, "ubicacion_id": UBICACION,
            "lineas": [{"sku": "92611-1T10", "cantidad": 3,
                        "precio_unitario_centavos": PRECIO,
                        "descripcion": "Jean · 10"}],
            "pagos": [{"medio_pago_id": "efectivo",
                       "monto_centavos": PRECIO * 3, "es_efectivo": True}]})
        assert r.status_code == 200, r.text
        yield c, motor, entrar_como

    await motor.dispose()
    dependencias.reiniciar()
    revertir(URL)


def _leer(motor, sql, params=None):
    async def ir():
        async with motor.connect() as cn:
            return (await cn.execute(text(sql), params or {})).first()
    return asyncio.get_event_loop().run_until_complete(ir())


def _devolver(c, *, cantidad=1, motivo="talla", reembolso="efectivo",
              devolucion_id="01JQ8X4T5N7D001R8S9V0W1X2Y"):
    return c.post("/api/retail/devoluciones", json={
        "devolucion_id": devolucion_id, "venta_id": VENTA,
        "seleccion": {"92611-1T10": cantidad},
        "motivo": motivo, "reembolso": reembolso})


# ── Buscar el ticket ────────────────────────────────────────────────────────

def test_el_ticket_se_busca_por_el_numero_del_papel(entorno):
    """Lo que la clienta trae en la mano es la tirilla, y ahí está `FV-20-1`.
    Pedirle el ULID de 26 caracteres no es una opción."""
    c, _, _ = entorno
    r = c.get(f"/api/retail/devoluciones/ticket/{NUMERO}")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["numero"] == NUMERO
    assert d["venta_id"] == VENTA
    assert len(d["lineas"]) == 1
    assert d["lineas"][0]["cantidad_vendida"] == 3
    assert d["lineas"][0]["cantidad_devolvible"] == 3
    assert d["lineas"][0]["talla"] == "10"


def test_un_ticket_que_no_existe_lo_dice(entorno):
    c, _, _ = entorno
    assert c.get("/api/retail/devoluciones/ticket/FV-20-999").status_code == 404


def test_dice_si_se_puede_devolver_en_efectivo(entorno):
    """Con turno abierto sí. La pantalla lo usa para apagar la opción ANTES de
    que la cajera la elija, en vez de fallar al confirmar."""
    c, _, _ = entorno
    assert c.get(f"/api/retail/devoluciones/ticket/{NUMERO}").json()["puede_efectivo"]


# ── Las cuatro escrituras ───────────────────────────────────────────────────

def test_devolver_escribe_repone_stock_y_saca_la_plata(entorno):
    c, motor, _ = entorno

    stock_antes = _leer(motor, "SELECT cantidad FROM retail.stock_ubicacion "
                               " WHERE ubicacion_id=:u AND variante_id=:v",
                        {"u": UBICACION, "v": VARIANTE}).cantidad
    assert stock_antes == STOCK - 3

    r = _devolver(c, cantidad=1)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["total_centavos"] == PRECIO
    assert d["unidades"] == 1
    assert d["salio_del_cajon"] is True

    # 1 · La devolución, con su IVA separado para la nota crédito.
    fila = _leer(motor, "SELECT total, iva_total, base_gravable, motivo, "
                        "       reembolso, unidades, sesion_id "
                        "  FROM retail.devoluciones WHERE venta_id=:v",
                 {"v": VENTA})
    assert fila.total == PRECIO
    assert fila.base_gravable + fila.iva_total == PRECIO
    assert fila.motivo == "talla"
    assert fila.reembolso == "efectivo"
    assert fila.sesion_id == SESION

    # 2 · La prenda volvió al saldo.
    stock = _leer(motor, "SELECT cantidad FROM retail.stock_ubicacion "
                         " WHERE ubicacion_id=:u AND variante_id=:v",
                  {"u": UBICACION, "v": VARIANTE}).cantidad
    assert stock == stock_antes + 1

    # 3 · La plata salió del arqueo, CON el medio de efectivo. Sin el medio, el
    #     movimiento no cuenta para el esperado y el cierre pediría una plata
    #     que la cajera ya entregó.
    mov = _leer(motor, "SELECT monto, tipo, medio_pago_id FROM retail.movimientos_caja "
                       " WHERE sesion_id=:s AND tipo='devolucion'", {"s": SESION})
    assert mov.monto == -PRECIO
    assert mov.medio_pago_id == "efectivo"

    # 4 · Constancia crítica.
    aud = _leer(motor, "SELECT severidad, evento FROM retail.auditoria "
                       " WHERE evento='venta.devuelta'")
    assert aud.severidad == "critico"

    # 5 · Y el caso que emitirá la nota crédito, ENCOLADO — no llamado en
    #     línea: la clienta no espera en el mostrador a un sistema de terceros.
    out = _leer(motor, "SELECT tipo, agregado_tipo FROM retail.outbox "
                       " WHERE tipo='abrir_caso_postventa'")
    assert out is not None
    assert out.agregado_tipo == "devolucion"


def test_el_efectivo_esperado_baja_lo_devuelto(entorno):
    """La consecuencia que de verdad importa: el arqueo del turno tiene que
    pedir menos plata después de la devolución. Es lo que hoy NO pasa —
    `postventa_caja.py` existe porque la cajera tiene que sumarlo a mano.

    Se mide sumando los movimientos del medio de efectivo y no leyendo el
    resumen del cierre: el resumen esconde el esperado cuando el cierre es
    ciego (INV-C4), así que una aserción sobre él probaría el permiso de quien
    mira en vez de la plata. Esta suma ES la fórmula del esperado
    (`SesionCaja._calcular`), y sale igual para todo el mundo.
    """
    c, motor, _ = entorno
    antes = _leer(motor, "SELECT coalesce(sum(monto),0) AS n "
                         "  FROM retail.movimientos_caja "
                         " WHERE sesion_id=:s AND medio_pago_id='efectivo'",
                  {"s": SESION}).n

    assert _devolver(c, cantidad=1).status_code == 200

    despues = _leer(motor, "SELECT coalesce(sum(monto),0) AS n "
                           "  FROM retail.movimientos_caja "
                           " WHERE sesion_id=:s AND medio_pago_id='efectivo'",
                    {"s": SESION}).n
    assert despues == antes - PRECIO


# ── La segunda visita ───────────────────────────────────────────────────────

def test_lo_ya_devuelto_baja_el_tope_del_ticket(entorno):
    c, _, _ = entorno
    assert _devolver(c, cantidad=2).status_code == 200

    d = c.get(f"/api/retail/devoluciones/ticket/{NUMERO}").json()
    linea = d["lineas"][0]
    assert linea["cantidad_vendida"] == 3
    assert linea["cantidad_devuelta"] == 2
    assert linea["cantidad_devolvible"] == 1


def test_no_se_devuelve_dos_veces_la_misma_prenda(entorno):
    """El caso que justifica todo: la clienta vuelve y pide devolver lo que ya
    devolvió. Si esto pasa, se le paga dos veces y entran al stock dos
    unidades que sólo salieron una vez."""
    c, _, _ = entorno
    assert _devolver(c, cantidad=3).status_code == 200

    r = _devolver(c, cantidad=1, devolucion_id="01JQ8X4T5N7D002R8S9V0W1X2Y")
    assert r.status_code == 400
    assert "ya se devolvió completa" in r.json()["detail"]["mensaje"]


def test_reintentar_la_misma_devolucion_no_la_duplica(entorno):
    """Mostrador con mala señal: la cajera pulsa dos veces. El id lo genera el
    dispositivo, así que la segunda es la MISMA devolución, no otra."""
    c, motor, _ = entorno
    assert _devolver(c, cantidad=1).status_code == 200
    assert _devolver(c, cantidad=1).status_code == 409

    n = _leer(motor, "SELECT count(*) AS n FROM retail.devoluciones "
                     " WHERE venta_id=:v", {"v": VENTA}).n
    assert n == 1


# ── Los reembolsos que NO tocan el cajón ────────────────────────────────────

def test_credito_en_tienda_no_mueve_la_caja(entorno):
    c, motor, _ = entorno
    r = _devolver(c, cantidad=1, reembolso="credito_tienda")
    assert r.status_code == 200
    assert r.json()["salio_del_cajon"] is False

    assert _leer(motor, "SELECT count(*) AS n FROM retail.movimientos_caja "
                        " WHERE sesion_id=:s AND tipo='devolucion'",
                 {"s": SESION}).n == 0
    # Y la prenda SÍ vuelve al stock: que no salga plata no significa que la
    # prenda se quede con la clienta.
    assert _leer(motor, "SELECT cantidad FROM retail.stock_ubicacion "
                        " WHERE ubicacion_id=:u AND variante_id=:v",
                 {"u": UBICACION, "v": VARIANTE}).cantidad == STOCK - 2


def test_un_motivo_inventado_se_rechaza(entorno):
    c, _, _ = entorno
    r = _devolver(c, motivo="porque si")
    assert r.status_code == 400
    assert "motivo de devolución válido" in r.json()["detail"]["mensaje"]


def test_no_se_devuelve_una_venta_anulada(entorno):
    """Anular ya deshizo la venta entera y su plata volvió por el arqueo.
    Devolverla encima sería pagar dos veces la misma prenda."""
    c, _, entrar_como = entorno
    entrar_como("laura", "Laura M.")
    r = c.post(f"/api/retail/ventas/{VENTA}/anular",
               json={"motivo": "cobrada dos veces por error"})
    assert r.status_code == 200, r.text

    r = _devolver(c, cantidad=1)
    assert r.status_code == 400
    assert "anulada" in r.json()["detail"]["mensaje"]
