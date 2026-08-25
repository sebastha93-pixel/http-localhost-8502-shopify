"""Consulta de inventario — vista 6.

Lo único que tiene que ser cierto: **el número que se ve es el que se puede
vender**. Un inventario que dice 3 cuando hay 1 no es un inventario impreciso,
es una promesa rota en el mostrador.
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

FLORIDA = "tienda:florida"
ARRAYANES = "tienda:arrayanes"
BODEGA = "bodega:central"


def _var(n: int) -> str:
    return "01JQ8X4T5N6P%03dR8S9V0W1X2Y" % n


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
        ("INSERT INTO retail.tiendas (id,nombre,umbral_stock_bajo) "
         "VALUES ('florida','Florida',8)", {}),
        ("INSERT INTO retail.tiendas (id,nombre) "
         "VALUES ('arrayanes','Arrayanes')", {}),
        ("INSERT INTO retail.ubicaciones (id,tipo,nombre,tienda_id) "
         "VALUES (:u,'tienda','Florida','florida')", {"u": FLORIDA}),
        ("INSERT INTO retail.ubicaciones (id,tipo,nombre,tienda_id) "
         "VALUES (:u,'tienda','Arrayanes','arrayanes')", {"u": ARRAYANES}),
        ("INSERT INTO retail.ubicaciones (id,tipo,nombre) "
         "VALUES (:u,'bodega','Central')", {"u": BODEGA}),
    ]
    # Una referencia con tallas 4, 6, 10 — NO el tallaje del prototipo.
    tallas = {1: "4", 2: "6", 3: "10"}
    for n, talla in tallas.items():
        semillas.append((
            "INSERT INTO retail.variantes "
            "(id,sku,referencia,talla,nombre,color,categoria,precio_con_iva) "
            "VALUES (:v,:sku,'92611-1',:t,'Jean Skinny','Azul','Jeans',16990000)",
            {"v": _var(n), "sku": f"92611-1T{talla}", "t": talla}))
    # Y otra referencia para que la tabla tenga más de una fila.
    semillas.append((
        "INSERT INTO retail.variantes "
        "(id,sku,referencia,talla,nombre,color,categoria,precio_con_iva) "
        "VALUES (:v,'93100-2T4','93100-2','4','Falda Midi','Negro','Faldas',13990000)",
        {"v": _var(9)}))

    async with motor.begin() as c:
        for sql, p in semillas:
            await c.execute(text(sql), p)
        # Florida: T4 con 20 (OK), T6 con 3 (bajo), T10 con 0 (agotado).
        for var, cant in ((_var(1), 20), (_var(2), 3), (_var(3), 0)):
            await c.execute(text(
                "INSERT INTO retail.stock_ubicacion "
                "(ubicacion_id,variante_id,cantidad) VALUES (:u,:v,:c)"),
                {"u": FLORIDA, "v": var, "c": cant})
        # 30 unidades: cómodamente por encima del umbral de 8. Con 5 habría
        # salido «baja» y la prueba de abajo no habría distinguido nada.
        await c.execute(text(
            "INSERT INTO retail.stock_ubicacion "
            "(ubicacion_id,variante_id,cantidad) VALUES (:u,:v,30)"),
            {"u": FLORIDA, "v": _var(9)})
        # Arrayanes y la bodega tienen de la talla agotada en Florida.
        await c.execute(text(
            "INSERT INTO retail.stock_ubicacion "
            "(ubicacion_id,variante_id,cantidad) VALUES (:u,:v,4)"),
            {"u": ARRAYANES, "v": _var(3)})
        await c.execute(text(
            "INSERT INTO retail.stock_ubicacion "
            "(ubicacion_id,variante_id,cantidad) VALUES (:u,:v,7)"),
            {"u": BODEGA, "v": _var(3)})
    # El read model se llena por la MISMA vía que en producción. Rellenarlo a
    # mano aquí escondería justo lo que hay que detectar: que la
    # reconstrucción se deje una columna sin copiar.
    from backend.modules.retail.application.consultas.buscar_producto import (
        ReconstruirCatalogoBusqueda,
    )
    from sqlalchemy.ext.asyncio import async_sessionmaker

    fabrica = async_sessionmaker(motor, expire_on_commit=False)
    async with fabrica() as s:
        await ReconstruirCatalogoBusqueda(s).ejecutar()
        await s.commit()

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


def _pedir(c, **extra):
    p = {"ubicacion_id": FLORIDA, "tienda_id": "florida", **extra}
    r = c.get("/api/retail/inventario", params=p)
    assert r.status_code == 200, r.text
    return r.json()


def _fila(d, ref):
    return next(f for f in d["filas"] if f["referencia"] == ref)


# ── Las columnas ────────────────────────────────────────────────────────────

def test_las_columnas_de_talla_salen_de_los_datos(cliente):
    """El handoff dibuja T24/T26/T28/T30/T32 —tallaje americano—. Los SKU de
    MALE parsean a 4, 6, 10. Fijar las columnas en la pantalla haría que el
    inventario real no apareciera en ninguna."""
    c, _ = cliente
    d = _pedir(c)
    assert d["columnas_talla"] == ["4", "6", "10"], (
        "las columnas no vienen del catálogo real"
    )


def test_la_talla_4_va_antes_que_la_10(cliente):
    """Como texto, '10' < '4'. Una tabla de tallas desordenada se lee mal
    aunque cada número esté bien."""
    c, _ = cliente
    assert _pedir(c)["columnas_talla"].index("4") < \
           _pedir(c)["columnas_talla"].index("10")


# ── Los estados ─────────────────────────────────────────────────────────────

def test_el_umbral_de_la_tienda_mide_el_TOTAL_de_la_referencia(cliente):
    """Como el prototipo (`tot <= 8`), y por una razón práctica: aplicarlo por
    talla marca TODO. Con 12 unidades repartidas en cinco tallas ninguna llega
    a 8, y un aviso que sale siempre no es un aviso.

    92611-1 tiene 23 en total: por encima de 8, y ninguna talla afinada. Sana.
    """
    c, _ = cliente
    fila = _fila(_pedir(c), "92611-1")
    por_talla = {t["talla"]: t for t in fila["tallas"]}

    assert por_talla["4"]["disponible"] == 20
    assert por_talla["6"]["disponible"] == 3
    assert por_talla["10"]["disponible"] == 0
    # Nadie afinó estas tallas: ninguna avisa por su cuenta.
    assert all(not t["es_bajo"] for t in fila["tallas"])

    assert fila["total"] == 23
    assert fila["estado"] == "ok"


def test_por_debajo_del_umbral_la_referencia_sale_baja(cliente):
    c, motor = cliente
    import asyncio

    async def bajar():
        async with motor.begin() as cn:
            await cn.execute(text(
                "UPDATE retail.stock_ubicacion SET cantidad = 2 "
                " WHERE ubicacion_id = :u AND variante_id = :v"),
                {"u": FLORIDA, "v": _var(1)})

    asyncio.get_event_loop().run_until_complete(bajar())
    fila = _fila(_pedir(c), "92611-1")
    assert fila["total"] == 5           # 2 + 3 + 0, por debajo de 8
    assert fila["estado"] == "bajo"


def test_una_referencia_sin_nada_sale_agotada(cliente):
    c, motor = cliente
    import asyncio

    async def vaciar():
        async with motor.begin() as cn:
            await cn.execute(text(
                "UPDATE retail.stock_ubicacion SET cantidad = 0 "
                " WHERE ubicacion_id = :u"), {"u": FLORIDA})

    asyncio.get_event_loop().run_until_complete(vaciar())
    for f in _pedir(c)["filas"]:
        assert f["estado"] == "agotado"


def test_una_talla_afinada_marca_la_referencia_aunque_el_total_este_sano(cliente):
    """Es lo que el umbral del total NO puede ver: una referencia con mucho
    stock a la que le falta justamente la talla que más se pide.

    92611-1 tiene 23 unidades —sana por total—, pero si alguien marcó que la
    talla 4 se repone a partir de 25, esa talla habla."""
    c, motor = cliente
    import asyncio

    async def afinar():
        async with motor.begin() as cn:
            await cn.execute(text(
                "UPDATE retail.stock_ubicacion SET stock_minimo = 25 "
                " WHERE ubicacion_id = :u AND variante_id = :v"),
                {"u": FLORIDA, "v": _var(1)})

    asyncio.get_event_loop().run_until_complete(afinar())
    fila = _fila(_pedir(c), "92611-1")
    por_talla = {t["talla"]: t for t in fila["tallas"]}

    assert por_talla["4"]["minimo"] == 25
    assert por_talla["4"]["es_bajo"] is True
    assert fila["total"] == 23 and fila["estado"] == "bajo"
    # La que nadie afinó no inventa un mínimo: 0 significa «sin configurar».
    assert por_talla["6"]["minimo"] == 0
    assert por_talla["6"]["es_bajo"] is False


# ── Lo reservado no está para vender ────────────────────────────────────────

def test_lo_reservado_por_otra_caja_no_aparece_como_disponible(cliente):
    """Es la peor conversación posible en el mostrador: ofrecer una prenda que
    otra caja ya está cobrando."""
    c, motor = cliente
    import asyncio

    async def reservar():
        async with motor.begin() as cn:
            await cn.execute(text(
                "UPDATE retail.stock_ubicacion SET reservado = 18 "
                " WHERE ubicacion_id = :u AND variante_id = :v"),
                {"u": FLORIDA, "v": _var(1)})

    asyncio.get_event_loop().run_until_complete(reservar())
    fila = _fila(_pedir(c), "92611-1")
    por_talla = {t["talla"]: t for t in fila["tallas"]}
    assert por_talla["4"]["disponible"] == 2, "está ofreciendo prenda apartada"
    # Y al descontarlo, la referencia entera cae por debajo del umbral.
    assert fila["total"] == 5 and fila["estado"] == "bajo"


# ── Dónde más hay ───────────────────────────────────────────────────────────

def test_dice_cuanto_hay_en_las_otras_ubicaciones(cliente):
    """Traslados quedan fuera de esta fase, pero saber que en Arrayanes quedan
    cuatro es la diferencia entre «no hay» y «te la consigo»."""
    c, _ = cliente
    fila = _fila(_pedir(c), "92611-1")
    # 4 en Arrayanes + 7 en la bodega central, de la talla agotada aquí.
    assert fila["en_otras_ubicaciones"] == 11


def test_no_cuenta_transito_ni_externas_como_stock_de_otra_tienda(cliente):
    """Lo que va en camino todavía no está en ningún mostrador."""
    c, motor = cliente
    import asyncio

    async def en_transito():
        async with motor.begin() as cn:
            await cn.execute(text(
                "INSERT INTO retail.ubicaciones (id,tipo,nombre) "
                "VALUES ('transito:1','transito','En camino')"))
            await cn.execute(text(
                "INSERT INTO retail.stock_ubicacion "
                "(ubicacion_id,variante_id,cantidad) VALUES "
                "('transito:1',:v,50)"), {"v": _var(3)})

    asyncio.get_event_loop().run_until_complete(en_transito())
    assert _fila(_pedir(c), "92611-1")["en_otras_ubicaciones"] == 11


# ── Los filtros ─────────────────────────────────────────────────────────────

def test_el_filtro_de_texto_busca_por_referencia_y_por_nombre(cliente):
    c, _ = cliente
    assert len(_pedir(c, q="92611")["filas"]) == 1
    assert len(_pedir(c, q="falda")["filas"]) == 1
    assert _pedir(c, q="falda")["filas"][0]["referencia"] == "93100-2"
    assert _pedir(c, q="noexiste")["filas"] == []


def test_el_filtro_por_categoria(cliente):
    c, _ = cliente
    d = _pedir(c, categoria="Faldas")
    assert [f["referencia"] for f in d["filas"]] == ["93100-2"]
    assert "Jeans" in d["categorias"] and "Faldas" in d["categorias"]


def test_solo_bajos_deja_ver_lo_que_hay_que_reponer(cliente):
    """El caso de uso de la administradora: qué pedir, no qué hay."""
    c, motor = cliente
    import asyncio

    async def bajar():
        async with motor.begin() as cn:
            await cn.execute(text(
                "UPDATE retail.stock_ubicacion SET cantidad = 1 "
                " WHERE ubicacion_id = :u AND variante_id = :v"),
                {"u": FLORIDA, "v": _var(1)})

    asyncio.get_event_loop().run_until_complete(bajar())
    d = _pedir(c, solo_bajos=True)
    refs = [f["referencia"] for f in d["filas"]]
    assert refs == ["92611-1"], refs      # la falda tiene 30: no hay que pedirla


def test_los_contadores_de_la_cabecera(cliente):
    c, _ = cliente
    d = _pedir(c)
    assert d["referencias"] == 2
    # 23 y 30 unidades: las dos por encima de 8, y ninguna talla afinada.
    assert d["con_stock_bajo"] == 0
    assert d["umbral_tienda"] == 8


def test_una_tienda_sin_umbral_configurado_usa_el_default_de_la_columna(cliente):
    """Arrayanes se sembró sin umbral: la columna trae 8 por defecto, así que
    la pantalla es útil el primer día sin configurar nada."""
    c, _ = cliente
    r = c.get("/api/retail/inventario",
              params={"ubicacion_id": ARRAYANES, "tienda_id": "arrayanes"})
    assert r.status_code == 200
    assert r.json()["umbral_tienda"] == 8
