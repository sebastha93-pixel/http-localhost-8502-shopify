"""El conteo de una tienda cargado en el POS mientras Siigo no deja cargarlo.

Arrayanes, 29-oct-2026: contaron y la página de Siigo no guardaba el ajuste.
Lo que no puede pasar:
  · que la sincronización pise el conteo con los números viejos de Siigo;
  · que las bolsas queden en cero sin que nadie lo vea (Florida, 28-oct);
  · que lo que se cargue en Siigo después devuelva lo ya vendido.
"""
from __future__ import annotations

import os

import pytest
import pytest_asyncio

pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

URL = os.environ.get("RETAIL_TEST_DATABASE_URL", "").strip()
pytestmark = pytest.mark.skipif(not URL, reason="Sin RETAIL_TEST_DATABASE_URL")

CONTEO = "01JQ8X4T5NC0NTE0R8S9V0W1X2"


def _p(code, arrayanes=0, florida=0, precio=149900):
    return {"code": code, "name": f"{code} JEAN", "stock_control": True,
            "tax_included": True, "account_group": {"name": "SKINNY"},
            "prices": [{"price_list": [{"value": precio}]}],
            "warehouses": [{"id": 37, "name": "Arrayanes", "quantity": arrayanes},
                           {"id": 48, "name": "Florida", "quantity": florida}],
            "additional_fields": {"barcode": code}}


SIIGO = [_p("26602-1T6", arrayanes=2, florida=4), _p("95613-1T12", arrayanes=8),
         _p("12617-2T8", arrayanes=5), _p("5353", arrayanes=60, precio=1000)]


@pytest_asyncio.fixture()
async def tienda():
    from backend.core.security import CurrentUser, get_current_user
    from backend.modules.retail.interfaces.http import dependencias
    from backend.modules.retail.interfaces.http.router import router
    from backend.modules.retail.migraciones.runner import aplicar, revertir
    from backend.modules.retail.sembrar_tiendas import sembrar
    from backend.modules.retail.sincronizar_inventario import sincronizar

    revertir(URL)
    aplicar(URL)
    sembrar(URL, aplicar=True)
    sincronizar(URL, aplicar=True, precios_de_lista=lambda c: {}, productos=SIIGO)
    os.environ["RETAIL_DATABASE_URL"] = URL
    dependencias.reiniciar()

    motor = create_engine(URL, future=True)
    with motor.begin() as c:
        c.execute(text(
            "INSERT INTO retail.permisos_pos (usuario_id,nombre,tiendas,puede_mover_caja) "
            "VALUES ('marcela','Marcela A.','{arrayanes}', true),"
            "       ('cajera','Cajera','{arrayanes}', false)"))
    quien = {"id": "marcela"}
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id=quien["id"], email="m@male.com", nombre="Marcela", rol="user",
        permisos={"retail": ["ver", "modificar"]})
    with TestClient(app) as c:
        yield {"c": c, "motor": motor, "quien": quien}
    motor.dispose()
    dependencias.reiniciar()
    revertir(URL)


def _stock(t, sku, ubicacion="tienda:arrayanes"):
    with t["motor"].connect() as c:
        return c.execute(text("""
            SELECT s.cantidad FROM retail.stock_ubicacion s
              JOIN retail.variantes v ON v.id = s.variante_id
             WHERE v.sku = :s AND s.ubicacion_id = :u"""),
            {"s": sku, "u": ubicacion}).scalar()


# El conteo de Arrayanes: el jean 26602 dio 3 (había 2), el 95613 dio 6
# (había 8), el 12617 no apareció y las bolsas tampoco. La pistola escribió
# el apóstrofo en vez del guion.
LINEAS = [{"codigo": "26602'1T6", "cantidad": 3},
          {"codigo": "95613-1T12", "cantidad": 6},
          {"codigo": "99999-9T9", "cantidad": 1}]


def test_el_ensayo_muestra_todo_y_NO_escribe(tienda):
    r = tienda["c"].post("/api/retail/inventario/conteo/ensayo", json={
        "tienda_id": "arrayanes", "lineas": LINEAS, "completo": True})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["desconocidos"] == ["99999-9T9"]
    assert {(c["sku"], c["antes"], c["contado"]) for c in d["cambios"]} == {
        ("26602-1T6", 2, 3), ("95613-1T12", 8, 6),
        ("12617-2T8", 5, 0), ("5353", 60, 0)}
    # Lo que no es prenda y quedaría en cero va aparte: es lo que se olvida.
    assert [f["sku"] for f in d["no_prendas_a_cero"]] == ["5353"]
    assert (d["unidades_antes"], d["unidades_despues"]) == (75, 9)
    assert _stock(tienda, "26602-1T6") == 2          # nada se movió


def test_cargar_el_conteo_deja_la_tienda_como_se_conto(tienda):
    cuerpo = {"tienda_id": "arrayanes", "lineas": LINEAS, "completo": True,
              "conteo_id": CONTEO}
    r = tienda["c"].post("/api/retail/inventario/conteo", json=cuerpo)
    assert r.status_code == 200, r.text
    assert [_stock(tienda, s) for s in ("26602-1T6", "95613-1T12", "12617-2T8",
                                        "5353")] == [3, 6, 0, 0]
    with tienda["motor"].connect() as c:
        movs = c.execute(text("""SELECT count(*) FROM retail.movimientos_inventario
                                  WHERE referencia_tipo = 'conteo_pos'""")).scalar()
        aud = c.execute(text("""SELECT severidad FROM retail.auditoria
                                 WHERE evento = 'inventario.conteo'""")).scalar()
    assert (movs, aud) == (4, "critico")
    # Reintentar (mala señal) no lo aplica dos veces.
    r = tienda["c"].post("/api/retail/inventario/conteo", json=cuerpo)
    assert r.status_code == 200 and r.json()["ya_estaba"] is True
    assert _stock(tienda, "26602-1T6") == 3


def test_un_conteo_parcial_no_toca_lo_que_no_se_conto(tienda):
    r = tienda["c"].post("/api/retail/inventario/conteo", json={
        "tienda_id": "arrayanes", "lineas": LINEAS[:1], "completo": False,
        "conteo_id": CONTEO})
    assert r.status_code == 200, r.text
    assert [_stock(tienda, s) for s in ("26602-1T6", "12617-2T8", "5353")] == [
        3, 5, 60]


def test_una_cajera_sin_el_permiso_no_puede_cargar_un_conteo(tienda):
    tienda["quien"]["id"] = "cajera"
    r = tienda["c"].post("/api/retail/inventario/conteo/ensayo", json={
        "tienda_id": "arrayanes", "lineas": LINEAS})
    assert r.status_code == 403 and "administradora" in r.text


def test_mientras_esta_pendiente_siigo_NO_pisa_el_conteo(tienda):
    """Y cuando se marca cargado en Siigo, la tienda vuelve a la normalidad."""
    from backend.modules.retail.sincronizar_inventario import sincronizar
    tienda["c"].post("/api/retail/inventario/conteo", json={
        "tienda_id": "arrayanes", "lineas": LINEAS, "completo": True,
        "conteo_id": CONTEO})
    # Siigo sigue con los números de antes, y a Florida le llegó mercancía.
    viejo = [_p("26602-1T6", arrayanes=2, florida=9), _p("95613-1T12", arrayanes=8),
             _p("12617-2T8", arrayanes=5), _p("5353", arrayanes=60, precio=1000)]
    r = sincronizar(URL, aplicar=True, precios_de_lista=lambda c: {}, productos=viejo)
    assert r["tiendas"]["arrayanes"]["en_pausa_por_conteo"] == CONTEO
    assert _stock(tienda, "26602-1T6") == 3                      # el conteo
    assert _stock(tienda, "26602-1T6", "tienda:florida") == 9    # Florida sí

    # Lo que hay que cargar en Siigo es lo de AHORA: se vendió un 95613.
    with tienda["motor"].begin() as c:
        c.execute(text("""UPDATE retail.stock_ubicacion SET cantidad = 5
                           WHERE ubicacion_id = 'tienda:arrayanes' AND variante_id =
                                 (SELECT id FROM retail.variantes WHERE sku = '95613-1T12')"""))
    d = tienda["c"].get(f"/api/retail/inventario/conteos/{CONTEO}/para-siigo").json()
    assert {f["sku"]: f["cantidad"] for f in d["filas"]} == {
        "26602-1T6": 3, "95613-1T12": 5}
    assert d["bodega_siigo"] == 37

    r = tienda["c"].post(f"/api/retail/inventario/conteos/{CONTEO}/en-siigo")
    assert r.status_code == 200, r.text
    ya = [_p("26602-1T6", arrayanes=3), _p("95613-1T12", arrayanes=5),
          _p("5353", arrayanes=40, precio=1000)]
    r = sincronizar(URL, aplicar=True, precios_de_lista=lambda c: {}, productos=ya)
    assert "en_pausa_por_conteo" not in r["tiendas"]["arrayanes"]
    assert _stock(tienda, "5353") == 40                          # Siigo manda
    lista = tienda["c"].get("/api/retail/inventario/conteos",
                            params={"tienda_id": "arrayanes"}).json()
    assert [(x["id"], x["estado"]) for x in lista] == [(CONTEO, "en_siigo")]


def test_un_conteo_nuevo_reemplaza_al_pendiente(tienda):
    for i, cid in enumerate((CONTEO, CONTEO[:-1] + "3")):
        r = tienda["c"].post("/api/retail/inventario/conteo", json={
            "tienda_id": "arrayanes", "lineas": [{"codigo": "26602-1T6",
                                                  "cantidad": 4 + i}],
            "completo": False, "conteo_id": cid})
        assert r.status_code == 200, r.text
    lista = tienda["c"].get("/api/retail/inventario/conteos",
                            params={"tienda_id": "arrayanes"}).json()
    assert sorted(x["estado"] for x in lista) == ["pendiente_siigo", "reemplazado"]
    assert _stock(tienda, "26602-1T6") == 5


def test_cantidades_que_no_son_numeros_se_rechazan_con_un_mensaje_claro(tienda):
    r = tienda["c"].post("/api/retail/inventario/conteo/ensayo", json={
        "tienda_id": "arrayanes", "lineas": [{"codigo": "26602-1T6",
                                              "cantidad": -2}]})
    assert r.status_code == 400 and "negativa" in r.text
