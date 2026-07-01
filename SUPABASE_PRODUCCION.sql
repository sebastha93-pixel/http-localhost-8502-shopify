-- ═══════════════════════════════════════════════════════════════════════
-- MALE'DENIM OS · Módulo Producción · Schema Fase 1
-- ═══════════════════════════════════════════════════════════════════════
-- Correr UNA VEZ en Supabase → SQL Editor.
-- Idempotente: se puede re-ejecutar sin romper.
-- ═══════════════════════════════════════════════════════════════════════

-- Extensión para uuid_generate_v4()
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";


-- ─────────────────────────────────────────────────────────────────────
-- Consecutivos globales (ING, ROLLO, OC, REM, PC, RI)
-- ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS produccion_consecutivos (
    prefijo     TEXT NOT NULL,
    anio        INTEGER NOT NULL,
    ultimo      INTEGER NOT NULL DEFAULT 0,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (prefijo, anio)
);


-- ─────────────────────────────────────────────────────────────────────
-- INVENTARIO DE TELA
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS ordenes_ingreso (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    numero_ingreso    TEXT UNIQUE NOT NULL,
    textilera         TEXT NOT NULL,
    nit_textilera     TEXT,
    numero_documento  TEXT NOT NULL,
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


CREATE TABLE IF NOT EXISTS rollos_tela (
    id                 UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    codigo_interno     TEXT UNIQUE NOT NULL,
    barcode            TEXT UNIQUE NOT NULL,
    orden_ingreso_id   UUID NOT NULL REFERENCES ordenes_ingreso(id) ON DELETE RESTRICT,
    numero_rollo       TEXT,
    serial             TEXT,
    lote_fabrica       TEXT,
    tono               TEXT,
    referencia_tela    TEXT,
    descripcion_tela   TEXT NOT NULL,
    ancho              NUMERIC(6,2),
    costo_metro        NUMERIC(12,2),
    metros_inicial     NUMERIC(10,2) NOT NULL,
    metros_disponible  NUMERIC(10,2) NOT NULL,
    fecha_ingreso      DATE NOT NULL DEFAULT CURRENT_DATE,
    fecha_ultimo_corte DATE,
    estado             TEXT NOT NULL DEFAULT 'disponible' CHECK (estado IN ('disponible','en_corte','agotado','con_novedad')),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (metros_disponible >= 0)
);

CREATE INDEX IF NOT EXISTS idx_rollos_ingreso ON rollos_tela(orden_ingreso_id);
CREATE INDEX IF NOT EXISTS idx_rollos_descripcion ON rollos_tela(descripcion_tela);
CREATE INDEX IF NOT EXISTS idx_rollos_estado ON rollos_tela(estado);
CREATE INDEX IF NOT EXISTS idx_rollos_barcode ON rollos_tela(barcode);
CREATE INDEX IF NOT EXISTS idx_rollos_tono ON rollos_tela(tono);


CREATE TABLE IF NOT EXISTS movimientos_inventario (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    rollo_id     UUID NOT NULL REFERENCES rollos_tela(id) ON DELETE RESTRICT,
    tipo         TEXT NOT NULL CHECK (tipo IN ('ingreso','corte','ajuste')),
    metros       NUMERIC(10,2) NOT NULL,
    doc_ref      TEXT,
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
    codigo_referencia      TEXT UNIQUE NOT NULL,
    nombre                 TEXT NOT NULL,
    tela                   TEXT,
    color                  TEXT,
    foto_url               TEXT,
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
    categoria         TEXT NOT NULL,
    item              TEXT NOT NULL,
    valor_unitario    NUMERIC(12,2) NOT NULL DEFAULT 0,
    cantidad          NUMERIC(10,3) NOT NULL DEFAULT 1,
    iva               NUMERIC(12,2) NOT NULL DEFAULT 0,
    total_sin_iva     NUMERIC(12,2) NOT NULL DEFAULT 0,
    total_con_iva     NUMERIC(12,2) NOT NULL DEFAULT 0,
    orden             INTEGER NOT NULL DEFAULT 0,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_precosteo_items_ref ON precosteo_items(referencia_id);


-- ─────────────────────────────────────────────────────────────────────
-- ORDEN DE CORTE
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


CREATE TABLE IF NOT EXISTS ordenes_corte (
    id                       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    consecutivo              TEXT UNIQUE NOT NULL,
    referencia_id            UUID NOT NULL REFERENCES referencias_precosteo(id) ON DELETE RESTRICT,
    tono                     TEXT,
    largo_trazo              NUMERIC(8,2) NOT NULL,
    prendas_por_trazo        INTEGER NOT NULL,
    curva_trazo              JSONB NOT NULL DEFAULT '{}',
    num_capas                INTEGER NOT NULL,
    prendas_estimadas        INTEGER,
    metros_consumidos        NUMERIC(10,2),
    rendimiento_teorico      NUMERIC(8,4),
    consumo_real_cortador    NUMERIC(10,2),
    diferencia_pct           NUMERIC(6,2),
    merma_tipo               TEXT,
    merma_valor              NUMERIC(10,2),
    indicaciones             TEXT,
    responsable              TEXT,
    fecha_limite             DATE,
    estado                   TEXT NOT NULL DEFAULT 'borrador' CHECK (estado IN ('borrador','autorizada','en_proceso','cortada')),
    autorizada_por           TEXT,
    fecha_autorizacion       TIMESTAMPTZ,
    fecha_cierre             TIMESTAMPTZ,
    cerrada_por              TEXT,
    confeccionista_id        UUID REFERENCES confeccionistas(id) ON DELETE SET NULL,
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
-- REMISIONES A CONFECCIONISTA
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS remisiones (
    id                 UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    consecutivo        TEXT UNIQUE NOT NULL,
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


-- ─────────────────────────────────────────────────────────────────────
-- INSUMOS
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS insumos (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    codigo              TEXT UNIQUE,
    nombre              TEXT NOT NULL,
    categoria           TEXT,
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
    consecutivo        TEXT UNIQUE NOT NULL,
    destino_tipo       TEXT NOT NULL CHECK (destino_tipo IN ('confeccionista','terminacion')),
    destino_id         UUID,
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
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS puede_autorizar_precosteo BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS puede_autorizar_corte     BOOLEAN NOT NULL DEFAULT FALSE;


-- ═══════════════════════════════════════════════════════════════════════
-- Fin del schema.
-- ═══════════════════════════════════════════════════════════════════════
