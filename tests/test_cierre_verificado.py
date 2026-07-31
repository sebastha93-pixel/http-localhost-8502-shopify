"""El cierre de caja se confirma contra Siigo, no contra lo que enviamos.

Hasta ahora sumaba `payload_snapshot` — lo que le MANDAMOS a Siigo. Nunca
volvia a leer la factura. Y hoy aprendimos que Siigo descarta en silencio lo
que no le gusta: paso con `warehouse` y el inventario nunca se movio mientras
creiamos que si.

Con esto, si un medio de pago no quedo en la factura, el cierre lo DICE en vez
de mandar a la cajera a buscar plata que la contabilidad no tiene.
"""
from backend.services import postventa_caja as C

DATAFONO, CAJA, ANTICIPO = 12244, 12243, 8316


def _factura(pagos):
    return {"payments": [{"id": i, "value": v} for i, v in pagos]}


def test_coincide_cuando_siigo_guardo_lo_mismo():
    r = C.comparar_pagos(enviado=[{"id": DATAFONO, "value": 30000}],
                         factura=_factura([(ANTICIPO, 169900), (DATAFONO, 30000)]))
    assert r["coincide"] is True
    assert r["en_siigo"] == 30000


def test_el_anticipo_se_ignora_en_ambos_lados():
    """No es plata de caja ni aqui ni alla."""
    r = C.comparar_pagos(enviado=[{"id": ANTICIPO, "value": 169900},
                                  {"id": CAJA, "value": 15000}],
                         factura=_factura([(ANTICIPO, 169900), (CAJA, 15000)]))
    assert r["coincide"] is True
    assert r["en_siigo"] == 15000


def test_delata_un_medio_que_siigo_no_guardo():
    """El caso que importa: mandamos dos, Siigo guardo uno."""
    r = C.comparar_pagos(
        enviado=[{"id": DATAFONO, "value": 30000}, {"id": CAJA, "value": 15000}],
        factura=_factura([(DATAFONO, 30000)]))
    assert r["coincide"] is False
    assert r["enviado"] == 45000 and r["en_siigo"] == 30000


def test_delata_un_monto_distinto():
    r = C.comparar_pagos(enviado=[{"id": DATAFONO, "value": 30000}],
                         factura=_factura([(DATAFONO, 25000)]))
    assert r["coincide"] is False


def test_tolera_el_peso_de_redondeo():
    r = C.comparar_pagos(enviado=[{"id": DATAFONO, "value": 30000}],
                         factura=_factura([(DATAFONO, 29999.6)]))
    assert r["coincide"] is True


def test_sin_factura_NO_se_da_por_confirmado():
    """Si no se pudo leer, se dice 'sin verificar' — no 'esta bien'."""
    r = C.comparar_pagos(enviado=[{"id": DATAFONO, "value": 30000}], factura=None)
    assert r["coincide"] is None
    assert r["motivo"]


def test_un_cierre_sin_cobros_no_necesita_verificacion():
    r = C.comparar_pagos(enviado=[], factura=None)
    assert r["coincide"] is True
    assert r["en_siigo"] == 0
