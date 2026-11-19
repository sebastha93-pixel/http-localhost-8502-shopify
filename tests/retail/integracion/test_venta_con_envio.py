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


class WebFalsa:
    """La tienda en línea, a pedido: qué tiene, a cuánto y si contesta."""

    def __init__(self):
        self.caida = False
        self.variantes = {"92611-1T10": self.variante("92611-1T10", PRECIO, 5)}

    @staticmethod
    def variante(sku, precio, disponible, lista=None, nombre="Jean skinny"):
        return {"sku": sku, "nombre": nombre, "talla": sku.rsplit("T", 1)[-1],
                "precio_centavos": precio,
                "precio_lista_centavos": lista or precio,
                "disponible": disponible, "activo": True}

    def consultar(self, skus):
        from backend.modules.retail.infrastructure import tienda_en_linea
        if self.caida:
            raise tienda_en_linea.TiendaEnLineaNoDisponible("sin red")
        return {s.upper(): self.variantes[s.upper()] for s in skus
                if s.upper() in self.variantes}

    def buscar(self, texto, limite=12):
        from backend.modules.retail.infrastructure import tienda_en_linea
        if self.caida:
            raise tienda_en_linea.TiendaEnLineaNoDisponible("sin red")
        return [{"nombre": v["nombre"], "variantes": [v]}
                for v in self.variantes.values()
                if texto.lower() in (v["nombre"] + v["sku"]).lower()]


class MelonnFalso:
    """Lo que Melonn hace mal, a pedido."""

    def __init__(self):
        self.pedidos = {}           # número de la venta → pedido que SÍ existe
        self.enviados = []          # cuerpos que llegaron a `crear_pedido`
        self.preguntas = []
        self.al_crear = "ok"        # ok | rechazo | sin_respuesta | crea_y_muere | cuota | ocupado
        self.al_leer = "ok"         # ok | cuota | ocupado | caido
        self.cancelaciones = []
        self.al_cancelar = "ok"     # ok | rechazo
        self.justo_antes_de_contestar = None   # corrutina: «mientras se pedía…»

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
        if self.justo_antes_de_contestar:
            await self.justo_antes_de_contestar()
        # COMO EL POST: envuelto en `sell_order` y sin estado.
        return {"sell_order": {"internal_order_number": p["internal_order_number"],
                               "external_order_number": p["external_order_number"],
                               "external_order_id": cuerpo["external_order_id"]}}

    async def pedir_cancelacion(self, numero, motivo):
        from backend.modules.retail.infrastructure.melonn import despacho as d
        if self.al_cancelar == "rechazo":
            raise d.RechazoDeMelonn("HTTP 409: Order can not be canceled")
        self.cancelaciones.append((numero, motivo))
        if numero in self.pedidos:
            self.pedidos[numero]["state"] = {"id": 15, "name": "Canceled"}


@pytest.fixture(autouse=True)
def melonn_de_los_endpoints(monkeypatch):
    """Ninguna prueba le habla al Melonn de verdad: anular una venta con envío
    le pregunta a Melonn antes, y esa pregunta cae aquí."""
    from backend.modules.retail.infrastructure.melonn import despacho
    falso = MelonnFalso()
    monkeypatch.setattr(despacho, "io_por_defecto", lambda: falso)
    return falso


@pytest.fixture(autouse=True)
def web(monkeypatch):
    """Ninguna prueba le pregunta a Shopify de verdad."""
    from backend.modules.retail.infrastructure import tienda_en_linea
    falsa = WebFalsa()
    monkeypatch.setattr(tienda_en_linea, "consultar", falsa.consultar)
    monkeypatch.setattr(tienda_en_linea, "buscar", falsa.buscar)
    return falsa
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


# ── Etapa 2: lo que hay en la tienda en línea, y a cuánto ───────────────────

def _linea(sku="92611-1T10", precio=PRECIO, cantidad=1, **extra):
    return [{"sku": sku, "cantidad": cantidad,
             "precio_unitario_centavos": precio, "descripcion": "Jean", **extra}]


def _pago(monto):
    return [{"medio_pago_id": "datafono_arrayanes", "monto_centavos": monto,
             "referencia": "V-1"}]


def _mensaje(r):
    return r.json()["detail"]["mensaje"]


def test_lleva_el_precio_de_la_web_de_hoy_sin_gastar_el_tope(entorno, web):
    """La web tiene la prenda en promoción: $99.900 contra $149.900 de lista.
    La clienta paga $99.900 y eso NO es un descuento de la vendedora —María
    tiene tope 0 y aun así puede cobrarla—: es el precio de la tienda en
    línea."""
    _habilitar(entorno)
    web.variantes["92611-1T10"] = web.variante("92611-1T10", 9_990_000, 5,
                                               lista=PRECIO)
    r = _vender_con_envio(entorno, lineas=_linea(precio=9_990_000),
                          pagos=_pago(9_990_000))
    assert r.status_code == 200, r.text
    assert tuple(_leer(entorno, """
        SELECT total, descuento_total FROM retail.ventas WHERE id = :v""",
        {"v": VENTA_ENVIO})[0]) == (9_990_000, 0)


def test_lo_que_la_vendedora_baje_de_ahi_si_es_descuento_suyo(entorno, web):
    """Por debajo del precio de la web ya no es la promoción de la web: es
    una rebaja de quien cobra, y pasa por su tope (el de María es 0)."""
    _habilitar(entorno)
    r = _vender_con_envio(entorno, lineas=_linea(precio=PRECIO - 1_000_000),
                          pagos=_pago(PRECIO - 1_000_000))
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "sobre_el_tope"
    assert _leer(entorno, "SELECT count(*) FROM retail.despachos")[0][0] == 0


def test_si_la_web_bajo_el_precio_no_se_cobra_el_viejo(entorno, web):
    _habilitar(entorno)
    web.variantes["92611-1T10"] = web.variante("92611-1T10", 9_990_000, 5)
    r = _vender_con_envio(entorno)                  # manda $149.900
    assert r.status_code == 400
    assert "ahora está en $99.900" in _mensaje(r)


def test_las_promociones_de_la_tienda_no_viajan_con_el_envio(entorno):
    _habilitar(entorno)
    _ejecutar(entorno, """
        INSERT INTO retail.promociones
            (id, nombre, tipo, porcentaje, desde, hasta, tiendas, activa)
        VALUES ('promo20', '20 % en tienda', 'porcentaje', 20,
                now() - interval '1 day', now() + interval '1 day',
                '{arrayanes}', true)""")
    r = _vender_con_envio(entorno, lineas=_linea(promocion_id="promo20"))
    assert r.status_code == 400
    assert "no aplican a una venta con envío" in _mensaje(r)
    assert _leer(entorno, "SELECT count(*) FROM retail.despachos")[0][0] == 0


def test_una_prenda_que_el_pos_no_conocia_se_crea_apagada(entorno, web):
    """El POS sólo carga lo que tiene existencia en una tienda. Lo que sólo
    está en la web se crea al venderlo, y entra APAGADO: existe para la venta,
    no para aparecer en el buscador del mostrador."""
    _habilitar(entorno)
    web.variantes["96617-1T8"] = web.variante(
        "96617-1T8", 18_990_000, 3, lista=19_990_000,
        nombre="Jean wide leg ballón")
    r = _vender_con_envio(entorno, lineas=_linea("96617-1T8", 18_990_000),
                          pagos=_pago(18_990_000))
    assert r.status_code == 200, r.text
    assert tuple(_leer(entorno, """
        SELECT referencia, talla, nombre, precio_con_iva, activa
          FROM retail.variantes WHERE sku = '96617-1T8'""")[0]) == (
        "96617-1", "8", "JEAN WIDE LEG BALLÓN", 19_990_000, False)
    assert _leer(entorno, "SELECT total FROM retail.ventas WHERE id = :v",
                 {"v": VENTA_ENVIO})[0][0] == 18_990_000


def test_sin_existencia_en_la_web_no_se_vende(entorno, web):
    _habilitar(entorno)
    web.variantes["92611-1T10"]["disponible"] = 0
    r = _vender_con_envio(entorno)
    assert r.status_code == 400
    assert "ya no queda" in _mensaje(r)

    web.variantes["92611-1T10"]["disponible"] = 1
    r = _vender_con_envio(entorno, lineas=_linea(cantidad=2),
                          pagos=_pago(PRECIO * 2))
    assert r.status_code == 400
    assert "sólo queda 1" in _mensaje(r)
    assert _leer(entorno, "SELECT count(*) FROM retail.ventas")[0][0] == 1


def test_lo_que_no_esta_en_la_web_no_se_vende_con_envio(entorno, web):
    _habilitar(entorno)
    web.variantes.clear()
    r = _vender_con_envio(entorno)
    assert r.status_code == 400
    assert "no está en la tienda en línea" in _mensaje(r)


def test_si_la_tienda_en_linea_no_contesta_no_se_cobra(entorno, web):
    """Falla cerrado: sin poder comprobar la existencia, no hay venta."""
    _habilitar(entorno)
    web.caida = True
    r = _vender_con_envio(entorno)
    assert r.status_code == 400
    assert "No se pudo consultar la tienda en línea" in _mensaje(r)
    assert _leer(entorno, "SELECT count(*) FROM retail.ventas")[0][0] == 1


def test_el_buscador_en_linea(entorno, web):
    c = _CLIENTE["c"]
    r = c.get("/api/retail/catalogo/en-linea",
              params={"tienda_id": "arrayanes", "q": "skinny"})
    assert r.status_code == 400                      # la tienda no vende así
    assert r.json()["detail"]["error"] == "sin_envio"

    _habilitar(entorno)
    r = c.get("/api/retail/catalogo/en-linea",
              params={"tienda_id": "arrayanes", "q": "skinny"})
    assert r.status_code == 200, r.text
    [p] = r.json()["productos"]
    assert (p["nombre"], p["variantes"][0]["sku"],
            p["variantes"][0]["disponible"]) == ("Jean skinny", "92611-1T10", 5)

    web.caida = True
    r = c.get("/api/retail/catalogo/en-linea",
              params={"tienda_id": "arrayanes", "q": "skinny"})
    assert r.status_code == 503
    assert r.json()["detail"]["error"] == "tienda_en_linea_no_disponible"
