-- ═══════════════════════════════════════════════════════════════════════════
-- CUADRE DE BODEGA POR PROCESO — conteo por talla en cada entrega + estado
-- ═══════════════════════════════════════════════════════════════════════════
--
-- POR QUÉ. Las prendas se pierden en confección y hoy solo se descubre al final
-- (cierre de terminación → bodega). Esta tabla guarda, por lote y por paso, el
-- CONTEO POR TALLA de lo que entregó/recibió ese paso, para cruzarlo contra lo
-- cortado y alertar el faltante EN el paso donde ocurrió.
--
-- GATE ANTI-ALERTAS-FALSAS. Todo conteo entra `por_confirmar` (venga de OCR de la
-- foto de la remisión o tecleado a mano). Solo al confirmarlo se cruza en firme y,
-- si falta, se dispara la campanita. Un faltante se puede `justificado` (dañadas,
-- 2das, re-conteo) para cerrar el eslabón.
--
-- Fase 1 solo escribe paso='confeccion'. El resto de pasos quedan modelados para
-- las fases siguientes (cadena completa corte→confección→lavandería→terminación→
-- bodega). unidades es jsonb por talla { "T12": 10, "T14": 8 }, igual que
-- ordenes_corte.unidades_cortadas. referencia_id es para el futuro cuadre por
-- referencia (hoy NULL = cuadre a nivel de orden de corte).
--
-- Idempotente. Se aplica en Supabase por MCP. GRANT en la MISMA migración
-- (regla 30-oct-2026): sin GRANT, service_role da 42501 aunque el código esté bien.
-- ═══════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS cuadre_lote_proceso (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  orden_corte_id     uuid NOT NULL REFERENCES ordenes_corte(id) ON DELETE CASCADE,
  -- NULL = cuadre a nivel de orden de corte (suma de referencias). Para el futuro
  -- cuadre por referencia se llenará con referencias_precosteo(id).
  referencia_id      uuid,
  paso               text NOT NULL CHECK (paso IN ('confeccion','lavanderia','terminacion','bodega')),
  -- Conteo por talla: { "T12": 10, "T14": 8, ... }. El total se calcula en la app.
  unidades           jsonb NOT NULL DEFAULT '{}'::jsonb,
  estado             text NOT NULL DEFAULT 'por_confirmar'
                       CHECK (estado IN ('por_confirmar','confirmado','justificado')),
  fuente             text CHECK (fuente IN ('ocr','manual')),
  remision_foto_url  text,
  confirmado_por     text,
  confirmado_at      timestamptz,
  justificado_por    text,
  justificado_motivo text,
  justificado_at     timestamptz,
  creado_por         text,
  creado_at          timestamptz NOT NULL DEFAULT now(),
  actualizado_at     timestamptz NOT NULL DEFAULT now()
);

-- Un solo cuadre por (lote, paso, referencia). COALESCE para que el caso
-- referencia_id NULL (cuadre a nivel de orden) también sea único — un UNIQUE
-- normal trata los NULL como distintos y dejaría colar duplicados.
CREATE UNIQUE INDEX IF NOT EXISTS idx_cuadre_lote_proceso_unico
  ON cuadre_lote_proceso (
    orden_corte_id, paso,
    COALESCE(referencia_id, '00000000-0000-0000-0000-000000000000'::uuid)
  );

CREATE INDEX IF NOT EXISTS idx_cuadre_lote_proceso_oc
  ON cuadre_lote_proceso (orden_corte_id, paso);
CREATE INDEX IF NOT EXISTS idx_cuadre_lote_proceso_estado
  ON cuadre_lote_proceso (estado);

-- RLS encendido sin políticas: el backend entra con service_role (salta RLS);
-- el anon key —si se expone— no lee cantidades de producción.
ALTER TABLE cuadre_lote_proceso ENABLE ROW LEVEL SECURITY;

-- GRANT mínimo al rol del backend (regla 30-oct-2026). gen_random_uuid → sin secuencia.
GRANT SELECT, INSERT, UPDATE, DELETE ON public.cuadre_lote_proceso TO service_role;

-- ───────────────────────────────────────────────────────────────────────────
-- Versionar las columnas de conteo que ya existían en prod (aplicadas a mano,
-- sin migración). Tipos tomados de la base real: todas integer salvo *_origen
-- que es text. IF NOT EXISTS = no-op donde ya están (prod); crea en entornos
-- nuevos con el tipo correcto.
-- ───────────────────────────────────────────────────────────────────────────
ALTER TABLE hoja_ruta_lote ADD COLUMN IF NOT EXISTS lav_cantidad_remision        integer;
ALTER TABLE hoja_ruta_lote ADD COLUMN IF NOT EXISTS lav_cantidad_remision_origen text;
ALTER TABLE hoja_ruta_lote ADD COLUMN IF NOT EXISTS term_cantidad_recibida       integer;
ALTER TABLE hoja_ruta_lote ADD COLUMN IF NOT EXISTS term_cantidad_terminada      integer;
