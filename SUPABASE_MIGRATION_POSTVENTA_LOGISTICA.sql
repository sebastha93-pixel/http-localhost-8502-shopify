-- ═══════════════════════════════════════════════════════════════════
-- MALE POSTVENTA IA — Logística inversa (guía de devolución y despacho)
-- Aplicar en Supabase SQL Editor. Idempotente.
-- ═══════════════════════════════════════════════════════════════════

create table if not exists postventa_logistica (
  id                    uuid primary key default gen_random_uuid(),
  brand_id              text not null default 'male',
  case_id               uuid not null references postventa_cases(id) on delete cascade,
  -- Pata de RETORNO: la prenda que devuelve la clienta
  guia_retorno          text,
  transportadora_retorno text,
  fecha_envio_cliente   timestamptz,
  fecha_recibido_bodega timestamptz,
  estado_retorno        text not null default 'pendiente',
  -- Pata de DESPACHO: la prenda de reemplazo
  guia_despacho         text,
  transportadora_despacho text,
  fecha_despacho        timestamptz,
  -- Costos y notas
  costo_retorno         numeric(12,2),
  costo_despacho        numeric(12,2),
  paga_transporte       text,          -- 'marca' | 'cliente'
  notas                 text,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now()
);

create index if not exists idx_postventa_logistica_case on postventa_logistica(case_id);
create index if not exists idx_postventa_logistica_brand on postventa_logistica(brand_id);
-- Buscar un caso por el nº de guía que reporta la transportadora.
create index if not exists idx_postventa_logistica_guia on postventa_logistica(guia_retorno);
