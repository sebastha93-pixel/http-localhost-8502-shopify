"""Tablero de las tiendas — todas, lado a lado, sólo para administradores.

Lo que estas pruebas cuidan es que el tablero no diga un número distinto al
del Panel y al del cierre: mismas ventas (sin las anuladas), mismo corte del
día, y el efectivo neto del vuelto.
"""
from __future__ import annotations

import asyncio
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

BOGOTA = timezone(timedelta(hours=-5))
SESIONES = {"florida": "01JQ8X4T5N6P7R8S9V0W1X2Y3Z",
            "arrayanes": "01JQ8X4T5N6P7R8S9V0W1X2Y4Z"}
VARIANTE = "01JQ8X4T5N6P001R8S9V0W1X2Y"
VARIANTE_2 = "01JQ8X4T5N6P002R8S9V0W1X2Y"


def _venta_id(n: int) -> str:
    return "01JQ8X4T5N7P%03dR8S9V0W1X2Y" % n


def _correr(co):
    return asyncio.get_event_loop().run_until_complete(co)


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
    semillas = []
    for tienda, nombre in (("florida", "Florida"), ("arrayanes", "Arrayanes")):
        caja = f"{tienda}_caja1"
        semillas += [
            ("INSERT INTO retail.tiendas (id,nombre,zona_horaria) "
             "VALUES (:t,:n,'America/Bogota')", {"t": tienda, "n": nombre}),
            ("INSERT INTO retail.cajas (id,tienda_id,nombre,prefijo_factura) "
             "VALUES (:c,:t,'Caja 1',:p)",
             {"c": caja, "t": tienda, "p": tienda[:3].upper()}),
            ("INSERT INTO retail.sesiones_caja "
             "(id,tienda_id,caja_id,numero_turno,base_inicial,abierta_por) "
             "VALUES (:s,:t,:c,1,20000000,'maria')",
             {"s": SESIONES[tienda], "t": tienda, "c": caja}),
            ("INSERT INTO retail.medios_pago "
             "(id,nombre,tipo,tienda_id,siigo_forma_pago_id,permite_vuelto) "
             "VALUES (:i,'Efectivo','efectivo',:t,1,true)",
             {"i": f"efectivo_{tienda}", "t": tienda}),
            ("INSERT INTO retail.medios_pago "
             "(id,nombre,tipo,tienda_id,siigo_forma_pago_id) "
             "VALUES (:i,'Datáfono','tarjeta',:t,2)",
             {"i": f"datafono_{tienda}", "t": tienda}),
        ]
    semillas += [
        ("INSERT INTO retail.variantes "
         "(id,sku,referencia,talla,nombre,color,precio_con_iva) "
         "VALUES (:v,'92611-1T10','92611-1','10','Jean Skinny','Azul',16990000)",
         {"v": VARIANTE}),
        ("INSERT INTO retail.variantes "
         "(id,sku,referencia,talla,nombre,color,precio_con_iva) "
         "VALUES (:v,'93100-2T4','93100-2','4','Falda Midi','Negro',13990000)",
         {"v": VARIANTE_2}),
        ("INSERT INTO retail.permisos_pos (usuario_id,nombre,rol,tiendas) "
         "VALUES ('maria','María Pérez','Cajera','{florida,arrayanes}')", {}),
    ]
    async with motor.begin() as c:
        for sql, p in semillas:
            await c.execute(text(sql), p)

    app = FastAPI()
    app.include_router(router)
    quien = {"rol": "admin"}
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id="jefe", email="j@male.com", nombre="Jefe", rol=quien["rol"],
        permisos={"retail": ["ver", "modificar"]})

    with TestClient(app) as c:
        yield c, motor, quien

    await motor.dispose()
    dependencias.reiniciar()
    revertir(URL)


async def _vender(motor, n: int, *, tienda: str, cuando: datetime, total: int,
                  pagos, vuelto: int = 0, estado: str = "cerrada",
                  cajera: str = "maria", variante: str = VARIANTE,
                  cantidad: int = 1):
    """La venta escrita directamente: aquí se prueba la LECTURA."""
    motivo = "prueba" if estado == "anulada" else None
    prefijo = tienda[:3].upper()
    async with motor.begin() as c:
        await c.execute(text("""
            INSERT INTO retail.ventas
                (id,numero,prefijo,consecutivo,tienda_id,caja_id,sesion_id,
                 cajera_id,estado,moneda,subtotal,descuento_total,total,pagado,
                 vuelto,cerrada_en,motivo_anulacion)
            VALUES (:i,:num,:pre,:c,:t,:caja,:s,:caj,:e,'COP',:tot,0,:tot,
                    :pag,:vue,:ts,:mot)
        """), {"i": _venta_id(n), "num": f"{prefijo}-{n}", "pre": prefijo,
               "c": n, "t": tienda, "caja": f"{tienda}_caja1",
               "s": SESIONES[tienda], "caj": cajera, "e": estado, "tot": total,
               "pag": total + vuelto, "vue": vuelto, "ts": cuando,
               "mot": motivo})
        await c.execute(text("""
            INSERT INTO retail.venta_lineas
                (id,venta_id,orden,variante_id,sku,descripcion,cantidad,
                 precio_unitario,descuento_monto,tasa_iva,base_gravable,
                 iva_monto,total_linea)
            VALUES (:i,:v,1,:var,'X','X',:cant,:p,0,19,:t,0,:t)
        """), {"i": _venta_id(n)[:22] + "0001", "v": _venta_id(n),
               "var": variante, "cant": cantidad, "p": total // cantidad,
               "t": total})
        for k, (medio, monto) in enumerate(pagos, start=1):
            await c.execute(text("""
                INSERT INTO retail.venta_pagos (id,venta_id,medio_pago_id,monto)
                VALUES (:i,:v,:m,:monto)
            """), {"i": _venta_id(n)[:22] + "9%03d" % k, "v": _venta_id(n),
                   "m": f"{medio}_{tienda}", "monto": monto})


def _tablero(c, **params):
    r = c.get("/api/retail/tablero", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def _hace_un_rato() -> datetime:
    """Un momento de HOY en Bogotá que ya pasó."""
    ahora = datetime.now(BOGOTA)
    inicio = ahora.replace(hour=0, minute=0, second=0, microsecond=0)
    return inicio + (ahora - inicio) / 2


def _tienda(d, tienda_id):
    return next(t for t in d["tiendas"] if t["id"] == tienda_id)


# ── Quién lo ve ─────────────────────────────────────────────────────────────

def test_solo_lo_ve_un_administrador(entorno):
    """Una cajera con permiso del POS ve SU panel, no el cruce de tiendas."""
    c, _, quien = entorno
    quien["rol"] = "user"
    r = c.get("/api/retail/tablero")
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "solo_administrador"


# ── Las tiendas lado a lado ─────────────────────────────────────────────────

def test_cada_tienda_con_lo_suyo_y_la_que_mas_vende_primero(entorno):
    c, motor, _ = entorno
    rato = _hace_un_rato()
    _correr(_vender(motor, 1, tienda="florida", cuando=rato, total=10000000,
                    pagos=[("datafono", 10000000)]))
    _correr(_vender(motor, 2, tienda="arrayanes", cuando=rato, total=30000000,
                    pagos=[("datafono", 30000000)], cantidad=2))
    _correr(_vender(motor, 3, tienda="arrayanes", cuando=rato, total=5000000,
                    pagos=[("datafono", 5000000)], estado="anulada"))

    d = _tablero(c)
    assert [t["id"] for t in d["tiendas"]] == ["arrayanes", "florida"]
    arr, flo = _tienda(d, "arrayanes"), _tienda(d, "florida")
    assert (arr["ventas_centavos"], arr["transacciones"], arr["unidades"]) == (
        30000000, 1, 2)
    # La anulada no es venta: se cuenta aparte, como en el Panel.
    assert (arr["anuladas"], arr["monto_anulado_centavos"]) == (1, 5000000)
    assert (flo["ventas_centavos"], flo["ticket_promedio_centavos"]) == (
        10000000, 10000000)
    assert arr["cajeras"] == [{"nombre": "María Pérez",
                               "ventas_centavos": 30000000, "transacciones": 1}]
    assert arr["turnos_abiertos"][0]["abierta_por"] == "María Pérez"


def test_una_tienda_sin_ventas_sigue_en_el_tablero(entorno):
    """Que una tienda no haya vendido es justo lo que hay que ver."""
    c, motor, _ = entorno
    _correr(_vender(motor, 1, tienda="florida", cuando=_hace_un_rato(),
                    total=10000000, pagos=[("datafono", 10000000)]))
    d = _tablero(c)
    arr = _tienda(d, "arrayanes")
    assert (arr["ventas_centavos"], arr["transacciones"], arr["ultima_venta"]) == (
        0, 0, "")


# ── La plata ────────────────────────────────────────────────────────────────

def test_el_efectivo_va_neto_del_vuelto_y_el_pago_mixto_se_reparte(entorno):
    """$100.000 de venta: $40.000 al datáfono y un billete de $100.000.
    Entran $60.000 en efectivo; los otros $40.000 del billete son vuelto."""
    c, motor, _ = entorno
    _correr(_vender(motor, 1, tienda="florida", cuando=_hace_un_rato(),
                    total=10000000, vuelto=4000000,
                    pagos=[("datafono", 4000000), ("efectivo", 10000000)]))
    medios = {m["nombre"]: m["centavos"] for m in _tienda(_tablero(c), "florida")["medios"]}
    assert medios == {"Efectivo": 6000000, "Datáfono": 4000000}
    # Los medios suman exactamente lo vendido: ni un peso de más por el vuelto.
    assert sum(medios.values()) == 10000000


# ── El tiempo ───────────────────────────────────────────────────────────────

def test_ayer_no_es_hoy_y_el_rango_trae_todos_los_dias(entorno):
    c, motor, _ = entorno
    rato = _hace_un_rato()
    _correr(_vender(motor, 1, tienda="florida", cuando=rato, total=10000000,
                    pagos=[("datafono", 10000000)]))
    _correr(_vender(motor, 2, tienda="florida", cuando=rato - timedelta(days=2),
                    total=7000000, pagos=[("datafono", 7000000)]))

    hoy = _tablero(c)
    assert _tienda(hoy, "florida")["ventas_centavos"] == 10000000
    assert hoy["serie_por"] == "hora"

    desde = (rato - timedelta(days=2)).date().isoformat()
    rango = _tablero(c, desde=desde, hasta=hoy["hoy"])
    assert _tienda(rango, "florida")["ventas_centavos"] == 17000000
    assert rango["serie_por"] == "dia"
    # Tres días, y el del medio —sin ventas— también está.
    assert [p["tiendas"].get("florida", 0) for p in rango["serie"]] == [
        7000000, 0, 10000000]


def test_ayer_se_compara_solo_hasta_esta_misma_hora(entorno):
    """A media mañana, «ayer» es lo vendido ayer HASTA media mañana. Contar
    el día entero de ayer haría que todas las mañanas parecieran malas."""
    c, motor, _ = entorno
    ahora = datetime.now(BOGOTA)
    inicio_ayer = (ahora - timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0)
    antes = inicio_ayer + (ahora - timedelta(days=1) - inicio_ayer) / 2
    fin_ayer = inicio_ayer.replace(hour=23, minute=59, second=59)
    _correr(_vender(motor, 1, tienda="florida", cuando=antes, total=8000000,
                    pagos=[("datafono", 8000000)]))
    if fin_ayer > ahora - timedelta(days=1) + timedelta(minutes=2):
        _correr(_vender(motor, 2, tienda="florida", cuando=fin_ayer,
                        total=5000000, pagos=[("datafono", 5000000)]))

    d = _tablero(c)
    assert d["anterior_cortado"] is True
    assert _tienda(d, "florida")["ventas_anterior_centavos"] == 8000000

    # Un periodo ya cerrado (ayer) se compara contra su día anterior COMPLETO.
    ayer = (ahora - timedelta(days=1)).date().isoformat()
    assert _tablero(c, desde=ayer, hasta=ayer)["anterior_cortado"] is False


# ── Lo que se está vendiendo ────────────────────────────────────────────────

def test_lo_mas_vendido_dice_en_que_tienda_se_vendio(entorno):
    c, motor, _ = entorno
    rato = _hace_un_rato()
    _correr(_vender(motor, 1, tienda="florida", cuando=rato, total=16990000,
                    pagos=[("datafono", 16990000)]))
    _correr(_vender(motor, 2, tienda="arrayanes", cuando=rato, total=33980000,
                    pagos=[("datafono", 33980000)], cantidad=2))
    _correr(_vender(motor, 3, tienda="arrayanes", cuando=rato, total=13990000,
                    pagos=[("datafono", 13990000)], variante=VARIANTE_2))

    vendidos = _tablero(c)["mas_vendidos"]
    assert [(m["referencia"], m["unidades"]) for m in vendidos] == [
        ("92611-1", 3), ("93100-2", 1)]
    assert vendidos[0]["tiendas"] == {"florida": 1, "arrayanes": 2}


# ── Cambios, devoluciones y anuladas ────────────────────────────────────────

async def _devolver(motor, n: int, *, venta: int, tienda: str, total: int,
                    reembolso: str, cuando: datetime, motivo: str = "talla"):
    """La devolución escrita directamente, como `_vender`: se prueba la
    lectura. La de efectivo lleva turno porque el esquema lo exige."""
    async with motor.begin() as c:
        await c.execute(text("""
            INSERT INTO retail.devoluciones
                (id,venta_id,numero_venta,tienda_id,caja_id,sesion_id,
                 usuario_id,motivo,reembolso,total,unidades,creada_en)
            VALUES (:i,:v,:num,:t,:caja,:s,'maria',:mot,:r,:tot,1,:ts)
        """), {"i": "01JQ8X4T5N8P%03dR8S9V0W1X2Y" % n, "v": _venta_id(venta),
               "num": f"{tienda[:3].upper()}-{venta}", "t": tienda,
               "caja": f"{tienda}_caja1",
               "s": SESIONES[tienda] if reembolso == "efectivo" else None,
               "mot": motivo, "r": reembolso, "tot": total, "ts": cuando})


def test_un_cambio_no_es_plata_devuelta(entorno):
    """Crédito de tienda: la clienta se lleva otra prenda y de la caja no sale
    nada. Contarlo como «devuelto» hacía leer plata que nunca salió."""
    c, motor, _ = entorno
    rato = _hace_un_rato()
    _correr(_vender(motor, 1, tienda="florida", cuando=rato - timedelta(days=3),
                    total=17490000, pagos=[("datafono", 17490000)]))
    _correr(_vender(motor, 2, tienda="florida", cuando=rato - timedelta(days=3),
                    total=5000000, pagos=[("efectivo", 5000000)]))
    _correr(_devolver(motor, 1, venta=1, tienda="florida", total=17490000,
                      reembolso="credito_tienda", cuando=rato))
    _correr(_devolver(motor, 2, venta=2, tienda="florida", total=5000000,
                      reembolso="efectivo", cuando=rato + timedelta(seconds=1),
                      motivo="defecto"))

    d = _tablero(c)
    flo = _tienda(d, "florida")
    assert (flo["cambios"], flo["monto_cambios_centavos"]) == (1, 17490000)
    assert (flo["reembolsos"], flo["monto_reembolsado_centavos"]) == (1, 5000000)
    # El total de lo que entró por «Cambios» sigue siendo la suma de los dos.
    assert (flo["devoluciones"], flo["monto_devuelto_centavos"]) == (2, 22490000)

    # El detalle: lo más reciente primero, con quién lo hizo y sin la clienta.
    assert [(x["numero_venta"], x["reembolso"], x["motivo"], x["total_centavos"],
             x["quien"], x["tienda"]) for x in d["detalle_devoluciones"]] == [
        ("FLO-2", "efectivo", "defecto", 5000000, "María Pérez", "Florida"),
        ("FLO-1", "credito_tienda", "talla", 17490000, "María Pérez", "Florida"),
    ]
    assert set(d["detalle_devoluciones"][0]) == {
        "cuando", "tienda_id", "tienda", "numero_venta", "motivo", "reembolso",
        "total_centavos", "unidades", "quien"}


def test_el_detalle_de_anuladas_trae_el_motivo(entorno):
    c, motor, _ = entorno
    _correr(_vender(motor, 1, tienda="arrayanes", cuando=_hace_un_rato(),
                    total=5000000, pagos=[("datafono", 5000000)],
                    estado="anulada"))
    d = _tablero(c)
    assert [(x["numero"], x["tienda"], x["total_centavos"], x["motivo"])
            for x in d["detalle_anuladas"]] == [
        ("ARR-1", "Arrayanes", 5000000, "prueba")]
    # Una venta de ayer anulada no aparece en el detalle de hoy.
    assert _tablero(c, desde="2020-01-01", hasta="2020-01-02")[
        "detalle_anuladas"] == []
