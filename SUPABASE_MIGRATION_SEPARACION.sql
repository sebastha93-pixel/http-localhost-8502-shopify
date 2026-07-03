-- Migración: checklist de separación de insumos por lote.
-- Guarda por tipo (confeccion/terminacion): items marcados, responsable
-- (BAY / HENRY HURTADO) y el "todo OK" final con fecha.
-- Ejecutar UNA vez en Supabase SQL Editor.

ALTER TABLE hoja_ruta_lote
  ADD COLUMN IF NOT EXISTS separacion_insumos JSONB NOT NULL DEFAULT '{}';
