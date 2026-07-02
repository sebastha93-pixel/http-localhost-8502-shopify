-- Migración: hoja de ruta del lote (confección → gap lavandería → terminación → despacho)
-- Ejecutar UNA vez en Supabase SQL editor.

CREATE TABLE IF NOT EXISTS hoja_ruta_lote (
    id                       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    token_publico            UUID UNIQUE NOT NULL DEFAULT uuid_generate_v4(),
    orden_corte_id           UUID NOT NULL UNIQUE REFERENCES ordenes_corte(id) ON DELETE CASCADE,
    remision_id              UUID REFERENCES remisiones(id) ON DELETE SET NULL,
    confeccionista_id        UUID NOT NULL REFERENCES confeccionistas(id) ON DELETE RESTRICT,
    terminacion_id           UUID REFERENCES confeccionistas(id) ON DELETE SET NULL,
    precio_confeccion        NUMERIC(12,2),
    precio_terminacion       NUMERIC(12,2),
    fecha_entrega_confeccion DATE,
    remision_lavanderia_url  TEXT,
    -- Estados: asignado, aceptado, en_confeccion, lavanderia,
    --          terminacion_recibida, terminacion_terminada, despachado
    etapa                    TEXT NOT NULL DEFAULT 'asignado',
    -- Timestamps por etapa (para calcular tiempos)
    asignado_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    aceptado_at              TIMESTAMPTZ,
    confeccion_iniciada_at   TIMESTAMPTZ,
    lavanderia_at            TIMESTAMPTZ,
    terminacion_recibida_at  TIMESTAMPTZ,
    terminacion_terminada_at TIMESTAMPTZ,
    despachado_at            TIMESTAMPTZ,
    notas                    TEXT,
    created_by               TEXT,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ruta_token       ON hoja_ruta_lote(token_publico);
CREATE INDEX IF NOT EXISTS idx_ruta_etapa       ON hoja_ruta_lote(etapa);
CREATE INDEX IF NOT EXISTS idx_ruta_conf        ON hoja_ruta_lote(confeccionista_id);
CREATE INDEX IF NOT EXISTS idx_ruta_orden_corte ON hoja_ruta_lote(orden_corte_id);
