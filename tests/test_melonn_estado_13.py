"""Estado 13 de Melonn ("sin stock") y la familia "on stand by".

Del 17 al 20-nov-2026 el 13 no estaba en ningún conjunto: esos pedidos no
salían en ninguna pestaña y la salud de logística quedó en rojo
("estados_desconocidos"). Estas pruebas recorren los tres filtros por los que
pasa un pedido (listado en vivo, ventana de 90 días y caché guardado) y la
marca de novedad que leen /contraentrega y /envios.
"""
from datetime import date, timedelta

import melonn_client as mc
from backend.services.metricas import es_novedad_visible

SIN_STOCK = "on stand by - not able to fulfil - no stock"


def _crudo(code: int, nombre: str, dias_atras: int = 1, cod: str = "100000") -> dict:
    return {
        "internal_order_number": "M999",
        "external_order_number": "66999",
        "creation_date": (date.today() - timedelta(days=dias_atras)).isoformat(),
        "sell_order_state": {"code": code, "name": nombre},
        "payment_on_delivery_amount": cod,
        "shipping_method": {"code": "SM", "name": "Envia"},
        "warehouse": {"code": "MED-2", "name": "Medellin"},
    }


def test_el_13_se_clasifica_como_novedad_y_no_como_desconocido():
    mc._ESTADOS_DESCONOCIDOS.discard(f"13|{SIN_STOCK}")
    assert mc._sub_estado_logistico(SIN_STOCK, 13) == "novedad"
    assert f"13|{SIN_STOCK}" not in mc._ESTADOS_DESCONOCIDOS


def test_el_13_pasa_el_listado_en_vivo():
    out = mc._normalizar_lote([_crudo(13, SIN_STOCK)])
    assert len(out) == 1
    assert out[0]["sub_estado_logistico"] == "novedad"


def test_un_13_viejo_sigue_dentro_de_la_ventana():
    # Un pedido sin stock de hace 100 días sigue siendo trabajo pendiente.
    corte = date.today() - timedelta(days=90)
    assert len(mc._filtrar_ventana([_crudo(13, SIN_STOCK, dias_atras=100)], corte)) == 1


def test_el_13_sobrevive_al_cache_guardado():
    p = mc._normalizar_lote([_crudo(13, SIN_STOCK)])[0]
    out = mc._enriquecer_y_filtrar([p])
    assert len(out) == 1
    assert out[0]["sub_estado_logistico"] == "novedad"


def test_el_13_sale_en_la_pestana_novedades():
    p = mc._enriquecer_y_filtrar(mc._normalizar_lote([_crudo(13, SIN_STOCK)]))[0]
    assert es_novedad_visible(p) is True


def test_los_otros_on_stand_by_entran_por_nombre_aunque_el_codigo_sea_nuevo():
    # Código inventado: lo que debe salvarlo es el nombre.
    nombre = "on stand by - not able to fulfil - expired promises"
    out = mc._normalizar_lote([_crudo(31, nombre)])
    assert len(out) == 1
    assert out[0]["sub_estado_logistico"] == "novedad"
    assert es_novedad_visible(out[0]) is True


def test_no_cambia_lo_que_ya_estaba_bien():
    # 26 sigue en "Autorizar" (no es novedad) y 15 (cancelada) sigue fuera.
    assert mc._sub_estado_logistico(
        "All items reserved - fulfillment on hold", 26) == "pendiente_despacho"
    assert mc._normalizar_lote([_crudo(15, "Canceled")]) == []
    assert mc._sub_estado_logistico("Shipped - in transit", 7) == "en_transito"
