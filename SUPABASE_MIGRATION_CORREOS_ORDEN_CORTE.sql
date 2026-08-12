-- Un registro por INTENTO de envío del correo de la orden de corte.
--
-- Por qué una tabla y no columnas en ordenes_corte: el reenvío ya existe
-- (actualizar_indicaciones_corte remanda el correo cuando cambian las
-- indicaciones), así que columnas planas se pisarían en el segundo envío y
-- perderían la historia. El caso real que motivó esto —2607-0017 salió a
-- barreto.corte@hotmail.com en vez de johnj2397@hotmail.com— solo se entiende
-- viendo los dos intentos, el equivocado y la corrección.
--
-- estado: enviado | entregado | rebotado | spam | demorado | fallido
--         | suprimido | error_envio
--   error_envio = Resend rechazó la petición y nunca creó el correo.
-- motivo: autorizacion | reenvio_indicaciones | reenvio_manual
CREATE TABLE IF NOT EXISTS correos_orden_corte (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  orden_corte_id        uuid NOT NULL REFERENCES ordenes_corte(id) ON DELETE CASCADE,
  destinatarios         text[] NOT NULL DEFAULT '{}',
  asunto                text,
  motivo                text NOT NULL,
  resend_id             text,
  estado                text NOT NULL,
  error                 text,
  enviado_por           text,
  created_at            timestamptz NOT NULL DEFAULT now(),
  estado_actualizado_at timestamptz
);

CREATE INDEX IF NOT EXISTS idx_correos_oc_orden
  ON correos_orden_corte(orden_corte_id, created_at DESC);

-- Mismo blindaje que ordenes_corte y orden_corte_rollos: RLS activa y CERO
-- políticas. El backend entra con la service key, que salta la RLS; nadie más
-- toca la tabla. Sin esto la bitácora de correos (con direcciones de los
-- cortadores) quedaría legible con la llave anónima.
ALTER TABLE correos_orden_corte ENABLE ROW LEVEL SECURITY;
