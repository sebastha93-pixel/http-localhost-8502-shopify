"""CerrarVenta, de punta a punta contra PostgreSQL.

El caso de uso escribe seis cosas en una transacción. Estas pruebas verifican
que las seis quedan —y, sobre todo, que los eventos que alguien querría hacer
desaparecer quedan marcados como críticos y encadenados.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio

pytest.importorskip("sqlalchemy")
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from backend.modules.retail.application.comandos.cerrar_venta import (  # noqa: E402
    CerrarVenta,
    RelojFijo,
)
from backend.modules.retail.domain.shared.dinero import Dinero  # noqa: E402
from backend.modules.retail.domain.shared.sku import Sku  # noqa: E402
from backend.modules.retail.domain.venta.descuento import Descuento  # noqa: E402
from backend.modules.retail.domain.venta.venta import Venta  # noqa: E402
from backend.modules.retail.infrastructure.persistencia.repo_auditoria import (  # noqa: E402
    GENESIS,
    RepositorioAuditoriaSQL,
    calcular_hash,
)
from backend.modules.retail.infrastructure.persistencia.unidad_de_trabajo import (  # noqa: E402
    UnidadDeTrabajoSQL,
    crear_fabrica,
)

URL = os.environ.get("RETAIL_TEST_DATABASE_URL", "").strip()
pytestmark = [
    pytest.mark.skipif(not URL, reason="Sin RETAIL_TEST_DATABASE_URL"),
    pytest.mark.asyncio,
]

COP = "COP"
AHORA = datetime(2026, 8, 5, 19, 42, tzinfo=timezone.utc)
SESION = "01JQ8X4T5N6P7R8S9V0W1X2Y3Z"
VENTA = "01JQ8X4T5N6P7R8S9V0W1X2Y41"
VARIANTE = "01JQ8X4T5N6P7R8S9V0W1X2Y42"
UBICACION = "tienda:florida"
MAPA = {"92611-1T10": VARIANTE}


@pytest_asyncio.fixture()
async def entorno():
    from backend.modules.retail.migraciones.runner import aplicar, revertir

    revertir(URL)
    aplicar(URL)
    motor = create_async_engine(URL)
    semillas = [
        ("INSERT INTO retail.tiendas (id,nombre) VALUES ('florida','Florida')", {}),
        ("INSERT INTO retail.cajas (id,tienda_id,nombre) "
         "VALUES ('florida_caja1','florida','Caja 1')", {}),
        ("INSERT INTO retail.ubicaciones (id,tipo,nombre,tienda_id) "
         "VALUES (:u,'tienda','Florida','florida')", {"u": UBICACION}),
        ("INSERT INTO retail.medios_pago (id,nombre,tipo,siigo_forma_pago_id) "
         "VALUES ('efectivo','Efectivo','efectivo',12243)", {}),
        ("INSERT INTO retail.variantes (id,sku,referencia,talla,nombre,precio_base) "
         "VALUES (:v,'92611-1T10','92611-1','10','Jean',14277311)", {"v": VARIANTE}),
        ("INSERT INTO retail.stock_ubicacion (ubicacion_id,variante_id,cantidad) "
         "VALUES (:u,:v,5)", {"u": UBICACION, "v": VARIANTE}),
        ("INSERT INTO retail.sesiones_caja "
         "(id,tienda_id,caja_id,numero_turno,base_inicial,abierta_por) "
         "VALUES (:s,'florida','florida_caja1',1,20000000,'maria')", {"s": SESION}),
    ]
    async with motor.begin() as c:
        for sql, p in semillas:
            await c.execute(text(sql), p)

    fabrica = crear_fabrica(motor)
    yield UnidadDeTrabajoSQL(fabrica), motor, fabrica
    await motor.dispose()
    revertir(URL)


def _venta(con_descuento=False) -> Venta:
    v = Venta.abrir(id=VENTA, numero="FV-20-1334", tienda_id="florida",
                    caja_id="florida_caja1", sesion_id=SESION,
                    cajera_id="maria", moneda=COP)
    v.agregar_linea(sku=Sku.parsear("92611-1T10"), descripcion="Jean · 10",
                    cantidad=2,
                    precio_unitario=Dinero.desde_pesos("142773.11", COP),
                    tasa_iva=Decimal("19"))
    if con_descuento:
        v.aplicar_descuento_linea(
            1, Descuento.porcentaje(30, motivo="clienta insistió"),
            tope_de_quien_aplica=Decimal("10"), autorizado_por="laura")
    v.registrar_pago("efectivo", Dinero.desde_pesos("400000", COP),
                     es_efectivo=True)
    return v


async def _filas(motor, sql: str) -> list:
    async with motor.connect() as c:
        return (await c.execute(text(sql))).mappings().all()


# ── El cierre completo ──────────────────────────────────────────────────────

async def test_cerrar_una_venta_escribe_las_seis_cosas(entorno):
    uow, motor, _ = entorno
    venta = _venta()

    resultado = await CerrarVenta(uow, reloj=RelojFijo(AHORA)).ejecutar(
        venta, variante_por_sku=MAPA, ubicacion_id=UBICACION,
        usuario_id="maria")

    assert resultado.numero == "FV-20-1334"
    assert resultado.total_centavos == 33980000       # $339.800
    assert resultado.vuelto_centavos == 6020000       # $60.200
    assert resultado.estado_fiscal == "pendiente"

    assert len(await _filas(motor, "SELECT 1 FROM retail.ventas")) == 1
    assert len(await _filas(motor, "SELECT 1 FROM retail.venta_lineas")) == 1
    assert len(await _filas(motor, "SELECT 1 FROM retail.venta_pagos")) == 1
    assert len(await _filas(motor, "SELECT 1 FROM retail.movimientos_inventario")) == 1
    assert len(await _filas(motor, "SELECT 1 FROM retail.movimientos_caja")) == 1
    assert len(await _filas(motor, "SELECT 1 FROM retail.auditoria")) == 1

    # El stock bajó de 5 a 3.
    saldo = await _filas(motor, "SELECT cantidad FROM retail.stock_ubicacion")
    assert saldo[0]["cantidad"] == 3


async def test_el_documento_fiscal_queda_encolado_no_emitido(entorno):
    """ADR-002: la venta no espera a Siigo. Se encola y la clienta se va."""
    uow, motor, _ = entorno
    await CerrarVenta(uow, reloj=RelojFijo(AHORA)).ejecutar(
        _venta(), variante_por_sku=MAPA, ubicacion_id=UBICACION,
        usuario_id="maria")

    cola = await _filas(motor, "SELECT tipo, estado FROM retail.outbox ORDER BY tipo")
    assert [(f["tipo"], f["estado"]) for f in cola] == [
        ("emitir_documento_fiscal", "pendiente"),
        ("publicar_stock_shopify", "pendiente"),
    ]
    # Y no existe ningún documento fiscal todavía: eso es del worker.
    assert await _filas(motor, "SELECT 1 FROM retail.documentos_fiscales") == []


async def test_la_plata_entra_a_la_caja_del_turno(entorno):
    uow, motor, fabrica = entorno
    await CerrarVenta(uow, reloj=RelojFijo(AHORA)).ejecutar(
        _venta(), variante_por_sku=MAPA, ubicacion_id=UBICACION,
        usuario_id="maria")

    async with UnidadDeTrabajoSQL(fabrica) as t:
        esperado = await t.caja.esperado_por_medio(SESION)
    assert esperado == {"efectivo": 40000000}   # los $400.000 cobrados


# ── Auditoría: lo que alguien querría hacer desaparecer ─────────────────────

async def test_un_descuento_autorizado_queda_como_critico(entorno):
    """Es el evento que más importa de todo el módulo.

    Si un descuento del 30% aprobado por un supervisor no deja rastro, el
    control anti-fraude no existe.
    """
    uow, motor, _ = entorno
    await CerrarVenta(uow, reloj=RelojFijo(AHORA)).ejecutar(
        _venta(con_descuento=True), variante_por_sku=MAPA,
        ubicacion_id=UBICACION, usuario_id="maria")

    criticos = await _filas(motor, """
        SELECT evento, payload FROM retail.auditoria WHERE severidad='critico'
    """)
    assert len(criticos) == 1
    assert criticos[0]["evento"] == "descuento.autorizado"
    p = criticos[0]["payload"]
    assert p["autorizado_por"] == "laura"
    assert p["motivo"] == "clienta insistió"
    # 2 x $142.773,11 = $285.546,22 de base; el 30% son $85.663,87.
    assert p["monto"] == 8566387


async def test_la_cadena_de_auditoria_se_encadena(entorno):
    uow, motor, fabrica = entorno
    await CerrarVenta(uow, reloj=RelojFijo(AHORA)).ejecutar(
        _venta(con_descuento=True), variante_por_sku=MAPA,
        ubicacion_id=UBICACION, usuario_id="maria")

    filas = await _filas(motor, """
        SELECT hash_anterior, hash FROM retail.auditoria ORDER BY id
    """)
    assert len(filas) == 2
    assert filas[0]["hash_anterior"] == GENESIS
    assert filas[1]["hash_anterior"] == filas[0]["hash"]

    async with UnidadDeTrabajoSQL(fabrica) as t:
        veredicto = await t.auditoria.verificar_cadena(tienda_id="florida")
    assert veredicto["integra"] is True
    assert veredicto["eventos"] == 2


async def test_alterar_un_evento_del_pasado_rompe_la_cadena(entorno):
    """ADR-010. No impide editar la tabla: hace que se note.

    Y dice DÓNDE se rompió: "la auditoría no cuadra" sin señalar el evento no
    le sirve a nadie.
    """
    uow, motor, fabrica = entorno
    await CerrarVenta(uow, reloj=RelojFijo(AHORA)).ejecutar(
        _venta(con_descuento=True), variante_por_sku=MAPA,
        ubicacion_id=UBICACION, usuario_id="maria")

    # Alguien entra a la base y le baja el monto al descuento indebido.
    async with motor.begin() as c:
        await c.execute(text("""
            UPDATE retail.auditoria
               SET payload = jsonb_set(payload, '{monto}', '1')
             WHERE severidad = 'critico'
        """))

    async with UnidadDeTrabajoSQL(fabrica) as t:
        veredicto = await t.auditoria.verificar_cadena(tienda_id="florida")

    assert veredicto["integra"] is False
    assert veredicto["motivo"] == "payload_alterado"
    assert veredicto["evento"] == "descuento.autorizado"



# ── Lo que NO debe pasar ────────────────────────────────────────────────────

async def test_si_falla_el_inventario_no_queda_ni_la_venta_ni_la_auditoria(entorno):
    """Una auditoría de algo que no pasó es peor que no tener auditoría."""
    uow, motor, _ = entorno
    venta = _venta()

    with pytest.raises(Exception):
        await CerrarVenta(uow, reloj=RelojFijo(AHORA)).ejecutar(
            venta, variante_por_sku=MAPA,
            ubicacion_id="ubicacion:que:no:existe", usuario_id="maria")

    assert await _filas(motor, "SELECT 1 FROM retail.ventas") == []
    assert await _filas(motor, "SELECT 1 FROM retail.auditoria") == []
    assert await _filas(motor, "SELECT 1 FROM retail.outbox") == []


async def test_no_se_cierra_una_venta_a_la_que_le_falta_plata(entorno):
    """El agregado se niega ANTES de tocar la base."""
    uow, motor, _ = entorno
    venta = Venta.abrir(id=VENTA, numero="FV-20-1334", tienda_id="florida",
                        caja_id="florida_caja1", sesion_id=SESION,
                        cajera_id="maria", moneda=COP)
    venta.agregar_linea(sku=Sku.parsear("92611-1T10"), descripcion="Jean",
                        cantidad=2,
                        precio_unitario=Dinero.desde_pesos("142773.11", COP),
                        tasa_iva=Decimal("19"))
    venta.registrar_pago("efectivo", Dinero.desde_pesos("100000", COP),
                         es_efectivo=True)

    from backend.modules.retail.domain.venta.errores import ReglaDeNegocio
    with pytest.raises(ReglaDeNegocio, match="falta"):
        await CerrarVenta(uow, reloj=RelojFijo(AHORA)).ejecutar(
            venta, variante_por_sku=MAPA, ubicacion_id=UBICACION,
            usuario_id="maria")

    assert await _filas(motor, "SELECT 1 FROM retail.ventas") == []
