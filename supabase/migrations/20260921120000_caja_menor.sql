-- ═══════════════════════════════════════════════════════════════════════════
-- CAJA MENOR — fondo fijo con soporte fotográfico por gasto
-- ═══════════════════════════════════════════════════════════════════════════
--
-- Modelo de fondo fijo (petty cash), el que se usa en la práctica:
--   · La caja tiene una BASE (el efectivo con que debe quedar llena).
--   · Cada GASTO descuenta del efectivo disponible y EXIGE descripción y foto
--     del soporte (recibo). Sin foto no hay gasto: es la trazabilidad.
--   · saldo_disponible = base − Σ(gastos abiertos, sin anular).
--   · Al REPONER, se suma lo gastado desde la última reposición, se cierra ese
--     periodo (los gastos quedan `periodo_cerrado`) y el saldo vuelve a la base.
--
-- Nace multi-caja aunque hoy la UI use una sola: cada movimiento cuelga de una
-- `caja_id`, así que abrir una segunda caja (una tienda, otra área) no pide
-- migración. Idempotente. Se aplica en Supabase por MCP.
-- ═══════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS caja_menor (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  nombre                text NOT NULL DEFAULT 'Caja menor',
  base                  numeric(14,2) NOT NULL DEFAULT 0,
  activa                boolean NOT NULL DEFAULT true,
  base_actualizada_por  text,
  base_actualizada_at   timestamptz,
  creada_at             timestamptz NOT NULL DEFAULT now(),
  actualizada_at        timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS caja_menor_movimiento (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  caja_id          uuid NOT NULL REFERENCES caja_menor(id) ON DELETE CASCADE,
  -- 'gasto'    → salida de efectivo (exige descripción + foto)
  -- 'reembolso'→ reposición del fondo: cierra los gastos del periodo
  tipo             text NOT NULL CHECK (tipo IN ('gasto', 'reembolso')),
  monto            numeric(14,2) NOT NULL CHECK (monto >= 0),
  descripcion      text NOT NULL DEFAULT '',
  categoria        text,
  foto_url         text,
  fecha            date NOT NULL DEFAULT current_date,
  -- Un gasto queda cerrado cuando una reposición lo salda. Los gastos abiertos
  -- (false) son los que componen el saldo disponible de hoy.
  periodo_cerrado  boolean NOT NULL DEFAULT false,
  reembolso_id     uuid REFERENCES caja_menor_movimiento(id) ON DELETE SET NULL,
  -- Anular = corregir un gasto mal cargado sin borrar el rastro. No suma al saldo.
  anulado          boolean NOT NULL DEFAULT false,
  anulado_por      text,
  anulado_at       timestamptz,
  motivo_anulacion text,
  usuario_id       text,
  usuario_nombre   text,
  creado_at        timestamptz NOT NULL DEFAULT now()
);

-- El saldo se calcula sobre los gastos ABIERTOS y sin anular de la caja: ese es
-- el filtro caliente, va indexado.
CREATE INDEX IF NOT EXISTS idx_caja_menor_mov_abiertos
  ON caja_menor_movimiento (caja_id, periodo_cerrado, anulado);

CREATE INDEX IF NOT EXISTS idx_caja_menor_mov_fecha
  ON caja_menor_movimiento (caja_id, fecha DESC);

CREATE INDEX IF NOT EXISTS idx_caja_menor_mov_reembolso
  ON caja_menor_movimiento (reembolso_id);

-- RLS encendido sin políticas, igual que `usuarios`: el backend usa la
-- service_role (que salta RLS) para TODO acceso a la caja, así que el anon key
-- —si alguna vez se expone— no puede leer plata ni recibos. Sin esto, PostgREST
-- deja la tabla del schema public abierta al anon por defecto.
ALTER TABLE caja_menor            ENABLE ROW LEVEL SECURITY;
ALTER TABLE caja_menor_movimiento ENABLE ROW LEVEL SECURITY;
