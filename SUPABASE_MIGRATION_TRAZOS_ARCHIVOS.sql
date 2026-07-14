-- Trazos/moldes de la orden de corte que sube el diseñador (Optitex, PDF, imagen).
-- trazos_archivos: lista de hasta 10 archivos [{url, filename, path}].
-- trazos_filename: nombre del primer archivo (compat con la versión de 1 archivo).
ALTER TABLE ordenes_corte ADD COLUMN IF NOT EXISTS trazos_filename text;
ALTER TABLE ordenes_corte ADD COLUMN IF NOT EXISTS trazos_archivos jsonb DEFAULT '[]'::jsonb;
