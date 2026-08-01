-- ═══════════════════════════════════════════════════════════════════════════
-- SALUD LOGÍSTICA: histórico de chequeos del tablero
-- ═══════════════════════════════════════════════════════════════════════════
--
-- POR QUÉ (2026-08-01): el tablero logístico falló cuatro veces en un día y
-- ninguna dio error — se veía normal con datos falsos. Se detectaron contando
-- pedidos a mano. Esta tabla guarda cada chequeo automático para dos cosas:
--
--   1. Comparar el total de ahora contra el del chequeo anterior. Una caída
--      brusca es el síntoma de "algo vació el caché" (pasó: 1.208 → 3).
--   2. Tener historia. "¿desde cuándo está mal?" hoy no se puede responder.
--
-- Idempotente. Correr en el SQL Editor de Supabase.
-- ═══════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS logistica_salud (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    creado_en  timestamptz NOT NULL DEFAULT now(),
    -- verde | amarillo | rojo
    semaforo   text NOT NULL,
    -- Total de pedidos en el tablero en ese momento. Es la serie que permite
    -- detectar la caída brusca, así que va en columna propia y no solo en el JSON.
    total      integer NOT NULL DEFAULT 0,
    hallazgos  jsonb NOT NULL DEFAULT '[]'::jsonb,
    medidas    jsonb NOT NULL DEFAULT '{}'::jsonb
);

-- El chequeo consulta SIEMPRE "el último": ese índice es el que se usa.
CREATE INDEX IF NOT EXISTS logistica_salud_reciente_idx
    ON logistica_salud (creado_en DESC);
-- Para poder listar solo los problemas sin escanear todo el histórico.
CREATE INDEX IF NOT EXISTS logistica_salud_semaforo_idx
    ON logistica_salud (semaforo, creado_en DESC);

-- ── Comprobación ──────────────────────────────────────────────────────────
-- SELECT creado_en, semaforo, total, jsonb_array_length(hallazgos) AS hallazgos
--   FROM logistica_salud ORDER BY creado_en DESC LIMIT 20;
