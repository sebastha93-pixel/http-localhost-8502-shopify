-- Migración: distinguir tipo de remisión (confección | terminación)
-- Ejecutar UNA vez en Supabase SQL editor.

ALTER TABLE remisiones
  ADD COLUMN IF NOT EXISTS tipo TEXT NOT NULL DEFAULT 'confeccion'
    CHECK (tipo IN ('confeccion','terminacion'));

CREATE INDEX IF NOT EXISTS idx_remisiones_tipo ON remisiones(tipo);
