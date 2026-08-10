"""El esquema, contra un PostgreSQL de verdad.

Estas pruebas no verifican que las tablas existan. Verifican que **la base
haga cumplir las invariantes que el diseño le encargó**, porque una regla que
sólo vive en Python tiene una ventana de carrera y un índice único no.

Necesitan un Postgres. Se salta el archivo entero si no hay
RETAIL_TEST_DATABASE_URL — nunca corren contra la base de producción.
"""
from __future__ import annotations

import os

import pytest

sa = pytest.importorskip("sqlalchemy", reason="SQLAlchemy no instalado")
from sqlalchemy import text  # noqa: E402
from sqlalchemy.exc import DBAPIError, IntegrityError  # noqa: E402

URL = os.environ.get("RETAIL_TEST_DATABASE_URL", "").strip()

pytestmark = pytest.mark.skipif(
    not URL,
    reason="Sin RETAIL_TEST_DATABASE_URL. Estas pruebas exigen una base "
           "explícita para no tocar producción por accidente.",
)

ULID_A = "01JQ8X4T5N6P7R8S9V0W1X2Y3Z"
ULID_B = "01JQ8X4T5N6P7R8S9V0W1X2Y40"
ULID_C = "01JQ8X4T5N6P7R8S9V0W1X2Y41"
ULID_D = "01JQ8X4T5N6P7R8S9V0W1X2Y42"


# ── Infraestructura de la prueba ────────────────────────────────────────────

@pytest.fixture(scope="module")
def engine():
    from backend.modules.retail.migraciones.runner import aplicar, revertir

    motor = sa.create_engine(URL, future=True)
    revertir(URL)          # base limpia aunque una corrida anterior fallara
    aplicar(URL)
    yield motor
    revertir(URL)
    motor.dispose()


@pytest.fixture()
def conn(engine):
    with engine.connect() as c:
        _sembrar(c)
        c.commit()
        yield c
        c.rollback()
        _limpiar(c)
        c.commit()


def _limpiar(c):
    c.execute(text("""
        TRUNCATE retail.venta_pagos, retail.venta_lineas, retail.ventas,
                 retail.documentos_fiscales, retail.arqueo_conteos,
                 retail.movimientos_caja, retail.sesiones_caja,
                 retail.stock_ubicacion, retail.movimientos_inventario,
                 retail.variantes, retail.medios_pago, retail.ubicaciones,
                 retail.dispositivos, retail.cajas, retail.tiendas
        RESTART IDENTITY CASCADE
    """))


def _sembrar(c):
    _limpiar(c)
    c.execute(text("""
        INSERT INTO retail.tiendas (id, nombre, siigo_bodega_id, siigo_centro_costo_id)
        VALUES ('florida', 'Florida', 48, 774)
    """))
    c.execute(text("""
        INSERT INTO retail.cajas (id, tienda_id, nombre, prefijo_factura)
        VALUES ('florida_caja1', 'florida', 'Florida · Caja 1', 'FV-20')
    """))
    c.execute(text("""
        INSERT INTO retail.ubicaciones (id, tipo, nombre, tienda_id, siigo_bodega_id)
        VALUES ('tienda:florida', 'tienda', 'Florida', 'florida', 48)
    """))
    c.execute(text("""
        INSERT INTO retail.medios_pago (id, nombre, tipo, siigo_forma_pago_id, permite_vuelto)
        VALUES ('efectivo', 'Efectivo', 'efectivo', 12243, true)
    """))
    c.execute(text(f"""
        INSERT INTO retail.variantes (id, sku, referencia, talla, nombre, precio_base)
        VALUES ('{ULID_D}', '92611-1T10', '92611-1', '10', 'Jean Skinny Azul', 14277311)
    """))


def _sesion(c, sesion_id=ULID_A, estado="abierta"):
    cerrada = "now()" if estado == "cerrada" else "NULL"
    c.execute(text(f"""
        INSERT INTO retail.sesiones_caja
            (id, tienda_id, caja_id, numero_turno, estado, base_inicial,
             abierta_por, cerrada_en)
        VALUES ('{sesion_id}', 'florida', 'florida_caja1', 1284, '{estado}',
                20000000, 'maria', {cerrada})
    """))


def _venta(c, venta_id=ULID_C, consecutivo=1334, estado="borrador",
           total=0, pagado=0, sesion_id=ULID_A):
    cerrada = "now()" if estado == "cerrada" else "NULL"
    c.execute(text(f"""
        INSERT INTO retail.ventas
            (id, numero, prefijo, consecutivo, tienda_id, caja_id, sesion_id,
             cajera_id, estado, total, pagado, cerrada_en)
        VALUES ('{venta_id}', 'FV-20-{consecutivo}', 'FV-20', {consecutivo},
                'florida', 'florida_caja1', '{sesion_id}', 'maria',
                '{estado}', {total}, {pagado}, {cerrada})
    """))


# ── INV-C1 · una sola sesión abierta por caja ───────────────────────────────

def test_la_base_impide_dos_turnos_abiertos_en_la_misma_caja(conn):
    """Dos turnos abiertos hacen imposible el arqueo.

    Comprobarlo en Python dejaría una ventana entre el SELECT y el INSERT en
    la que dos dispositivos abren turno a la vez. El índice no la tiene.
    """
    _sesion(conn, ULID_A)
    conn.commit()
    with pytest.raises(IntegrityError) as e:
        _sesion(conn, ULID_B)
        conn.commit()
    assert "ux_sesion_abierta" in str(e.value)


def test_cerrar_el_turno_libera_la_caja_para_el_siguiente(conn):
    _sesion(conn, ULID_A, estado="cerrada")
    _sesion(conn, ULID_B, estado="abierta")
    conn.commit()  # no debe reventar


# ── INV-V10 · idempotencia del ticket ───────────────────────────────────────

def test_el_mismo_consecutivo_no_se_repite_en_la_caja(conn):
    _sesion(conn)
    _venta(conn, ULID_C, consecutivo=1334)
    conn.commit()
    with pytest.raises(IntegrityError) as e:
        _venta(conn, ULID_B, consecutivo=1334)
        conn.commit()
    assert "ux_venta_numero" in str(e.value)


def test_reintentar_la_misma_venta_no_la_duplica(conn):
    """ON CONFLICT DO NOTHING: el outbox puede reintentar sin miedo (ADR-005)."""
    _sesion(conn)
    _venta(conn, ULID_C, consecutivo=1334)
    conn.commit()
    r = conn.execute(text(f"""
        INSERT INTO retail.ventas
            (id, numero, prefijo, consecutivo, tienda_id, caja_id, sesion_id,
             cajera_id, estado)
        VALUES ('{ULID_C}', 'FV-20-1334', 'FV-20', 1334, 'florida',
                'florida_caja1', '{ULID_A}', 'maria', 'borrador')
        ON CONFLICT (id) DO NOTHING
    """))
    assert r.rowcount == 0
    conn.commit()
    assert conn.execute(text("SELECT count(*) FROM retail.ventas")).scalar() == 1


# ── INV-V3 y V7 · las reglas del dinero, en la base ─────────────────────────

def test_no_se_puede_guardar_una_venta_cerrada_con_faltante(conn):
    """INV-V3 también vive en la base: la pantalla se puede saltar, el CHECK no."""
    _sesion(conn)
    with pytest.raises(IntegrityError):
        _venta(conn, ULID_C, estado="cerrada", total=16990000, pagado=10000000)
        conn.commit()


def test_una_linea_en_cero_exige_ser_obsequio_autorizado(conn):
    """INV-V7. Un precio en cero es la forma clásica de sacar mercancía."""
    _sesion(conn)
    _venta(conn)
    conn.commit()
    with pytest.raises(IntegrityError):
        conn.execute(text(f"""
            INSERT INTO retail.venta_lineas
                (id, venta_id, orden, variante_id, sku, descripcion, cantidad,
                 precio_unitario)
            VALUES ('{ULID_B}', '{ULID_C}', 1, '{ULID_D}', '92611-1T10',
                    'Jean', 1, 0)
        """))
        conn.commit()


def test_un_obsequio_autorizado_si_puede_ir_en_cero(conn):
    _sesion(conn)
    _venta(conn)
    conn.execute(text(f"""
        INSERT INTO retail.venta_lineas
            (id, venta_id, orden, variante_id, sku, descripcion, cantidad,
             precio_unitario, obsequio, autorizado_por)
        VALUES ('{ULID_B}', '{ULID_C}', 1, '{ULID_D}', '92611-1T10',
                'Jean', 1, 0, true, 'laura')
    """))
    conn.commit()


def test_un_descuento_sin_motivo_no_se_guarda(conn):
    _sesion(conn)
    _venta(conn)
    conn.commit()
    with pytest.raises(IntegrityError):
        conn.execute(text(f"""
            INSERT INTO retail.venta_lineas
                (id, venta_id, orden, variante_id, sku, descripcion, cantidad,
                 precio_unitario, descuento_monto)
            VALUES ('{ULID_B}', '{ULID_C}', 1, '{ULID_D}', '92611-1T10',
                    'Jean', 1, 14277311, 899000)
        """))
        conn.commit()


# ── INV-F1 · un solo documento fiscal emitido por venta ─────────────────────

def test_no_pueden_existir_dos_facturas_emitidas_de_la_misma_venta(conn):
    """R4: dos réplicas del worker emitiendo a la vez producen un error,
    no una factura duplicada ante la DIAN."""
    _sesion(conn)
    _venta(conn, ULID_C, estado="cerrada", total=16990000, pagado=16990000)
    for doc in (ULID_A, ULID_B):
        conn.execute(text(f"""
            INSERT INTO retail.documentos_fiscales
                (id, venta_id, tipo, estado, payload_snapshot)
            VALUES ('{doc}', '{ULID_C}', 'factura_electronica', 'pendiente', '{{}}')
        """))
    conn.commit()

    conn.execute(text(
        f"UPDATE retail.documentos_fiscales SET estado='emitido' WHERE id='{ULID_A}'"))
    conn.commit()
    with pytest.raises(IntegrityError) as e:
        conn.execute(text(
            f"UPDATE retail.documentos_fiscales SET estado='emitido' WHERE id='{ULID_B}'"))
        conn.commit()
    assert "ux_doc_emitido" in str(e.value)


# ── INV-I1 · la reserva atómica ─────────────────────────────────────────────

def test_la_reserva_atomica_no_deja_vender_lo_que_no_hay(conn):
    """Una sola sentencia. Sin SELECT previo, sin ventana de carrera.

    Es la diferencia entre "no debería sobrevender" y "no puede".
    """
    conn.execute(text(f"""
        INSERT INTO retail.stock_ubicacion (ubicacion_id, variante_id, cantidad)
        VALUES ('tienda:florida', '{ULID_D}', 2)
    """))
    conn.commit()

    reserva = text("""
        UPDATE retail.stock_ubicacion
           SET reservado = reservado + :n, actualizado_en = now()
         WHERE ubicacion_id = :u AND variante_id = :v
           AND (cantidad - reservado) >= :n
        RETURNING cantidad - reservado AS disponible
    """)
    params = {"u": "tienda:florida", "v": ULID_D}

    assert conn.execute(reserva, {**params, "n": 2}).rowcount == 1
    # La segunda caja pide la misma prenda: cero filas, y el saldo no se movió.
    assert conn.execute(reserva, {**params, "n": 1}).rowcount == 0
    conn.commit()

    fila = conn.execute(text(
        f"SELECT cantidad, reservado FROM retail.stock_ubicacion "
        f"WHERE variante_id='{ULID_D}'")).one()
    assert (fila.cantidad, fila.reservado) == (2, 2)


def test_el_libro_mayor_no_admite_asientos_sin_referencia(conn):
    """INV-I3. Un asiento sin origen no se puede auditar."""
    with pytest.raises(IntegrityError):
        conn.execute(text(f"""
            INSERT INTO retail.movimientos_inventario
                (ubicacion_id, variante_id, delta, saldo_despues, motivo,
                 referencia_tipo, referencia_id, usuario_id)
            VALUES ('tienda:florida', '{ULID_D}', -1, 1, 'venta', 'venta', '', 'maria')
        """))
        conn.commit()


def test_el_libro_mayor_es_append_only(conn):
    """INV-I5. Corregir es un movimiento contrario, no una edición."""
    priv = conn.execute(text("""
        SELECT has_table_privilege('public', 'retail.movimientos_inventario', 'UPDATE')
    """)).scalar()
    assert priv is False


# ── El dominio del dinero ───────────────────────────────────────────────────

def test_el_ulid_invalido_lo_rechaza_la_base(conn):
    with pytest.raises((IntegrityError, DBAPIError)):
        conn.execute(text("""
            INSERT INTO retail.dispositivos (id, caja_id, nombre, token_hash, registrado_por)
            VALUES ('no-es-un-ulid-valido-xxxxxx', 'florida_caja1', 'tablet', 'x', 'maria')
        """))
        conn.commit()


def test_el_dinero_es_entero_de_64_bits(conn):
    """ADR-008. Si fuera numeric o float, el redondeo volvería por la puerta
    de atrás justo donde más duele."""
    tipo = conn.execute(text("""
        SELECT data_type FROM information_schema.columns
         WHERE table_schema='retail' AND table_name='ventas' AND column_name='total'
    """)).scalar()
    assert tipo == "bigint"


def test_la_auditoria_esta_particionada_y_es_append_only(conn):
    es_particionada = conn.execute(text("""
        SELECT relkind = 'p' FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
         WHERE n.nspname='retail' AND c.relname='auditoria'
    """)).scalar()
    assert es_particionada is True
    assert conn.execute(text("""
        SELECT has_table_privilege('public', 'retail.auditoria', 'DELETE')
    """)).scalar() is False


def test_la_migracion_es_reversible(engine):
    """CI corre upgrade y downgrade en cada build.

    Una migración que no se puede revertir es una que nadie se atreve a
    desplegar un viernes.
    """
    from backend.modules.retail.migraciones.runner import aplicar, revertir

    revertir(URL)
    with engine.connect() as c:
        quedan = c.execute(text("""
            SELECT count(*) FROM information_schema.tables
             WHERE table_schema = 'retail' AND table_name <> 'alembic_version'
        """)).scalar()
    assert quedan == 0, "el downgrade dejó tablas atrás"

    aplicar(URL)
    with engine.connect() as c:
        assert c.execute(text("""
            SELECT count(*) FROM information_schema.tables
             WHERE table_schema = 'retail' AND table_name = 'ventas'
        """)).scalar() == 1
