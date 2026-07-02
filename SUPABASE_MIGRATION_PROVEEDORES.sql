-- Migración: separar tipos de proveedores (confección / terminación) +
-- token público separado para la vista de terminación.
-- Ejecutar UNA vez en Supabase SQL editor.

-- 1) Tipo de proveedor en confeccionistas.
--    'confeccion'  → cose la prenda
--    'terminacion' → hace la etapa final (planchado, empaque, etiqueta)
--    Existentes quedan como 'confeccion' por defecto.
ALTER TABLE confeccionistas
  ADD COLUMN IF NOT EXISTS tipo TEXT NOT NULL DEFAULT 'confeccion'
    CHECK (tipo IN ('confeccion','terminacion'));

CREATE INDEX IF NOT EXISTS idx_confeccionistas_tipo
  ON confeccionistas(tipo, activo);

-- 2) Token público separado para la vista de terminación del lote.
ALTER TABLE hoja_ruta_lote
  ADD COLUMN IF NOT EXISTS token_publico_terminacion UUID UNIQUE
    DEFAULT uuid_generate_v4();

CREATE INDEX IF NOT EXISTS idx_ruta_token_terminacion
  ON hoja_ruta_lote(token_publico_terminacion);
