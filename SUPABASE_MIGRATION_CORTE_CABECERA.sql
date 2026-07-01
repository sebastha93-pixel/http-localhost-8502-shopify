-- Migración: cabecera nueva orden de corte
-- Ejecutar UNA vez en Supabase SQL editor.

ALTER TABLE ordenes_corte
  ADD COLUMN IF NOT EXISTS promedio_tecnico     NUMERIC(8,4),
  ADD COLUMN IF NOT EXISTS cantidad_programada  INTEGER,
  ADD COLUMN IF NOT EXISTS fecha_envio          DATE,
  ADD COLUMN IF NOT EXISTS trazos_url           TEXT,
  ADD COLUMN IF NOT EXISTS destinatarios_correo TEXT[] DEFAULT '{}';

-- Bucket para adjuntos de trazos (crear una vez en Storage → New bucket "produccion-trazos" pública read)
