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
    _habilitar,
    _vender_con_envio,
    web,
)

pytestmark = pytest.mark.skipif(not URL, reason="Sin RETAIL_TEST_DATABASE_URL")


class MelonnFalso:
    """Lo que Melonn hace mal, a pedido."""

    def __init__(self):
        self.pedidos = {}           # número de la venta → pedido que SÍ existe
        self.enviados = []          # cuerpos que llegaron a `crear_pedido`
        self.preguntas = []
        self.al_crear = "ok"        # ok | rechazo | sin_respuesta | crea_y_muere | cuota | ocupado
        self.al_leer = "ok"         # ok | cuota | ocupado | caido
        self.cancelaciones = []

    async def leer_pedido(self, numero):
        from backend.modules.retail.infrastructure.melonn import despacho as d
        self.preguntas.append(numero)
        if self.al_leer == "cuota":
            raise d.CuotaAgotada("cuota diaria de Melonn agotada")
        if self.al_leer == "ocupado":
            raise d.MelonnOcupado("Melonn HTTP 429")
        if self.al_leer == "caido":
            raise RuntimeError("Melonn HTTP 500")
        return self.pedidos.get(numero)

    def _guardar(self, cuerpo):
        n = cuerpo["external_order_number"]
        # COMO EL GET (medido 2026-11-17): el pedido suelto, estado con `id` y
        # el nombre repetido.
        self.pedidos[n] = {
            "internal_order_number": f"M17949449650{len(self.pedidos):05d}",
            "external_order_number": n,
            "state": {"id": 2, "name": "All items reserved - ready for fulfillment" * 2},
            "melonn_tracking_link": f"https://rastreo.melonn.com/{n}"}
        return self.pedidos[n]

    async def crear_pedido(self, cuerpo):
        from backend.modules.retail.infrastructure.melonn import despacho as d
        if self.al_crear == "cuota":
            raise d.CuotaAgotada("cuota diaria de Melonn agotada")
        if self.al_crear == "ocupado":
            raise d.MelonnOcupado("Melonn HTTP 429")
        self.enviados.append(cuerpo)
        if self.al_crear == "rechazo":
            raise d.RechazoDeMelonn("HTTP 400: No stock available for sku 92611-1T10")
        if self.al_crear == "sin_respuesta":
            raise RuntimeError("timeout")
        p = self._guardar(cuerpo)
        if self.al_crear == "crea_y_muere":
            raise RuntimeError("se cortó después de crear")
        # COMO EL POST: envuelto en `sell_order` y sin estado.
        return {"sell_order": {"internal_order_number": p["internal_order_number"],
                               "external_order_number": p["external_order_number"],
                               "external_order_id": cuerpo["external_order_id"]}}

    async def pedir_cancelacion(self, numero, motivo):
        self.cancelaciones.append((numero, motivo))
        if numero in self.pedidos:
            self.pedidos[numero]["state"] = {"id": 15, "name": "Canceled"}


def _drenar(melonn, *, dentro_de=timedelta(minutes=1), siigo=None):
    from backend.modules.retail.application.comandos.drenar_outbox import DrenarOutbox
    from backend.modules.retail.infrastructure.melonn import despacho
    from backend.modules.retail.infrastructure.persistencia.unidad_de_trabajo import (
        UnidadDeTrabajoSQL, crear_fabrica, crear_motor,
    )
    from backend.modules.retail.infrastructure.siigo import emisor_factura

    async def ir():
        m = crear_motor(URL)
        try:
            return await DrenarOutbox(
                UnidadDeTrabajoSQL(crear_fabrica(m)),
                {"emitir_documento_fiscal":
                     emisor_factura.crear_manejador(siigo or SiigoFalso()),
                 "crear_despacho_melonn": despacho.crear_manejador(melonn)},
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
    assert _drenar(melonn).reintentos == 1
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
