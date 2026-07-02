-- Migración: notas del confeccionista y del proveedor de terminación
-- Ejecutar UNA vez en Supabase SQL editor.

ALTER TABLE hoja_ruta_lote
  ADD COLUMN IF NOT EXISTS nota_confeccionista TEXT,
  ADD COLUMN IF NOT EXISTS nota_terminacion   TEXT;
