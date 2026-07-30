"""La bodega va como NUMERO en el POST de Siigo, no como objeto.

Doc oficial (siigoapi.docs.apiary.io):
    items.warehouse  number  Identificador de la bodega/almacen asociada al
                             producto. Campo opcional, si se envia debe existir
                             en Siigo nube y estar activo.

Mandabamos {"id": 5}. Siigo descarta en silencio un campo opcional mal
formado: la NC se creaba bien, pero SIN bodega, y el inventario no se movia.
Es la misma asimetria de `taxes` (el GET los expande, el POST los quiere
planos) que ya nos habia costado un rechazo.
"""
from backend.services import fiscal_logic as F


FACTURA = {"id": "f1", "name": "FV-11-1202", "date": "2026-07-30",
           "customer": {"identification": "43424374"},
           "items": [{"code": "95527-1T10", "description": "JEAN", "quantity": 1,
                      "price": 125966.39, "seller": 937,
                      # El GET de Siigo lo devuelve EXPANDIDO como objeto.
                      "warehouse": {"id": 32, "name": "MELONN"},
                      "taxes": [{"id": 6352, "name": "IVA 19%", "percentage": 19}]}]}


def _item_nc(**kw):
    p = F.construir_payload_nota_credito(
        factura=FACTURA, skus_a_acreditar=["95527-1T10"],
        modo="prueba", fecha="2026-07-30", **kw)
    return p["items"][0]


def test_la_bodega_de_la_nc_va_como_numero():
    assert _item_nc(bodega_destino=5)["warehouse"] == 5


def test_no_va_como_objeto():
    """Con {'id': 5} Siigo lo ignora y el stock nunca se mueve."""
    assert not isinstance(_item_nc(bodega_destino=5)["warehouse"], dict)


def test_al_copiar_de_la_factura_tambien_se_aplana():
    """El GET la trae como {'id': 32, 'name': 'MELONN'}; el POST quiere 32."""
    assert _item_nc()["warehouse"] == 32


def test_sin_bodega_el_campo_no_se_manda():
    sin = {**FACTURA, "items": [{k: v for k, v in FACTURA["items"][0].items()
                                 if k != "warehouse"}]}
    p = F.construir_payload_nota_credito(factura=sin, skus_a_acreditar=["95527-1T10"],
                                         modo="prueba", fecha="2026-07-30")
    assert "warehouse" not in p["items"][0]


def test_la_factura_de_reemplazo_tambien_manda_numero():
    p = F.construir_payload_factura_reemplazo(
        factura_original=FACTURA,
        item_reemplazo={"code": "95527-1T12", "description": "JEAN", "price_base": 125966.39},
        credito_con_iva=149900.0, modo="prueba", fecha="2026-07-30",
        documento_id=31433, bodega_id=5, pago_excedente_id=None)
    assert p["items"][0]["warehouse"] == 5


def test_la_factura_de_reemplazo_aplana_la_del_item():
    p = F.construir_payload_factura_reemplazo(
        factura_original=FACTURA,
        item_reemplazo={"code": "X", "description": "X", "price_base": 100.0,
                        "warehouse": {"id": 3, "name": "Arrayanes"}},
        credito_con_iva=119.0, modo="prueba", fecha="2026-07-30")
    assert p["items"][0]["warehouse"] == 3
