-- ═══════════════════════════════════════════════════════════════════
-- MALE POSTVENTA IA — Cambio en tienda física (omnicanal)
-- Aplicar en Supabase SQL Editor. Idempotente.
-- ═══════════════════════════════════════════════════════════════════

-- Punto de venta donde se atiende el cambio. NULL = caso online.
alter table postventa_cases
  add column if not exists tienda text;

-- Forma de pago con la que la clienta cubrió el excedente en la tienda.
alter table postventa_cases
  add column if not exists pago_excedente_id integer;

create index if not exists idx_postventa_cases_tienda
  on postventa_cases(brand_id, tienda);
