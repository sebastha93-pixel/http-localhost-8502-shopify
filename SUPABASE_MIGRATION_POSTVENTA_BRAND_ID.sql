-- ═══════════════════════════════════════════════════════════════════
-- MALE POSTVENTA IA — Multi-tenant: columna brand_id
-- Aplicar en Supabase SQL Editor DESPUÉS de SUPABASE_MIGRATION_POSTVENTA.sql
-- Idempotente (ADD COLUMN IF NOT EXISTS). Default 'male' → los datos
-- existentes quedan etiquetados como MALE automáticamente.
-- ═══════════════════════════════════════════════════════════════════

alter table postventa_cases    add column if not exists brand_id text not null default 'male';
alter table postventa_items    add column if not exists brand_id text not null default 'male';
alter table postventa_evidence add column if not exists brand_id text not null default 'male';
alter table postventa_timeline add column if not exists brand_id text not null default 'male';
alter table postventa_fiscal   add column if not exists brand_id text not null default 'male';

-- Índice para el consecutivo por marca (cuenta casos de la marca en el año)
-- y para filtrar la bandeja por tenant.
create index if not exists idx_postventa_cases_brand
  on postventa_cases(brand_id, created_at desc);
create index if not exists idx_postventa_items_brand    on postventa_items(brand_id);
create index if not exists idx_postventa_evidence_brand on postventa_evidence(brand_id);
create index if not exists idx_postventa_timeline_brand on postventa_timeline(brand_id);
create index if not exists idx_postventa_fiscal_brand   on postventa_fiscal(brand_id);
