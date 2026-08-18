"""Traer la base de clientas de Siigo sin romper nada.

POR QUÉ IMPORTA, y no es la comodidad de no volver a teclear: MALE lleva años
facturando desde Siigo POS. Si el POS nuevo arranca vacío, la primera factura a
una clienta que Siigo YA TIENE la duplica en la contabilidad o se cae.
`retail.clientes.siigo_customer_id` existe desde la migración 0001 y no lo
escribía nadie — es justo el vínculo que lo evita.

Se prueba con una lista, sin red y sin credenciales. Una importación que sólo
se puede probar contra la cuenta real es una importación sin pruebas.
"""
from __future__ import annotations

import asyncio
import os

import pytest
import pytest_asyncio

pytest.importorskip("sqlalchemy")

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

URL = os.environ.get("RETAIL_TEST_DATABASE_URL", "").strip()
pytestmark = pytest.mark.skipif(not URL, reason="Sin RETAIL_TEST_DATABASE_URL")

_N = [0]


def nuevo_id() -> str:
    # El alfabeto ULID excluye I, L, O y U — se confunden con 1 y 0. Con una
    # «I» aquí el dominio `retail.ulid` rechaza la fila.
    _N[0] += 1
    return f"01JQ8X4T5N6P7R8S9V0W1X{_N[0]:04d}"


def de_siigo(**kw) -> dict:
    base = {"siigo_customer_id": "sg-1", "tipo_documento": "CC",
            "numero_documento": "1037368561", "dv": "6", "nombre": "ELI",
            "apellido": "GONZALEZ", "telefono": "3117910110",
            "correo": "eli@correo.com", "direccion": "CL 50 A 86-450",
            "ciudad": "Medellín", "activo_en_siigo": True}
    base.update(kw)
    return base


@pytest_asyncio.fixture()
async def sesion():
    from backend.modules.retail.migraciones.runner import aplicar, revertir

    revertir(URL)
    aplicar(URL)
    motor = create_async_engine(URL)
    hacer = async_sessionmaker(motor, expire_on_commit=False)
    async with hacer() as s:
        yield s
    await motor.dispose()
    revertir(URL)


async def importar(s, clientas, dry_run=False):
    from backend.modules.retail.application.comandos.importar_clientes import (
        ImportarClientes,
    )
    r = await ImportarClientes(s).ejecutar(
        clientas, usuario_id="sebastian", dry_run=dry_run, nuevo_id=nuevo_id)
    await s.commit()
    return r


def correr(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ── EL PUNTO: el vínculo con Siigo ──────────────────────────────────────────

def test_una_clienta_nueva_se_crea_CON_su_id_de_siigo(sesion):
    r = correr(importar(sesion, [de_siigo()]))
    assert r.creadas == 1

    async def leer():
        return (await sesion.execute(text(
            "SELECT siigo_customer_id, direccion, ciudad, dv FROM retail.clientes "
            " WHERE numero_documento='1037368561'"))).mappings().first()

    f = correr(leer())
    assert f["siigo_customer_id"] == "sg-1"   # el vínculo, que es el objetivo
    assert f["direccion"] == "CL 50 A 86-450"  # la factura la exige
    assert f["dv"] == "6"


def test_a_una_que_YA_EXISTIA_aqui_se_le_pone_el_vinculo(sesion):
    """El caso que de verdad evita el daño: la cajera la creó a mano en el
    mostrador y Siigo ya la tenía. Sin enlazar, al facturar se duplica."""
    async def sembrar():
        await sesion.execute(text(
            "INSERT INTO retail.clientes (id,tipo_documento,numero_documento,"
            " nombre,apellido) VALUES ('01JQ8X4T5N6P7R8S9V0W1XAA01','CC',"
            " '1037368561','Eli','Gonzalez')"))
        await sesion.commit()

    correr(sembrar())
    r = correr(importar(sesion, [de_siigo()]))
    assert r.creadas == 0
    assert r.enlazadas == 1

    async def leer():
        return (await sesion.execute(text(
            "SELECT siigo_customer_id FROM retail.clientes "
            " WHERE numero_documento='1037368561'"))).scalar()

    assert correr(leer()) == "sg-1"


# ── No hacer daño ───────────────────────────────────────────────────────────

def test_NO_pisa_lo_que_alguien_corrigio_a_mano(sesion):
    """Si la cajera arregló el teléfono en el mostrador —porque la clienta se
    lo acaba de dictar— ese dato es MÁS nuevo que el de Siigo."""
    async def sembrar():
        await sesion.execute(text(
            "INSERT INTO retail.clientes (id,tipo_documento,numero_documento,"
            " nombre,apellido,telefono) VALUES ('01JQ8X4T5N6P7R8S9V0W1XAA02',"
            " 'CC','1037368561','Eli','Gonzalez','3009999999')"))
        await sesion.commit()

    correr(sembrar())
    correr(importar(sesion, [de_siigo(telefono="3117910110")]))

    async def leer():
        return (await sesion.execute(text(
            "SELECT telefono, direccion FROM retail.clientes "
            " WHERE numero_documento='1037368561'"))).mappings().first()

    f = correr(leer())
    assert f["telefono"] == "3009999999"          # el del mostrador GANA
    assert f["direccion"] == "CL 50 A 86-450"     # lo vacío SÍ se rellena


def test_correrlo_dos_veces_no_cambia_nada(sesion):
    """Va a haber que correrlo varias veces. Una importación que sólo se puede
    correr una vez es una importación que nadie se atreve a correr."""
    correr(importar(sesion, [de_siigo()]))
    segunda = correr(importar(sesion, [de_siigo()]))
    assert (segunda.creadas, segunda.enlazadas, segunda.completadas) == (0, 0, 0)


def test_el_ensayo_no_toca_la_base(sesion):
    r = correr(importar(sesion, [de_siigo()], dry_run=True))
    assert r.creadas == 1 and r.ensayo is True

    async def contar():
        return (await sesion.execute(
            text("SELECT count(*) FROM retail.clientes"))).scalar()

    assert correr(contar()) == 0


# ── Los casos raros, que son los que rompen una importación ─────────────────

def test_mismo_numero_con_OTRO_tipo_no_se_fusiona(sesion):
    """Una CE y una CC con los mismos dígitos son dos personas. Fusionarlas
    manda la factura de una al correo de la otra: silencioso, y además un
    problema de datos personales. Se marca para que lo decida un humano."""
    async def sembrar():
        await sesion.execute(text(
            "INSERT INTO retail.clientes (id,tipo_documento,numero_documento,"
            " nombre,apellido) VALUES ('01JQ8X4T5N6P7R8S9V0W1XAA03','CE',"
            " '1037368561','Otra','Persona')"))
        await sesion.commit()

    correr(sembrar())
    r = correr(importar(sesion, [de_siigo(tipo_documento="CC")]))
    assert r.ambiguas == 1
    assert r.creadas == 0
    assert "ambigua" in r.ejemplos[0]


def test_sin_documento_se_cuenta_y_sigue(sesion):
    """Abortar la importación entera por una fila mala dejaría la base a
    medias, que es el peor de los dos estados."""
    r = correr(importar(sesion, [de_siigo(numero_documento=""),
                                 de_siigo(numero_documento="900123456")]))
    assert r.sin_documento == 1
    assert r.creadas == 1


def test_las_inactivas_de_siigo_no_entran(sesion):
    r = correr(importar(sesion, [de_siigo(activo_en_siigo=False)]))
    assert r.inactivas == 1 and r.creadas == 0


# ── El mapeo desde el JSON de Siigo ─────────────────────────────────────────

def test_el_correo_sale_de_CONTACTS_no_de_la_raiz():
    """Es donde llega la factura electrónica. Leerlo del sitio equivocado deja
    a la clienta sin recibirla y nadie se entera."""
    from backend.modules.retail.infrastructure.siigo import clientes_siigo

    c = clientes_siigo.a_cliente({
        "id": "sg-9", "identification": "1037368561", "check_digit": "6",
        "id_type": {"code": "13"}, "name": ["ELI", "GONZALEZ"],
        "address": {"address": "CL 50 A 86-450",
                    "city": {"city_name": "Medellín"}},
        "phones": [{"number": "3117910110"}],
        "contacts": [{"first_name": "Eli", "email": "eli@correo.com"}],
    })
    assert c["correo"] == "eli@correo.com"
    assert c["tipo_documento"] == "CC"        # el código 13 de Siigo
    assert c["ciudad"] == "Medellín"
    assert c["apellido"] == "GONZALEZ"


def test_un_tipo_de_documento_DESCONOCIDO_no_se_adivina():
    """Un tipo equivocado en una factura es un rechazo de la DIAN. Si Siigo
    manda un código que no conocemos, se deja como viene y se ve."""
    from backend.modules.retail.infrastructure.siigo import clientes_siigo

    c = clientes_siigo.a_cliente({"identification": "1", "id_type": {"code": "99"}})
    assert c["tipo_documento"] == "99"


def test_una_clienta_a_la_que_le_falta_todo_no_revienta():
    from backend.modules.retail.infrastructure.siigo import clientes_siigo

    c = clientes_siigo.a_cliente({"identification": "123"})
    assert c["numero_documento"] == "123"
    assert c["correo"] == "" and c["direccion"] == ""


# ── LA PAGINACIÓN, que es donde una importación miente ──────────────────────

def test_si_siigo_dice_7000_y_solo_llegan_4000_REVIENTA(monkeypatch):
    """«Importé 4.000 clientas» cuando había 7.000 es un número que se lee como
    prueba y es falso. Las 3.000 que faltan no se descubren hasta que una de
    ellas llega al mostrador y la cajera la crea de nuevo — duplicándola en la
    contabilidad, que es justo lo que esto venía a evitar."""
    from backend.modules.retail.infrastructure.siigo import clientes_siigo
    from backend.services import siigo

    def falso(path, params=None):
        # Dice que hay 7.000 y devuelve una página corta: se acabó antes.
        return {"pagination": {"total_results": 7000},
                "results": [{"identification": str(i)} for i in range(10)]}

    monkeypatch.setattr(siigo, "siigo_get", falso)
    with pytest.raises(RuntimeError, match="7000"):
        list(clientes_siigo.paginar(page_size=100))


def test_si_la_paginacion_no_termina_tampoco_se_calla(monkeypatch):
    """Un bucle que siempre devuelve página llena. Sin tope, se importa para
    siempre; con un tope que devuelve lo que alcanzó, se importa a medias."""
    from backend.modules.retail.infrastructure.siigo import clientes_siigo
    from backend.services import siigo

    monkeypatch.setattr(siigo, "siigo_get", lambda p, params=None: {
        "pagination": {"total_results": 10 ** 9},
        "results": [{"identification": "1"}] * (params or {}).get("page_size", 2)})
    with pytest.raises(RuntimeError, match="páginas"):
        list(clientes_siigo.paginar(page_size=2, tope_paginas=3))


def test_una_lectura_COMPLETA_no_se_queja(monkeypatch):
    from backend.modules.retail.infrastructure.siigo import clientes_siigo
    from backend.services import siigo

    paginas = {1: [{"identification": "1"}, {"identification": "2"}],
               2: [{"identification": "3"}]}
    monkeypatch.setattr(siigo, "siigo_get", lambda p, params=None: {
        "pagination": {"total_results": 3},
        "results": paginas.get((params or {}).get("page", 1), [])})
    assert len(list(clientes_siigo.paginar(page_size=2))) == 3
