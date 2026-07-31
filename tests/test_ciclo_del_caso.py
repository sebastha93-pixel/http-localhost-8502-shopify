"""Los pasos que un caso recorre DE VERDAD.

Se le pintaban los 12 estados posibles a todos los casos por igual. Un cambio
de talla en tienda son cuatro pasos, pero la pantalla decia "paso 3 de 10" y
mostraba logistica inversa que nunca va a ocurrir —la clienta trae la prenda
en la mano.

Un flujo se siente pesado sobre todo porque se VE pesado.
"""
from backend.services import postventa_logic as L


def test_un_cambio_en_tienda_son_cuatro_pasos():
    """Sin aprobacion (no es garantia) y sin logistica inversa (presencial)."""
    assert L.ciclo_del_caso("cambio_talla", tienda="florida_caja1") == [
        "aprobado", "nota_credito_emitida", "factura_emitida", "cerrado"]


def test_una_garantia_en_tienda_agrega_la_aprobacion():
    c = L.ciclo_del_caso("garantia", tienda="florida_caja1")
    assert c[:3] == ["creado", "pendiente_validacion", "aprobado"]


def test_un_cambio_online_si_lleva_logistica_inversa():
    """La prenda tiene que viajar de vuelta antes de acreditarla."""
    c = L.ciclo_del_caso("cambio_talla")
    assert "esperando_envio_cliente" in c
    assert "en_transito_bodega" in c
    assert "recibido_bodega" in c
    assert "cambio_enviado" in c


def test_en_tienda_no_hay_nada_que_despachar():
    c = L.ciclo_del_caso("cambio_talla", tienda="arrayanes")
    assert "esperando_envio_cliente" not in c
    assert "cambio_enviado" not in c


def test_un_reembolso_no_lleva_factura():
    """Solo nota credito: no hay prenda nueva que facturar."""
    assert "factura_emitida" not in L.ciclo_del_caso("reembolso", tienda="arrayanes")


def test_un_bono_tampoco():
    assert "factura_emitida" not in L.ciclo_del_caso("bono")


def test_siempre_arranca_donde_nace_el_caso():
    for tipo in ("cambio_talla", "cambio_ref", "garantia", "reembolso"):
        assert L.ciclo_del_caso(tipo)[0] == L.estado_inicial(tipo)


def test_siempre_termina_en_cerrado():
    for tipo in ("cambio_talla", "garantia", "reembolso", "bono"):
        assert L.ciclo_del_caso(tipo)[-1] == "cerrado"


def test_todos_los_pasos_son_estados_validos():
    for tipo in ("cambio_talla", "cambio_ref", "garantia", "reembolso", "bono"):
        for t in ("", "florida_caja1"):
            assert set(L.ciclo_del_caso(tipo, tienda=t)) <= L.ESTADOS


def test_el_ciclo_respeta_las_transiciones_permitidas():
    """De nada sirve pintar un camino que el motor no deja recorrer."""
    for tipo in ("cambio_talla", "garantia", "reembolso"):
        for t in ("", "florida_caja1"):
            c = L.ciclo_del_caso(tipo, tienda=t)
            for antes, despues in zip(c, c[1:]):
                assert L.transicion_valida(antes, despues), f"{antes} → {despues}"


def test_un_reembolso_no_despacha_nada():
    """No hay prenda de reemplazo: se cierra con la nota credito."""
    assert "cambio_enviado" not in L.ciclo_del_caso("reembolso")
