"""La prueba que justifica ADR-004.

Cerrar una venta escribe siete cosas: la venta, sus líneas, sus pagos, los
asientos de inventario, el movimiento de caja, la auditoría y el outbox.
**O entran todas, o no entra ninguna.**

Con `supabase-py` (PostgREST) eso no se podía: cada escritura es una petición
HTTP independiente. Un fallo a mitad de camino dejaba stock descargado sin
venta —o venta sin plata en la caja— y nadie se enteraba hasta el cierre
contable del mes.

Estas pruebas rompen la transacción a propósito y verifican que no quedó nada.
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

from backend.modules.retail.domain.shared.dinero import Dinero  # noqa: E402
from backend.modules.retail.domain.shared.sku import Sku  # noqa: E402
from backend.modules.retail.domain.venta.venta import Venta  # noqa: E402
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


@pytest_asyncio.fixture()
async def uow():
    from backend.modules.retail.migraciones.runner import aplicar, revertir

    revertir(URL)
    aplicar(URL)

    motor = create_async_engine(URL)
    # Una sentencia por execute: psycopg3 no admite varias con parámetros.
    sembrado = [
        ("INSERT INTO retail.tiendas (id, nombre) VALUES ('florida','Florida')", {}),
        ("INSERT INTO retail.cajas (id, tienda_id, nombre) "
         "VALUES ('florida_caja1','florida','Caja 1')", {}),
        ("INSERT INTO retail.ubicaciones (id, tipo, nombre, tienda_id) "
         "VALUES (:ubi,'tienda','Florida','florida')", {"ubi": UBICACION}),
        ("INSERT INTO retail.medios_pago (id,nombre,tipo,siigo_forma_pago_id) "
         "VALUES ('efectivo','Efectivo','efectivo',12243)", {}),
        ("INSERT INTO retail.variantes (id,sku,referencia,talla,nombre,precio_con_iva) "
         "VALUES (:var,'92611-1T10','92611-1','10','Jean',16990000)",
         {"var": VARIANTE}),
        ("INSERT INTO retail.stock_ubicacion (ubicacion_id,variante_id,cantidad) "
         "VALUES (:ubi,:var,5)", {"ubi": UBICACION, "var": VARIANTE}),
        ("INSERT INTO retail.sesiones_caja "
         "(id,tienda_id,caja_id,numero_turno,base_inicial,abierta_por) "
         "VALUES (:ses,'florida','florida_caja1',1,20000000,'maria')",
         {"ses": SESION}),
    ]
    async with motor.begin() as c:
        for sql, params in sembrado:
            await c.execute(text(sql), params)

    fabrica = crear_fabrica(motor)
    yield UnidadDeTrabajoSQL(fabrica), motor
    await motor.dispose()
    revertir(URL)


def _venta_lista() -> Venta:
    v = Venta.abrir(id=VENTA, numero="FV-20-1334", tienda_id="florida",
                    caja_id="florida_caja1", sesion_id=SESION,
                    cajera_id="maria", moneda=COP)
    v.agregar_linea(sku=Sku.parsear("92611-1T10"), descripcion="Jean · 10",
                    cantidad=2, precio_unitario=Dinero.desde_pesos("169900", COP),
                    tasa_iva=Decimal("19"))
    v.registrar_pago("efectivo", Dinero.desde_pesos("400000", COP),
                     es_efectivo=True)
    return v


async def _contar(motor, tabla: str) -> int:
    async with motor.connect() as c:
        return (await c.execute(text(f"SELECT count(*) FROM retail.{tabla}"))).scalar()


# ── El camino feliz ─────────────────────────────────────────────────────────

async def test_un_cierre_completo_deja_todo_escrito(uow):
    trabajo, motor = uow
    venta = _venta_lista()
    venta.cerrar(AHORA)

    async with trabajo as t:
        await t.ventas.guardar(venta, variante_por_sku={"92611-1T10": VARIANTE})
        await t.inventario.confirmar_salida(
            ubicacion_id=UBICACION, variante_id=VARIANTE, cantidad=2,
            referencia_id=venta.id, usuario_id="maria")
        await t.commit()

    assert await _contar(motor, "ventas") == 1
    assert await _contar(motor, "venta_lineas") == 1
    assert await _contar(motor, "venta_pagos") == 1
    assert await _contar(motor, "movimientos_inventario") == 1

    async with motor.connect() as c:
        saldo = (await c.execute(text(
            "SELECT cantidad FROM retail.stock_ubicacion"))).scalar()
    assert saldo == 3


# ── Lo que importa: cuando algo se rompe ────────────────────────────────────

async def test_si_revienta_a_mitad_no_queda_NADA(uow):
    """El corazón de ADR-004.

    Se escribe la venta, se descarga el stock, y justo antes del commit
    revienta. Sin transacción real, esto dejaría el stock en 3 y ninguna venta
    que lo explique — un faltante de inventario fantasma.
    """
    trabajo, motor = uow
    venta = _venta_lista()
    venta.cerrar(AHORA)

    with pytest.raises(RuntimeError):
        async with trabajo as t:
            await t.ventas.guardar(venta, variante_por_sku={"92611-1T10": VARIANTE})
            await t.inventario.confirmar_salida(
                ubicacion_id=UBICACION, variante_id=VARIANTE, cantidad=2,
                referencia_id=venta.id, usuario_id="maria")
            raise RuntimeError("se cayó la red justo aquí")

    assert await _contar(motor, "ventas") == 0
    assert await _contar(motor, "venta_lineas") == 0
    assert await _contar(motor, "venta_pagos") == 0
    assert await _contar(motor, "movimientos_inventario") == 0

    async with motor.connect() as c:
        saldo = (await c.execute(text(
            "SELECT cantidad FROM retail.stock_ubicacion"))).scalar()
    assert saldo == 5, "el stock se movió sin que existiera la venta"


async def test_salir_sin_commit_tambien_revierte(uow):
    """El default seguro.

    Olvidar el commit pierde datos, que es molesto y visible. Olvidar el
    rollback los deja a medio escribir, que es silencioso y mucho peor.
    """
    trabajo, motor = uow
    venta = _venta_lista()

    async with trabajo as t:
        await t.ventas.guardar(venta, variante_por_sku={"92611-1T10": VARIANTE})
        # sin commit

    assert await _contar(motor, "ventas") == 0


async def test_una_violacion_de_constraint_arrastra_toda_la_transaccion(uow):
    """La base rechaza una venta cerrada con faltante (INV-V3), y al hacerlo
    tiene que llevarse también el movimiento de inventario."""
    trabajo, motor = uow
    venta = _venta_lista()
    venta.cerrar(AHORA)

    with pytest.raises(Exception):
        async with trabajo as t:
            await t.inventario.confirmar_salida(
                ubicacion_id=UBICACION, variante_id=VARIANTE, cantidad=2,
                referencia_id=venta.id, usuario_id="maria")
            await t.ventas.guardar(venta, variante_por_sku={"92611-1T10": VARIANTE})
            # Rompe el CHECK (estado <> 'cerrada' OR pagado >= total)
            await t.sesion.execute(text(
                "UPDATE retail.ventas SET pagado = 1 WHERE id = :i"), {"i": venta.id})
            await t.commit()

    assert await _contar(motor, "movimientos_inventario") == 0


# ── Idempotencia: reintentar el mismo cierre ────────────────────────────────

async def test_guardar_la_misma_venta_dos_veces_no_la_duplica(uow):
    """El dispositivo reintenta por diseño (ADR-005). Reintentar tiene que ser
    inofensivo, no un 500."""
    trabajo, motor = uow
    venta = _venta_lista()
    venta.cerrar(AHORA)
    mapa = {"92611-1T10": VARIANTE}

    for _ in range(3):
        async with trabajo as t:
            await t.ventas.guardar(venta, variante_por_sku=mapa)
            await t.commit()

    assert await _contar(motor, "ventas") == 1
    assert await _contar(motor, "venta_lineas") == 1
    assert await _contar(motor, "venta_pagos") == 1


# ── Ida y vuelta por la base ────────────────────────────────────────────────

async def test_la_venta_sobrevive_al_viaje_a_la_base(uow):
    """Los totales que se leen son exactamente los que se escribieron.

    Es donde se caería un redondeo si el dinero no fuera entero: $169.900 × 2
    tiene que volver clavado.
    """
    trabajo, motor = uow
    venta = _venta_lista()
    venta.cerrar(AHORA)

    async with trabajo as t:
        await t.ventas.guardar(venta, variante_por_sku={"92611-1T10": VARIANTE})
        await t.commit()

    async with trabajo as t:
        leida = await t.ventas.obtener(VENTA)

    assert leida is not None
    assert leida.total() == venta.total()
    assert leida.total() == Dinero.desde_pesos("339800", COP)
    assert leida.iva_total() == venta.iva_total()
    assert leida.pagado() == venta.pagado()
    assert len(leida.lineas) == 1
    assert leida.lineas[0].sku.codigo == "92611-1T10"


# ── La reserva atómica, ahora desde el repositorio ──────────────────────────

async def test_la_reserva_no_deja_vender_lo_que_no_hay(uow):
    trabajo, motor = uow
    async with trabajo as t:
        assert await t.inventario.reservar(
            ubicacion_id=UBICACION, variante_id=VARIANTE, cantidad=5) == 0
        # La segunda caja pide una más: no alcanza.
        assert await t.inventario.reservar(
            ubicacion_id=UBICACION, variante_id=VARIANTE, cantidad=1) is None
        await t.commit()

    async with trabajo as t:
        saldo = await t.inventario.saldo(
            ubicacion_id=UBICACION, variante_id=VARIANTE)
    assert saldo == {"cantidad": 5, "reservado": 5, "disponible": 0}
