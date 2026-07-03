-- Migración: informe del cortador por ESPIGAS.
-- espigas_metros: metros extendidos por espiga {"4": 1.2, "6-12": 2.4, ...}
-- retazos_metros: retazos medidos en METROS (antes era cantidad de unidades)
-- Ejecutar UNA vez en Supabase SQL Editor.

ALTER TABLE ordenes_corte
  ADD COLUMN IF NOT EXISTS espigas_metros JSONB,
  ADD COLUMN IF NOT EXISTS retazos_metros NUMERIC;
