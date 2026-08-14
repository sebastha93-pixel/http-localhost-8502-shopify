"""Los medios de pago salen de la TIENDA, no de una lista en el código.

LO QUE HABÍA DEBAJO DE «faltan Addi, Sumas y el QR de Wompi»:

**Con tarjeta no se podía cobrar.** La pantalla mandaba `datafono_florida` y en
la base el medio se llama `datafono`. La llave foránea lo rechazaba con un
error de base de datos que en pantalla no dice nada. Las ocho ventas de prueba
fueron en efectivo, por eso nunca saltó — y por eso la primera prueba de este
archivo es ésa.

**La lista estaba quemada en el frontend**, así que `activo`, `orden`,
`entra_al_arqueo` y `exige_referencia` no los leía nadie: la tabla era
decorativa y añadir un medio era tocar código.
"""
from __future__ import annotations

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
VARIANTE = "01JQ8X4T5N6P7R8S9V0W1X2Y42"
UBICACION = "tienda:florida"
PRECIO = 16990000


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
            f"INSERT INTO retail.ubicaciones (id,tipo,nombre,tienda_id) "
            f"VALUES ('{UBICACION}','tienda','Florida','florida')",
            "INSERT INTO retail.medios_pago (id,nombre,tipo,siigo_forma_pago_id,"
            " permite_vuelto,orden) VALUES ('efectivo','Efectivo','efectivo',12243,true,1)",
            "INSERT INTO retail.medios_pago (id,nombre,tipo,siigo_forma_pago_id,"
            " exige_referencia,orden) VALUES ('datafono','Tarjeta','tarjeta',12244,true,2)",
            # wompi_qr, addi y sumas NO se siembran aquí: los trae la
            # migración 0015. Así la prueba comprueba lo que de verdad va a
            # haber en la tienda, no una copia mía de lo que creo que hay.
            "INSERT INTO retail.medios_pago (id,nombre,tipo,exige_referencia,orden,activo)"
            " VALUES ('viejo','Un medio dado de baja','otro',false,9,false)",
            f"INSERT INTO retail.variantes (id,sku,referencia,talla,nombre,"
            f"precio_con_iva) VALUES ('{VARIANTE}','92611-1T10','92611-1','10','Jean',{PRECIO})",
            f"INSERT INTO retail.stock_ubicacion (ubicacion_id,variante_id,cantidad)"
            f" VALUES ('{UBICACION}','{VARIANTE}',50)",
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
        t = c.post("/api/retail/caja/turno", json={
            "sesion_id": SESION, "tienda_id": "florida",
            "caja_id": "florida_caja1"})
        assert t.status_code == 200, t.text
        yield c, motor, t.json()

    await motor.dispose()
    dependencias.reiniciar()
    revertir(URL)


def vender(c, turno, pagos, venta_id="01JQ8X4T5N7V001R8S9V0W1X2Y"):
    return c.post("/api/retail/ventas/cerrar", json={
        "venta_id": venta_id,
        "numero": f"FV-20-{turno['consecutivo_siguiente']}",
        "tienda_id": "florida", "caja_id": "florida_caja1",
        "sesion_id": SESION, "ubicacion_id": UBICACION,
        "lineas": [{"sku": "92611-1T10", "cantidad": 1,
                    "precio_unitario_centavos": PRECIO,
                    "descripcion": "Jean · 10"}],
        "pagos": pagos})


# ── EL BUG QUE ESTABA VIVO ──────────────────────────────────────────────────

def test_un_medio_que_no_existe_se_rechaza_CON_UN_MENSAJE(entorno):
    """La pantalla mandaba `datafono_florida` y en la base el id es `datafono`:
    TODO cobro con tarjeta fallaba. Lo hacía la llave foránea, con un error de
    base de datos que en pantalla no dice nada — y nadie lo notó porque todas
    las ventas de prueba fueron en efectivo."""
    c, _, turno = entorno
    r = vender(c, turno, [{"medio_pago_id": "datafono_florida",
                           "monto_centavos": PRECIO, "es_efectivo": False}])
    assert r.status_code == 400
    assert "datafono_florida" in r.json()["detail"]["mensaje"]
    assert "no tiene" in r.json()["detail"]["mensaje"]


def test_con_tarjeta_SE_PUEDE_COBRAR(entorno):
    c, _, turno = entorno
    r = vender(c, turno, [{"medio_pago_id": "datafono", "monto_centavos": PRECIO,
                           "es_efectivo": False, "referencia": "APR-884511"}])
    assert r.status_code == 200, r.text


# ── La lista sale de la tienda ──────────────────────────────────────────────

def test_los_medios_viajan_con_el_contexto(entorno):
    """Van con lo que el equipo ya guarda: una venta con Addi o con QR hay que
    poder cobrarla también cuando se cayó el internet de la tienda."""
    c, _, _ = entorno
    d = c.get("/api/retail/caja/contexto",
              params={"caja_id": "florida_caja1"}).json()
    ids = [m["id"] for m in d["medios_pago"]]
    assert ids == ["efectivo", "datafono", "wompi_qr", "addi", "sumas"]
    assert "viejo" not in ids                                    # `activo=false`


def test_solo_el_efectivo_da_vuelto(entorno):
    """Cobrar de más en un datáfono o en Addi es un error de digitación que
    aparecería como sobrante en el arqueo sin saber de dónde salió."""
    c, _, _ = entorno
    d = c.get("/api/retail/caja/contexto",
              params={"caja_id": "florida_caja1"}).json()
    con_vuelto = [m["id"] for m in d["medios_pago"] if m["permite_vuelto"]]
    assert con_vuelto == ["efectivo"]


def test_dice_cuales_NO_pueden_facturar_todavia(entorno):
    """Un medio sin forma de pago de Siigo se cobra igual —la caja nunca se
    bloquea por Siigo, ADR-002— pero quien cobra tiene derecho a saber que ese
    documento va a quedar esperando, en vez de descubrirlo cuando la clienta
    reclame la factura."""
    c, _, _ = entorno
    d = c.get("/api/retail/caja/contexto",
              params={"caja_id": "florida_caja1"}).json()
    listas = {m["id"]: m["factura_lista"] for m in d["medios_pago"]}
    assert listas == {"efectivo": True, "datafono": True, "wompi_qr": False,
                      "addi": False, "sumas": False}


# ── LA REFERENCIA, que estaba muerta desde la migración 0001 ────────────────

def test_sin_numero_de_aprobacion_no_pasa(entorno):
    """`exige_referencia` existía desde 0001 y no lo leía nadie. Es el único
    hilo que une una línea del POS con una del informe de Addi: sin él, cuadrar
    el día es comparar dos totales y encogerse de hombros cuando no dan."""
    c, _, turno = entorno
    r = vender(c, turno, [{"medio_pago_id": "addi", "monto_centavos": PRECIO,
                           "es_efectivo": False}])
    assert r.status_code == 400
    assert "aprobación" in r.json()["detail"]["mensaje"]
    assert "Addi" in r.json()["detail"]["mensaje"]


def test_una_referencia_en_blanco_tampoco(entorno):
    """Espacios no son una referencia. Aceptarlos deja la fila con algo que
    parece un dato y no sirve para cuadrar nada."""
    c, _, turno = entorno
    r = vender(c, turno, [{"medio_pago_id": "addi", "monto_centavos": PRECIO,
                           "es_efectivo": False, "referencia": "   "}])
    assert r.status_code == 400


def test_con_referencia_pasa_Y_SE_GUARDA(entorno):
    """Guardarla es el punto: si se validara y se tirara, la validación sería
    un trámite."""
    c, motor, turno = entorno
    r = vender(c, turno, [{"medio_pago_id": "addi", "monto_centavos": PRECIO,
                           "es_efectivo": False, "referencia": "ADDI-99120"}])
    assert r.status_code == 200, r.text

    import asyncio

    async def leer():
        async with motor.connect() as cn:
            return (await cn.execute(text(
                "SELECT referencia FROM retail.venta_pagos "
                " WHERE medio_pago_id='addi'"))).scalar()

    assert asyncio.get_event_loop().run_until_complete(leer()) == "ADDI-99120"


def test_el_efectivo_no_pide_referencia(entorno):
    """Un billete no trae número de aprobación. Pedirlo entrenaría a la cajera
    a escribir cualquier cosa, que es como se mata un control."""
    c, _, turno = entorno
    r = vender(c, turno, [{"medio_pago_id": "efectivo",
                           "monto_centavos": PRECIO, "es_efectivo": True}])
    assert r.status_code == 200, r.text


# ── Financiación: ni efectivo ni crédito de la tienda ───────────────────────

def test_addi_NO_entra_al_conteo_de_efectivo(entorno):
    """Addi no pone plata en el cajón. Si contara como efectivo, el arqueo
    pediría contar $169.900 que no están y la cajera cerraría con un faltante
    que no existe."""
    c, _, turno = entorno
    vender(c, turno, [{"medio_pago_id": "addi", "monto_centavos": PRECIO,
                       "es_efectivo": False, "referencia": "ADDI-1"}])
    d = c.get("/api/retail/caja/cierre/resumen",
              params={"sesion_id": SESION}).json()
    addi = next(m for m in d["medios"] if m["medio_pago_id"] == "addi")
    assert addi["es_efectivo"] is False


def test_pero_SI_HAY_QUE_DECLARARLO(entorno):
    """Y aquí se separa de un crédito a 30 días. En el crédito el riesgo lo
    lleva MALE y no hay nada que cuadrar. Con Addi el tercero ya aprobó y
    entrega un informe diario: si no se declara, una venta que el POS registró
    y que Addi nunca aprobó no la descubre nadie."""
    c, _, turno = entorno
    vender(c, turno, [{"medio_pago_id": "addi", "monto_centavos": PRECIO,
                       "es_efectivo": False, "referencia": "ADDI-1"}])
    d = c.get("/api/retail/caja/cierre/resumen",
              params={"sesion_id": SESION}).json()
    addi = next(m for m in d["medios"] if m["medio_pago_id"] == "addi")
    assert addi["entra_al_arqueo"] is True


def test_se_puede_pagar_MITAD_Addi_MITAD_efectivo(entorno):
    """Es el caso normal de la financiación en una tienda: el cupo aprobado no
    cubre todo y la clienta completa con un billete."""
    c, _, turno = entorno
    mitad = PRECIO // 2
    r = vender(c, turno, [
        {"medio_pago_id": "addi", "monto_centavos": mitad,
         "es_efectivo": False, "referencia": "ADDI-7788"},
        {"medio_pago_id": "efectivo", "monto_centavos": PRECIO - mitad,
         "es_efectivo": True}])
    assert r.status_code == 200, r.text


# ── PAGO MIXTO ──────────────────────────────────────────────────────────────
#
# El dominio siempre lo aceptó —`Venta` tiene `saldo()`, `vuelto()` e INV-V3—
# pero la pantalla mandaba un solo pago. Con Addi eso deja de ser un detalle:
# el cupo aprobado casi nunca cubre la compra entera. Sin pago mixto la cajera
# tendría que partir la venta en dos tiquetes, y entonces el inventario, la
# numeración y la factura cuentan dos ventas donde hubo una.

def test_el_vuelto_sale_del_efectivo(entorno):
    """Addi $100.000 + un billete de $100.000 sobre una venta de $169.900. El
    excedente entró en efectivo, así que se puede devolver."""
    c, _, turno = entorno
    r = vender(c, turno, [
        {"medio_pago_id": "addi", "monto_centavos": 10000000,
         "es_efectivo": False, "referencia": "ADDI-55120"},
        {"medio_pago_id": "efectivo", "monto_centavos": 10000000,
         "es_efectivo": True}])
    assert r.status_code == 200, r.text
    assert r.json()["vuelto_centavos"] == 20000000 - PRECIO


def test_un_excedente_MAYOR_QUE_EL_EFECTIVO_se_rechaza(entorno):
    """INV-V3, y la regla exacta importa: el vuelto no sale «del efectivo de
    este pago», sale del efectivo que hay en el cajón. $10.000 en billetes no
    pueden devolver $30.100, así que esta venta no cierra.

    (Escribí antes esta prueba con $50.000 en efectivo esperando un rechazo, y
    el código tenía razón: con $50.000 el cajón SÍ puede devolver $30.100.)
    """
    c, _, turno = entorno
    r = vender(c, turno, [
        {"medio_pago_id": "efectivo", "monto_centavos": 1000000,
         "es_efectivo": True},
        {"medio_pago_id": "addi", "monto_centavos": 19000000,
         "es_efectivo": False, "referencia": "ADDI-9"}])
    assert r.status_code == 400
    assert "vuelto" in r.json()["detail"]["mensaje"]


def test_pero_si_el_efectivo_ALCANZA_para_el_vuelto_sí_pasa(entorno):
    """El otro lado de la misma regla, para que quede escrito por qué no es
    «el excedente tiene que ser de la línea de efectivo»."""
    c, _, turno = entorno
    r = vender(c, turno, [
        {"medio_pago_id": "efectivo", "monto_centavos": 5000000,
         "es_efectivo": True},
        {"medio_pago_id": "addi", "monto_centavos": 15000000,
         "es_efectivo": False, "referencia": "ADDI-9"}])
    assert r.status_code == 200, r.text
    assert r.json()["vuelto_centavos"] == 20000000 - PRECIO


def test_si_entre_los_dos_no_alcanza_tampoco(entorno):
    """El otro lado de INV-V3, y el que de verdad cuesta plata: cerrar una
    venta cobrando de menos."""
    c, _, turno = entorno
    r = vender(c, turno, [
        {"medio_pago_id": "addi", "monto_centavos": 5000000,
         "es_efectivo": False, "referencia": "ADDI-3"},
        {"medio_pago_id": "efectivo", "monto_centavos": 5000000,
         "es_efectivo": True}])
    assert r.status_code == 400
    assert "falta cobrar" in r.json()["detail"]["mensaje"].lower()


def test_cada_pago_exige_SU_referencia(entorno):
    """Que uno de los dos la traiga no cubre al otro: son dos cobros distintos
    en dos informes distintos."""
    c, _, turno = entorno
    r = vender(c, turno, [
        {"medio_pago_id": "addi", "monto_centavos": 10000000,
         "es_efectivo": False, "referencia": "ADDI-1"},
        {"medio_pago_id": "datafono", "monto_centavos": 6990000,
         "es_efectivo": False}])
    assert r.status_code == 400
    assert "Tarjeta" in r.json()["detail"]["mensaje"]


def test_la_tirilla_muestra_LOS_DOS_pagos_con_su_referencia(entorno):
    """Es el comprobante de la clienta: si sólo saliera uno, quien pagó mitad
    y mitad no tiene con qué demostrar la otra mitad."""
    c, _, turno = entorno
    venta = "01JQ8X4T5N7V001R8S9V0W1X2Y"
    vender(c, turno, [
        {"medio_pago_id": "addi", "monto_centavos": 10000000,
         "es_efectivo": False, "referencia": "ADDI-55120"},
        {"medio_pago_id": "efectivo", "monto_centavos": 6990000,
         "es_efectivo": True}], venta_id=venta)

    t = c.get(f"/api/retail/ventas/{venta}/tirilla").json()
    assert [(p["nombre"], p["monto_centavos"]) for p in t["pagos"]] == [
        ("Addi", 10000000), ("Efectivo", 6990000)]
    assert t["pagos"][0]["referencia"] == "ADDI-55120"
