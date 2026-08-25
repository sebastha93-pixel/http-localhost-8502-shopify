"""El hash de la cadena de auditoría — función pura, sin base de datos.

Va en su propio archivo porque el resto de `integracion` lleva la marca
asyncio y un fixture de PostgreSQL, y esto no necesita ninguno de los dos.
"""
import pytest

pytest.importorskip("sqlalchemy")

from backend.modules.retail.infrastructure.persistencia.repo_auditoria import (  # noqa: E402
    GENESIS,
    calcular_hash,
)


def test_no_depende_del_orden_de_las_claves():
    """Sin esto, la verificación fallaría por el orden de un diccionario y
    nadie sabría por qué. El payload se serializa con sort_keys."""
    a = calcular_hash("x", {"total": 100, "sku": "92611-1T10"})
    b = calcular_hash("x", {"sku": "92611-1T10", "total": 100})
    assert a == b


def test_cambiar_un_solo_centavo_cambia_el_hash():
    """Es toda la utilidad de la cadena: bajarle el monto a un descuento
    indebido tiene que ser detectable."""
    a = calcular_hash(GENESIS, {"monto": 8566387})
    b = calcular_hash(GENESIS, {"monto": 8566386})
    assert a != b


def test_el_mismo_evento_en_distinta_posicion_da_hash_distinto():
    """El eslabón anterior entra en el cálculo: por eso no se puede reordenar
    ni reinsertar un evento sin que se note."""
    assert calcular_hash(GENESIS, {"e": 1}) != calcular_hash("otro", {"e": 1})
