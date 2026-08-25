"""Conceder permisos del POS sin pasar por `psql`.

Hasta ahora dar de alta una cajera —o quitarle el permiso a alguien que se
fue— exigía que alguien con acceso a la base lo hiciera a mano. Eso no puede
pasar en una tienda: significa que el sistema no se puede operar sin quien lo
construyó.

LO QUE MÁS IMPORTA AQUÍ ES LA PUERTA. Un panel de permisos sin control es peor
que no tenerlo: cualquiera se concede el permiso de anular, anula una venta, y
se lo quita. Por eso son dos cosas — sólo el administrador del ERP entra, y
cada cambio queda en la auditoría con el antes y el después.
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
        await c.execute(text(
            "INSERT INTO retail.tiendas (id,nombre) VALUES ('florida','Florida')"))
        await c.execute(text(
            "INSERT INTO retail.permisos_pos (usuario_id,nombre,tiendas) "
            "VALUES ('maria','María R.','{florida}')"))

    app = FastAPI()
    app.include_router(router)

    def entrar_como(uid: str, rol: str):
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            id=uid, email=f"{uid}@male.com", nombre=uid.title(), rol=rol,
            permisos={"retail": ["ver", "modificar"]})

    entrar_como("maria", "user")

    with TestClient(app) as c:
        yield c, motor, entrar_como

    await motor.dispose()
    dependencias.reiniciar()
    revertir(URL)


CUERPO = {
    "nombre": "Sofía L.", "rol": "Cajera", "tiendas": ["florida"],
    "tope_descuento_pct": "15", "puede_anular_venta": True,
    "puede_cerrar_con_descuadre": False, "puede_ver_esperado": False,
    "puede_mover_caja": True, "puede_ver_auditoria": False, "activo": True,
}


# ── LA PUERTA, que es lo que más importa ────────────────────────────────────

def test_una_cajera_NO_puede_conceder_permisos(entorno):
    """El agujero que un panel de permisos abre si no se cierra: cualquiera se
    concede el permiso de anular, anula una venta, y se lo quita."""
    c, _, _ = entorno
    r = c.patch("/api/retail/admin/permisos/sofia", json=CUERPO)
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "solo_administrador"


def test_ni_siquiera_puede_LEERLOS(entorno):
    """Quién puede anular y quién ve la auditoría es información con la que se
    elige a quién pedirle favores."""
    c, _, _ = entorno
    assert c.get("/api/retail/admin/permisos").status_code == 403


def test_tener_permisos_del_POS_no_basta(entorno):
    """Quien puede anular ventas no tiene por qué poder darse a sí mismo el
    permiso de ver la auditoría. Conceder es un acto sobre PERSONAS y vive en
    el rol de administrador del ERP, no en los permisos de tienda."""
    c, motor, entrar_como = entorno

    async def darle_todo():
        async with motor.begin() as cn:
            await cn.execute(text("""
                UPDATE retail.permisos_pos
                   SET puede_anular_venta = true, puede_mover_caja = true,
                       puede_ver_auditoria = true, puede_cerrar_con_descuadre = true
                 WHERE usuario_id = 'maria'
            """))

    asyncio.get_event_loop().run_until_complete(darle_todo())
    assert c.patch("/api/retail/admin/permisos/sofia",
                 json=CUERPO).status_code == 403


def test_el_administrador_si(entorno):
    c, _, entrar_como = entorno
    entrar_como("sebastian", "admin")
    assert c.get("/api/retail/admin/permisos").status_code == 200
    assert c.patch("/api/retail/admin/permisos/sofia",
                 json=CUERPO).status_code == 200


# ── Crear y modificar ───────────────────────────────────────────────────────

def test_dar_de_alta_una_cajera_nueva(entorno):
    c, _, entrar_como = entorno
    entrar_como("sebastian", "admin")

    r = c.patch("/api/retail/admin/permisos/sofia", json=CUERPO)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["nombre"] == "Sofía L."
    assert d["tope_descuento_pct"] == "15.00"
    assert d["puede_anular_venta"] is True
    assert d["puede_ver_auditoria"] is False

    listado = c.get("/api/retail/admin/permisos").json()
    assert {u["usuario_id"] for u in listado} == {"maria", "sofia"}


def test_quitar_el_permiso_a_alguien_que_se_fue(entorno):
    """`activo = false` en vez de borrar: la fila sigue explicando las ventas y
    los descuentos que esa persona hizo. Borrarla dejaría la auditoría llena de
    identificadores sin nombre."""
    c, _, entrar_como = entorno
    entrar_como("sebastian", "admin")
    c.patch("/api/retail/admin/permisos/sofia", json=CUERPO)

    r = c.patch("/api/retail/admin/permisos/sofia",
              json={**CUERPO, "activo": False})
    assert r.status_code == 200
    assert r.json()["activo"] is False

    # Y sigue apareciendo en el listado, marcada.
    listado = c.get("/api/retail/admin/permisos").json()
    sofia = next(u for u in listado if u["usuario_id"] == "sofia")
    assert sofia["activo"] is False


def test_el_tope_tiene_que_ser_un_porcentaje(entorno):
    c, _, entrar_como = entorno
    entrar_como("sebastian", "admin")
    for malo in ("150", "-5"):
        r = c.patch("/api/retail/admin/permisos/sofia",
                  json={**CUERPO, "tope_descuento_pct": malo})
        assert r.status_code == 400, malo
    r = c.patch("/api/retail/admin/permisos/sofia",
              json={**CUERPO, "tope_descuento_pct": "no soy un número"})
    assert r.status_code == 400


# ── El rastro ───────────────────────────────────────────────────────────────

def test_cambiar_permisos_queda_CRITICO_con_el_antes_y_el_despues(entorno):
    """Conceder permisos habilita todas las demás operaciones. Sin rastro,
    alguien se da el permiso de anular, anula una venta y se lo quita — y en la
    auditoría sólo queda la anulación, hecha por alguien que «podía»."""
    c, motor, entrar_como = entorno
    entrar_como("sebastian", "admin")

    c.patch("/api/retail/admin/permisos/maria",
          json={**CUERPO, "nombre": "María R.", "puede_ver_auditoria": True})

    async def leer():
        async with motor.connect() as cn:
            return (await cn.execute(text("""
                SELECT severidad, usuario_id, payload FROM retail.auditoria
                 WHERE evento = 'permisos.cambiados'
            """))).mappings().first()

    a = asyncio.get_event_loop().run_until_complete(leer())
    assert a is not None
    assert a["severidad"] == "critico"
    assert a["usuario_id"] == "sebastian"        # QUIÉN lo concedió
    assert a["payload"]["sobre"] == "maria"      # A QUIÉN
    assert a["payload"]["antes"] is not None     # cómo estaba
    assert a["payload"]["despues"]["auditoria"] is True


def test_el_renglon_dice_QUE_PERMISO_se_movió(entorno):
    """Sin este caso el evento caía al volcado genérico y salía en pantalla
    como `antes={'activo': 'True', 'puede_mover_...`. Y repetir los siete
    permisos en cada renglón esconde el único que cambió, que es lo que se
    está buscando."""
    c, motor, entrar_como = entorno
    entrar_como("sebastian", "admin")
    c.patch("/api/retail/admin/permisos/maria",
          json={**CUERPO, "nombre": "María R.", "puede_anular_venta": False,
                "puede_mover_caja": False, "tope_descuento_pct": "0"})
    c.patch("/api/retail/admin/permisos/maria",
          json={**CUERPO, "nombre": "María R.", "puede_anular_venta": True,
                "puede_mover_caja": False, "tope_descuento_pct": "0"})

    # Se lee como María y el permiso se da por SQL: ser administrador del ERP
    # no da acceso a la auditoría —son cosas distintas a propósito— y hacerlo
    # con un PATCH más metería un evento extra en el renglón que se comprueba.
    async def dejarla_ver():
        async with motor.begin() as cn:
            await cn.execute(text("UPDATE retail.permisos_pos "
                                  "SET puede_ver_auditoria = true "
                                  " WHERE usuario_id = 'maria'"))

    asyncio.get_event_loop().run_until_complete(dejarla_ver())
    entrar_como("maria", "user")
    d = c.get("/api/retail/auditoria", params={"tienda_id": "florida"}).json()
    ultimo = next(e for e in d["eventos"] if e["evento"] == "permisos.cambiados")
    assert ultimo["resumen"] == "maria · +anular"


def test_un_alta_nueva_no_tiene_ANTES(entorno):
    """Distinguir «se creó» de «se cambió» importa al revisar: un permiso que
    aparece de la nada no es lo mismo que uno que alguien subió."""
    c, motor, entrar_como = entorno
    entrar_como("sebastian", "admin")
    c.patch("/api/retail/admin/permisos/sofia", json=CUERPO)

    async def leer():
        async with motor.connect() as cn:
            return (await cn.execute(text("""
                SELECT payload FROM retail.auditoria
                 WHERE evento='permisos.cambiados'
                   AND payload->>'sobre' = 'sofia'
            """))).scalar()

    p = asyncio.get_event_loop().run_until_complete(leer())
    assert p["antes"] is None
