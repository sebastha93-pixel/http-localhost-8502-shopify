-- Marca cuándo se le envió al proveedor el mensaje de bienvenida
-- (plantilla contacto_proveedores). Sirve para NO reenviarlo: el envío masivo
-- solo va a los que no tienen esta fecha.
ALTER TABLE confeccionistas
  ADD COLUMN IF NOT EXISTS contacto_bienvenida_at timestamptz;
