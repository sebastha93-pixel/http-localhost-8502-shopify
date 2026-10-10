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

    # Sin pausas y con una sola consulta inmediata: las pruebas no esperan.
    consultas_inmediatas = 1
    pausa = 0

    def __init__(self):
        self.enviadas = []          # cuerpos que llegaron a `crear_factura`
        self.en_siigo = []          # facturas que SÍ existen allá
        self.al_crear = "ok"        # ok | rechazo | sin_respuesta | crea_y_muere
        self.tipo = {"id": DOC_SIIGO, "active": True, "discount_type": "Value"}
        self.clientes = {"222222222222"}
        # Lo que contesta la DIAN cuando se le pregunta por una factura.
        self.dian = "accepted"      # accepted | draft | rejected
        self.lecturas = 0
        self.clientes_creados = []
        self.al_crear_cliente = "ok"   # ok | rechazo | ya_existia
        self.nc_enviadas = []
        self.nc_en_siigo = []
        self.al_crear_nc = "ok"     # ok | rechazo | sin_respuesta | crea_y_muere
        self.dian_nc = "accepted"

    # ── Notas crédito ──
    async def crear_nota_credito(self, cuerpo):
        from backend.modules.retail.infrastructure.siigo.emisor_factura import (
            RechazoDeSiigo,
        )
        self.nc_enviadas.append(cuerpo)
        if self.al_crear_nc == "rechazo":
            raise RechazoDeSiigo('HTTP 400: {"Code":"invalid_document"}')
        if self.al_crear_nc == "sin_respuesta":
            raise RuntimeError("timeout")
        # Como la cuenta: sin `prefix`, el número es `name`.
        nc = {"id": f"nc-{len(self.nc_en_siigo) + 1}",
              "name": f"NC-1-{7505 + len(self.nc_en_siigo)}", "prefix": None,
              "observations": cuerpo["observations"],
              "stamp": {"status": "Draft"}}
        self.nc_en_siigo.append(nc)
        if self.al_crear_nc == "crea_y_muere":
            raise RuntimeError("se cortó después de crear")
        return nc

    async def leer_nota_credito(self, siigo_id):
        nc = dict(next(x for x in self.nc_en_siigo if x["id"] == siigo_id))
        nc["stamp"] = {"accepted": {"status": "Accepted", "cude": "d" * 96},
                       "draft": {"status": "Draft"},
                       "rejected": {"status": "Rejected", "errors": "CAD01"},
                       }[self.dian_nc]
        return nc

    async def buscar_nc_por_marca(self, *, desde, marca):
        return next((n for n in self.nc_en_siigo
                     if marca in n["observations"]), None)

    async def leer_factura(self, siigo_id):
        self.lecturas += 1
        f = dict(next(x for x in self.en_siigo if x["id"] == siigo_id))
        # COMO LO DEVUELVE EL GET: bodega, centro de costo e impuestos
        # EXPANDIDOS. La nota crédito tiene que aplanarlos.
        c = f["_cuerpo"]
        f.update({
            "items": [{"code": it["code"], "description": it["description"],
                       "quantity": float(it["quantity"]), "price": 125966.386555,
                       "warehouse": {"id": it["warehouse"], "name": "ARRAYANES"},
                       "taxes": [{"id": 6352, "name": "IVA 19%", "percentage": 19}]}
                      for it in c["items"]],
            "payments": [{"id": p["id"], "name": "Caja general Arrayanes",
                          "value": p["value"]} for p in c["payments"]],
            "customer": {"id": "x", "identification": c["customer"]["identification"],
                         "branch_office": 0},
            "seller": c["seller"], "cost_center": c.get("cost_center"),
            "total": sum(p["value"] for p in c["payments"]),
        })
        f["stamp"] = {
            "accepted": {"status": "Accepted", "cufe": "c" * 96},
            "draft": {"status": "Draft"},
            "rejected": {"status": "Rejected", "errors": "FAD06 valor inválido"},
        }[self.dian]
        return f

    async def crear_cliente(self, cuerpo):
        from backend.modules.retail.infrastructure.siigo.emisor_factura import (
            RechazoDeSiigo,
        )
        self.clientes_creados.append(cuerpo)
        if self.al_crear_cliente == "rechazo":
            raise RechazoDeSiigo('HTTP 400: {"Code":"invalid_reference"}')
        if self.al_crear_cliente == "ya_existia":
            self.clientes.add(cuerpo["identification"])
            raise RechazoDeSiigo('HTTP 400: {"Code":"already_exists"}')
        self.clientes.add(cuerpo["identification"])
        return {"id": "cli-siigo-1", "identification": cuerpo["identification"]}

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
        # COMO RESPONDE LA CUENTA (medido el 2026-10-08): `name` es el código
        # interno del comprobante; el número legal es `prefix` + `number`.
        n = 11452 + len(self.en_siigo)
        creada = {"id": f"siigo-{len(self.en_siigo) + 1}",
                  "name": f"FV-6-{n}", "prefix": "TARR", "number": n,
                  "observations": cuerpo["observations"],
                  "stamp": {"status": "Draft", "cufe": None},
                  "_cuerpo": cuerpo}
        self.en_siigo.append(creada)
        if self.al_crear == "crea_y_muere":
            raise RuntimeError("se cortó después de crear")
        return creada


#  El cliente HTTP de la prueba en curso, para las que anulan por la API.
_CLIENTE: dict = {}


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
            "INSERT INTO retail.permisos_pos "
            "(usuario_id,nombre,tiendas,puede_anular_venta) "
            "VALUES ('maria','María R.','{arrayanes}',true)"))
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
        _CLIENTE["c"] = c
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
    from backend.modules.retail.infrastructure.siigo.emisor_nota_credito import (
        crear_manejador as manejador_nc,
    )

    async def ir():
        m = crear_motor(URL)
        try:
            return await DrenarOutbox(
                UnidadDeTrabajoSQL(crear_fabrica(m)),
                {"emitir_documento_fiscal": crear_manejador(siigo),
                 "emitir_nota_credito": manejador_nc(siigo)},
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

    assert _estado(entorno) == ("emitido", ("procesado", 1), [("emitido", "TARR-11452")])
    [cuerpo] = siigo.enviadas
    assert cuerpo["document"] == {"id": DOC_SIIGO}
    assert cuerpo["seller"] == 842
    assert cuerpo["customer"]["identification"] == "222222222222"
    assert cuerpo["items"][0]["warehouse"] == 37          # bodega de Arrayanes
    # A Siigo va lo que ENTRÓ ($299.800 exactos), no los $300.000 entregados.
    assert cuerpo["payments"] == [{"id": 8282, "value": 299800.0,
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
    assert _estado(entorno)[2] == [("emitido", "TARR-11452")]


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


# ── CREADA EN SIIGO NO ES FACTURA: falta la DIAN ────────────────────────────

def _doc(motor):
    return tuple(_leer(motor, "SELECT estado, numero, cufe "
                              "FROM retail.documentos_fiscales")[0])


def test_el_numero_de_la_factura_es_prefijo_y_consecutivo_NO_el_name(entorno):
    """`name` es «FV-6-11452», el código interno de Siigo. Lo que la DIAN
    validó, y lo que va impreso, es «TARR-11452»."""
    _drenar(SiigoFalso())
    assert _doc(entorno)[1] == "TARR-11452"


def test_en_produccion_solo_queda_emitida_cuando_la_dian_valida(entorno, monkeypatch):
    monkeypatch.setenv("RETAIL_FISCAL_MODO", "produccion")
    siigo = SiigoFalso()
    r = _drenar(siigo)
    assert r.procesados == 1, r.errores
    assert _doc(entorno) == ("emitido", "TARR-11452", "c" * 96)
    assert _estado(entorno)[0] == "emitido"
    assert siigo.lecturas == 1


def test_si_la_dian_tarda_la_venta_NO_figura_emitida_y_no_se_reenvia(entorno, monkeypatch):
    """Lo que estaba mal: creada en Siigo = `emitido`. Con la DIAN todavía
    pensando, la tirilla habría dicho «factura» de un borrador."""
    monkeypatch.setenv("RETAIL_FISCAL_MODO", "produccion")
    siigo = SiigoFalso()
    siigo.dian = "draft"
    r = _drenar(siigo)
    assert (r.procesados, r.fallidos, r.reintentos) == (0, 0, 0)
    assert _doc(entorno) == ("verificando", "TARR-11452", None)
    venta, cola, _ = _estado(entorno)
    assert venta == "enviando"
    assert cola == ("pendiente", 0)          # esperar NO gasta intentos

    # Vuelve a mirar en un minuto, no en una hora: la clienta está ahí.
    espera = _leer(entorno, "SELECT extract(epoch FROM "
                            "(proximo_intento_en - now())) FROM retail.outbox")[0][0]
    assert float(espera) < 300

    siigo.dian = "accepted"
    r = _drenar(siigo, dentro_de=timedelta(minutes=5))
    assert r.procesados == 1, r.errores
    assert len(siigo.enviadas) == 1, "se reenvió una factura que ya estaba en Siigo"
    assert _doc(entorno) == ("emitido", "TARR-11452", "c" * 96)


def test_si_la_dian_la_rechaza_queda_a_la_vista_y_no_se_reenvia(entorno, monkeypatch):
    monkeypatch.setenv("RETAIL_FISCAL_MODO", "produccion")
    siigo = SiigoFalso()
    siigo.dian = "rejected"
    r = _drenar(siigo)
    assert r.fallidos == 1 and "FAD06" in r.errores[0]
    venta, cola, docs = _estado(entorno)
    assert venta == "rechazado" and cola[0] == "fallido"
    assert docs == [("rechazado", "TARR-11452")]

    _drenar(siigo, dentro_de=timedelta(hours=9))
    assert len(siigo.enviadas) == 1


def test_horas_sin_validar_deja_de_insistir_y_pide_que_alguien_mire(entorno, monkeypatch):
    monkeypatch.setenv("RETAIL_FISCAL_MODO", "produccion")
    siigo = SiigoFalso()
    siigo.dian = "draft"
    _drenar(siigo)
    _ejecutar(entorno, "UPDATE retail.documentos_fiscales "
                       "SET creado_en = now() - interval '7 hours'")
    r = _drenar(siigo, dentro_de=timedelta(minutes=5))
    assert r.fallidos == 1 and "revisar en Siigo" in r.errores[0]
    assert _estado(entorno)[0] == "discrepante"
    assert len(siigo.enviadas) == 1


def test_en_prueba_el_documento_existe_pero_la_tirilla_NO_lo_llama_factura(entorno):
    """Modo prueba: se crea en Siigo sin estampar. No hay CUFE, no hay DIAN,
    y un papel que dijera «FACTURA ELECTRÓNICA» sería falso."""
    from backend.modules.retail.application.consultas.tirilla import ArmarTirilla
    from sqlalchemy.ext.asyncio import AsyncSession

    _drenar(SiigoFalso())
    assert _doc(entorno) == ("emitido", "TARR-11452", None)

    async def ir():
        async with AsyncSession(entorno) as s:
            return await ArmarTirilla(s).ejecutar(VENTA)
    t = _correr(ir())
    assert t.es_documento_fiscal is False
    assert t.qr_ruta is None


def test_la_tirilla_de_una_factura_validada_lleva_lo_que_pide_la_norma(entorno, monkeypatch):
    from backend.modules.retail.application.consultas.tirilla import ArmarTirilla
    from sqlalchemy.ext.asyncio import AsyncSession

    monkeypatch.setenv("RETAIL_FISCAL_MODO", "produccion")

    async def ir():
        async with AsyncSession(entorno) as s:
            return await ArmarTirilla(s).ejecutar(VENTA)

    # Esta prueba fija el texto con la resolución heredada de la TIENDA: la
    # caja sin resolución propia.
    _ejecutar(entorno, "UPDATE retail.cajas SET autorizacion_prefijo = NULL")

    # Antes de emitir: viene en camino, y todavía no es factura.
    antes = _correr(ir())
    assert antes.factura_en_camino is True and antes.es_documento_fiscal is False
    assert antes.resolucion_dian is None

    _drenar(SiigoFalso())
    t = _correr(ir())
    assert t.es_documento_fiscal is True
    assert t.factura_en_camino is False
    assert t.documento_fiscal == "TARR-11452"
    assert t.numero.startswith("ARRPOS-")          # el del POS, como referencia
    assert t.cufe == "c" * 96 and t.qr_ruta
    assert t.fecha_expedicion
    assert t.regimen == "Responsable de IVA - Actividad económica 4782"
    assert t.resolucion_dian == (
        "Número Autorización 18764083761292 aprobado en 20241120 prefijo TARR "
        "desde el número 1 al 1000000 Vigencia: 24 meses")


def test_la_resolucion_es_de_la_CAJA_y_sin_sus_datos_no_hay_factura(entorno, monkeypatch):
    """Las resoluciones nuevas van por caja (Florida tiene dos). Con el prefijo
    puesto y el resto sin cargar, la tirilla NO toma prestado el número de la
    resolución vieja de la tienda: no se llama factura hasta tener los datos."""
    from backend.modules.retail.application.consultas.tirilla import ArmarTirilla
    from sqlalchemy.ext.asyncio import AsyncSession

    monkeypatch.setenv("RETAIL_FISCAL_MODO", "produccion")
    _drenar(SiigoFalso())
    _ejecutar(entorno, "UPDATE retail.documentos_fiscales SET numero = 'ARRT-1'")
    # La caja con el prefijo y NADA más, como quedó el día que se crearon.
    _ejecutar(entorno, "UPDATE retail.cajas SET autorizacion_numero = NULL, "
                       "autorizacion_aprobada = NULL")

    async def ir():
        async with AsyncSession(entorno) as s:
            return await ArmarTirilla(s).ejecutar(VENTA)
    t = _correr(ir())
    assert t.resolucion_dian is None and t.es_documento_fiscal is False

    _ejecutar(entorno, """
        UPDATE retail.cajas SET autorizacion_numero = '18764099999999',
               autorizacion_desde = 1, autorizacion_hasta = 50000,
               autorizacion_aprobada = DATE '2026-10-09', autorizacion_meses = 24
         WHERE id = 'arrayanes_caja1'""")
    t = _correr(ir())
    assert t.es_documento_fiscal is True
    assert t.resolucion_dian == (
        "Número Autorización 18764099999999 aprobado en 20261009 prefijo ARRT "
        "desde el número 1 al 50000 Vigencia: 24 meses")


def test_la_resolucion_NO_se_le_pega_a_un_numero_que_no_ampara(entorno, monkeypatch):
    """La caja apuntando al comprobante que no es: Siigo devuelve una factura
    con otro prefijo. Imprimirle la resolución de la tienda sería un dato
    falso en un papel fiscal — sin resolución, el papel no se llama factura."""
    from backend.modules.retail.application.consultas.tirilla import ArmarTirilla
    from sqlalchemy.ext.asyncio import AsyncSession

    monkeypatch.setenv("RETAIL_FISCAL_MODO", "produccion")
    _drenar(SiigoFalso())
    _ejecutar(entorno, "UPDATE retail.documentos_fiscales SET numero = 'FE-67701'")

    async def ir():
        async with AsyncSession(entorno) as s:
            return await ArmarTirilla(s).ejecutar(VENTA)
    t = _correr(ir())
    assert t.resolucion_dian is None
    assert t.es_documento_fiscal is False


def test_con_la_facturacion_apagada_nada_viene_en_camino(entorno, monkeypatch):
    from backend.modules.retail.application.consultas.tirilla import ArmarTirilla
    from sqlalchemy.ext.asyncio import AsyncSession

    async def ir():
        async with AsyncSession(entorno) as s:
            return await ArmarTirilla(s).ejecutar(VENTA)
    for m in ("apagado", "prueba"):
        monkeypatch.setenv("RETAIL_FISCAL_MODO", m)
        assert _correr(ir()).factura_en_camino is False


# ── La clienta que Siigo no conoce ──────────────────────────────────────────

CLIENTA = "01JQ8X4T5NCK0F1R8S9V0W1X2Y"


def _con_clienta(motor, *, nombre="Laura", apellido="Gómez Ríos",
                 correo="laura@correo.com"):
    _ejecutar(motor, """
        INSERT INTO retail.clientes (id, tipo_documento, numero_documento,
            nombre, apellido, telefono, correo, ciudad, direccion)
        VALUES (:i, 'CC', '1037000111', :n, :a, '+573001112233', :c,
                'Itagüí', 'CL 50 # 40-20')
    """, {"i": CLIENTA, "n": nombre, "a": apellido, "c": correo})
    _ejecutar(motor, "UPDATE retail.ventas SET cliente_id = :i", {"i": CLIENTA})


def test_la_clienta_nueva_se_crea_en_siigo_y_se_le_factura_A_ELLA(entorno, monkeypatch):
    monkeypatch.setenv("RETAIL_FISCAL_MODO", "produccion")
    _con_clienta(entorno)
    siigo = SiigoFalso()
    r = _drenar(siigo)
    assert r.procesados == 1, r.errores

    [c] = siigo.clientes_creados
    assert c["person_type"] == "Person" and c["id_type"] == "13"
    assert c["identification"] == "1037000111"
    assert c["name"] == ["Laura", "Gómez Ríos"]
    assert c["phones"] == [{"number": "3001112233"}]      # sin el +57
    assert c["address"]["city"] == {"country_code": "Co", "state_code": "05",
                                    "city_code": "05360"}
    assert c["contacts"][0]["email"] == "laura@correo.com"

    [f] = siigo.enviadas
    assert f["customer"]["identification"] == "1037000111"
    assert f["mail"] == {"send": True}       # dejó correo: Siigo se la manda
    assert _leer(entorno, "SELECT siigo_customer_id FROM retail.clientes"
                 )[0][0] == "cli-siigo-1"


def test_la_clienta_que_siigo_ya_tiene_NO_se_vuelve_a_crear(entorno):
    _con_clienta(entorno)
    siigo = SiigoFalso()
    siigo.clientes.add("1037000111")
    assert _drenar(siigo).procesados == 1
    assert siigo.clientes_creados == []


def test_una_clienta_con_un_solo_nombre_espera_y_NO_sale_a_nombre_de_otra(entorno):
    _con_clienta(entorno, nombre="Laura", apellido="")
    siigo = SiigoFalso()
    r = _drenar(siigo)
    assert r.sin_manejador == 1
    assert siigo.clientes_creados == [] and siigo.enviadas == []
    motivo = _leer(entorno, "SELECT ultimo_error FROM retail.outbox")[0][0]
    assert "nombre y apellido" in motivo
    assert _estado(entorno)[1] == ("pendiente", 0)

    # Se completa la ficha y sale sola, sin que nadie la reencole.
    _ejecutar(entorno, "UPDATE retail.clientes SET apellido = 'Gómez'")
    assert _drenar(siigo, dentro_de=timedelta(hours=3)).procesados == 1
    assert siigo.enviadas[0]["customer"]["identification"] == "1037000111"


def test_si_siigo_no_deja_crearla_la_venta_espera(entorno):
    _con_clienta(entorno)
    siigo = SiigoFalso()
    siigo.al_crear_cliente = "rechazo"
    assert _drenar(siigo).sin_manejador == 1
    assert siigo.enviadas == []
    assert "no dejó crear" in _leer(entorno, "SELECT ultimo_error FROM retail.outbox")[0][0]


def test_si_otra_caja_la_creo_un_segundo_antes_se_sigue(entorno):
    _con_clienta(entorno)
    siigo = SiigoFalso()
    siigo.al_crear_cliente = "ya_existia"
    assert _drenar(siigo).procesados == 1
    assert len(siigo.enviadas) == 1


def test_sin_correo_no_se_le_pide_a_siigo_que_mande_nada(entorno, monkeypatch):
    monkeypatch.setenv("RETAIL_FISCAL_MODO", "produccion")
    _con_clienta(entorno, correo=None)
    siigo = SiigoFalso()
    _drenar(siigo)
    assert "mail" not in siigo.enviadas[0]
    assert "email" not in siigo.clientes_creados[0]["contacts"][0]


def test_cerrar_una_venta_no_llama_a_siigo_si_el_empuje_no_esta_habilitado():
    """En las pruebas —y en cualquier proceso que no sea el backend real— la
    pasada inmediata no existe: no hay un Siigo al que llamar."""
    from backend.modules.retail.infrastructure import planificador_outbox
    assert planificador_outbox.empujar() is False


def test_una_venta_anulada_antes_no_se_factura(entorno):
    _ejecutar(entorno, "UPDATE retail.ventas SET estado = 'anulada', motivo_anulacion = 'cobrada dos veces'")
    siigo = SiigoFalso()
    assert _drenar(siigo).procesados == 1
    assert siigo.enviadas == []


# ── ANULAR UNA VENTA QUE YA TENÍA FACTURA ───────────────────────────────────

def _anular():
    r = _CLIENTE["c"].post(f"/api/retail/ventas/{VENTA}/anular",
                           json={"motivo": "cobrada dos veces"})
    assert r.status_code == 200, r.text
    return r.json()


def _docs(motor):
    return [tuple(f) for f in _leer(
        motor, "SELECT tipo, estado, numero FROM retail.documentos_fiscales "
               "ORDER BY creado_en, tipo")]


def _cola(motor):
    return [tuple(f) for f in _leer(
        motor, "SELECT tipo, estado FROM retail.outbox ORDER BY id")]


def test_anular_una_venta_facturada_emite_su_nota_credito(entorno, monkeypatch):
    monkeypatch.setenv("RETAIL_FISCAL_MODO", "produccion")
    siigo = SiigoFalso()
    _drenar(siigo)
    assert _anular()["exige_nota_credito"] is True

    r = _drenar(siigo, dentro_de=timedelta(minutes=5))
    assert r.procesados == 1, r.errores
    assert _docs(entorno) == [("factura_electronica", "emitido", "TARR-11452"),
                              ("nota_credito", "emitido", "NC-1-7505")]

    [nc] = siigo.nc_enviadas
    assert nc["invoice"] == "siigo-1"                 # contra ESA factura
    assert nc["document"] == {"id": 11817}
    assert nc["reason"] == 2                          # anulación, no devolución
    assert nc["stamp"] == {"send": True}
    # Copiada de la factura, no recalculada — y APLANADA: el GET devuelve la
    # bodega y los impuestos expandidos, y así Siigo los descarta en silencio.
    [f] = siigo.enviadas
    assert [(i["code"], i["quantity"]) for i in nc["items"]] == [
        (i["code"], i["quantity"]) for i in f["items"]]
    assert nc["items"][0]["warehouse"] == 37
    assert nc["items"][0]["taxes"] == [{"id": 6352}]
    assert nc["seller"] == 842 and nc["cost_center"] == 677
    # La plata sale por donde entró: la caja de la tienda, no un saldo a favor.
    assert nc["payments"] == [{"id": 8282, "value": 299800.0,
                               "due_date": nc["date"]}]
    assert nc["customer"]["identification"] == "222222222222"


def test_la_nota_credito_tampoco_se_emite_dos_veces(entorno, monkeypatch):
    """El mismo caso que justifica el diseño de la factura: Siigo la crea y la
    respuesta se pierde. Dos notas crédito sobre una factura es acreditar el
    doble de lo que se vendió."""
    monkeypatch.setenv("RETAIL_FISCAL_MODO", "produccion")
    siigo = SiigoFalso()
    _drenar(siigo)
    _anular()

    siigo.al_crear_nc = "crea_y_muere"
    assert _drenar(siigo, dentro_de=timedelta(minutes=5)).reintentos == 1
    siigo.al_crear_nc = "ok"
    r = _drenar(siigo, dentro_de=timedelta(hours=3))
    assert r.procesados == 1, r.errores
    assert len(siigo.nc_enviadas) == 1 and len(siigo.nc_en_siigo) == 1
    assert _docs(entorno)[1] == ("nota_credito", "emitido", "NC-1-7505")

    _drenar(siigo, dentro_de=timedelta(hours=9))
    assert len(siigo.nc_enviadas) == 1


def test_la_nota_credito_espera_a_la_dian_sin_reenviar(entorno, monkeypatch):
    monkeypatch.setenv("RETAIL_FISCAL_MODO", "produccion")
    siigo = SiigoFalso()
    _drenar(siigo)
    _anular()
    siigo.dian_nc = "draft"
    r = _drenar(siigo, dentro_de=timedelta(minutes=5))
    assert (r.procesados, r.fallidos) == (0, 0)
    assert _docs(entorno)[1] == ("nota_credito", "verificando", "NC-1-7505")

    siigo.dian_nc = "accepted"
    assert _drenar(siigo, dentro_de=timedelta(minutes=30)).procesados == 1
    assert len(siigo.nc_enviadas) == 1
    cude = _leer(entorno, "SELECT cufe FROM retail.documentos_fiscales "
                          "WHERE tipo = 'nota_credito'")[0][0]
    assert cude == "d" * 96


def test_un_rechazo_de_la_nota_credito_queda_a_la_vista(entorno, monkeypatch):
    monkeypatch.setenv("RETAIL_FISCAL_MODO", "produccion")
    siigo = SiigoFalso()
    _drenar(siigo)
    _anular()
    siigo.al_crear_nc = "rechazo"
    r = _drenar(siigo, dentro_de=timedelta(minutes=5))
    assert r.fallidos == 1 and "invalid_document" in r.errores[0]
    assert _docs(entorno)[1][:2] == ("nota_credito", "rechazado")
    # La factura sigue siendo la factura: el rechazo de la NC no la toca.
    assert _docs(entorno)[0] == ("factura_electronica", "emitido", "TARR-11452")
    assert _estado(entorno)[0] == "emitido"


def test_anular_antes_de_facturar_no_emite_ni_factura_ni_nota_credito(entorno, monkeypatch):
    monkeypatch.setenv("RETAIL_FISCAL_MODO", "produccion")
    assert _anular()["exige_nota_credito"] is False
    siigo = SiigoFalso()
    _drenar(siigo)
    assert siigo.enviadas == [] and siigo.nc_enviadas == []
    assert _docs(entorno) == []


def test_anulada_CON_LA_FACTURA_EN_CAMINO_no_queda_una_factura_viva(entorno, monkeypatch):
    """El hueco: la factura está en Siigo esperando a la DIAN, y en ese minuto
    la cajera anula. `AnularVenta` no ve factura y no encola nota crédito; el
    emisor soltaba la venta por «anulada». Resultado: una factura validada de
    una venta que no existe, y nadie que la anule."""
    monkeypatch.setenv("RETAIL_FISCAL_MODO", "produccion")
    siigo = SiigoFalso()
    siigo.dian = "draft"
    _drenar(siigo)
    assert _docs(entorno) == [("factura_electronica", "verificando", "TARR-11452")]

    assert _anular()["exige_nota_credito"] is False      # todavía no había factura

    siigo.dian = "accepted"
    _drenar(siigo, dentro_de=timedelta(minutes=5))       # la factura termina…
    assert ("emitir_nota_credito", "pendiente") in _cola(entorno)   # …y se encola su NC
    r = _drenar(siigo, dentro_de=timedelta(minutes=10))
    assert r.procesados == 1, r.errores
    assert _docs(entorno) == [("factura_electronica", "emitido", "TARR-11452"),
                              ("nota_credito", "emitido", "NC-1-7505")]
    assert len(siigo.enviadas) == 1


def test_anulada_con_el_envio_perdido_NO_se_envia_la_factura(entorno, monkeypatch):
    """«Enviando» sin respuesta, y la venta se anula. Si la factura no llegó a
    Siigo, mandarla ahora sería facturar una venta que ya no existe."""
    monkeypatch.setenv("RETAIL_FISCAL_MODO", "produccion")
    siigo = SiigoFalso()
    siigo.al_crear = "sin_respuesta"
    _drenar(siigo)
    _anular()
    siigo.al_crear = "ok"
    r = _drenar(siigo, dentro_de=timedelta(hours=3))
    assert r.procesados == 1, r.errores
    assert len(siigo.enviadas) == 1 and siigo.en_siigo == []
    assert _docs(entorno) == [("factura_electronica", "fallido", None)]
    assert _estado(entorno)[0] == "no_aplica"


def test_una_factura_de_prueba_no_lleva_nota_credito(entorno):
    """En modo prueba la factura no fue a la DIAN: Siigo no la deja acreditar.
    Se borra allá."""
    siigo = SiigoFalso()
    _drenar(siigo)
    _anular()
    r = _drenar(siigo, dentro_de=timedelta(minutes=5))
    assert siigo.nc_enviadas == []
    nota = _leer(entorno, "SELECT ultimo_error FROM retail.outbox "
                          "WHERE tipo = 'emitir_nota_credito'")[0][0]
    assert "se borra en Siigo" in nota


def test_sin_comprobante_de_nota_credito_espera(entorno, monkeypatch):
    monkeypatch.setenv("RETAIL_FISCAL_MODO", "produccion")
    siigo = SiigoFalso()
    _drenar(siigo)
    _anular()
    _ejecutar(entorno, "UPDATE retail.tiendas SET siigo_nc_documento_id = NULL")
    assert _drenar(siigo, dentro_de=timedelta(minutes=5)).sin_manejador == 1
    assert siigo.nc_enviadas == []


def test_con_todo_apagado_la_nota_credito_tambien_espera(entorno, monkeypatch):
    monkeypatch.setenv("RETAIL_FISCAL_MODO", "produccion")
    siigo = SiigoFalso()
    _drenar(siigo)
    _anular()
    monkeypatch.setenv("RETAIL_FISCAL_MODO", "apagado")
    assert _drenar(siigo, dentro_de=timedelta(minutes=5)).sin_manejador == 1
    assert siigo.nc_enviadas == []


def test_si_falta_la_libreria_del_qr_la_tirilla_SALE_IGUAL(entorno, monkeypatch):
    """Pasó en producción el primer día: `segno` no estaba instalado y la
    tirilla de toda venta ya facturada respondía 500. La factura existía y
    el papel no salía."""
    import builtins
    from backend.modules.retail.application.consultas.tirilla import ArmarTirilla
    from sqlalchemy.ext.asyncio import AsyncSession

    monkeypatch.setenv("RETAIL_FISCAL_MODO", "produccion")
    # El Siigo falso numera con TARR: se usa la resolución de la tienda.
    _ejecutar(entorno, "UPDATE retail.cajas SET autorizacion_prefijo = NULL")
    _drenar(SiigoFalso())

    real = builtins.__import__

    def sin_segno(nombre, *a, **kw):
        if nombre == "segno":
            raise ImportError("No module named 'segno'")
        return real(nombre, *a, **kw)
    monkeypatch.setattr(builtins, "__import__", sin_segno)

    async def ir():
        async with AsyncSession(entorno) as s:
            return await ArmarTirilla(s).ejecutar(VENTA)
    t = _correr(ir())
    assert t.es_documento_fiscal is True and t.cufe == "c" * 96
    assert t.qr_ruta is None


def test_la_libreria_del_qr_esta_en_lo_que_instala_PRODUCCION():
    """El servidor instala `requirements.txt`, no el de las pruebas."""
    import pathlib
    raiz = pathlib.Path(__file__).resolve().parents[3]
    assert "segno" in (raiz / "requirements.txt").read_text()


# ── BUSCAR LA VENTA QUE VIENEN A CAMBIAR ────────────────────────────────────

def _buscar_cambio(q):
    r = _CLIENTE["c"].get("/api/retail/devoluciones/buscar", params={"q": q})
    assert r.status_code == 200, r.text
    return r.json()


def test_el_cambio_se_busca_por_el_numero_que_va_GRANDE_en_el_papel(entorno, monkeypatch):
    """La tirilla dice «No. TARR-11452». La búsqueda sólo entendía el número
    interno del POS, que va en letra chica: la asesora tecleaba lo que veía y
    «no existía»."""
    monkeypatch.setenv("RETAIL_FISCAL_MODO", "produccion")
    _drenar(SiigoFalso())

    for como in ("TARR-11452", "tarr11452", "TARR 11452", "11452",
                 "FV-6-11452", "fv 6 11452"):
        [v] = _buscar_cambio(como)
        assert v["factura"] == "TARR-11452", como
        assert v["numero"].startswith("ARRPOS-")
        assert v["tienda"] == "Arrayanes" and v["total_centavos"] == 29_980_000

    # El del POS sigue sirviendo.
    numero_pos = _buscar_cambio("11452")[0]["numero"]
    assert _buscar_cambio(numero_pos)[0]["factura"] == "TARR-11452"
    assert _buscar_cambio("TARR-99999") == []


def test_el_cambio_se_busca_por_la_cedula_de_la_clienta(entorno, monkeypatch):
    monkeypatch.setenv("RETAIL_FISCAL_MODO", "produccion")
    _con_clienta(entorno)
    siigo = SiigoFalso()
    siigo.clientes.add("1037000111")
    _drenar(siigo)

    for como in ("1037000111", "1.037.000.111"):
        [v] = _buscar_cambio(como)
        assert v["cliente"] == "Laura Gómez Ríos" and v["factura"] == "TARR-11452"
    # Media cédula no trae medio padrón.
    assert _buscar_cambio("1037") == []


def test_con_el_numero_encontrado_se_abre_el_ticket_para_devolver(entorno, monkeypatch):
    monkeypatch.setenv("RETAIL_FISCAL_MODO", "produccion")
    _drenar(SiigoFalso())
    [v] = _buscar_cambio("TARR-11452")
    r = _CLIENTE["c"].get(f"/api/retail/devoluciones/ticket/{v['numero']}",
                          params={"caja_id": "arrayanes_caja1"})
    assert r.status_code == 200, r.text
    assert r.json()["lineas"][0]["sku"] == "92611-1T10"
