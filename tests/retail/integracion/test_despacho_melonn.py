"""El pedido a Melonn de una venta con envío — con un Melonn falso.

UNA VENTA, UN PEDIDO. Un pedido repetido son dos paquetes a la misma clienta;
uno que no se pidió es una clienta que pagó y no recibe. Estas pruebas cuidan
las dos cosas, y en especial lo que Siigo enseñó el 2026-11-18: «no contestó»
no es «no se creó», y «busqué y no está» al minuto tampoco.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest

from tests.retail.integracion.test_emisor_factura import (  # noqa: F401
    URL,
    SiigoFalso,
    _correr,
    _ejecutar,
    _leer,
    entorno,
)
from tests.retail.integracion.test_venta_con_envio import (  # noqa: F401
    VENTA_ENVIO,
    MelonnFalso,
    _habilitar,
    _stock,
    _vender_con_envio,
    melonn_de_los_endpoints,
    web,
)

pytestmark = pytest.mark.skipif(not URL, reason="Sin RETAIL_TEST_DATABASE_URL")


def _drenar(melonn, *, dentro_de=timedelta(minutes=1), siigo=None):
    from backend.modules.retail.application.comandos.drenar_outbox import DrenarOutbox
    from backend.modules.retail.infrastructure.melonn import despacho
    from backend.modules.retail.infrastructure.persistencia.unidad_de_trabajo import (
        UnidadDeTrabajoSQL, crear_fabrica, crear_motor,
    )
    from backend.modules.retail.infrastructure.siigo import (
        emisor_factura, emisor_nota_credito,
    )

    async def ir():
        m = crear_motor(URL)
        try:
            return await DrenarOutbox(
                UnidadDeTrabajoSQL(crear_fabrica(m)),
                {"emitir_documento_fiscal":
                     emisor_factura.crear_manejador(siigo or SiigoFalso()),
                 "emitir_nota_credito": emisor_nota_credito.crear_manejador(
                     siigo or SiigoFalso()),
                 "crear_despacho_melonn": despacho.crear_manejador(melonn),
                 "cancelar_despacho_melonn": despacho.crear_verificador(melonn)},
            ).ejecutar(ahora=datetime.now(timezone.utc) + dentro_de, limite=20)
        finally:
            await m.dispose()
    with mock.patch.object(despacho, "_ahora",
                           lambda: datetime.now(timezone.utc) + dentro_de):
        return _correr(ir())


def _despacho(motor):
    return tuple(_leer(motor, """
        SELECT estado, melonn_numero, melonn_estado, seguimiento_url, ultimo_error
          FROM retail.despachos WHERE venta_id = :v""", {"v": VENTA_ENVIO})[0])


def _trabajo(motor):
    return tuple(_leer(motor, """
        SELECT estado, intentos, ultimo_error FROM retail.outbox
         WHERE tipo = 'crear_despacho_melonn'""")[0])


@pytest.fixture
def vendida(entorno):
    """Una venta con envío recién cobrada, con su despacho por pedir."""
    _habilitar(entorno)
    r = _vender_con_envio(entorno)
    assert r.status_code == 200, r.text
    return entorno


def _numero(motor):
    return _leer(motor, "SELECT numero FROM retail.ventas WHERE id = :v",
                 {"v": VENTA_ENVIO})[0][0]


# ── El camino normal ────────────────────────────────────────────────────────

def test_cobrar_con_envio_deja_el_pedido_en_la_cola(vendida):
    assert _trabajo(vendida)[:2] == ("pendiente", 0)
    # Una venta de mostrador (la de `entorno`) no encola despacho.
    assert _leer(vendida, "SELECT count(*) FROM retail.outbox "
                          "WHERE tipo = 'crear_despacho_melonn'")[0][0] == 1


def test_se_pide_a_melonn_prepagado_y_con_la_direccion(vendida):
    melonn = MelonnFalso()
    r = _drenar(melonn)
    assert r.fallidos == 0, r.errores

    [cuerpo] = melonn.enviados
    numero = _numero(vendida)
    assert cuerpo["external_order_number"] == numero
    # Numérico y fuera del rango de los pedidos de Shopify.
    assert cuerpo["external_order_id"].isdigit()
    assert cuerpo["external_order_id"].startswith("999")
    assert cuerpo["shipping_method_code"] == "MEL-15"
    assert cuerpo["line_items"] == [{"sku": "92611-1T10", "quantity": 1}]
    assert cuerpo["shipping_info"] == {
        "address_l1": "Calle 10 # 43-21", "address_l2": "Apto 502",
        "city": "Medellín", "region": "Antioquia", "country": "Colombia",
        "full_name": "Laura Gómez", "phone_number": "+57-3001234567"}
    # PREPAGADO Y D2C: nada de contra entrega ni de B2B.
    assert not [k for k in cuerpo if "payment_on_delivery" in k or "b2b" in k]

    estado, m_numero, m_estado, seguimiento, error = _despacho(vendida)
    assert (estado, error) == ("en_melonn", None)
    assert m_numero.startswith("M1794944965")
    assert _trabajo(vendida)[0] == "procesado"


def test_drenar_dos_veces_no_pide_dos(vendida):
    melonn = MelonnFalso()
    _drenar(melonn)
    _drenar(melonn, dentro_de=timedelta(hours=3))
    assert len(melonn.enviados) == 1


# ── UNA VENTA, UN PEDIDO ────────────────────────────────────────────────────

def test_si_ya_estaba_en_melonn_se_adopta_y_no_se_crea_otro(vendida):
    melonn = MelonnFalso()
    melonn._guardar({"external_order_number": _numero(vendida)})
    r = _drenar(melonn)
    assert r.procesados >= 1 and melonn.enviados == []
    estado, m_numero, m_estado, seguimiento, _ = _despacho(vendida)
    assert estado == "en_melonn" and m_numero.startswith("M1794944965")
    # El nombre del estado llega repetido en el detalle: se guarda una vez.
    assert m_estado == "All items reserved - ready for fulfillment"
    assert seguimiento.startswith("https://rastreo.melonn.com/")


def test_si_melonn_lo_creo_y_no_alcanzo_a_avisar_no_se_pide_otro(vendida):
    melonn = MelonnFalso()
    melonn.al_crear = "crea_y_muere"
    assert _drenar(melonn).reintentos == 1
    assert _despacho(vendida)[0] == "pendiente"

    melonn.al_crear = "ok"
    r = _drenar(melonn, dentro_de=timedelta(minutes=3))
    assert r.fallidos == 0, r.errores
    assert len(melonn.enviados) == 1, "se pidió por segunda vez"
    assert _despacho(vendida)[0] == "en_melonn"


def test_si_melonn_lo_crea_TARDE_no_se_pide_otro_antes_de_tiempo(vendida):
    """La lección de Siigo (2026-11-18): el envío se corta, se pregunta y NO
    está — pero aparece minutos después. Mientras no pase el plazo, sólo se
    pregunta, y preguntar no gasta ninguno de los ocho intentos."""
    melonn = MelonnFalso()
    melonn.al_crear = "sin_respuesta"
    assert _drenar(melonn).reintentos == 1
    melonn.al_crear = "ok"
    for minutos in (2, 5, 20, 40):
        _drenar(melonn, dentro_de=timedelta(minutes=minutos))
        assert len(melonn.enviados) == 1, f"volvió a pedir a los {minutos} min"
    assert _trabajo(vendida)[:2] == ("pendiente", 1)
    assert "se sigue preguntando" in _trabajo(vendida)[2]

    melonn._guardar(melonn.enviados[0])          # Melonn por fin lo crea
    _drenar(melonn, dentro_de=timedelta(minutes=43))
    assert len(melonn.enviados) == 1
    assert _despacho(vendida)[0] == "en_melonn"


def test_pasado_el_plazo_sin_aparecer_si_se_vuelve_a_pedir(vendida):
    melonn = MelonnFalso()
    melonn.al_crear = "sin_respuesta"
    _drenar(melonn)
    melonn.al_crear = "ok"
    _drenar(melonn, dentro_de=timedelta(minutes=50))
    assert len(melonn.enviados) == 2 and len(melonn.pedidos) == 1
    assert _despacho(vendida)[0] == "en_melonn"


# ── Cuando Melonn dice que no, o no puede ───────────────────────────────────

def test_un_rechazo_queda_a_la_vista_de_la_oficina_y_no_se_reintenta(vendida):
    melonn = MelonnFalso()
    melonn.al_crear = "rechazo"
    r = _drenar(melonn)
    assert r.fallidos == 0, r.errores
    estado, _, m_estado, _, error = _despacho(vendida)
    assert estado == "no_creado" and "No stock available" in error
    assert m_estado is None
    _drenar(melonn, dentro_de=timedelta(hours=5))
    assert len(melonn.enviados) == 1


@pytest.mark.parametrize("donde", ["al_leer", "al_crear"])
def test_sin_cuota_espera_sin_gastar_intentos(vendida, donde):
    melonn = MelonnFalso()
    setattr(melonn, donde, "cuota")
    r = _drenar(melonn)
    assert (r.reintentos, r.fallidos) == (0, 0), r.errores
    assert melonn.enviados == []
    assert _trabajo(vendida)[:2] == ("pendiente", 0)
    assert _despacho(vendida)[:3] == ("pendiente", None, None)

    setattr(melonn, donde, "ok")
    # Sin cuota no salió nada: al volver se pide de una, sin plazo de espera.
    _drenar(melonn, dentro_de=timedelta(minutes=31))
    assert len(melonn.enviados) == 1 and _despacho(vendida)[0] == "en_melonn"


def test_si_no_se_puede_preguntar_no_se_pide(vendida):
    """«No pude preguntar» no es «no existe»: con Melonn caído no se crea."""
    melonn = MelonnFalso()
    melonn.al_leer = "caido"
    _drenar(melonn)
    assert melonn.enviados == [] and _despacho(vendida)[0] == "pendiente"


def test_un_pedido_que_melonn_tiene_cancelado_va_a_la_oficina(vendida):
    melonn = MelonnFalso()
    melonn._guardar({"external_order_number": _numero(vendida)})
    melonn.pedidos[_numero(vendida)]["state"] = {"id": 15, "name": "Canceled"}
    _drenar(melonn)
    estado, _, m_estado, _, error = _despacho(vendida)
    assert (estado, m_estado) == ("no_creado", "Canceled")
    assert "CANCELADO" in error and melonn.enviados == []


def test_la_venta_anulada_antes_de_pedirlo_no_se_pide(vendida):
    _ejecutar(vendida, """
        UPDATE retail.ventas
           SET estado = 'anulada', anulada_en = now(), anulada_por = 'maria',
               motivo_anulacion = 'la clienta se arrepintió en la caja'
         WHERE id = :v""", {"v": VENTA_ENVIO})
    melonn = MelonnFalso()
    _drenar(melonn)
    assert melonn.enviados == []
    assert _despacho(vendida)[0] == "cancelado"


# ── Armar el pedido ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("crudo, esperado", [
    ("3001234567", "+57-3001234567"), ("300 123 4567", "+57-3001234567"),
    ("+57 300-123-4567", "+57-3001234567"), ("573001234567", "+57-3001234567")])
def test_el_telefono_va_como_lo_recibe_melonn(crudo, esperado):
    from backend.modules.retail.infrastructure.melonn.despacho import _telefono
    assert _telefono(crudo) == esperado


def test_el_id_externo_es_siempre_el_mismo_para_la_misma_venta():
    from backend.modules.retail.infrastructure.melonn.despacho import id_externo
    assert id_externo("FERPOS-2538") == id_externo("FERPOS-2538")
    assert id_externo("FERPOS-2538") != id_externo("FERPOS-2539")
    assert len(id_externo("FERPOS-2538")) == 13


# ── Cancelar: que no llegue un paquete cuya plata ya se devolvió ────────────

def _anular_en_caja():
    from tests.retail.integracion.test_emisor_factura import _CLIENTE
    return _CLIENTE["c"].post(f"/api/retail/ventas/{VENTA_ENVIO}/anular",
                              json={"motivo": "la clienta se arrepintió"})


def _venta(motor):
    return _leer(motor, "SELECT estado FROM retail.ventas WHERE id = :v",
                 {"v": VENTA_ENVIO})[0][0]


def _verificador(motor):
    return tuple(_leer(motor, """
        SELECT estado, ultimo_error FROM retail.outbox
         WHERE tipo = 'cancelar_despacho_melonn'""")[0])


def test_anular_en_la_caja_le_pide_a_melonn_que_no_la_despache(
        vendida, melonn_de_los_endpoints):
    melonn = melonn_de_los_endpoints
    _drenar(melonn)                                   # ya está en Melonn
    assert _despacho(vendida)[0] == "en_melonn"

    r = _anular_en_caja()
    assert r.status_code == 200, r.text
    assert melonn.cancelaciones and melonn.cancelaciones[0][0] == _numero(vendida)
    assert _venta(vendida) == "anulada"
    estado, _, m_estado, _, _ = _despacho(vendida)
    assert (estado, m_estado) == ("cancelado", "cancelación pedida")
    assert _stock(vendida, "bodega:en_linea") == 0    # la prenda volvió

    # El verificador confirma que Melonn lo dejó cancelado.
    _drenar(melonn, dentro_de=timedelta(minutes=2))
    assert _despacho(vendida)[2] == "Canceled"
    assert _verificador(vendida)[0] == "procesado"


def test_si_melonn_ya_la_despacho_no_se_anula(vendida, melonn_de_los_endpoints):
    melonn = melonn_de_los_endpoints
    _drenar(melonn)
    melonn.pedidos[_numero(vendida)]["state"] = {"id": 7, "name": "Shipped - in transit"}
    r = _anular_en_caja()
    assert r.status_code == 409 and r.json()["detail"]["error"] == "ya_salio"
    assert _venta(vendida) == "cerrada" and melonn.cancelaciones == []
    assert _despacho(vendida)[0] == "en_melonn"


@pytest.mark.parametrize("falla", ["caido", "cuota", "ocupado"])
def test_si_melonn_no_contesta_no_se_anula(vendida, melonn_de_los_endpoints, falla):
    """Devolver la plata sin saber si el paquete sale es el peor resultado."""
    melonn = melonn_de_los_endpoints
    _drenar(melonn)
    melonn.al_leer = falla
    r = _anular_en_caja()
    assert r.status_code == 503 and r.json()["detail"]["error"] == "melonn_no_responde"
    assert _venta(vendida) == "cerrada" and _despacho(vendida)[0] == "en_melonn"


def test_si_melonn_no_deja_cancelar_no_se_anula(vendida, melonn_de_los_endpoints):
    melonn = melonn_de_los_endpoints
    _drenar(melonn)
    melonn.al_cancelar = "rechazo"
    r = _anular_en_caja()
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "melonn_no_deja_cancelar"
    assert _venta(vendida) == "cerrada"


def test_anulada_antes_de_pedirse_nunca_llega_a_melonn(vendida, melonn_de_los_endpoints):
    melonn = melonn_de_los_endpoints
    assert _anular_en_caja().status_code == 200
    assert _despacho(vendida)[0] == "cancelado"
    _drenar(melonn)
    _drenar(melonn, dentro_de=timedelta(hours=2))
    assert melonn.enviados == []
    # Pasado el plazo sin que aparezca nada, el verificador da por cerrado.
    assert _verificador(vendida)[0] == "procesado"
    assert _despacho(vendida)[2] is None


def test_cancelada_MIENTRAS_se_pedia_se_cancela_tambien_en_melonn(vendida):
    """La carrera: el pedido va en camino hacia Melonn y en ese instante
    alguien anula la venta. El pedido nace para una venta que ya no existe."""
    melonn = MelonnFalso()

    async def alguien_la_cancela():
        from sqlalchemy import text
        async with vendida.begin() as cn:
            await cn.execute(text("""
                UPDATE retail.despachos SET estado = 'cancelado',
                       melonn_estado = 'cancelación pedida' WHERE venta_id = :v"""),
                {"v": VENTA_ENVIO})
    melonn.justo_antes_de_contestar = alguien_la_cancela
    _drenar(melonn)
    assert len(melonn.enviados) == 1
    assert melonn.cancelaciones and melonn.cancelaciones[0][0] == _numero(vendida)
    estado, m_numero, m_estado, _, _ = _despacho(vendida)
    assert (estado, m_estado) == ("cancelado", "cancelación pedida")
    assert m_numero.startswith("M1794944965")        # queda el rastro


def test_el_verificador_cancela_el_pedido_que_melonn_creo_tarde(vendida):
    melonn = MelonnFalso()
    melonn.al_crear = "sin_respuesta"
    _drenar(melonn)                                   # envío sin respuesta
    _ejecutar(vendida, """
        UPDATE retail.despachos SET estado = 'cancelado',
               melonn_estado = 'cancelación pedida' WHERE venta_id = :v""",
        {"v": VENTA_ENVIO})
    _ejecutar(vendida, """
        INSERT INTO retail.outbox (tipo, agregado_tipo, agregado_id, payload,
                                   estado, intentos, max_intentos)
        VALUES ('cancelar_despacho_melonn', 'venta', :v,
                jsonb_build_object('venta_id', CAST(:v AS text)), 'pendiente', 0, 8)""",
        {"v": VENTA_ENVIO})
    _drenar(melonn, dentro_de=timedelta(minutes=2))   # todavía no aparece
    assert _verificador(vendida)[0] == "pendiente"

    melonn._guardar(melonn.enviados[0])               # Melonn lo crea tarde
    _drenar(melonn, dentro_de=timedelta(minutes=12))
    assert [c[0] for c in melonn.cancelaciones] == [_numero(vendida)]
    _drenar(melonn, dentro_de=timedelta(minutes=16))
    assert _despacho(vendida)[2] == "Canceled"
    assert _verificador(vendida)[0] == "procesado"


def test_si_melonn_lo_despacho_a_pesar_de_cancelar_se_grita(vendida, melonn_de_los_endpoints):
    melonn = melonn_de_los_endpoints
    _drenar(melonn)
    assert _anular_en_caja().status_code == 200
    # Melonn dijo que sí… y lo despachó igual.
    melonn.pedidos[_numero(vendida)]["state"] = {"id": 7, "name": "Shipped - in transit"}
    _drenar(melonn, dentro_de=timedelta(minutes=2))
    assert "MELONN LO DESPACHÓ" in _despacho(vendida)[4]


# ── La oficina ──────────────────────────────────────────────────────────────

def _como(rol):
    from backend.core.security import CurrentUser, get_current_user
    from tests.retail.integracion.test_emisor_factura import _CLIENTE
    c = _CLIENTE["c"]
    c.app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id="sebastian" if rol == "admin" else "maria", email="x@male.com",
        nombre="Oficina", rol=rol, permisos={"retail": ["ver", "modificar"]})
    return c


def _cancelar_desde_oficina(c, venta=VENTA_ENVIO):
    return c.post(f"/api/retail/despachos/{venta}/cancelar", json={
        "motivo": "Melonn no tenía la prenda",
        "resolucion": "Se le devolvió por transferencia a Bancolombia"})


def _cerrar_turno(motor):
    from tests.retail.integracion.test_emisor_factura import SESION
    _ejecutar(motor, "UPDATE retail.sesiones_caja SET estado = 'cerrada', "
                     "cerrada_por = 'maria', cerrada_en = now() WHERE id = :i",
              {"i": SESION})


def test_la_oficina_cancela_aunque_el_turno_este_cerrado(
        vendida, melonn_de_los_endpoints, monkeypatch):
    """Melonn no pudo despachar y la caja cerró ayer. Se anula la venta, sale
    la nota crédito contra la bodega de la tienda en línea, y el arqueo
    —firmado— no se toca: la plata se devuelve por fuera."""
    monkeypatch.setenv("RETAIL_FISCAL_MODO", "produccion")
    melonn, siigo = melonn_de_los_endpoints, SiigoFalso()
    melonn.al_crear = "rechazo"
    _drenar(melonn, siigo=siigo)                      # factura sí, despacho no
    assert _despacho(vendida)[0] == "no_creado"
    _cerrar_turno(vendida)
    movimientos = _leer(vendida, "SELECT count(*) FROM retail.movimientos_caja")[0][0]

    r = _cancelar_desde_oficina(_como("admin"))
    assert r.status_code == 200, r.text
    assert r.json()["exige_nota_credito"] is True
    assert _venta(vendida) == "anulada"
    assert _leer(vendida, "SELECT count(*) FROM retail.movimientos_caja")[0][0] == movimientos
    assert _stock(vendida, "bodega:en_linea") == 0
    assert _stock(vendida, "tienda:arrayanes") == 7
    resuelto = _leer(vendida, "SELECT estado, resuelto_por, resolucion "
                              "FROM retail.despachos")[0]
    assert tuple(resuelto) == ("cancelado", "sebastian",
                               "Se le devolvió por transferencia a Bancolombia")

    _drenar(melonn, siigo=siigo, dentro_de=timedelta(minutes=5))
    [nc] = siigo.nc_enviadas
    assert {i["warehouse"] for i in nc["items"]} == {32}


def test_cancelar_desde_la_oficina_es_solo_de_administradores(vendida):
    r = _cancelar_desde_oficina(_como("user"))
    assert r.status_code == 403 and r.json()["detail"]["error"] == "solo_administrador"
    assert _venta(vendida) == "cerrada"


def test_la_oficina_no_anula_por_aqui_una_venta_de_mostrador(vendida):
    from tests.retail.integracion.test_emisor_factura import VENTA
    r = _cancelar_desde_oficina(_como("admin"), venta=VENTA)
    assert r.status_code == 400 and "no es con envío" in r.json()["detail"]["mensaje"]


def test_lo_que_ya_salio_no_lo_cancela_ni_la_oficina(vendida, melonn_de_los_endpoints):
    _drenar(melonn_de_los_endpoints)
    _ejecutar(vendida, "UPDATE retail.despachos SET estado = 'despachado'")
    r = _cancelar_desde_oficina(_como("admin"))
    assert r.status_code == 400 and "ya salió" in r.json()["detail"]["mensaje"]
    assert _venta(vendida) == "cerrada"


def test_la_lista_de_la_oficina_pone_primero_lo_que_hay_que_resolver(
        vendida, melonn_de_los_endpoints):
    melonn = melonn_de_los_endpoints
    melonn.al_crear = "rechazo"
    _drenar(melonn)
    r = _como("admin").get("/api/retail/despachos?abiertos=true")
    assert r.status_code == 200, r.text
    [d] = r.json()
    assert d["numero"] == _numero(vendida) and d["estado"] == "no_creado"
    assert d["requiere_atencion"] is True and "No stock" in d["ultimo_error"]
    assert d["prendas"] == ["92611-1T10 ×1"]
    assert (d["destinatario"], d["ciudad"]) == ("Laura Gómez", "Medellín")
    assert d["tienda_id"] == "arrayanes" and d["total_centavos"] > 0

    assert _como("user").get("/api/retail/despachos").status_code == 403


# ── Cómo va el despacho ─────────────────────────────────────────────────────

def _refrescar(melonn, *, dentro_de):
    from backend.modules.retail.infrastructure.melonn import despacho
    from backend.modules.retail.infrastructure.persistencia.unidad_de_trabajo import (
        UnidadDeTrabajoSQL, crear_fabrica, crear_motor,
    )

    async def ir():
        m = crear_motor(URL)
        try:
            return await despacho.refrescar_despachos(
                UnidadDeTrabajoSQL(crear_fabrica(m)), melonn)
        finally:
            await m.dispose()
    with mock.patch.object(despacho, "_ahora",
                           lambda: datetime.now(timezone.utc) + dentro_de):
        return _correr(ir())


def test_el_despacho_avanza_con_lo_que_dice_melonn(vendida):
    melonn = MelonnFalso()
    _drenar(melonn)
    numero = _numero(vendida)
    # Recién pedido: no se le pregunta todavía.
    assert _refrescar(melonn, dentro_de=timedelta(minutes=5)) == 0

    melonn.pedidos[numero]["state"] = {"id": 7, "name": "Shipped - in transit"}
    assert _refrescar(melonn, dentro_de=timedelta(minutes=40)) == 1
    assert _despacho(vendida)[:3] == ("despachado", melonn.pedidos[numero][
        "internal_order_number"], "Shipped - in transit")

    melonn.pedidos[numero]["state"] = {"id": 8, "name": "Delivered to buyer"}
    _refrescar(melonn, dentro_de=timedelta(minutes=80))
    assert _despacho(vendida)[0] == "entregado"
    # Entregado es final: no se vuelve a preguntar.
    antes = len(melonn.preguntas)
    _refrescar(melonn, dentro_de=timedelta(hours=5))
    assert len(melonn.preguntas) == antes


def test_si_melonn_lo_cancela_por_su_cuenta_va_a_la_oficina(vendida):
    melonn = MelonnFalso()
    _drenar(melonn)
    melonn.pedidos[_numero(vendida)]["state"] = {"id": 15, "name": "Canceled"}
    _refrescar(melonn, dentro_de=timedelta(minutes=40))
    estado, _, _, _, error = _despacho(vendida)
    assert estado == "no_creado" and "MELONN CANCELÓ" in error


def test_una_novedad_de_entrega_se_avisa(vendida):
    melonn = MelonnFalso()
    _drenar(melonn)
    melonn.pedidos[_numero(vendida)]["state"] = {"id": 20, "name": "Delivery not posible"}
    _refrescar(melonn, dentro_de=timedelta(minutes=40))
    estado, _, _, _, error = _despacho(vendida)
    assert estado == "despachado" and "no pudo entregar" in error


# ── Lo que encontró la revisión (2026-11-18) ────────────────────────────────

def _sql(motor, sql, **p):
    """Para los ganchos del Melonn falso: algo que pasa «mientras tanto»."""
    async def ir():
        from sqlalchemy import text
        async with motor.begin() as cn:
            await cn.execute(text(sql), {"v": VENTA_ENVIO, **p})
    return ir


def test_melonn_caido_dos_horas_no_deja_la_venta_sin_pedido_y_en_silencio(vendida):
    """ANTES: ocho preguntas fallidas agotaban el trabajo. Quedaba una venta
    cobrada, sin pedido, sin error y sin nadie reintentando."""
    melonn = MelonnFalso()
    melonn.al_leer = "caido"
    for minutos in (1, 5, 10, 20, 40, 70, 100, 130, 160, 190):
        r = _drenar(melonn, dentro_de=timedelta(minutes=minutos))
        assert r.fallidos == 0
    # Preguntar no gasta intentos, y la oficina VE que algo pasa.
    assert _trabajo(vendida)[:2] == ("pendiente", 0)
    assert "No se ha podido hablar con Melonn" in _despacho(vendida)[4]

    melonn.al_leer = "ok"
    _drenar(melonn, dentro_de=timedelta(minutes=200))
    assert len(melonn.enviados) == 1
    assert _despacho(vendida)[0] == "en_melonn" and _despacho(vendida)[4] is None


def test_si_el_trabajo_se_rinde_la_oficina_lo_ve_y_puede_reintentar(
        vendida, melonn_de_los_endpoints):
    melonn = melonn_de_los_endpoints
    melonn.al_crear = "sin_respuesta"
    for vuelta in range(8):                    # ocho envíos sin respuesta
        _drenar(melonn, dentro_de=timedelta(hours=vuelta * 2))
    assert len(melonn.enviados) == 8 and _trabajo(vendida)[0] == "fallido"
    assert _despacho(vendida)[0] == "pendiente"

    [d] = _como("admin").get("/api/retail/despachos?abiertos=true").json()
    assert d["requiere_atencion"] is True and d["ultimo_error"]

    melonn.al_crear = "ok"
    assert _como("user").post(
        f"/api/retail/despachos/{VENTA_ENVIO}/reintentar").status_code == 403
    r = _como("admin").post(f"/api/retail/despachos/{VENTA_ENVIO}/reintentar")
    assert r.status_code == 200, r.text
    # El plazo tras el último envío sin respuesta se sigue respetando.
    _drenar(melonn, dentro_de=timedelta(hours=14, minutes=5))
    assert len(melonn.enviados) == 8
    _drenar(melonn, dentro_de=timedelta(hours=15))
    assert len(melonn.enviados) == 9 and _despacho(vendida)[0] == "en_melonn"


def test_un_pedido_que_lleva_rato_sin_salir_pide_atencion(vendida):
    """La red de seguridad: pase lo que pase con el trabajo, un despacho que
    sigue «pendiente» veinte minutos después se muestra como problema."""
    _ejecutar(vendida, "UPDATE retail.despachos SET creado_en = now() - interval '25 minutes'")
    [d] = _como("admin").get("/api/retail/despachos?abiertos=true").json()
    assert d["requiere_atencion"] is True and "sin pedirse" in d["ultimo_error"]


def test_una_anulacion_que_se_rechaza_no_le_cancela_nada_a_melonn(
        vendida, melonn_de_los_endpoints):
    """ANTES: primero se cancelaba en Melonn y después se miraba si quien
    anulaba podía. Con el turno cerrado (o sin permiso) quedaba la venta
    cobrada y su pedido cancelado."""
    melonn = melonn_de_los_endpoints
    _drenar(melonn)
    preguntas = len(melonn.preguntas)
    _cerrar_turno(vendida)
    r = _anular_en_caja()
    assert r.status_code == 400 and "turno ya cerrado" in r.json()["detail"]["mensaje"]
    assert melonn.cancelaciones == [] and len(melonn.preguntas) == preguntas
    assert _venta(vendida) == "cerrada" and _despacho(vendida)[0] == "en_melonn"


def test_sin_permiso_de_anular_tampoco_se_toca_melonn(vendida, melonn_de_los_endpoints):
    melonn = melonn_de_los_endpoints
    _drenar(melonn)
    _ejecutar(vendida, "UPDATE retail.permisos_pos SET puede_anular_venta = false")
    r = _anular_en_caja()
    assert r.status_code == 403
    assert melonn.cancelaciones == [] and _despacho(vendida)[0] == "en_melonn"


def test_dos_manejadores_a_la_vez_no_piden_dos(vendida):
    """Mientras éste preguntaba, otro ya dejó escrito «voy a enviar»."""
    melonn = MelonnFalso()
    melonn.justo_despues_de_leer = _sql(vendida, """
        UPDATE retail.despachos SET melonn_estado = 'enviando', actualizado_en = now()
         WHERE venta_id = :v""")
    r = _drenar(melonn)
    assert melonn.enviados == [] and r.fallidos == 0
    assert _trabajo(vendida)[:2] == ("pendiente", 0)


def test_anulada_mientras_se_preguntaba_ya_no_se_pide(vendida):
    melonn = MelonnFalso()
    melonn.justo_despues_de_leer = _sql(vendida, """
        UPDATE retail.despachos SET estado = 'cancelado',
               melonn_estado = 'cancelación pedida' WHERE venta_id = :v""")
    _drenar(melonn)
    assert melonn.enviados == []
    assert _despacho(vendida)[:3] == ("cancelado", None, "cancelación pedida")


def test_si_otro_manejador_ya_lo_anoto_no_se_le_cancela_el_pedido_bueno(vendida):
    """«No lo pude anotar» no significa «lo cancelaron»."""
    melonn = MelonnFalso()
    melonn.justo_antes_de_contestar = _sql(vendida, """
        UPDATE retail.despachos SET estado = 'en_melonn', melonn_numero = 'M-OTRO'
         WHERE venta_id = :v""")
    _drenar(melonn)
    assert melonn.cancelaciones == []
    assert _despacho(vendida)[:2] == ("en_melonn", "M-OTRO")


def test_cancelada_mientras_se_pedia_deja_un_verificador_nuevo(vendida):
    melonn = MelonnFalso()
    melonn.justo_antes_de_contestar = _sql(vendida, """
        UPDATE retail.despachos SET estado = 'cancelado',
               melonn_estado = 'cancelación pedida' WHERE venta_id = :v""")
    _drenar(melonn)
    assert _verificador(vendida)[0] == "pendiente"
    _drenar(melonn, dentro_de=timedelta(minutes=5))
    assert _despacho(vendida)[2] == "Canceled"


def test_el_verificador_no_cierra_mientras_un_pedido_pueda_aparecer(vendida):
    """Aunque `melonn_estado` no diga «cancelación pedida» (otro lo pisó):
    dentro del plazo no se da por hecho que Melonn no tiene nada."""
    _ejecutar(vendida, """
        UPDATE retail.despachos SET estado = 'cancelado', melonn_estado = 'enviando',
               actualizado_en = now() WHERE venta_id = :v""", {"v": VENTA_ENVIO})
    _ejecutar(vendida, """
        INSERT INTO retail.outbox (tipo, agregado_tipo, agregado_id, payload,
                                   estado, intentos, max_intentos)
        VALUES ('cancelar_despacho_melonn', 'venta', :v,
                jsonb_build_object('venta_id', CAST(:v AS text)), 'pendiente', 0, 8)""",
        {"v": VENTA_ENVIO})
    _drenar(MelonnFalso(), dentro_de=timedelta(minutes=2))
    assert _verificador(vendida)[0] == "pendiente"


def test_un_rechazo_tardio_no_pisa_la_cancelacion(vendida):
    melonn = MelonnFalso()
    melonn.al_crear = "rechazo"
    melonn.justo_despues_de_leer = None
    original = melonn.crear_pedido

    async def cancelan_y_rechaza(cuerpo):
        await _sql(vendida, "UPDATE retail.despachos SET estado = 'cancelado' "
                            "WHERE venta_id = :v")()
        return await original(cuerpo)
    melonn.crear_pedido = cancelan_y_rechaza
    _drenar(melonn)
    assert _despacho(vendida)[0] == "cancelado"


def test_el_verificador_tampoco_se_rinde_por_no_poder_preguntar(
        vendida, melonn_de_los_endpoints):
    melonn = melonn_de_los_endpoints
    _drenar(melonn)
    assert _anular_en_caja().status_code == 200
    melonn.al_leer = "caido"
    for minutos in (2, 10, 30, 60, 120, 180, 240, 300, 330, 350):
        _drenar(melonn, dentro_de=timedelta(minutes=minutos))
    assert _verificador(vendida)[0] == "pendiente"
    assert "No se ha podido hablar con Melonn" in _despacho(vendida)[4]


def test_si_melonn_nunca_confirma_la_cancelacion_queda_el_aviso(vendida):
    melonn = MelonnFalso()
    _drenar(melonn)
    _ejecutar(vendida, """
        UPDATE retail.despachos SET estado = 'cancelado',
               melonn_estado = 'cancelación pedida', actualizado_en = now()
         WHERE venta_id = :v""", {"v": VENTA_ENVIO})
    _ejecutar(vendida, """
        INSERT INTO retail.outbox (tipo, agregado_tipo, agregado_id, payload,
                                   estado, intentos, max_intentos)
        VALUES ('cancelar_despacho_melonn', 'venta', :v,
                jsonb_build_object('venta_id', CAST(:v AS text)), 'pendiente', 0, 8)""",
        {"v": VENTA_ENVIO})

    async def no_hace_caso(numero, motivo):      # Melonn recibe y no cancela
        melonn.cancelaciones.append((numero, motivo))
    melonn.pedir_cancelacion = no_hace_caso
    for horas in (0.1, 1, 3, 5, 7):
        _drenar(melonn, dentro_de=timedelta(hours=horas))
    assert "no ha confirmado la cancelación" in _despacho(vendida)[4]
    assert _verificador(vendida)[0] == "procesado"
