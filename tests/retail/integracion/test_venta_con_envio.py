"""Venta con envío a domicilio — los cimientos (migración 0042).

Lo que estas pruebas cuidan, en orden de lo que más dolería:

1. Que una venta de MOSTRADOR siga siendo exactamente lo que era. (Eso ya lo
   vigila `test_emisor_factura.py`, que comprueba la bodega 37 de Arrayanes en
   la factura y en la nota crédito; aquí se comprueba que el canal por defecto
   no cambia nada.)
2. Que una venta CON ENVÍO se facture con el comprobante, el vendedor y el
   centro de costos de la tienda que cobró, pero con la bodega de la tienda en
   línea —que es donde está la prenda—, y sin tocar el estante de la tienda.
3. Que nadie pueda vender con envío donde no está habilitado, sin dirección o
   sin red.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from tests.retail.integracion.test_emisor_factura import (  # noqa: F401
    PRECIO,
    SESION,
    URL,
    VARIANTE,
    SiigoFalso,
    _CLIENTE,
    _docs,
    _drenar,
    _ejecutar,
    _leer,
    entorno,
)

pytestmark = pytest.mark.skipif(not URL, reason="Sin RETAIL_TEST_DATABASE_URL")

VENTA_ENVIO = "01JQ8X4T5N7V0F2R8S9V0W1X2Y"
ENTREGA = {"destinatario": "Laura Gómez", "telefono": "3001234567",
           "direccion": "Calle 10 # 43-21", "complemento": "Apto 502",
           "ciudad": "Medellín", "departamento": "Antioquia"}


def _habilitar(motor):
    _ejecutar(motor, "UPDATE retail.tiendas SET vende_con_envio = true "
                     "WHERE id = 'arrayanes'")


def _vender_con_envio(motor, **cambios):
    """Otra venta en el turno que abrió `entorno`, esta vez con envío."""
    siguiente = _leer(motor, """
        SELECT prefijo || '-' || siguiente FROM retail.bloques_consecutivo
         WHERE caja_id = 'arrayanes_caja1' ORDER BY desde DESC LIMIT 1""")[0][0]
    cuerpo = {
        "venta_id": VENTA_ENVIO, "numero": siguiente,
        "tienda_id": "arrayanes", "caja_id": "arrayanes_caja1",
        "sesion_id": SESION, "ubicacion_id": "tienda:arrayanes",
        "canal": "envio", "entrega": ENTREGA,
        "lineas": [{"sku": "92611-1T10", "cantidad": 1,
                    "precio_unitario_centavos": PRECIO,
                    "descripcion": "Jean · 10"}],
        "pagos": [{"medio_pago_id": "datafono_arrayanes",
                   "monto_centavos": PRECIO, "referencia": "V-1"}],
    }
    cuerpo.update(cambios)
    return _CLIENTE["c"].post("/api/retail/ventas/cerrar", json=cuerpo)


def _stock(motor, ubicacion):
    filas = _leer(motor, "SELECT cantidad FROM retail.stock_ubicacion "
                         "WHERE ubicacion_id = :u AND variante_id = :v",
                  {"u": ubicacion, "v": VARIANTE})
    return filas[0][0] if filas else None


# ── Lo que ya existía no cambia ─────────────────────────────────────────────

def test_una_venta_de_mostrador_sigue_siendo_de_mostrador(entorno):
    """La venta que hace `entorno` no dice canal: es de mostrador, sale del
    estante de la tienda y no tiene despacho."""
    assert _leer(entorno, "SELECT canal FROM retail.ventas")[0][0] == "mostrador"
    assert _stock(entorno, "tienda:arrayanes") == 7          # 9 − 2 vendidas
    assert _stock(entorno, "bodega:en_linea") is None
    assert _leer(entorno, "SELECT count(*) FROM retail.despachos")[0][0] == 0


# ── La venta con envío ──────────────────────────────────────────────────────

def test_la_venta_con_envio_no_toca_el_estante_y_deja_su_despacho(entorno):
    _habilitar(entorno)
    r = _vender_con_envio(entorno)
    assert r.status_code == 200, r.text

    assert _leer(entorno, "SELECT canal FROM retail.ventas WHERE id = :v",
                 {"v": VENTA_ENVIO})[0][0] == "envio"
    # El estante de Arrayanes sigue como lo dejó la venta de mostrador: la
    # prenda de ESTA venta nunca estuvo ahí.
    assert _stock(entorno, "tienda:arrayanes") == 7
    assert _stock(entorno, "bodega:en_linea") == -1
    assert [tuple(f) for f in _leer(entorno, """
        SELECT estado, destinatario, telefono, direccion, complemento, ciudad,
               departamento FROM retail.despachos WHERE venta_id = :v""",
        {"v": VENTA_ENVIO})] == [
        ("pendiente", "Laura Gómez", "3001234567", "Calle 10 # 43-21",
         "Apto 502", "Medellín", "Antioquia")]


def test_se_factura_con_la_bodega_de_la_tienda_en_linea(entorno):
    """Comprobante, vendedor y centro de costos de la tienda que cobró; la
    bodega, la de la tienda en línea (32). Y la marca del POS sigue entera al
    principio de la observación: por ella se reencuentra la factura."""
    _habilitar(entorno)
    assert _vender_con_envio(entorno).status_code == 200
    siigo = SiigoFalso()
    r = _drenar(siigo)
    assert r.procesados == 2, r.errores

    mostrador, envio = sorted(siigo.enviadas,
                              key=lambda c: "Entrega" in c["observations"])
    # La de mostrador, idéntica a la de siempre.
    assert {i["warehouse"] for i in mostrador["items"]} == {37}
    assert "Entrega a domicilio" not in mostrador["observations"]

    assert {i["warehouse"] for i in envio["items"]} == {32}
    assert envio["document"] == mostrador["document"]
    assert envio["seller"] == mostrador["seller"]
    assert envio.get("cost_center") == mostrador.get("cost_center")
    numero = _leer(entorno, "SELECT numero FROM retail.ventas WHERE id = :v",
                   {"v": VENTA_ENVIO})[0][0]
    assert envio["observations"] == (
        f"POS {numero} · {VENTA_ENVIO} · Entrega a domicilio")


def test_anularla_devuelve_la_prenda_a_la_bodega_en_linea(entorno, monkeypatch):
    """Anulada antes de despacharse, la prenda vuelve a donde estaba: la nota
    crédito lleva la bodega 32 y el estante de la tienda no se entera."""
    monkeypatch.setenv("RETAIL_FISCAL_MODO", "produccion")
    _habilitar(entorno)
    assert _vender_con_envio(entorno).status_code == 200
    siigo = SiigoFalso()
    _drenar(siigo)

    r = _CLIENTE["c"].post(f"/api/retail/ventas/{VENTA_ENVIO}/anular",
                           json={"motivo": "la clienta se arrepintió"})
    assert r.status_code == 200, r.text
    r = _drenar(siigo, dentro_de=timedelta(minutes=5))
    assert r.procesados == 1, r.errores

    [nc] = siigo.nc_enviadas
    assert {i["warehouse"] for i in nc["items"]} == {32}
    assert _stock(entorno, "bodega:en_linea") == 0
    assert _stock(entorno, "tienda:arrayanes") == 7


# ── Lo que no se deja ───────────────────────────────────────────────────────

def test_una_tienda_sin_habilitar_no_vende_con_envio(entorno):
    r = _vender_con_envio(entorno)
    assert r.status_code == 400
    assert "no tiene habilitada" in r.json()["detail"]["mensaje"]
    assert _leer(entorno, "SELECT count(*) FROM retail.ventas")[0][0] == 1


def test_sin_direccion_no_hay_venta_con_envio(entorno):
    _habilitar(entorno)
    r = _vender_con_envio(entorno, entrega=None)
    assert r.status_code == 400
    assert "a dónde enviar" in r.json()["detail"]["mensaje"]

    r = _vender_con_envio(entorno, entrega={**ENTREGA, "ciudad": "   "})
    assert r.status_code == 400
    assert "ciudad" in r.json()["detail"]["mensaje"]
    assert _leer(entorno, "SELECT count(*) FROM retail.despachos")[0][0] == 0


def test_sin_red_no_se_vende_con_envio(entorno):
    """Sin conexión no hay cómo saber si la prenda existe en la tienda en
    línea: esa venta no se acepta ni cuando llega después por la cola."""
    _habilitar(entorno)
    r = _vender_con_envio(entorno, origen="fuera_de_linea")
    assert r.status_code == 400
    assert "sin conexión" in r.json()["detail"]["mensaje"]


def test_un_canal_desconocido_se_rechaza(entorno):
    r = _vender_con_envio(entorno, canal="domicilio")
    assert r.status_code == 400
    assert "canal" in r.json()["detail"]["mensaje"]


# ── La tienda y la caja ─────────────────────────────────────────────────────

def test_la_caja_sabe_si_su_tienda_vende_con_envio(entorno):
    c = _CLIENTE["c"]
    ctx = c.get("/api/retail/caja/contexto",
                params={"caja_id": "arrayanes_caja1"}).json()
    assert ctx["vende_con_envio"] is False
    _habilitar(entorno)
    ctx = c.get("/api/retail/caja/contexto",
                params={"caja_id": "arrayanes_caja1"}).json()
    assert ctx["vende_con_envio"] is True


def test_la_sincronizacion_no_le_resta_al_estante_lo_vendido_con_envio(entorno):
    """La sincronización horaria le resta a Siigo lo cobrado sin facturar,
    para no «devolver» al estante lo recién vendido. Lo vendido con envío no
    salió de ese estante: no se le resta."""
    from backend.modules.retail.sincronizar_inventario import sincronizar

    _habilitar(entorno)
    assert _vender_con_envio(entorno).status_code == 200
    # Siigo dice 9 en Arrayanes. Hay 2 de mostrador y 1 con envío sin facturar.
    from tests.retail.integracion.test_sincronizar_inventario import _p

    r = sincronizar(URL, productos=[_p("92611-1T10", "JEAN", arrayanes=9)],
                    aplicar=True, precios_de_lista=lambda codigos: {})
    assert r["tiendas"]["arrayanes"].get("problemas", []) == [], r
    assert _stock(entorno, "tienda:arrayanes") == 7           # 9 − 2, no 9 − 3
