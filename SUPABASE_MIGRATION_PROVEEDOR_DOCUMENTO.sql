-- Migración: documento de identidad (cédula/NIT) del proveedor.
-- El cruce del costeo real con Siigo ancla los Documentos Soporte al
-- proveedor por su identificación — no solo por la REF digitada.
-- Ejecutar UNA vez en Supabase SQL Editor.

ALTER TABLE confeccionistas
  ADD COLUMN IF NOT EXISTS documento TEXT;

COMMENT ON COLUMN confeccionistas.documento IS
  'Cédula o NIT (como está registrado en Siigo) — ancla del cruce de costeo';
