-- FIX: la tabla `insumos` quedó sin la columna cantidad_disponible
-- (se creó antes con otra estructura y CREATE TABLE IF NOT EXISTS no la
-- alteró). Este script agrega las columnas faltantes sin borrar datos.
-- Ejecutar UNA vez en Supabase SQL Editor.

ALTER TABLE insumos
  ADD COLUMN IF NOT EXISTS cantidad_disponible NUMERIC NOT NULL DEFAULT 0;

ALTER TABLE insumos
  ADD COLUMN IF NOT EXISTS unidad TEXT NOT NULL DEFAULT 'und';

ALTER TABLE insumos
  ADD COLUMN IF NOT EXISTS categoria TEXT NOT NULL DEFAULT 'INSUMO CONFECCION';

ALTER TABLE insumos
  ADD COLUMN IF NOT EXISTS codigo TEXT UNIQUE;

ALTER TABLE insumos
  ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

-- Verificación: debe listar todas las columnas esperadas
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'insumos'
ORDER BY ordinal_position;
