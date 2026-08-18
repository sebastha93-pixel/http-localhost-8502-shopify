-- ═══════════════════════════════════════════════════════════════════════════
-- PORTAL DE LAVANDERÍA — el dato entra por un enlace, no leyendo un chat
-- ═══════════════════════════════════════════════════════════════════════════
--
-- LA PREGUNTA ERA OTRA (2026-08-18): "¿cómo traemos la información del grupo de
-- WhatsApp para que actualice el estado de los lotes y traiga la remisión de
-- lavandería?". La respuesta corta es que el grupo NO se puede leer:
--
--   · la Groups API de Meta exige Official Business Account (check verde)
--   · tope de 8 participantes
--   · solo funciona con grupos creados por la propia API — a uno nacido en el
--     WhatsApp normal no hay forma de entrar
--   · y el número que podría hacerlo alimenta las conversaciones del CRM:
--     meterle el tráfico de producción ensucia el análisis de ventas
--
-- Así que el dato entra por donde ya entra el de confección y terminación: un
-- enlace con token, que se manda por el mismo WhatsApp. La diferencia no es
-- solo técnica: un "ya salió" en el chat hay que interpretarlo; acá cada hecho
-- queda con lote, autor y hora.
--
-- Idempotente. Ya aplicada en Supabase por MCP.
-- ═══════════════════════════════════════════════════════════════════════════

ALTER TABLE hoja_ruta_lote
  ADD COLUMN IF NOT EXISTS token_publico_lavanderia uuid DEFAULT gen_random_uuid(),
  ADD COLUMN IF NOT EXISTS lav_recibido_at        timestamptz,
  ADD COLUMN IF NOT EXISTS lav_entregado_at       timestamptz,
  ADD COLUMN IF NOT EXISTS lav_cantidad_recibida  integer,
  ADD COLUMN IF NOT EXISTS lav_cantidad_entregada integer,
  ADD COLUMN IF NOT EXISTS nota_lavanderia        text,
  ADD COLUMN IF NOT EXISTS lav_fecha_estimada     date;

-- El DEFAULT solo aplica a filas nuevas: los lotes que ya existen necesitan
-- token o su enlace nunca funcionaría.
UPDATE hoja_ruta_lote
   SET token_publico_lavanderia = gen_random_uuid()
 WHERE token_publico_lavanderia IS NULL;

-- El enlace entra por el token: sin índice único es un escaneo por apertura, y
-- nada impediría dos lotes con el mismo token.
CREATE UNIQUE INDEX IF NOT EXISTS idx_hrl_token_lavanderia
    ON hoja_ruta_lote (token_publico_lavanderia);

COMMENT ON COLUMN hoja_ruta_lote.lav_entregado_at IS
    'Cuando la lavanderia dice que entrego el lote. NO avanza la etapa a terminacion_recibida: esa la firma terminacion desde su propio enlace. Que la lavanderia entregue y que terminacion reciba pueden estar separados por un dia y un camion.';

COMMENT ON COLUMN hoja_ruta_lote.lav_fecha_estimada IS
    'Fecha que promete la lavanderia. La usa el aviso de atraso.';

-- La lavandería ahora también deja notas en el timeline. Sin ampliar el CHECK,
-- cada insert con actor='lavanderia' falla y la nota se va al campo legacy que
-- la UI no muestra: se pierde en silencio.
ALTER TABLE notas_hoja_ruta
  DROP CONSTRAINT IF EXISTS notas_hoja_ruta_actor_check;

ALTER TABLE notas_hoja_ruta
  ADD CONSTRAINT notas_hoja_ruta_actor_check
  CHECK (actor = ANY (ARRAY['confeccionista'::text, 'terminacion'::text,
                            'lavanderia'::text, 'admin'::text]));

-- ── Comprobación ──────────────────────────────────────────────────────────
-- SELECT count(*) AS lotes,
--        count(token_publico_lavanderia) AS con_token,
--        count(lav_recibido_at)  AS recibidos,
--        count(lav_entregado_at) AS entregados
--   FROM hoja_ruta_lote;
