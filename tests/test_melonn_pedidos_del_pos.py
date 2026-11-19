"""Un pedido que el POS le crea a Melonn (venta con envío a domicilio) no es
un pedido de Shopify ni de contra entrega, y el OS no puede tratarlo como tal.

Melonn no devuelve los `tags`: se reconoce por su número (`FERPOS-2538`).
"""
import melonn_client as mc
from backend.services import cartera_cod


def _crudo(numero, **mas):
    return {"internal_order_number": "M1794944965087455",
            "external_order_number": numero, "external_order_id": "9991234567890",
            "sell_order_state": {"code": 2, "name": "Ready for fulfillment"},
            "shipping_method": {"code": "MEL-15", "name": "Estándar"},
            "warehouse": {"code": "MED-2", "name": "Medellin"},
            "creation_date": "2026-11-18", **mas}


def test_el_pedido_del_pos_no_lleva_id_de_shopify():
    p = mc._normalizar(_crudo("FERPOS-2538"))
    assert p["orden_tienda"] == "FERPOS-2538"
    assert p["origen"] == "pos"
    # Vacío: así no entra al lote `ids=` que el enriquecedor le manda a Shopify.
    assert p["external_order_id"] == ""
    assert p["es_contraentrega"] is False and p["canal_venta"] == "D2C"


def test_el_pedido_de_la_web_queda_exactamente_igual():
    p = mc._normalizar(_crudo("#62531", external_order_id="6123456789012"))
    assert (p["orden_tienda"], p["external_order_id"], p["origen"]) == (
        "62531", "6123456789012", "")


def test_reconoce_solo_numeros_de_caja():
    for si in ("FERPOS-2538", "ARRPOS-44446", "FLPOS-100502", "#FLPOS-1"):
        assert mc.es_pedido_del_pos(si), si
    for no in ("62531", "#62531", "60822#60821", "PRUEBA-POS-1", "T1001", "", None,
               "POS-12", "ferpos-2538"):
        assert not mc.es_pedido_del_pos(no), no


def test_el_detalle_del_pos_se_pide_sin_numeral(monkeypatch):
    """Antes: primero `%23FERPOS-2538` (404, una petición de cuota perdida) y
    después el bueno."""
    pedidas = []

    def get_falso(ruta, params=None):
        pedidas.append(ruta)
        return None
    monkeypatch.setattr(mc, "_get", get_falso)
    pos = mc._normalizar(_crudo("FERPOS-2538"))
    web = mc._normalizar(_crudo("#62531", external_order_id="6123456789012"))
    mc._enriquecer_desde_melonn([pos, web])
    assert "sell-orders/FERPOS-2538" in pedidas
    assert not [r for r in pedidas if "%23FERPOS" in r]
    # El de la web sigue pidiéndose con «#» primero, como siempre.
    assert pedidas[pedidas.index("sell-orders/%2362531")] == "sell-orders/%2362531"


def test_la_cartera_cod_no_lee_un_numero_de_caja_como_pedido_web():
    assert cartera_cod._numeros_orden("FLPOS-99501") == []
    assert cartera_cod._numeros_orden("#ARRPOS-44446") == []
    # Lo de siempre, intacto.
    assert cartera_cod._numeros_orden("60822#60821") == ["60822", "60821"]
    assert cartera_cod._numeros_orden("#61966") == ["61966"]
    assert cartera_cod._numeros_orden(None) == []
