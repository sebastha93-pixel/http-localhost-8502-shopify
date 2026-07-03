-- Migración: lavanderías como tercer tipo de proveedor + lavandería del lote.
-- Ejecutar UNA vez en Supabase SQL Editor.

-- 1) Permitir tipo 'lavanderia' en proveedores
ALTER TABLE confeccionistas DROP CONSTRAINT IF EXISTS confeccionistas_tipo_check;
ALTER TABLE confeccionistas
  ADD CONSTRAINT confeccionistas_tipo_check
  CHECK (tipo IN ('confeccion','terminacion','lavanderia'));

-- 2) En qué lavandería está el lote (se marca al salir de confección)
ALTER TABLE hoja_ruta_lote
  ADD COLUMN IF NOT EXISTS lavanderia_id UUID REFERENCES confeccionistas(id);

CREATE INDEX IF NOT EXISTS idx_ruta_lavanderia ON hoja_ruta_lote(lavanderia_id);
