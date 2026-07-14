-- Nombre original del archivo de trazos/molde subido por el diseñador,
-- para mostrárselo al cortador en "Mis despachos".
ALTER TABLE ordenes_corte ADD COLUMN IF NOT EXISTS trazos_filename text;
