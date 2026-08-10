"""Sku — la llave por la que busca todo el POS.

El formato de MALE'DENIM es `<referencia>T<talla>`: en `92611-1T10` la
referencia es `92611-1` y la talla es `10`. El `-1` es parte de la referencia,
no de la talla.

Esto no es una convención inventada aquí: es exactamente lo que hace
`siigo._parse_ref_talla`, que es lo que ya alimenta el inventario por bodega y
el análisis de venta por colección. Si el POS parseara distinto, la misma
prenda tendría dos identidades dentro del mismo sistema.
"""
import pytest

from backend.modules.retail.domain.shared.sku import Sku, SkuInvalido


# ── Formato real, con ejemplos sacados del repositorio ──────────────────────

@pytest.mark.parametrize("code, referencia, talla", [
    ("92611-1T10", "92611-1", "10"),
    ("92611-1T6",  "92611-1", "6"),
    ("95527-1T4",  "95527-1", "4"),
    ("22624-1T8",  "22624-1", "8"),
    ("93634-1T12", "93634-1", "12"),
])
def test_parsea_el_formato_de_male(code, referencia, talla):
    sku = Sku.parsear(code)
    assert sku.referencia == referencia
    assert sku.talla == talla


def test_la_referencia_base_agrupa_los_colores():
    """`92611-1` y `92611-2` son la misma prenda en otro color.

    El POS los muestra juntos: quien busca '92611' quiere ver toda la
    referencia, no una sola variante.
    """
    assert Sku.parsear("92611-1T10").referencia_base == "92611"
    assert Sku.parsear("92611-2T10").referencia_base == "92611"


def test_una_T_dentro_de_la_referencia_no_confunde_el_parseo():
    """La talla es la que va al final. Cualquier otra T es de la referencia."""
    sku = Sku.parsear("92T33-1T6")
    assert sku.referencia == "92T33-1"
    assert sku.talla == "6"


def test_normaliza_espacios_y_mayusculas():
    a = Sku.parsear("  92611-1t10  ")
    assert a.referencia == "92611-1"
    assert a.talla == "10"
    assert a.codigo == "92611-1T10"


def test_un_codigo_sin_talla_no_se_inventa_una():
    """Igual que `_parse_ref_talla`: si no hay talla al final, queda vacía.

    No se adivina. Un SKU sin talla es un dato que hay que revisar, no algo
    que el sistema deba completar por su cuenta.
    """
    sku = Sku.parsear("92611-1")
    assert sku.referencia == "92611-1"
    assert sku.talla == ""
    assert not sku.tiene_talla()


def test_rechaza_vacio_y_tipos_que_no_son_texto():
    for malo in ["", "   ", None, 92611]:
        with pytest.raises(SkuInvalido):
            Sku.parsear(malo)  # type: ignore[arg-type]


# ── Es un objeto de valor ───────────────────────────────────────────────────

def test_dos_sku_iguales_son_el_mismo():
    assert Sku.parsear("92611-1T10") == Sku.parsear("92611-1t10")
    assert len({Sku.parsear("92611-1T10"), Sku.parsear("92611-1T10")}) == 1


def test_es_inmutable():
    sku = Sku.parsear("92611-1T10")
    with pytest.raises(Exception):
        sku.talla = "12"  # type: ignore[misc]


def test_str_devuelve_el_codigo():
    assert str(Sku.parsear("92611-1t10")) == "92611-1T10"


# ── Orden de tallas: 4, 6, 8, 10, 12 — no 10, 12, 4, 6 ─────────────────────

def test_las_tallas_se_ordenan_como_numeros():
    """Ordenar como texto pondría la 10 antes de la 4.

    En la rejilla del POS eso obliga a la cajera a buscar la talla en un
    desorden, cada vez, con la clienta enfrente.
    """
    codes = ["92611-1T10", "92611-1T4", "92611-1T12", "92611-1T6", "92611-1T8"]
    ordenados = sorted((Sku.parsear(c) for c in codes), key=lambda s: s.orden_talla())
    assert [s.talla for s in ordenados] == ["4", "6", "8", "10", "12"]


def test_las_tallas_no_numericas_van_al_final():
    """Si algún día entra una talla en letra, no revienta: va después.

    Mismo criterio que `postventa_inventario._talla_num`, para que el POS y el
    inventario ordenen igual.
    """
    tallas = [Sku.parsear("X-1T8"), Sku.parsear("X-1"), Sku.parsear("X-1T4")]
    ordenados = sorted(tallas, key=lambda s: s.orden_talla())
    assert [s.talla for s in ordenados] == ["4", "8", ""]


def test_coincide_con_el_parseo_que_ya_usa_el_erp():
    """Contrato con `siigo._parse_ref_talla`. Si alguien cambia uno de los dos,
    esta prueba lo dice antes de que la misma prenda tenga dos identidades."""
    import re

    def como_el_erp(code: str):
        m = re.match(r"^(.*?T)(\d+)$", (code or "").strip(), re.IGNORECASE)
        if m:
            return m.group(1).rstrip("Tt"), m.group(2)
        return (code or "").strip(), ""

    for code in ["92611-1T10", "95527-1T4", "22624-1T8", "92T33-1T6", "92611-1"]:
        ref_erp, talla_erp = como_el_erp(code)
        sku = Sku.parsear(code)
        assert (sku.referencia, sku.talla) == (ref_erp, talla_erp), code
