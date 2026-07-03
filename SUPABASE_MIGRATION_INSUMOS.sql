-- Migración: inventario de INSUMOS (cierres, botones, marquillas, bolsas…).
-- Entradas por ingreso manual; salidas automáticas al marcar la remisión
-- como recogida/despachada (descuenta lo calculado del precosteo).
-- Ejecutar UNA vez en Supabase SQL Editor.

CREATE TABLE IF NOT EXISTS insumos (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    nombre      TEXT NOT NULL,
    categoria   TEXT NOT NULL DEFAULT 'INSUMO CONFECCION'
                CHECK (categoria IN ('INSUMO CONFECCION','INSUMO TERMINACION','OTRO')),
    unidad      TEXT NOT NULL DEFAULT 'und',
    cantidad_disponible NUMERIC NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (nombre)
);

CREATE TABLE IF NOT EXISTS insumos_movimientos (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    insumo_id   UUID NOT NULL REFERENCES insumos(id) ON DELETE CASCADE,
    tipo        TEXT NOT NULL CHECK (tipo IN ('ingreso','salida','ajuste')),
    cantidad    NUMERIC NOT NULL,           -- + entra, − sale
    doc_ref     TEXT,                        -- REM-XXXX, ingreso manual, etc.
    nota        TEXT,
    usuario     TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_insumos_mov_insumo ON insumos_movimientos(insumo_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_insumos_categoria ON insumos(categoria);
