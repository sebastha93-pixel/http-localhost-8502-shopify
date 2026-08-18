"""Dar de alta una clienta en el mostrador.

Es el endpoint que la cajera usa con CADA clienta nueva, y no tenía ninguna
prueba. Lo descubrí buscando cobertura de la dirección: la importación desde
Siigo sí estaba probada, y el alta —la vía por la que van a entrar las clientas
del día a día— no.

LA DIRECCIÓN Y LA CIUDAD IMPORTAN AUNQUE LA FACTURA NO LAS MANDE. Cuando MALE
crea un documento en Siigo, el bloque del cliente lleva sólo `identification` y
`branch_office`: Siigo resuelve el resto de su propio maestro, y la dirección
que sale impresa es la suya. Pero para que exista allá hay que poder crearla, y
para crearla hace falta la dirección. Sin ella, la clienta que se da de alta en
el mostrador es una que después no se puede llevar a Siigo.
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

CLIENTE = "01JQ8X4T5N6P7R8S9V0W1XCB01"


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


CUERPO = {
    "cliente_id": CLIENTE, "tipo_documento": "CC",
    "numero_documento": "1037368561", "nombre": "Eli González",
    "telefono": "3117910110", "correo": "eli@correo.com",
    "direccion": "CL 50 A 86-450 APTO 513", "ciudad": "Medellín",
}


def test_se_crea_con_direccion_y_ciudad(entorno):
    """Sin ellas, la clienta del mostrador no se puede llevar después a Siigo,
    y queda una base de dos clases: la importada, facturable, y la del día a
    día, que no."""
    import asyncio

    c, motor = entorno
    r = c.post("/api/retail/clientes", json=CUERPO)
    assert r.status_code == 200, r.text

    async def leer():
        async with motor.connect() as cn:
            return (await cn.execute(text(
                "SELECT nombre, apellido, direccion, ciudad, creado_por "
                "  FROM retail.clientes WHERE numero_documento='1037368561'"
            ))).mappings().first()

    f = asyncio.get_event_loop().run_until_complete(leer())
    assert f["direccion"] == "CL 50 A 86-450 APTO 513"
    assert f["ciudad"] == "Medellín"
    # El nombre se parte porque así lo pide Siigo: `name` es un arreglo.
    assert (f["nombre"], f["apellido"]) == ("Eli", "González")
    assert f["creado_por"] == "maria"     # quién la dio de alta


def test_sin_direccion_tambien_se_crea(entorno):
    """No se bloquea: la mayoría de las ventas de tienda no llevan clienta, y
    obligar a un campo más en el mostrador son segundos de los treinta. Lo que
    falte se completa el día que haga falta facturar."""
    c, _ = entorno
    r = c.post("/api/retail/clientes",
               json={k: v for k, v in CUERPO.items()
                     if k not in ("direccion", "ciudad")})
    assert r.status_code == 200, r.text


def test_el_correo_se_valida_ANTES_de_guardar(entorno):
    """Ahí llega la factura electrónica. Un error de dedo es una factura que
    nunca llega y una clienta que llama tres días después."""
    c, _ = entorno
    r = c.post("/api/retail/clientes", json={**CUERPO, "correo": "eli.correo"})
    assert r.status_code == 400
    assert "correo" in r.json()["detail"]["mensaje"].lower()


def test_un_documento_repetido_manda_a_BUSCARLA(entorno):
    """El mensaje importa: quien llega aquí es porque no la encontró. Decirle
    «ya existe» sin decirle qué hacer la deja atascada con la clienta
    esperando."""
    c, _ = entorno
    c.post("/api/retail/clientes", json=CUERPO)
    r = c.post("/api/retail/clientes",
               json={**CUERPO, "cliente_id": "01JQ8X4T5N6P7R8S9V0W1XCB02"})
    assert r.status_code == 400
    assert "Búscala" in r.json()["detail"]["mensaje"]


def test_un_telefono_a_medias_no_pasa(entorno):
    c, _ = entorno
    r = c.post("/api/retail/clientes", json={**CUERPO, "telefono": "311"})
    assert r.status_code == 400
    assert "teléfono" in r.json()["detail"]["mensaje"].lower()


def test_recien_creada_se_ENCUENTRA_al_buscarla(entorno):
    """El caso real: la cajera la crea y en la siguiente venta la busca. Si el
    alta no la deja encontrable, se crea dos veces."""
    c, _ = entorno
    c.post("/api/retail/clientes", json=CUERPO)
    r = c.get("/api/retail/clientes/buscar", params={"documento": "10373"})
    assert r.status_code == 200
    assert [x["numero_documento"] for x in r.json()] == ["1037368561"]
    assert r.json()[0]["compras"] == 0
