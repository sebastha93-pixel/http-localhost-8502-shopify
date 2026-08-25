"""El viaje de ida y vuelta del IVA.

Un precio de vitrina se guarda sin IVA y la pantalla vuelve a sumarlo. Si ese
viaje no regresa al mismo número, la cajera ve $139.900,01 en la etiqueta de
una prenda que cuesta $139.900 — y eso no se explica en un mostrador.
"""
import pytest

from backend.modules.retail.domain.shared.impuestos import (
    base_desde_vitrina,
    con_iva,
    iva_de,
)


def test_el_caso_que_lo_destapo():
    """$139.900 con la división ingenua volvía como $139.900,01.

    Y resultó que NINGUNA base da 13.990.000 exacto: el total salta de
    13.989.999 a 13.990.001. Lo que sí se garantiza es que nunca se cobre de
    más — el centavo perdido va a favor de la clienta.
    """
    base = base_desde_vitrina(13990000)
    assert con_iva(base) <= 13990000
    assert 13990000 - con_iva(base) <= 1


@pytest.mark.parametrize("vitrina", [
    16990000, 18990000, 10990000, 13990000, 24990000, 7990000,
])
def test_ningun_precio_del_catalogo_se_cobra_de_mas(vitrina):
    """Regresar exacto no siempre es posible; cobrar de más nunca es
    aceptable."""
    vuelta = con_iva(base_desde_vitrina(vitrina))
    assert vuelta <= vitrina
    assert vitrina - vuelta <= 1


def test_cuantos_precios_son_inalcanzables():
    """Mide el problema en vez de esconderlo.

    Con IVA del 19% hay totales que NINGUNA base puede formar. Esta prueba
    fija cuántos son —para que si alguien cambia el redondeo y empeora, se
    note— y garantiza que ninguno se cobra de más.
    """
    precios = list(range(100000, 100000001, 10000))   # $1.000 … $1.000.000
    inalcanzables = [p for p in precios if con_iva(base_desde_vitrina(p)) != p]

    assert all(con_iva(base_desde_vitrina(p)) < p for p in inalcanzables)
    # Alrededor de un 16%: uno de cada seis precios redondos.
    assert len(inalcanzables) / len(precios) < 0.2


def test_el_modelo_del_handoff_SI_cierra_siempre():
    """`separar_iva` no puede fallar: la base sale por resta.

    Es el modelo correcto —el precio ES el de vitrina y el IVA se deriva— y
    por eso base + IVA da el total exacto para cualquier precio.
    """
    from backend.modules.retail.domain.shared.impuestos import separar_iva

    for p in range(100000, 100000001, 10000):
        base, iva = separar_iva(p)
        assert base + iva == p


def test_tambien_con_otras_tarifas():
    """El día que entre un producto exento o al 5%, no puede reventar."""
    from backend.modules.retail.domain.shared.impuestos import separar_iva

    for tasa in (0, 5, 19):
        for vitrina in (5000000, 13990000, 24990000):
            base, iva = separar_iva(vitrina, tasa)
            assert base + iva == vitrina


def test_exento_no_toca_el_precio():
    assert base_desde_vitrina(13990000, 0) == 13990000
    assert iva_de(13990000, 0) == 0


def test_no_acepta_float():
    with pytest.raises(TypeError):
        iva_de(1000, 19.0)


def test_precio_en_cero():
    assert base_desde_vitrina(0) == 0
