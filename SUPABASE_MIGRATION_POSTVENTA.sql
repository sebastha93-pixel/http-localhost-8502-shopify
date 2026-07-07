-- ═══════════════════════════════════════════════════════════════════
-- MALE POSTVENTA IA — Migración base (Sub-proyecto #1: Postventa Core)
-- Aplicar en Supabase SQL Editor. Idempotente (IF NOT EXISTS).
-- ═══════════════════════════════════════════════════════════════════

create extension if not exists "pgcrypto";

-- 1. Casos ───────────────────────────────────────────────────────────
create table if not exists postventa_cases (
  id                  uuid primary key default gen_random_uuid(),
  case_number         text unique not null,
  shopify_order_id    text,
  shopify_order_name  text,
  customer_email      text,
  customer_phone      text,
  customer_name       text,
  status              text not null default 'creado',
  type                text not null,
  reason              text not null,
  subreason           text,
  priority            text not null default 'media',
  source              text not null default 'interno',
  assigned_to         uuid,
  notes_internas      text,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  closed_at           timestamptz
);
create index if not exists idx_postventa_cases_status on postventa_cases(status);
create index if not exists idx_postventa_cases_created on postventa_cases(created_at desc);

-- 2. Items ───────────────────────────────────────────────────────────
create table if not exists postventa_items (
  id                 uuid primary key default gen_random_uuid(),
  case_id            uuid not null references postventa_cases(id) on delete cascade,
  original_sku       text,
  original_variant   text,
  original_price     numeric(12,2),
  requested_sku      text,
  requested_variant  text,
  requested_price    numeric(12,2),
  price_difference   numeric(12,2),
  item_status        text not null default 'pendiente'
);
create index if not exists idx_postventa_items_case on postventa_items(case_id);

-- 3. Evidencias ──────────────────────────────────────────────────────
create table if not exists postventa_evidence (
  id           uuid primary key default gen_random_uuid(),
  case_id      uuid not null references postventa_cases(id) on delete cascade,
  file_url     text not null,
  file_type    text,
  uploaded_by  uuid,
  created_at   timestamptz not null default now()
);
create index if not exists idx_postventa_evidence_case on postventa_evidence(case_id);

-- 4. Timeline ────────────────────────────────────────────────────────
create table if not exists postventa_timeline (
  id           uuid primary key default gen_random_uuid(),
  case_id      uuid not null references postventa_cases(id) on delete cascade,
  event_type   text not null,
  description  text,
  created_by   text,            -- uuid del usuario o 'sistema'
  created_at   timestamptz not null default now()
);
create index if not exists idx_postventa_timeline_case on postventa_timeline(case_id, created_at);

-- 5. Fiscal (usado por el plan #2, se crea desde ya) ──────────────────
create table if not exists postventa_fiscal (
  id                     uuid primary key default gen_random_uuid(),
  case_id                uuid not null references postventa_cases(id) on delete cascade,
  doc_kind               text not null,     -- 'nota_credito' | 'factura'
  siigo_invoice_ref      text,
  siigo_document_id      text,
  siigo_document_number  text,
  amount                 numeric(12,2),
  status                 text not null default 'pendiente',
  error_detail           text,
  payload_snapshot       jsonb,
  created_at             timestamptz not null default now()
);
create index if not exists idx_postventa_fiscal_case on postventa_fiscal(case_id);
