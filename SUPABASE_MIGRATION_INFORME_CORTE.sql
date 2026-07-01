-- Migración: informe del cortador (cierre de la orden)
-- Ejecutar UNA vez en Supabase SQL editor.

ALTER TABLE ordenes_corte
  ADD COLUMN IF NOT EXISTS referencia_lote     TEXT,
  ADD COLUMN IF NOT EXISTS capas_real          INTEGER,
  ADD COLUMN IF NOT EXISTS promedio_real       NUMERIC(8,4),
  ADD COLUMN IF NOT EXISTS unidades_cortadas   JSONB DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS retazos_cantidad    INTEGER,
  ADD COLUMN IF NOT EXISTS fecha_entrega       DATE,
  ADD COLUMN IF NOT EXISTS precio_corte        NUMERIC(12,2);
