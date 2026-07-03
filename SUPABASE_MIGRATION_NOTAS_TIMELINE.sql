-- Migración: timeline de notas por hoja de ruta.
-- Reemplaza los TEXT únicos `nota_confeccionista` / `nota_terminacion`
-- (que se sobrescribían) por una tabla con histórico completo.
-- Los campos viejos siguen ahí para compat; no se borran.
-- Ejecutar UNA vez en Supabase SQL editor.

CREATE TABLE IF NOT EXISTS notas_hoja_ruta (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    ruta_id     UUID NOT NULL REFERENCES hoja_ruta_lote(id) ON DELETE CASCADE,
    actor       TEXT NOT NULL CHECK (actor IN ('confeccionista','terminacion','admin')),
    autor       TEXT,   -- email o identificador del emisor
    mensaje     TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_notas_ruta_id      ON notas_hoja_ruta(ruta_id);
CREATE INDEX IF NOT EXISTS idx_notas_created_at   ON notas_hoja_ruta(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_notas_actor        ON notas_hoja_ruta(actor);

-- Backfill: si hay notas antiguas en hoja_ruta_lote, cárgalas como una primera nota.
INSERT INTO notas_hoja_ruta (ruta_id, actor, mensaje)
  SELECT id, 'confeccionista', nota_confeccionista
  FROM hoja_ruta_lote
  WHERE nota_confeccionista IS NOT NULL AND nota_confeccionista <> ''
  ON CONFLICT DO NOTHING;

INSERT INTO notas_hoja_ruta (ruta_id, actor, mensaje)
  SELECT id, 'terminacion', nota_terminacion
  FROM hoja_ruta_lote
  WHERE nota_terminacion IS NOT NULL AND nota_terminacion <> ''
  ON CONFLICT DO NOTHING;
