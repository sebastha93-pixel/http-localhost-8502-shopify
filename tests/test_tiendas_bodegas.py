"""Las bodegas configuradas tienen que EXISTIR en Siigo.

Historia: se configuro Florida=5 y Arrayanes=3 porque ese es el numero que
se ve en la pantalla de Siigo. La API usa otros: Florida=48, Arrayanes=37.
Siigo respondio "The warehouse doesn't exist: 5" solo cuando por fin le
llego el campo bien formado — antes lo descartaba en silencio.

Mismo patron que los tipos de documento (FV-11 -> 31433): el numero visible
NO es el id de la API. Nunca se configura un id sin confirmarlo contra Siigo.
"""
from backend.services import tiendas


BODEGAS_SIIGO = [
    {"id": 16, "name": "INSUMOS", "active": True},
    {"id": 32, "name": "MELONN", "active": True},
    {"id": 37, "name": "Arrayanes", "active": True},
    {"id": 45, "name": "Segundas", "active": True},
    {"id": 48, "name": "Florida", "active": True},
]


def test_florida_usa_el_id_real_de_la_api():
    assert tiendas.BODEGA_FLORIDA == 48


def test_arrayanes_usa_el_id_real_de_la_api():
    assert tiendas.BODEGA_ARRAYANES == 37


def test_las_dos_cajas_de_florida_comparten_bodega():
    assert (tiendas.obtener("florida_caja1")["bodega_id"]
            == tiendas.obtener("florida_caja2")["bodega_id"] == 48)


def test_todas_las_bodegas_configuradas_existen_en_siigo():
    assert tiendas.bodegas_invalidas(BODEGAS_SIIGO) == []


def test_delata_una_bodega_que_no_existe():
    """Lo que habria cazado el bug antes de emitir."""
    malas = tiendas.bodegas_invalidas([{"id": 32, "name": "MELONN", "active": True}])
    claves = {m["tienda"] for m in malas}
    assert claves == {"florida_caja1", "florida_caja2", "arrayanes"}
    assert malas[0]["motivo"] == "no_existe"


def test_delata_una_bodega_inactiva():
    """Siigo la rechaza igual: 'debe existir y estar activo'."""
    apagada = [dict(b, active=False) if b["id"] == 48 else b for b in BODEGAS_SIIGO]
    malas = tiendas.bodegas_invalidas(apagada)
    assert {m["tienda"] for m in malas} == {"florida_caja1", "florida_caja2"}
    assert malas[0]["motivo"] == "inactiva"


def test_sin_datos_de_siigo_no_inventa_un_veredicto():
    """Si no se pudo consultar Siigo, no se puede decir que este bien."""
    assert tiendas.bodegas_invalidas([]) is None
