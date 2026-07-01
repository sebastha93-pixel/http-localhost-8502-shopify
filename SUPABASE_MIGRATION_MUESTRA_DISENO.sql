-- Migración: precosteo muestra de diseño
-- Ejecutar UNA vez en Supabase SQL editor.

ALTER TABLE referencias_precosteo
  ADD COLUMN IF NOT EXISTS es_muestra_diseno BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_precosteo_muestra_diseno
  ON referencias_precosteo(es_muestra_diseno) WHERE es_muestra_diseno = true;
