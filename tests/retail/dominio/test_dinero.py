"""Dinero — el objeto de valor del que cuelga todo el módulo retail.

POR QUÉ EXISTE ESTE ARCHIVO: en este mismo repositorio un cambio salió
facturado por 67.960 cuando la prenda valía 169.900, porque el precio se tomó
de una fuente que ya traía el IVA incluido y se volvió a normalizar
(`postventa_inventario.precio_base`). Nadie se enteró hasta que la factura ya
estaba emitida.

La lección no fue "revisar mejor". Fue que la aritmética de dinero en float, y
la ambigüedad sobre si un número lleva IVA o no, producen errores que ninguna
prueba de humo detecta: el resultado es un número plausible.

Estas pruebas corren sin base de datos, sin red y sin FastAPI.
"""
from decimal import Decimal

import pytest

from backend.modules.retail.domain.shared.dinero import Dinero, MonedaDistinta


COP = "COP"


# ── Construcción ────────────────────────────────────────────────────────────

def test_se_construye_desde_centavos_enteros():
    d = Dinero(16990000, COP)
    assert d.centavos == 16990000
    assert d.moneda == COP


def test_desde_pesos_acepta_texto_y_decimal():
    assert Dinero.desde_pesos("169900", COP).centavos == 16990000
    assert Dinero.desde_pesos(Decimal("169900.45"), COP).centavos == 16990045
    assert Dinero.desde_pesos(169900, COP).centavos == 16990000


def test_rechaza_float_al_construir():
    """El float es exactamente cómo entró el bug de los 169.900.

    No se acepta ni siquiera un float 'que se ve bien': 0.1 + 0.2 no es 0.3, y
    un centavo perdido por línea es una factura que no cuadra con el arqueo.
    """
    with pytest.raises(TypeError, match="float"):
        Dinero.desde_pesos(169900.0, COP)
    with pytest.raises(TypeError, match="float"):
        Dinero(16990000.0, COP)  # type: ignore[arg-type]


def test_cero():
    assert Dinero.cero(COP).centavos == 0
    assert Dinero.cero(COP).es_cero()


# ── Aritmética ──────────────────────────────────────────────────────────────

def test_suma_y_resta():
    a = Dinero.desde_pesos("169900", COP)
    b = Dinero.desde_pesos("89900", COP)
    assert (a + b).centavos == 25980000
    assert (a - b).centavos == 8000000


def test_multiplicar_por_cantidad():
    assert (Dinero.desde_pesos("169900", COP) * 3).centavos == 50970000


def test_multiplicar_por_float_no_se_permite():
    with pytest.raises(TypeError):
        Dinero.desde_pesos("169900", COP) * 1.5  # type: ignore[operator]


def test_sumar_monedas_distintas_es_un_error():
    """Sumar COP con USD produce un número. Ese es el problema."""
    with pytest.raises(MonedaDistinta):
        Dinero(100, COP) + Dinero(100, "USD")


def test_comparaciones():
    a = Dinero.desde_pesos("100", COP)
    b = Dinero.desde_pesos("200", COP)
    assert a < b and b > a and a != b
    assert a == Dinero.desde_pesos("100", COP)
    assert not Dinero.desde_pesos("-1", COP).es_positivo()


def test_es_inmutable():
    d = Dinero(100, COP)
    with pytest.raises(Exception):
        d.centavos = 200  # type: ignore[misc]


# ── Porcentajes: el redondeo tiene que ser una decisión, no un accidente ────

def test_porcentaje_redondea_medio_hacia_arriba():
    """La facturación colombiana redondea medio hacia arriba, no al par.

    El redondeo bancario (ROUND_HALF_EVEN, el de Python por defecto) daría
    otro resultado en los empates, y la diferencia aparece en el arqueo.
    """
    # 1.005 pesos exactos = 100,5 centavos → 101, no 100
    assert Dinero(201, COP).porcentaje(Decimal("50")).centavos == 101


def test_porcentaje_de_un_descuento_real():
    precio = Dinero.desde_pesos("89900", COP)
    assert precio.porcentaje(Decimal("10")).centavos == 899000  # $8.990


def test_porcentaje_no_acepta_float():
    with pytest.raises(TypeError):
        Dinero.desde_pesos("100", COP).porcentaje(10.0)  # type: ignore[arg-type]


# ── Reparto: distribuir sin perder ni inventar centavos ─────────────────────

def test_repartir_en_partes_iguales_no_pierde_centavos():
    """$100 entre 3 no es $33,33 tres veces: falta un centavo.

    Ese centavo tiene que ir a alguna parte. Si se pierde, el total de las
    líneas no suma el total de la factura y Siigo la rechaza —o peor, la
    acepta y el descuadre aparece en el cierre del mes.
    """
    partes = Dinero(10000, COP).repartir(3)
    assert [p.centavos for p in partes] == [3334, 3333, 3333]
    assert sum(p.centavos for p in partes) == 10000


def test_repartir_proporcional_conserva_el_total():
    """Un descuento global de $10.000 sobre líneas de $30.000 y $70.000."""
    partes = Dinero.desde_pesos("10000", COP).repartir_proporcional([30000, 70000])
    assert sum(p.centavos for p in partes) == 1000000
    assert [p.centavos for p in partes] == [300000, 700000]


def test_repartir_proporcional_con_residuo():
    partes = Dinero(1000, COP).repartir_proporcional([1, 1, 1])
    assert sum(p.centavos for p in partes) == 1000
    assert [p.centavos for p in partes] == [334, 333, 333]


def test_repartir_entre_cero_es_un_error():
    with pytest.raises(ValueError):
        Dinero(100, COP).repartir(0)


def test_repartir_proporcional_sobre_pesos_en_cero():
    """Todas las líneas en cero: no hay proporción posible, se reparte igual."""
    partes = Dinero(900, COP).repartir_proporcional([0, 0, 0])
    assert sum(p.centavos for p in partes) == 900


# ── Bordes con la realidad de Siigo ─────────────────────────────────────────

def test_a_decimal_para_el_payload_de_siigo():
    """Siigo recibe decimales, no centavos. La conversión ocurre en el borde."""
    assert Dinero(16990000, COP).a_decimal() == Decimal("169900.00")
    assert Dinero(16990045, COP).a_decimal() == Decimal("169900.45")


def test_formateo_para_la_pantalla():
    assert Dinero.desde_pesos("169900", COP).formateado() == "$169.900"
    assert Dinero.desde_pesos("1699000", COP).formateado() == "$1.699.000"
    assert Dinero.desde_pesos("-8990", COP).formateado() == "-$8.990"
    assert Dinero.cero(COP).formateado() == "$0"


def test_formateo_muestra_centavos_solo_si_los_hay():
    """En COP el peso es la unidad. Mostrar ',00' en cada precio es ruido."""
    assert Dinero(16990045, COP).formateado() == "$169.900,45"
