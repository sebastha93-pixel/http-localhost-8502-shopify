-- ═══════════════════════════════════════════════════════════════════════
-- MALE'DENIM OS · Módulo Producción · Schema Fase 1
-- ═══════════════════════════════════════════════════════════════════════
-- Correr UNA VEZ en Supabase → SQL Editor.
-- Idempotente: usa IF NOT EXISTS en todo, se puede re-ejecutar sin romper.
-- ═══════════════════════════════════════════════════════════════════════

-- Extensión para uuid_generate_v4() (Supabase la trae, pero por si acaso)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ─────────────────────────────────────────────────────────────────────
-- Consecutivos globales (ING, ROLLO, OC, REM, PC, RI)
-- ─────────────────────────────────────────────────────────────────────
-- Función helper: next_consecutivo('ING', 2026) → 'ING-2026-0001'
CREATE TABLE IF NOT EXISTS produccion_consecutivos (
    prefijo     TEXT NOT NULL,        -- ING | ROLLO | OC | REM | PC | RI
    anio        INTEGER NOT NULL,
    ultimo      INTEGER NOT NULL DEFAULT 0,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (prefijo, anio)
);

CREATE OR REPLACE FUNCTION next_consecutivo(p_prefijo TEXT, p_anio INTEGER, p_width INTEGER DEFAULT 4)
RETURNS TEXT AS $$
DECLARE
    v_ultimo INTEGER;
BEGIN
    INSERT INTO produccion_consecutivos (prefijo, anio, ultimo)
    VALUES (p_prefijo, p_anio, 1)
    ON CONFLICT (prefijo, anio)
    DO UPDATE SET ultimo = produccion_consecutivos.ultimo + 1,
                  updated_at = NOW()
    RETURNING ultimo INTO v_ultimo;

    RETURN p_prefijo || '-' || p_anio::TEXT || '-' || lpad(v_ultimo::TEXT, p_width, '0');
END;
$$ LANGUAGE plpgsql;

-- ─────────────────────────────────────────────────────────────────────
-- INVENTARIO DE TELA
-- ─────────────────────────────────────────────────────────────────────

-- Cabecera de la orden de ingreso (una entrega de textilera)
CREATE TABLE IF NOT EXISTS ordenes_ingreso (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    numero_ingreso    TEXT UNIQUE NOT NULL,       -- ING-2026-0001
    textilera         TEXT NOT NULL,
    nit_textilera     TEXT,
    numero_documento  TEXT NOT NULL,              -- remisión/factura/lista de la textilera
    tipo_documento    TEXT NOT NULL CHECK (tipo_documento IN ('remision','factura','lista_empaque','consulta')),
    fecha             DATE NOT NULL,
    orden_compra      TEXT,
    total_rollos      INTEGER NOT NULL DEFAULT 0,
    total_metros      NUMERIC(12,2) NOT NULL DEFAULT 0,
    estado            TEXT NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente','recibida_parcial','recibida_completa','conciliada')),
    observaciones     TEXT,
    created_by        TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ordenes_ingreso_textilera ON ordenes_ingreso(textilera);
CREATE INDEX IF NOT EXISTS idx_ordenes_ingreso_fecha ON ordenes_ingreso(fecha DESC);
CREATE INDEX IF NOT EXISTS idx_ordenes_ingreso_estado ON ordenes_ingreso(estado);

-- Rollo de tela (unidad de inventario, uno por línea de la textilera)
CREATE TABLE IF NOT EXISTS rollos_tela (
    id                 UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    codigo_interno     TEXT UNIQUE NOT NULL,       -- ROLLO-2026-000001
    barcode            TEXT UNIQUE NOT NULL,       -- Code128 → mismo que codigo_interno usualmente
    orden_ingreso_id   UUID NOT NULL REFERENCES ordenes_ingreso(id) ON DELETE RESTRICT,
    numero_rollo       TEXT,                       -- el que trae la textilera
    serial             TEXT,
    lote_fabrica       TEXT,
    tono               TEXT,                       -- A, B, 653, 999, etc.
    referencia_tela    TEXT,                       -- código del catálogo textilera
    descripcion_tela   TEXT NOT NULL,              -- SANDDENIM, FUNKY, etc.
    ancho              NUMERIC(6,2),               -- cm
    costo_metro        NUMERIC(12,2),              -- COP
    metros_inicial     NUMERIC(10,2) NOT NULL,
    metros_disponible  NUMERIC(10,2) NOT NULL,
    fecha_ingreso      DATE NOT NULL DEFAULT CURRENT_DATE,
    fecha_ultimo_corte DATE,
    estado             TEXT NOT NULL DEFAULT 'disponible' CHECK (estado IN ('disponible','en_corte','agotado','con_novedad')),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (metros_disponible >= 0),
    CHECK (metros_disponible <= metros_inicial + 0.01)  -- tolerancia float
);
CREATE INDEX IF NOT EXISTS idx_rollos_ingreso ON rollos_tela(orden_ingreso_id);
CREATE INDEX IF NOT EXISTS idx_rollos_descripcion ON rollos_tela(descripcion_tela);
CREATE INDEX IF NOT EXISTS idx_rollos_estado ON rollos_tela(estado);
CREATE INDEX IF NOT EXISTS idx_rollos_barcode ON rollos_tela(barcode);
CREATE INDEX IF NOT EXISTS idx_rollos_tono ON rollos_tela(tono);

-- Libro mayor auditable — todo movimiento sobre un rollo
CREATE TABLE IF NOT EXISTS movimientos_inventario (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    rollo_id     UUID NOT NULL REFERENCES rollos_tela(id) ON DELETE RESTRICT,
    tipo         TEXT NOT NULL CHECK (tipo IN ('ingreso','corte','ajuste')),
    metros       NUMERIC(10,2) NOT NULL,           -- signed: + ingreso/ajuste positivo, - corte/ajuste negativo
    doc_ref      TEXT,                             -- ING-.../OC-.../ajuste manual
    usuario      TEXT,
    nota         TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_movimientos_rollo ON movimientos_inventario(rollo_id);
CREATE INDEX IF NOT EXISTS idx_movimientos_tipo ON movimientos_inventario(tipo);
CREATE INDEX IF NOT EXISTS idx_movimientos_fecha ON movimientos_inventario(created_at DESC);

-- ─────────────────────────────────────────────────────────────────────
-- PRECOSTEO
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS referencias_precosteo (
    id                     UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    codigo_referencia      TEXT UNIQUE NOT NULL,   -- 14500-1
    nombre                 TEXT NOT NULL,          -- SKINNY OSCURO
    tela                   TEXT,
    color                  TEXT,
    foto_url               TEXT,                   -- Supabase Storage
    iva_pct                NUMERIC(5,2) NOT NULL DEFAULT 19,
    costo_total_sin_iva    NUMERIC(12,2) NOT NULL DEFAULT 0,
    costo_total_con_iva    NUMERIC(12,2) NOT NULL DEFAULT 0,
    precio_sugerido_venta  NUMERIC(12,2),
    margen                 NUMERIC(5,2),
    estado                 TEXT NOT NULL DEFAULT 'borrador' CHECK (estado IN ('borrador','autorizada')),
    autorizada_por         TEXT,
    fecha_autorizacion     TIMESTAMPTZ,
    bloqueada              BOOLEAN NOT NULL DEFAULT FALSE,
    created_by             TEXT,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ref_precosteo_estado ON referencias_precosteo(estado);
CREATE INDEX IF NOT EXISTS idx_ref_precosteo_tela ON referencias_precosteo(tela);

CREATE TABLE IF NOT EXISTS precosteo_items (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    referencia_id     UUID NOT NULL REFERENCES referencias_precosteo(id) ON DELETE CASCADE,
    categoria         TEXT NOT NULL,               -- DIRTY JEANS / MP / PROCESO / INSUMO / etc.
    item              TEXT NOT NULL,               -- PRECIO TELA / FORRO / CIERRE / BOTON…
    valor_unitario    NUMERIC(12,2) NOT NULL DEFAULT 0,
    cantidad          NUMERIC(10,3) NOT NULL DEFAULT 1,
    iva               NUMERIC(12,2) NOT NULL DEFAULT 0,
    total_sin_iva     NUMERIC(12,2) NOT NULL DEFAULT 0,   -- = valor_unitario × cantidad
    total_con_iva     NUMERIC(12,2) NOT NULL DEFAULT 0,   -- = total_sin_iva + iva
    orden             INTEGER NOT NULL DEFAULT 0,         -- para ordenar en el formato
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_precosteo_items_ref ON precosteo_items(referencia_id);

-- ─────────────────────────────────────────────────────────────────────
-- ORDEN DE CORTE
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS ordenes_corte (
    id                       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    consecutivo              TEXT UNIQUE NOT NULL,             -- OC-2026-0001
    referencia_id            UUID NOT NULL REFERENCES referencias_precosteo(id) ON DELETE RESTRICT,
    tono                     TEXT,
    largo_trazo              NUMERIC(8,2) NOT NULL,            -- metros
    prendas_por_trazo        INTEGER NOT NULL,
    curva_trazo              JSONB NOT NULL DEFAULT '{}',      -- {"4":2,"6":4,"8":6,...}
    num_capas                INTEGER NOT NULL,
    prendas_estimadas        INTEGER,                          -- = prendas_por_trazo × num_capas
    metros_consumidos        NUMERIC(10,2),                    -- teórico = largo_trazo × num_capas
    rendimiento_teorico      NUMERIC(8,4),                     -- = largo_trazo / prendas_por_trazo
    consumo_real_cortador    NUMERIC(10,2),                    -- lo ingresa cortador al cerrar
    diferencia_pct           NUMERIC(6,2),                     -- (real - teórico) / teórico × 100
    merma_tipo               TEXT CHECK (merma_tipo IN ('porcentaje','metros') OR merma_tipo IS NULL),
    merma_valor              NUMERIC(10,2),
    indicaciones             TEXT,
    responsable              TEXT,                             -- nombre del cortador
    fecha_limite             DATE,
    estado                   TEXT NOT NULL DEFAULT 'borrador' CHECK (estado IN ('borrador','autorizada','en_proceso','cortada')),
    autorizada_por           TEXT,
    fecha_autorizacion       TIMESTAMPTZ,
    fecha_cierre             TIMESTAMPTZ,
    cerrada_por              TEXT,
    confeccionista_id        UUID,                             -- FK opcional (después de cortar)
    created_by               TEXT,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_oc_estado ON ordenes_corte(estado);
CREATE INDEX IF NOT EXISTS idx_oc_referencia ON ordenes_corte(referencia_id);
CREATE INDEX IF NOT EXISTS idx_oc_responsable ON ordenes_corte(responsable);
CREATE INDEX IF NOT EXISTS idx_oc_fecha ON ordenes_corte(created_at DESC);

CREATE TABLE IF NOT EXISTS orden_corte_rollos (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    orden_corte_id  UUID NOT NULL REFERENCES ordenes_corte(id) ON DELETE CASCADE,
    rollo_id        UUID NOT NULL REFERENCES rollos_tela(id) ON DELETE RESTRICT,
    metros_usados   NUMERIC(10,2) NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (orden_corte_id, rollo_id)
);
CREATE INDEX IF NOT EXISTS idx_oc_rollos_oc ON orden_corte_rollos(orden_corte_id);
CREATE INDEX IF NOT EXISTS idx_oc_rollos_rollo ON orden_corte_rollos(rollo_id);

-- ─────────────────────────────────────────────────────────────────────
-- CONFECCIONISTAS + REMISIONES
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS confeccionistas (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    nombre      TEXT NOT NULL,
    telefono    TEXT,
    direccion   TEXT,
    activo      BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS remisiones (
    id                 UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    consecutivo        TEXT UNIQUE NOT NULL,       -- REM-2026-0001
    confeccionista_id  UUID NOT NULL REFERENCES confeccionistas(id) ON DELETE RESTRICT,
    fecha_recogida     DATE NOT NULL,
    estado             TEXT NOT NULL DEFAULT 'generada' CHECK (estado IN ('generada','recogida')),
    pdf_url            TEXT,
    created_by         TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_rem_confeccionista ON remisiones(confeccionista_id);
CREATE INDEX IF NOT EXISTS idx_rem_estado ON remisiones(estado);

CREATE TABLE IF NOT EXISTS remision_items (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    remision_id     UUID NOT NULL REFERENCES remisiones(id) ON DELETE CASCADE,
    orden_corte_id  UUID NOT NULL REFERENCES ordenes_corte(id) ON DELETE RESTRICT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (remision_id, orden_corte_id)
);
CREATE INDEX IF NOT EXISTS idx_rem_items_rem ON remision_items(remision_id);

-- FK diferida al confeccionista en ordenes_corte
ALTER TABLE ordenes_corte
    DROP CONSTRAINT IF EXISTS fk_oc_confeccionista;
ALTER TABLE ordenes_corte
    ADD CONSTRAINT fk_oc_confeccionista
    FOREIGN KEY (confeccionista_id) REFERENCES confeccionistas(id) ON DELETE SET NULL;

-- ─────────────────────────────────────────────────────────────────────
-- INSUMOS
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS insumos (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    codigo              TEXT UNIQUE,
    nombre              TEXT NOT NULL,           -- Cierre, Botón, Remache, Hilo…
    categoria           TEXT,                    -- confeccion / empaque / terminacion
    unidad              TEXT NOT NULL DEFAULT 'unidad',
    stock_inicial       NUMERIC(12,3) NOT NULL DEFAULT 0,
    stock_disponible    NUMERIC(12,3) NOT NULL DEFAULT 0,
    stock_minimo        NUMERIC(12,3) NOT NULL DEFAULT 0,
    costo_unitario      NUMERIC(12,2),
    activo              BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (stock_disponible >= 0)
);
CREATE INDEX IF NOT EXISTS idx_insumos_categoria ON insumos(categoria);
CREATE INDEX IF NOT EXISTS idx_insumos_activo ON insumos(activo);

CREATE TABLE IF NOT EXISTS remisiones_insumos (
    id                 UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    consecutivo        TEXT UNIQUE NOT NULL,     -- RI-2026-0001
    destino_tipo       TEXT NOT NULL CHECK (destino_tipo IN ('confeccionista','terminacion')),
    destino_id         UUID,                     -- confeccionistas(id) si destino_tipo='confeccionista'
    fecha              DATE NOT NULL DEFAULT CURRENT_DATE,
    observaciones      TEXT,
    created_by         TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS remision_insumo_items (
    id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    remision_insumo_id    UUID NOT NULL REFERENCES remisiones_insumos(id) ON DELETE CASCADE,
    insumo_id             UUID NOT NULL REFERENCES insumos(id) ON DELETE RESTRICT,
    cantidad              NUMERIC(12,3) NOT NULL,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_rem_ins_items_rem ON remision_insumo_items(remision_insumo_id);
CREATE INDEX IF NOT EXISTS idx_rem_ins_items_insumo ON remision_insumo_items(insumo_id);

-- ─────────────────────────────────────────────────────────────────────
-- USUARIOS: flags de autorización
-- ─────────────────────────────────────────────────────────────────────
-- Idempotente: si no existen las columnas, las añade.
ALTER TABLE usuarios
    ADD COLUMN IF NOT EXISTS puede_autorizar_precosteo BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS puede_autorizar_corte     BOOLEAN NOT NULL DEFAULT FALSE;

-- ─────────────────────────────────────────────────────────────────────
-- Trigger auto-update updated_at
-- ─────────────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION touch_updated_at() RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$
DECLARE
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'ordenes_ingreso','rollos_tela','referencias_precosteo',
        'ordenes_corte','confeccionistas','remisiones','insumos'
    ] LOOP
        EXECUTE format(
            'DROP TRIGGER IF EXISTS trg_%s_updated ON %I;
             CREATE TRIGGER trg_%s_updated
             BEFORE UPDATE ON %I
             FOR EACH ROW EXECUTE FUNCTION touch_updated_at();',
            t, t, t, t
        );
    END LOOP;
END $$;

-- ═══════════════════════════════════════════════════════════════════════
-- Fin del schema. Verificación:
-- SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename LIKE '%rollo%';
-- SELECT next_consecutivo('ING', 2026);  -- prueba consecutivo
-- ═══════════════════════════════════════════════════════════════════════
