"""Elegir la misma prenda dos veces no ensucia el historial.

En un caso real quedaron CINCO eventos "Se lleva 92611-1T10": la asesora
volvio a la lista y reeligio mientras ajustaba el precio. El historial es lo
que se mira cuando algo no cuadra; cinco lineas iguales lo vuelven ruido.
"""
from backend.services import postventa_logic as L


def test_reelegir_la_misma_referencia_no_es_un_cambio():
    assert L.hubo_cambio_de_reemplazo("A-1", "A-1") is False


def test_elegir_otra_si_lo_es():
    assert L.hubo_cambio_de_reemplazo("A-1", "B-2") is True


def test_elegir_por_primera_vez_lo_es():
    assert L.hubo_cambio_de_reemplazo(None, "B-2") is True
    assert L.hubo_cambio_de_reemplazo("", "B-2") is True


def test_no_se_deja_enganar_por_espacios_ni_mayusculas():
    assert L.hubo_cambio_de_reemplazo(" a-1 ", "A-1") is False
