"""Lo que se corrige en Siigo llega al POS.

Florida, 2026-10-16: una clienta entró al POS desde Siigo con el correo
genérico de Siigo POS (`FECLIENTE@…`). Contabilidad lo corrigió en Siigo y el
POS lo siguió mostrando: la importación sólo rellena campos VACÍOS, y la caja
no tiene cómo editar una clienta. La corrección se quedaba en Siigo para
siempre.

La regla: gana lo MÁS NUEVO. Si Siigo cambió después de la última vez que el
POS tocó a la clienta, lo de Siigo manda.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, text  # noqa: E402

URL = os.environ.get("RETAIL_TEST_DATABASE_URL", "").strip()
pytestmark = pytest.mark.skipif(not URL, reason="Sin RETAIL_TEST_DATABASE_URL")

SIIGO_ID = "b638c878-0a67-4af1-923e-f3ac08e398dd"
CLIENTA = "01JQ8X4T5N6P7R8S9V0W1XCB01"


@pytest.fixture()
def motor():
    from backend.modules.retail.infrastructure.persistencia.unidad_de_trabajo import (
        normalizar_url,
    )
    from backend.modules.retail.migraciones.runner import aplicar, revertir

    revertir(URL)
    aplicar(URL)
    m = create_engine(normalizar_url(URL), future=True)
    with m.begin() as c:
        c.execute(text("""
            INSERT INTO retail.clientes
                (id, tipo_documento, numero_documento, nombre, apellido,
                 telefono, correo, siigo_customer_id, creado_por, creado_en,
                 actualizado_en)
            VALUES (:id, 'CC', '1039690075', 'acevedo', 'liza', '3117792829',
                    'feclient@disssensas.com', :sid, 'busqueda_en_caja',
                    :ts, :ts)
        """), {"id": CLIENTA, "sid": SIIGO_ID,
               "ts": datetime.now(timezone.utc) - timedelta(hours=1)})
    yield m
    m.dispose()
    revertir(URL)


def _de_siigo(**cambios) -> dict:
    base = {"siigo_customer_id": SIIGO_ID, "tipo_documento": "CC",
            "numero_documento": "1039690075", "nombre": "acevedo",
            "apellido": "liza", "telefono": "3117792829",
            "correo": "sol.leidy.melissa@hotmail.com", "direccion": "",
            "ciudad": "", "dv": None, "activo_en_siigo": True,
            "actualizado_en_siigo": datetime.now(timezone.utc)}
    base.update(cambios)
    return base


def _fila(motor) -> dict:
    with motor.connect() as c:
        return dict(c.execute(text(
            "SELECT * FROM retail.clientes WHERE id = :i"),
            {"i": CLIENTA}).mappings().one())


def test_la_correccion_de_Siigo_llega_al_POS(motor):
    from backend.modules.retail.infrastructure.siigo import clientes_corregidos

    n = clientes_corregidos.traer(URL, leer=lambda: [_de_siigo()])

    assert n == 1
    fila = _fila(motor)
    assert fila["correo"] == "sol.leidy.melissa@hotmail.com"
    # Lo que no vino distinto, no se toca.
    assert (fila["nombre"], fila["apellido"]) == ("acevedo", "liza")
    assert fila["ciudad"] is None


def test_lo_que_el_POS_cambio_DESPUES_no_se_pisa(motor):
    """Si el POS tocó a la clienta después de la última edición en Siigo,
    lo del POS es más nuevo."""
    from backend.modules.retail.infrastructure.siigo import clientes_corregidos

    viejo = datetime.now(timezone.utc) - timedelta(days=1)
    n = clientes_corregidos.traer(
        URL, leer=lambda: [_de_siigo(actualizado_en_siigo=viejo)])

    assert n == 0
    assert _fila(motor)["correo"] == "feclient@disssensas.com"


def test_un_campo_vacio_en_Siigo_no_borra_el_del_POS(motor):
    from backend.modules.retail.infrastructure.siigo import clientes_corregidos

    clientes_corregidos.traer(
        URL, leer=lambda: [_de_siigo(telefono="", correo="")])

    fila = _fila(motor)
    assert fila["telefono"] == "3117792829"
    assert fila["correo"] == "feclient@disssensas.com"


def test_correrlo_dos_veces_no_vuelve_a_cambiar_nada(motor):
    from backend.modules.retail.infrastructure.siigo import clientes_corregidos

    leer = lambda: [_de_siigo(  # noqa: E731
        actualizado_en_siigo=datetime.now(timezone.utc) - timedelta(minutes=5))]
    assert clientes_corregidos.traer(URL, leer=leer) == 1
    assert clientes_corregidos.traer(URL, leer=leer) == 0


def test_una_clienta_que_el_POS_no_tiene_no_se_crea_aqui(motor):
    """Crear es de la búsqueda en caja y de la importación; esto sólo pone al
    día a las que ya están enlazadas."""
    from backend.modules.retail.infrastructure.siigo import clientes_corregidos

    otra = _de_siigo(siigo_customer_id="otra-de-siigo",
                     numero_documento="43180115")
    assert clientes_corregidos.traer(URL, leer=lambda: [otra]) == 0
    with motor.connect() as c:
        assert c.execute(text("SELECT count(*) FROM retail.clientes")).scalar() == 1


def test_el_correo_se_compara_sin_mayusculas(motor):
    """Siigo lo devuelve como lo escribió contabilidad; el POS lo guarda en
    minúscula. «Distinto» por mayúsculas no es una corrección."""
    from backend.modules.retail.infrastructure.siigo import clientes_corregidos

    with motor.begin() as c:
        c.execute(text("UPDATE retail.clientes SET correo = 'sol.leidy.melissa@hotmail.com'"))
    n = clientes_corregidos.traer(
        URL, leer=lambda: [_de_siigo(correo="SOL.LEIDY.MELISSA@HOTMAIL.COM")])
    assert n == 0


def test_la_fecha_de_Siigo_se_lee_como_UTC():
    """`metadata.last_updated` llega sin zona (`2026-10-16T20:19:25.053`). Es
    UTC: medido el 16-oct contra una clienta creada en el POS a las 19:53 UTC
    y corregida en Siigo 26 minutos después."""
    from backend.modules.retail.infrastructure.siigo.clientes_siigo import a_cliente

    c = a_cliente({"id": SIIGO_ID, "identification": "1039690075",
                   "name": ["acevedo", "liza"],
                   "metadata": {"last_updated": "2026-10-16T20:19:25.053"}})
    assert c["actualizado_en_siigo"] == datetime(
        2026, 10, 16, 20, 19, 25, 53000, tzinfo=timezone.utc)
