"""¿Puede el POS emitir con los comprobantes que hoy usa Siigo POS?

EL PLAN ES QUEDARSE CON LAS RESOLUCIONES QUE YA EXISTEN (`FL`, `FV-11`,
`FV-12`, `FV-6`), no crear unas nuevas. Y hay evidencia medida contra
producción —anotada en `codigo/backend/services/tiendas.py`— de que hoy no se
puede: `POST /invoices` responde «The id cannot be used, you must verify the
document settings».

EL MECANISMO ES UNA AUSENCIA, NO UNA BANDERA. La documentación oficial de
`/document-types` lista `id, code, name, type, active, consecutive,
automatic_number, electronic_type, prefix, cost_center…` y no trae ningún campo
que diga «es de punto de venta». Los comprobantes atados al POS de Siigo
simplemente NO SALEN en la respuesta.

Se prueba con un Siigo falso porque las credenciales viven en Railway. Lo que
se comprueba aquí no es qué contesta la cuenta de MALE —eso hay que ir a
mirarlo— sino que el diagnóstico INTERPRETE BIEN las tres respuestas posibles.
"""
from __future__ import annotations

import pytest


def _tipo(code, **kw):
    base = {"id": 99999, "code": code, "name": f"Factura {code}", "type": "FV",
            "active": True, "consecutive": 1, "automatic_number": False,
            "electronic_type": "ElectronicInvoice", "cost_center_mandatory": False}
    base.update(kw)
    return base


@pytest.fixture()
def siigo_falso(monkeypatch):
    from backend.services import siigo

    estado = {"tipos": [], "pagos": []}

    def falso(path, params=None):
        if path == "/document-types":
            return estado["tipos"]
        if path == "/payment-types":
            return estado["pagos"]
        raise AssertionError(f"llamada inesperada: {path}")

    monkeypatch.setattr(siigo, "siigo_get", falso)
    monkeypatch.setattr(siigo, "siigo_configurado", lambda: True)
    return estado


# ── El caso que hay que descartar antes de escribir el emisor ───────────────

def test_si_el_prefijo_NO_aparece_dice_que_hay_que_reconfigurarlo(siigo_falso):
    """Es lo que el código de MALE ya midió: `/document-types` no devuelve
    FV-11 ni FV-12, y por eso `POST /invoices` los rechaza. El diagnóstico
    tiene que decirlo con todas las letras, no dejarlo a interpretación."""
    from backend.modules.retail.infrastructure.siigo import comprobantes_siigo

    siigo_falso["tipos"] = [_tipo("FV-1", id=11810, consecutive=4021)]
    d = comprobantes_siigo.diagnostico_comprobantes()

    assert d["veredicto"]["FL"]["emitible_por_api"] is False
    assert "punto de venta" in d["veredicto"]["FL"]["por_que"]
    assert "reconfigurar" in d["resumen"].lower()
    # Y dice cuál queda como alternativa, con su costo.
    assert "FV-1" in d["resumen"]
    assert "mezclar el canal" in d["resumen"]


def test_si_el_prefijo_SI_aparece_da_el_numero_del_RELEVO(siigo_falso):
    """`consecutive` es dónde va la numeración HOY. Es el dato que evita que el
    POS arranque en 1 y pise facturas ya emitidas bajo la misma resolución —y
    se lee de la API, no de una tirilla impresa."""
    from backend.modules.retail.infrastructure.siigo import comprobantes_siigo

    siigo_falso["tipos"] = [_tipo("FL", id=40011, consecutive=1536)]
    d = comprobantes_siigo.diagnostico_comprobantes()

    v = d["veredicto"]["FL"]
    assert v["emitible_por_api"] is True
    assert v["consecutive"] == 1536
    assert v["document_id"] == 40011
    assert "continuar desde ese número" in d["resumen"]


def test_automatic_number_viaja_porque_cambia_QUIEN_numera(siigo_falso):
    """Si el número lo pone Siigo, el que la tableta ya imprimió en el papel NO
    es el de la factura. Eso cambia cómo se numera, y la numeración ya está en
    producción de pruebas."""
    from backend.modules.retail.infrastructure.siigo import comprobantes_siigo

    siigo_falso["tipos"] = [_tipo("FL", automatic_number=True)]
    d = comprobantes_siigo.diagnostico_comprobantes()
    assert d["veredicto"]["FL"]["automatic_number"] is True


def test_un_comprobante_INACTIVO_no_cuenta_como_emitible(siigo_falso):
    """FV-5 «Cambios» está en la cuenta pero inactivo. Aparecer en la lista no
    basta: emitir con uno inactivo falla en el momento del cobro."""
    from backend.modules.retail.infrastructure.siigo import comprobantes_siigo

    siigo_falso["tipos"] = [_tipo("FV-5", id=27154, active=False)]
    d = comprobantes_siigo.diagnostico_comprobantes()
    assert d["veredicto"]["FV-5"]["emitible_por_api"] is False


def test_trae_las_formas_de_pago_CON_SU_ID(siigo_falso):
    """Es lo que falta para Addi, Wompi y Sumas. El código de MALE sólo lee el
    NOMBRE de los pagos de una factura (`payments[].name`), nunca el id — por
    eso los ids no estaban en el repo aunque los medios sí existan en Siigo."""
    from backend.modules.retail.infrastructure.siigo import comprobantes_siigo

    siigo_falso["tipos"] = [_tipo("FV-1")]
    siigo_falso["pagos"] = [{"id": 12243, "name": "EFECTIVO"},
                            {"id": 20551, "name": "ADDI PAYMENT"}]
    d = comprobantes_siigo.diagnostico_comprobantes()

    assert {p["name"] for p in d["formas_pago"]} == {"EFECTIVO", "ADDI PAYMENT"}


def test_sin_credenciales_lo_dice_en_vez_de_reventar(monkeypatch):
    from backend.services import siigo
    from backend.modules.retail.infrastructure.siigo import comprobantes_siigo

    monkeypatch.setattr(siigo, "siigo_configurado", lambda: False)
    assert comprobantes_siigo.diagnostico_comprobantes() == {
        "_error": "siigo_no_configurado"}


def test_lista_lo_que_siigo_SI_devuelve(siigo_falso):
    """Para poder ver de un vistazo qué comprobantes hay disponibles, sin
    tener que adivinar cuál pedir."""
    from backend.modules.retail.infrastructure.siigo import comprobantes_siigo

    siigo_falso["tipos"] = [_tipo("FV-1"), _tipo("FV-2"), _tipo("FV-5")]
    d = comprobantes_siigo.diagnostico_comprobantes()
    assert d["prefijos_que_devuelve_siigo"] == ["FV-1", "FV-2", "FV-5"]
