-- Marca cuándo un proveedor RESPONDIÓ por WhatsApp (escribió a la línea).
-- Lo setea el webhook de mensajes entrantes al hacer match del número que
-- escribe con el teléfono de un confeccionista. Así se ve en Proveedores
-- quién ya contestó, sin entrar a Meta ni al teléfono.
ALTER TABLE confeccionistas
  ADD COLUMN IF NOT EXISTS contacto_respondio_at timestamptz;
