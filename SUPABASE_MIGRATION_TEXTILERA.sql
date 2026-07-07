-- Migración: permitir el tipo 'textilera' en proveedores.
-- Las textileras (proveedores de tela) se registran en el mismo directorio
-- con su NIT, para cruzar el costo de la tela con las facturas de compra
-- de Siigo (igual que confeccionistas con documento).
-- Ejecutar UNA vez en Supabase SQL Editor.

ALTER TABLE confeccionistas DROP CONSTRAINT IF EXISTS confeccionistas_tipo_check;
ALTER TABLE confeccionistas ADD CONSTRAINT confeccionistas_tipo_check
  CHECK (tipo IN ('confeccion','terminacion','lavanderia','otros','textilera'));
