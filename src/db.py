"""
Capa de acceso a la base de datos central — Male Denim OS
SQLite (desarrollo) → PostgreSQL (producción, mismo código)

Tablas:
  pedidos            ← tabla maestra, eje de todo el sistema
  logistica_snapshots← historial de estados logísticos por día
  liquidaciones      ← liquidaciones COD de Melonn
  movimientos_banco  ← extracto bancario
  pagos_plataforma   ← Wompi / MercadoPago / Addi
"""

import sqlite3
from pathlib import Path
from datetime import datetime
from contextlib import contextmanager
from typing import Optional

DB_PATH = Path(__file__).parent.parent / "data" / "db" / "maledenim.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


# ── Conexión ──────────────────────────────────────────────────────────────────
@contextmanager
def get_conn():
    """Context manager: abre conexión, hace commit/rollback automático."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row          # rows como dicts
    conn.execute("PRAGMA journal_mode=WAL")  # mejor concurrencia
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Creación de tablas ────────────────────────────────────────────────────────
SCHEMA = """
-- ═══════════════════════════════════════
-- TABLA MAESTRA DE PEDIDOS
-- Una fila = un pedido. Eje del sistema.
-- ═══════════════════════════════════════
CREATE TABLE IF NOT EXISTS pedidos (
    -- Identificación
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    orden_shopify           TEXT,
    orden_melonn            TEXT UNIQUE,
    fecha_pedido            DATE,
    canal                   TEXT,          -- shopify / asesor / marketplace

    -- Cliente
    nombre_cliente          TEXT,
    telefono_cliente        TEXT,
    email_cliente           TEXT,
    ciudad_destino          TEXT,
    region_destino          TEXT,

    -- Producto (resumen)
    sku                     TEXT,
    producto                TEXT,
    cantidad                INTEGER,
    precio_venta            REAL,
    costo_producto          REAL,

    -- Pago
    metodo_pago             TEXT,          -- cod / wompi / mercadopago / addi / transferencia
    plataforma_pago         TEXT,
    valor_pagado            REAL,
    estado_pago             TEXT DEFAULT 'pendiente',  -- pendiente / pagado / fallido / devuelto

    -- Logística (último estado conocido)
    transportadora          TEXT,
    fecha_despacho          DATE,
    fecha_promesa           DATE,
    fecha_entrega           DATE,
    estado_melonn           TEXT,
    zona_logistica          TEXT,
    dias_en_transito        INTEGER,
    score_riesgo            INTEGER,
    nivel_riesgo            TEXT DEFAULT 'NORMAL',
    incidencia              TEXT DEFAULT 'NINGUNO',
    categoria_incidencia    TEXT DEFAULT 'OK',
    es_contraentrega        INTEGER DEFAULT 0,  -- 0/1 (SQLite bool)
    link_melonn             TEXT,

    -- Contraentrega
    valor_cod               REAL,
    estado_recaudo          TEXT DEFAULT 'pendiente',  -- pendiente / recaudado / no_pago / devuelto
    fecha_recaudo           DATE,
    liquidacion_id          INTEGER REFERENCES liquidaciones(id),

    -- Financiero (desembolso)
    valor_desembolsado      REAL,
    fecha_desembolso        DATE,
    referencia_bancaria     TEXT,
    estado_banco            TEXT DEFAULT 'pendiente',  -- pendiente / recibido / diferencia

    -- Contabilidad
    factura_siigo           TEXT,
    estado_contable         TEXT DEFAULT 'pendiente',

    -- Conciliación
    conciliado              INTEGER DEFAULT 0,
    estado_conciliacion     TEXT DEFAULT 'pendiente',  -- ok / diferencia / pendiente / error
    diferencia              REAL DEFAULT 0,

    -- Metadata
    creado_en               DATETIME DEFAULT CURRENT_TIMESTAMP,
    actualizado_en          DATETIME DEFAULT CURRENT_TIMESTAMP,
    fuente                  TEXT DEFAULT 'csv'  -- csv / shopify_api / melonn_api
);

-- ═══════════════════════════════════════
-- HISTORIAL LOGÍSTICO (snapshot diario)
-- Permite ver evolución de riesgo día a día
-- ═══════════════════════════════════════
CREATE TABLE IF NOT EXISTS logistica_snapshots (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha_snapshot      DATE NOT NULL,
    orden_melonn        TEXT NOT NULL,
    orden_shopify       TEXT,
    estado_melonn       TEXT,
    dias_en_transito    INTEGER,
    score_riesgo        INTEGER,
    nivel_riesgo        TEXT,
    incidencia          TEXT,
    transportadora      TEXT,
    ciudad_destino      TEXT,
    es_contraentrega    INTEGER,
    valor_cod           REAL,
    fuente_csv          TEXT,   -- nombre del archivo CSV procesado
    UNIQUE(fecha_snapshot, orden_melonn)
);

-- ═══════════════════════════════════════
-- LIQUIDACIONES COD (Melonn liquida por lotes)
-- ═══════════════════════════════════════
CREATE TABLE IF NOT EXISTS liquidaciones (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    referencia_liquidacion  TEXT UNIQUE,
    fecha_liquidacion       DATE,
    periodo_inicio          DATE,
    periodo_fin             DATE,
    total_pedidos           INTEGER,
    valor_liquidado         REAL,
    valor_recibido_banco    REAL,
    diferencia              REAL DEFAULT 0,
    estado                  TEXT DEFAULT 'pendiente',  -- pendiente / parcial / completo
    observaciones           TEXT,
    creado_en               DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ═══════════════════════════════════════
-- MOVIMIENTOS BANCARIOS
-- ═══════════════════════════════════════
CREATE TABLE IF NOT EXISTS movimientos_banco (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha               DATE NOT NULL,
    descripcion         TEXT,
    valor               REAL NOT NULL,
    tipo                TEXT,              -- ingreso / egreso
    origen              TEXT,              -- wompi / melonn / addi / transferencia / otro
    referencia          TEXT,
    pedido_id           INTEGER REFERENCES pedidos(id),
    conciliado          INTEGER DEFAULT 0,
    creado_en           DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ═══════════════════════════════════════
-- PAGOS POR PLATAFORMA
-- ═══════════════════════════════════════
CREATE TABLE IF NOT EXISTS pagos_plataforma (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    plataforma              TEXT NOT NULL,  -- wompi / mercadopago / addi
    referencia_plataforma   TEXT UNIQUE,
    pedido_id               INTEGER REFERENCES pedidos(id),
    orden_shopify           TEXT,
    valor_bruto             REAL,
    comision                REAL DEFAULT 0,
    valor_neto              REAL,
    estado                  TEXT,           -- aprobado / rechazado / devuelto / contracargo
    fecha_transaccion       DATE,
    fecha_desembolso        DATE,
    conciliado              INTEGER DEFAULT 0,
    creado_en               DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ═══════════════════════════════════════
-- PRODUCTOS (catálogo Shopify)
-- ═══════════════════════════════════════
CREATE TABLE IF NOT EXISTS productos (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    shopify_id          TEXT UNIQUE,
    titulo              TEXT,
    tipo                TEXT,
    proveedor           TEXT,
    estado              TEXT,               -- active / draft / archived
    tags                TEXT,
    fecha_creacion      DATE,
    fecha_publicacion   DATE,               -- published_at = fecha lanzamiento
    precio_min          REAL,
    precio_max          REAL,
    inventario_total    INTEGER DEFAULT 0,
    variantes_json      TEXT,               -- JSON con todas las variantes/SKUs
    imagenes_json       TEXT,               -- JSON con URLs de imágenes
    actualizado_en      DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ═══════════════════════════════════════
-- CLIENTES (Shopify customers)
-- ═══════════════════════════════════════
CREATE TABLE IF NOT EXISTS clientes (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    shopify_id          TEXT UNIQUE,
    nombre              TEXT,
    email               TEXT,
    telefono            TEXT,
    ciudad              TEXT,
    region              TEXT,
    pais                TEXT DEFAULT 'CO',
    total_pedidos       INTEGER DEFAULT 0,
    total_gastado       REAL DEFAULT 0,
    acepta_marketing    INTEGER DEFAULT 0,
    tags                TEXT,
    fecha_primer_pedido DATE,
    fecha_ultimo_pedido DATE,
    actualizado_en      DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ═══════════════════════════════════════
-- LOG DE SINCRONIZACIÓN SHOPIFY
-- ═══════════════════════════════════════
CREATE TABLE IF NOT EXISTS shopify_sync_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha_sync      DATETIME DEFAULT CURRENT_TIMESTAMP,
    entidad         TEXT,       -- pedidos / productos / clientes / transacciones
    registros_api   INTEGER DEFAULT 0,
    insertados      INTEGER DEFAULT 0,
    actualizados    INTEGER DEFAULT 0,
    errores         INTEGER DEFAULT 0,
    duracion_seg    REAL,
    estado          TEXT DEFAULT 'ok',   -- ok / error / parcial
    mensaje         TEXT
);

-- ═══════════════════════════════════════
-- ÍNDICES para rendimiento
-- ═══════════════════════════════════════
CREATE INDEX IF NOT EXISTS idx_pedidos_shopify   ON pedidos(orden_shopify);
CREATE INDEX IF NOT EXISTS idx_pedidos_melonn    ON pedidos(orden_melonn);
CREATE INDEX IF NOT EXISTS idx_pedidos_nivel     ON pedidos(nivel_riesgo);
CREATE INDEX IF NOT EXISTS idx_pedidos_cod       ON pedidos(es_contraentrega);
CREATE INDEX IF NOT EXISTS idx_pedidos_concil    ON pedidos(conciliado);
CREATE INDEX IF NOT EXISTS idx_snapshots_fecha   ON logistica_snapshots(fecha_snapshot);
CREATE INDEX IF NOT EXISTS idx_snapshots_orden   ON logistica_snapshots(orden_melonn);
CREATE INDEX IF NOT EXISTS idx_banco_fecha       ON movimientos_banco(fecha);
CREATE INDEX IF NOT EXISTS idx_pagos_plataforma  ON pagos_plataforma(plataforma);
CREATE INDEX IF NOT EXISTS idx_productos_estado  ON productos(estado);
CREATE INDEX IF NOT EXISTS idx_productos_pub     ON productos(fecha_publicacion);
CREATE INDEX IF NOT EXISTS idx_clientes_shopify  ON clientes(shopify_id);
CREATE INDEX IF NOT EXISTS idx_sync_log_fecha    ON shopify_sync_log(fecha_sync);
"""


def init_db() -> None:
    """Crea todas las tablas si no existen."""
    with get_conn() as conn:
        conn.executescript(SCHEMA)
    print(f"Base de datos lista: {DB_PATH}")


# ── Operaciones de pedidos ─────────────────────────────────────────────────────
def upsert_pedido(p: dict) -> int:
    """
    Inserta o actualiza un pedido por orden_melonn.
    Retorna el id del pedido.
    """
    sql = """
    INSERT INTO pedidos (
        orden_shopify, orden_melonn, fecha_pedido, canal,
        nombre_cliente, telefono_cliente, email_cliente, ciudad_destino, region_destino,
        sku, producto, cantidad, precio_venta,
        metodo_pago, plataforma_pago, valor_pagado, es_contraentrega, valor_cod,
        transportadora, fecha_despacho, fecha_promesa, fecha_entrega,
        estado_melonn, zona_logistica, dias_en_transito,
        score_riesgo, nivel_riesgo, incidencia, categoria_incidencia,
        link_melonn, fuente, actualizado_en
    ) VALUES (
        :orden_shopify, :orden_melonn, :fecha_pedido, :canal,
        :nombre_cliente, :telefono_cliente, :email_cliente, :ciudad_destino, :region_destino,
        :sku, :producto, :cantidad, :precio_venta,
        :metodo_pago, :plataforma_pago, :valor_pagado, :es_contraentrega, :valor_cod,
        :transportadora, :fecha_despacho, :fecha_promesa, :fecha_entrega,
        :estado_melonn, :zona_logistica, :dias_en_transito,
        :score_riesgo, :nivel_riesgo, :incidencia, :categoria_incidencia,
        :link_melonn, :fuente, CURRENT_TIMESTAMP
    )
    ON CONFLICT(orden_melonn) DO UPDATE SET
        estado_melonn       = excluded.estado_melonn,
        dias_en_transito    = excluded.dias_en_transito,
        score_riesgo        = excluded.score_riesgo,
        nivel_riesgo        = excluded.nivel_riesgo,
        incidencia          = excluded.incidencia,
        categoria_incidencia= excluded.categoria_incidencia,
        fecha_entrega       = excluded.fecha_entrega,
        actualizado_en      = CURRENT_TIMESTAMP
    """
    with get_conn() as conn:
        cur = conn.execute(sql, p)
        return cur.lastrowid


def guardar_snapshot(pedidos: list, fecha: str, fuente_csv: str) -> int:
    """
    Guarda un snapshot logístico diario de todos los pedidos.
    Permite ver la evolución del riesgo día a día.
    """
    sql = """
    INSERT OR REPLACE INTO logistica_snapshots (
        fecha_snapshot, orden_melonn, orden_shopify,
        estado_melonn, dias_en_transito, score_riesgo, nivel_riesgo,
        incidencia, transportadora, ciudad_destino, es_contraentrega, valor_cod,
        fuente_csv
    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    """
    rows = [
        (fecha,
         p.get("orden_melonn"), p.get("orden_shopify"),
         p.get("estado_melonn"), p.get("dias_en_transito"), p.get("score_riesgo"),
         p.get("nivel_riesgo"), p.get("incidencia"), p.get("transportadora"),
         p.get("ciudad_destino"), 1 if p.get("es_contraentrega") else 0,
         p.get("valor_cod"), fuente_csv)
        for p in pedidos
    ]
    with get_conn() as conn:
        conn.executemany(sql, rows)
    return len(rows)


def obtener_pedidos_activos(nivel: Optional[str] = None, solo_cod: bool = False) -> list:
    """Retorna pedidos activos (no entregados) con filtros opcionales."""
    sql = "SELECT * FROM pedidos WHERE fecha_entrega IS NULL"
    params = []
    if nivel:
        sql += " AND nivel_riesgo = ?"
        params.append(nivel)
    if solo_cod:
        sql += " AND es_contraentrega = 1"
    sql += " ORDER BY score_riesgo DESC, dias_en_transito DESC"
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def obtener_historico_orden(orden_melonn: str) -> list:
    """Retorna el historial de snapshots de un pedido específico."""
    sql = """
    SELECT fecha_snapshot, estado_melonn, dias_en_transito,
           score_riesgo, nivel_riesgo, incidencia
    FROM logistica_snapshots
    WHERE orden_melonn = ?
    ORDER BY fecha_snapshot ASC
    """
    with get_conn() as conn:
        rows = conn.execute(sql, (orden_melonn,)).fetchall()
    return [dict(r) for r in rows]


def stats_db() -> dict:
    """Retorna estadísticas generales de la base de datos."""
    with get_conn() as conn:
        total     = conn.execute("SELECT COUNT(*) FROM pedidos").fetchone()[0]
        activos   = conn.execute("SELECT COUNT(*) FROM pedidos WHERE fecha_entrega IS NULL").fetchone()[0]
        criticos  = conn.execute("SELECT COUNT(*) FROM pedidos WHERE nivel_riesgo='CRITICO'").fetchone()[0]
        snapshots = conn.execute("SELECT COUNT(*) FROM logistica_snapshots").fetchone()[0]
        dias      = conn.execute("SELECT COUNT(DISTINCT fecha_snapshot) FROM logistica_snapshots").fetchone()[0]
    return {
        "total_pedidos": total,
        "activos": activos,
        "criticos": criticos,
        "snapshots": snapshots,
        "dias_con_datos": dias,
    }


if __name__ == "__main__":
    init_db()
    s = stats_db()
    print("\nEstado de la base de datos:")
    for k, v in s.items():
        print(f"  {k}: {v}")
    print(f"\nRuta: {DB_PATH}")
