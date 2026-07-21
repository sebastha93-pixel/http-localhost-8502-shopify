-- ═══════════════════════════════════════════════════════════════════════
-- Impresión automática de TERMINACIÓN: stickers de barra (Honeywell) +
-- instrucciones de lavado (SAT), encolados al crear la remisión.
-- Idempotente.
-- ═══════════════════════════════════════════════════════════════════════

-- Cola genérica de trabajos de impresión (las remisiones PDF siguen usando
-- remisiones.impresa_at; esta tabla es para etiquetas térmicas y futuros docs).
create table if not exists impresion_trabajos (
  id             uuid primary key default gen_random_uuid(),
  tipo           text not null,     -- 'sticker_codigo' | 'instruccion_lavado'
  destino        text not null,     -- 'honeywell' | 'sat' | 'ricoh'
  formato        text not null default 'zpl',  -- 'zpl' | 'pdf'
  remision_id    uuid references remisiones(id) on delete cascade,
  orden_corte_id uuid,
  referencia_id  uuid,
  payload        jsonb not null default '{}'::jsonb,
  impresa_at     timestamptz,
  created_at     timestamptz not null default now()
);

create index if not exists idx_imp_trab_pendientes
  on impresion_trabajos(destino, created_at) where impresa_at is null;

-- Instrucciones de lavado POR referencia/tela (las imprime la SAT).
alter table referencias_precosteo
  add column if not exists instrucciones_lavado text;
