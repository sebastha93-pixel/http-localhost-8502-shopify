"""Emitir la factura de una venta — contra un Siigo de mentira.

LO QUE SE PRUEBA ES UNA SOLA COSA, de varias maneras: **una venta, una
factura.** Una factura de más no es un error de software; es un documento
ante la DIAN que se anula con nota crédito y con el contador.

El Siigo falso deja programar lo que la red real hace mal: responder que no,
no responder, o crear la factura y morirse antes de avisar.

LO QUE ESTO NO PRUEBA, y conviene tenerlo presente: que Siigo acepte el
documento. Eso sólo lo dice la primera emisión de verdad, en modo prueba.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

URL = os.environ.get("RETAIL_TEST_DATABASE_URL", "").strip()
pytestmark = pytest.mark.skipif(not URL, reason="Sin RETAIL_TEST_DATABASE_URL")

SESION = "01JQ8X4T5N6P0F1R8S9V0W1X2Y"
VENTA = "01JQ8X4T5N7V0F1R8S9V0W1X2Y"
VARIANTE = "01JQ8X4T5N6P7R8S9V0W1X2Y45"
PRECIO = 14_990_000
DOC_SIIGO = 40001


class SiigoFalso:
    """Lo que la red real hace mal, a pedido."""

    def __init__(self):
        self.enviadas = []          # cuerpos que llegaron a `crear_factura`
        self.en_siigo = []          # facturas que SÍ existen allá
        self.al_crear = "ok"        # ok | rechazo | sin_respuesta | crea_y_muere
        self.tipo = {"id": DOC_SIIGO, "active": True, "discount_type": "Value"}
        self.clientes = {"222222222222"}

    async def tipo_documento(self, documento_id):
        return self.tipo

    async def existe_cliente(self, identificacion):
        return identificacion in self.clientes

    async def buscar_por_marca(self, *, documento_id, fecha, marca):
        return next((f for f in self.en_siigo
                     if marca in f["observations"]), None)

    async def crear_factura(self, cuerpo):
        from backend.modules.retail.infrastructure.siigo.emisor_factura import (
            RechazoDeSiigo,
        )
        self.enviadas.append(cuerpo)
        if self.al_crear == "rechazo":
            raise RechazoDeSiigo('HTTP 400: {"Code":"invalid_total_payments"}')
        if self.al_crear == "sin_respuesta":
            raise RuntimeError("timeout")
        creada = {"id": f"siigo-{len(self.en_siigo) + 1}",
                  "name": f"FE-{100 + len(self.en_siigo)}",
                  "observations": cuerpo["observations"],
                  "stamp": {"status": "Draft", "cufe": None}}
        self.en_siigo.append(creada)
        if self.al_crear == "crea_y_muere":
            raise RuntimeError("se cortó después de crear")
        return creada


def _correr(c):
    return asyncio.get_event_loop().run_until_complete(c)


def _leer(motor, sql, params=None):
    async def ir():
        async with motor.connect() as cn:
            return (await cn.execute(text(sql), params or {})).all()
    return _correr(ir())


def _ejecutar(motor, sql, params=None):
    async def ir():
        async with motor.begin() as cn:
            await cn.execute(text(sql), params or {})
    _correr(ir())


@pytest_asyncio.fixture()
async def entorno(monkeypatch):
    from backend.core.security import CurrentUser, get_current_user
    from backend.modules.retail.interfaces.http import dependencias
    from backend.modules.retail.interfaces.http.router import router
    from backend.modules.retail.migraciones.runner import aplicar, revertir
    from backend.modules.retail.sembrar_tiendas import sembrar

    revertir(URL)
    aplicar(URL)
    sembrar(URL, aplicar=True)
    os.environ["RETAIL_DATABASE_URL"] = URL
    dependencias.reiniciar()
    monkeypatch.setenv("RETAIL_FISCAL_MODO", "prueba")

    motor = create_async_engine(URL)
    async with motor.begin() as c:
        await c.execute(text(
            "INSERT INTO retail.variantes "
            "(id,sku,referencia,talla,nombre,precio_con_iva) "
            "VALUES (:v,'92611-1T10','92611-1','10','Jean',:p)"),
            {"v": VARIANTE, "p": PRECIO})
        await c.execute(text(
            "INSERT INTO retail.stock_ubicacion (ubicacion_id,variante_id,cantidad) "
            "VALUES ('tienda:arrayanes',:v,9)"), {"v": VARIANTE})
        await c.execute(text(
            "INSERT INTO retail.permisos_pos (usuario_id,nombre,tiendas) "
            "VALUES ('maria','María R.','{arrayanes}')"))
        # La tienda YA configurada para facturar: comprobante y vendedor.
        await c.execute(text(
            "UPDATE retail.cajas SET siigo_documento_id = :d "
            "WHERE id = 'arrayanes_caja1'"), {"d": DOC_SIIGO})
        await c.execute(text(
            "UPDATE retail.tiendas SET siigo_vendedor_id = 842 "
            "WHERE id = 'arrayanes'"))

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id="maria", email="maria@male.com", nombre="María R.", rol="user",
        permisos={"retail": ["ver", "modificar"]})

    with TestClient(app) as c:
        t = c.post("/api/retail/caja/turno", json={
            "sesion_id": SESION, "tienda_id": "arrayanes",
            "caja_id": "arrayanes_caja1"}).json()
        # Dos prendas, pagadas con $300.000: lleva vuelto y lleva el centavo.
        r = c.post("/api/retail/ventas/cerrar", json={
            "venta_id": VENTA,
            "numero": f"{t['prefijo']}-{t['consecutivo_siguiente']}",
            "tienda_id": "arrayanes", "caja_id": "arrayanes_caja1",
            "sesion_id": SESION, "ubicacion_id": "tienda:arrayanes",
            "lineas": [{"sku": "92611-1T10", "cantidad": 2,
                        "precio_unitario_centavos": PRECIO,
                        "descripcion": "Jean · 10"}],
            "pagos": [{"medio_pago_id": "efectivo_arrayanes",
                       "monto_centavos": 30_000_000, "es_efectivo": True}]})
        assert r.status_code == 200, r.text
        yield motor

    await motor.dispose()
    dependencias.reiniciar()
    revertir(URL)


def _drenar(siigo, *, dentro_de=timedelta(minutes=1)):
    from backend.modules.retail.application.comandos.drenar_outbox import DrenarOutbox
    from backend.modules.retail.infrastructure.persistencia.unidad_de_trabajo import (
        UnidadDeTrabajoSQL, crear_fabrica, crear_motor,
    )
    from backend.modules.retail.infrastructure.siigo.emisor_factura import (
        crear_manejador,
    )

    async def ir():
        m = crear_motor(URL)
        try:
            return await DrenarOutbox(
                UnidadDeTrabajoSQL(crear_fabrica(m)),
                {"emitir_documento_fiscal": crear_manejador(siigo)},
            ).ejecutar(ahora=datetime.now(timezone.utc) + dentro_de, limite=20)
        finally:
            await m.dispose()
    return _correr(ir())


def _estado(motor):
    venta = _leer(motor, "SELECT estado_fiscal FROM retail.ventas")[0][0]
    cola = _leer(motor, "SELECT estado, intentos FROM retail.outbox")[0]
    docs = _leer(motor, "SELECT estado, numero FROM retail.documentos_fiscales")
    return venta, tuple(cola), [tuple(d) for d in docs]


# ── El camino normal ────────────────────────────────────────────────────────

def test_la_venta_se_factura_y_queda_anotada(entorno):
    siigo = SiigoFalso()
    r = _drenar(siigo)
    assert (r.procesados, r.fallidos) == (1, 0), r.errores

    assert _estado(entorno) == ("emitido", ("procesado", 1), [("emitido", "FE-100")])
    [cuerpo] = siigo.enviadas
    assert cuerpo["document"] == {"id": DOC_SIIGO}
    assert cuerpo["seller"] == 842
    assert cuerpo["customer"]["identification"] == "222222222222"
    assert cuerpo["items"][0]["warehouse"] == 37          # bodega de Arrayanes
    # A Siigo va lo que ENTRÓ ($299.800,01 con su centavo), no los $300.000.
    assert cuerpo["payments"] == [{"id": 8282, "value": 299800.01,
                                   "due_date": cuerpo["date"]}]
    # En modo prueba NO se estampa: no va a la DIAN.
    assert "stamp" not in cuerpo
    assert "_resumen" not in cuerpo      # eso es nuestro, no de Siigo


def test_drenar_dos_veces_no_emite_dos(entorno):
    siigo = SiigoFalso()
    _drenar(siigo)
    _drenar(siigo, dentro_de=timedelta(hours=3))
    assert len(siigo.enviadas) == 1


# ── UNA VENTA, UNA FACTURA ──────────────────────────────────────────────────

def test_si_siigo_la_creo_y_no_alcanzo_a_avisar_NO_se_emite_otra(entorno):
    """EL CASO QUE JUSTIFICA TODO EL DISEÑO. La factura se crea, la respuesta
    se pierde. Reintentar a ciegas emitiría la segunda. El reintento primero
    la BUSCA por su marca, la encuentra y la adopta."""
    siigo = SiigoFalso()
    siigo.al_crear = "crea_y_muere"
    r = _drenar(siigo)
    assert r.reintentos == 1
    assert _estado(entorno)[2] == [("enviando", None)]   # quedó la señal

    siigo.al_crear = "ok"
    r = _drenar(siigo, dentro_de=timedelta(hours=3))
    assert r.procesados == 1, r.errores
    assert len(siigo.enviadas) == 1, "se envió por segunda vez"
    assert len(siigo.en_siigo) == 1
    assert _estado(entorno)[2] == [("emitido", "FE-100")]


def test_si_nunca_llego_el_reintento_si_la_envia(entorno):
    """La otra mitad: «enviando» y en Siigo no hay nada. Ahí sí se manda."""
    siigo = SiigoFalso()
    siigo.al_crear = "sin_respuesta"
    assert _drenar(siigo).reintentos == 1

    siigo.al_crear = "ok"
    assert _drenar(siigo, dentro_de=timedelta(hours=3)).procesados == 1
    assert len(siigo.enviadas) == 2          # el que falló y el bueno
    assert len(siigo.en_siigo) == 1          # y UNA sola factura


# ── Cuando Siigo dice que no ────────────────────────────────────────────────

def test_un_rechazo_no_se_reintenta_ocho_veces(entorno):
    """Un 4xx es el documento mal armado: no mejora por insistir, y cada
    reintento retrasa que alguien lo vea."""
    siigo = SiigoFalso()
    siigo.al_crear = "rechazo"
    r = _drenar(siigo)
    assert r.fallidos == 1 and "invalid_total_payments" in r.errores[0]

    venta, cola, docs = _estado(entorno)
    assert venta == "rechazado" and cola[0] == "fallido"
    assert docs == [("rechazado", None)]

    _drenar(siigo, dentro_de=timedelta(hours=9))
    assert len(siigo.enviadas) == 1


# ── «Todavía no» no es un fallo ─────────────────────────────────────────────

def test_apagado_no_emite_ni_gasta_intentos(entorno, monkeypatch):
    """El valor por defecto. Encender la facturación es cambiar una variable,
    y lo que estaba en cola sale solo."""
    monkeypatch.setenv("RETAIL_FISCAL_MODO", "apagado")
    siigo = SiigoFalso()
    r = _drenar(siigo)
    assert r.sin_manejador == 1 and siigo.enviadas == []
    assert _estado(entorno)[1] == ("pendiente", 0)

    monkeypatch.setenv("RETAIL_FISCAL_MODO", "prueba")
    assert _drenar(siigo, dentro_de=timedelta(hours=3)).procesados == 1


def test_sin_comprobante_configurado_espera(entorno):
    _ejecutar(entorno, "UPDATE retail.cajas SET siigo_documento_id = NULL")
    siigo = SiigoFalso()
    assert _drenar(siigo).sin_manejador == 1
    assert siigo.enviadas == []
    motivo = _leer(entorno, "SELECT ultimo_error FROM retail.outbox")[0][0]
    assert "no tiene comprobante" in motivo
    assert _estado(entorno)[1] == ("pendiente", 0)


def test_si_siigo_no_expone_el_comprobante_espera(entorno):
    """Es lo que pasa HOY con FL, TARR y FV-6: no salen en /document-types."""
    siigo = SiigoFalso()
    siigo.tipo = None
    assert _drenar(siigo).sin_manejador == 1
    assert siigo.enviadas == []


def test_en_produccion_si_se_estampa(entorno, monkeypatch):
    monkeypatch.setenv("RETAIL_FISCAL_MODO", "produccion")
    siigo = SiigoFalso()
    _drenar(siigo)
    assert siigo.enviadas[0]["stamp"] == {"send": True}


def test_una_venta_anulada_antes_no_se_factura(entorno):
    _ejecutar(entorno, "UPDATE retail.ventas SET estado = 'anulada', motivo_anulacion = 'cobrada dos veces'")
    siigo = SiigoFalso()
    assert _drenar(siigo).procesados == 1
    assert siigo.enviadas == []
