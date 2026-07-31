"""Inventario de tienda servido desde NUESTRA base, no desde Siigo.

Antes cada busqueda le pedia a Siigo el catalogo completo (hasta 80 paginas
a ~1 peticion/segundo). Con 4 workers de uvicorn y un cache en memoria POR
PROCESO, la busqueda caia en un worker con cache caliente —instantanea— y la
verificacion en otro con cache frio, que respondia "no se pudo leer el
inventario" sobre una prenda que si existia.

Aqui se prueba el ARMADO de las filas (puro). La consulta a Supabase va
aparte.
"""
from backend.services import postventa_inventario as I


CRUDO = {"referencias": [
    {"code": "92611-1T6", "referencia": "92611-1", "talla": "6",
     "nombre": "JEAN WIDE LEG GRIS", "stock": {"Florida": 6, "Arrayanes": 2},
     "total": 8},
    {"code": "92611-1T8", "referencia": "92611-1", "talla": "8",
     "nombre": "JEAN WIDE LEG GRIS", "stock": {"Florida": 3}, "total": 3},
]}


def test_una_fila_por_referencia_y_bodega():
    filas = I.filas_desde_siigo(CRUDO, brand_id="male")
    assert len(filas) == 3          # T6 en dos bodegas + T8 en una


def test_cada_fila_lleva_su_bodega_y_cantidad():
    porc = {(f["code"], f["bodega"]): f for f in I.filas_desde_siigo(CRUDO, brand_id="male")}
    assert porc[("92611-1T6", "Florida")]["cantidad"] == 6
    assert porc[("92611-1T6", "Arrayanes")]["cantidad"] == 2


def test_no_guarda_bodegas_en_cero():
    """Ocupan espacio y ensucian la busqueda sin aportar nada."""
    crudo = {"referencias": [{"code": "X-1", "stock": {"Florida": 0}, "total": 0}]}
    assert I.filas_desde_siigo(crudo, brand_id="male") == []


def test_lleva_la_marca_para_multi_tenant():
    assert all(f["brand_id"] == "male"
               for f in I.filas_desde_siigo(CRUDO, brand_id="male"))


def test_un_inventario_vacio_no_revienta():
    assert I.filas_desde_siigo({}, brand_id="male") == []


# ── Frescura: la asesora tiene que saber de cuando es el dato ──────────────

def test_dice_hace_cuanto_se_actualizo():
    assert I.frescura_texto(0) == "actualizado hace un momento"
    assert "5 minutos" in I.frescura_texto(5 * 60)
    assert "2 horas" in I.frescura_texto(2 * 3600)


def test_avisa_cuando_el_dato_esta_viejo():
    """Un inventario de ayer puede hacer prometer una prenda que ya se vendio."""
    assert I.esta_viejo(3 * 3600) is True
    assert I.esta_viejo(10 * 60) is False


def test_sin_fecha_se_considera_viejo():
    assert I.esta_viejo(None) is True
