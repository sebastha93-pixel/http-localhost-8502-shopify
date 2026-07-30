"""Con que medios de pago se cobro el excedente.

La factura del cambio sale por FV-1 (los prefijos de caja no se pueden usar
por API), asi que la caja de la tienda NO la ve en su consecutivo. Para que
el arqueo diario cuadre igual, hay que dejar marcado con que medio se cobro
y cuanto: datafono Florida, efectivo caja Florida, etc.

Se permite repartir entre varios medios, como en el POS (parte tarjeta,
parte efectivo). Lo que no se permite es que la suma no de.
"""
import pytest
from backend.services import fiscal_logic as F
from backend.services import tiendas

DATAFONO_FL = 12244
CAJA_FL = 12243
DATAFONO_ARR = 8987


def test_un_solo_medio_cubre_el_excedente():
    pagos = F.repartir_excedente([{"id": DATAFONO_FL, "value": 30000}], 30000)
    assert pagos == [{"id": DATAFONO_FL, "value": 30000.0}]


def test_se_puede_partir_entre_tarjeta_y_efectivo():
    """Como en la caja: 20 mil con tarjeta y 10 mil en efectivo."""
    pagos = F.repartir_excedente(
        [{"id": DATAFONO_FL, "value": 20000}, {"id": CAJA_FL, "value": 10000}], 30000)
    assert sum(p["value"] for p in pagos) == 30000


def test_si_no_suma_se_rechaza():
    """Descuadrar la caja en silencio es exactamente lo que se quiere evitar."""
    with pytest.raises(ValueError) as e:
        F.repartir_excedente([{"id": DATAFONO_FL, "value": 25000}], 30000)
    assert "25.000" in str(e.value) and "30.000" in str(e.value)


def test_tolera_el_centavo_del_redondeo():
    F.repartir_excedente([{"id": DATAFONO_FL, "value": 29999.6}], 30000)


def test_sin_excedente_no_se_piden_medios():
    assert F.repartir_excedente([], 0) == []


def test_con_excedente_pero_sin_medios_se_rechaza():
    """Si nadie dice como se cobro, el arqueo no se puede cruzar."""
    with pytest.raises(ValueError):
        F.repartir_excedente([], 30000)


def test_un_medio_en_cero_no_cuenta():
    pagos = F.repartir_excedente(
        [{"id": DATAFONO_FL, "value": 30000}, {"id": CAJA_FL, "value": 0}], 30000)
    assert len(pagos) == 1


# ── El medio tiene que ser de ESA caja ─────────────────────────────────────

def test_la_caja_de_otra_tienda_se_rechaza():
    """Cobrar en el datafono de Florida un cambio de Arrayanes descuadra las
    dos cajas a la vez."""
    malos = tiendas.pagos_ajenos("arrayanes", [{"id": DATAFONO_FL, "value": 30000}])
    assert malos == [DATAFONO_FL]


def test_los_medios_propios_pasan():
    assert tiendas.pagos_ajenos("arrayanes", [{"id": DATAFONO_ARR, "value": 30000}]) == []


def test_el_anticipo_no_es_un_medio_de_caja():
    """El anticipo lo pone el sistema, no la cajera: no se valida contra la
    tienda ni entra al arqueo."""
    assert tiendas.pagos_ajenos(
        "arrayanes", [{"id": F.ANTICIPO_CLIENTES_ID, "value": 100000}]) == []
