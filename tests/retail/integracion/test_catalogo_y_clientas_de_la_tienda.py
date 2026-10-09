"""Lo que la caja ve: el catálogo ENTERO de su tienda y las clientas de Siigo.

Los dos fallos salieron el primer día de venta real (Arrayanes, 2026-10-09):
«hay referencias que siguen sin aparecer» y una clienta de años a la que hubo
que digitar entera.
"""
from __future__ import annotations

import os

import pytest
import pytest_asyncio

pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

URL = os.environ.get("RETAIL_TEST_DATABASE_URL", "").strip()
pytestmark = pytest.mark.skipif(not URL, reason="Sin RETAIL_TEST_DATABASE_URL")


def _p(code, arrayanes=0, florida=0):
    return {"code": code, "name": f"{code} JEAN", "stock_control": True,
            "tax_included": True, "account_group": {"name": "SKINNY"},
            "prices": [{"price_list": [{"value": 149900}]}],
            "warehouses": [{"id": 37, "name": "Arrayanes", "quantity": arrayanes},
                           {"id": 48, "name": "Florida", "quantity": florida}],
            "additional_fields": {"barcode": code}}


@pytest_asyncio.fixture()
async def cliente():
    from backend.core.security import CurrentUser, get_current_user
    from backend.modules.retail.interfaces.http import dependencias
    from backend.modules.retail.interfaces.http import router as modulo
    from backend.modules.retail.migraciones.runner import aplicar, revertir
    from backend.modules.retail.sembrar_tiendas import sembrar

    revertir(URL)
    aplicar(URL)
    sembrar(URL, aplicar=True)
    os.environ["RETAIL_DATABASE_URL"] = URL
    dependencias.reiniciar()
    modulo._NO_ESTA_EN_SIIGO.clear()

    app = FastAPI()
    app.include_router(modulo.router)
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id="maria", email="m@male.com", nombre="María", rol="user",
        permisos={"retail": ["ver", "modificar"]})
    with TestClient(app) as c:
        yield c
    dependencias.reiniciar()
    revertir(URL)


def _catalogo(c, **params):
    r = c.get("/api/retail/catalogo/referencias",
              params={"ubicacion_id": "tienda:arrayanes", **params})
    assert r.status_code == 200, r.text
    return r.json()["referencias"]


# ── El catálogo ─────────────────────────────────────────────────────────────

def test_salen_TODAS_las_referencias_de_la_tienda_no_las_primeras_60(cliente):
    from backend.modules.retail.sincronizar_inventario import sincronizar
    sincronizar(URL, aplicar=True, precios_de_lista=lambda c: {}, productos=[
        _p(f"9{n:04d}-1T6", arrayanes=2) for n in range(150)])
    refs = _catalogo(cliente)
    assert len(refs) == 150
    assert refs[-1]["referencia"] == "90149-1"       # la última también está


def test_no_salen_las_referencias_que_solo_tiene_la_OTRA_tienda(cliente):
    from backend.modules.retail.sincronizar_inventario import sincronizar
    sincronizar(URL, aplicar=True, precios_de_lista=lambda c: {}, productos=[
        _p("10001-1T6", arrayanes=2), _p("20002-1T6", florida=5)])
    assert [r["referencia"] for r in _catalogo(cliente)] == ["10001-1"]


def test_la_talla_agotada_de_una_referencia_que_si_hay_sale_en_cero(cliente):
    from backend.modules.retail.sincronizar_inventario import sincronizar
    sincronizar(URL, aplicar=True, precios_de_lista=lambda c: {}, productos=[
        _p("10001-1T6", arrayanes=2), _p("10001-1T8", florida=3)])
    [ref] = _catalogo(cliente)
    assert {t["talla"]: t["disponible"] for t in ref["tallas"]} == {"6": 2, "8": 0}


def test_buscando_una_referencia_agotada_SE_VE_y_se_ve_que_no_hay(cliente):
    """Quien busca por código tiene que encontrarla en cero, no concluir que
    no existe."""
    from backend.modules.retail.sincronizar_inventario import sincronizar
    sincronizar(URL, aplicar=True, precios_de_lista=lambda c: {}, productos=[
        _p("10001-1T6", arrayanes=2), _p("20002-1T6", florida=5)])
    [ref] = _catalogo(cliente, q="20002")
    assert ref["referencia"] == "20002-1"
    assert ref["tallas"][0]["disponible"] == 0


# ── Las clientas ────────────────────────────────────────────────────────────

LAURA = {"siigo_customer_id": "sg-1", "tipo_documento": "CC",
         "numero_documento": "1037000111", "dv": None, "nombre": "Laura",
         "apellido": "Gómez Ríos", "telefono": "3001112233",
         "correo": "laura@correo.com", "direccion": "CL 50 # 40-20",
         "ciudad": "Itagüí", "activo_en_siigo": True}


def _siigo(monkeypatch, respuestas):
    from backend.modules.retail.infrastructure.siigo import clientes_siigo
    llamadas = []

    def falso(documento):
        llamadas.append(documento)
        r = respuestas.get(documento)
        if isinstance(r, Exception):
            raise r
        return r
    monkeypatch.setattr(clientes_siigo, "buscar_por_documento", falso)
    return llamadas


def _buscar(c, documento):
    r = c.get("/api/retail/clientes/buscar", params={"documento": documento})
    assert r.status_code == 200, r.text
    return r.json()


def test_la_clienta_que_ya_esta_en_siigo_aparece_sin_digitarla(cliente, monkeypatch):
    llamadas = _siigo(monkeypatch, {"1037000111": LAURA})
    [c] = _buscar(cliente, "1.037.000.111")
    assert c["nombre"] == "Laura Gómez Ríos"
    assert c["correo"] == "laura@correo.com"
    assert llamadas == ["1037000111"]

    # La segunda vez ya está aquí: no se vuelve a ir a Siigo.
    assert _buscar(cliente, "1037000111")[0]["nombre"] == "Laura Gómez Ríos"
    assert llamadas == ["1037000111"]


def test_mientras_se_teclea_no_se_le_pregunta_a_siigo(cliente, monkeypatch):
    """Siigo sólo encuentra el documento completo, y aguanta una petición por
    segundo. Cada tecla no puede ser un viaje."""
    llamadas = _siigo(monkeypatch, {})
    for parcial in ("103", "1037", "10370"):
        assert _buscar(cliente, parcial) == []
    assert llamadas == []


def test_lo_que_siigo_no_conoce_no_se_vuelve_a_preguntar_enseguida(cliente, monkeypatch):
    llamadas = _siigo(monkeypatch, {})
    assert _buscar(cliente, "99999999") == []
    assert _buscar(cliente, "99999999") == []
    assert llamadas == ["99999999"]


def test_si_siigo_falla_la_busqueda_responde_vacio_y_no_un_error(cliente, monkeypatch):
    """La cajera la crea a mano, como antes. Lo que no puede pasar es que la
    caída de un tercero le bloquee el buscador."""
    _siigo(monkeypatch, {"1037000111": RuntimeError("Siigo HTTP 503")})
    assert _buscar(cliente, "1037000111") == []
