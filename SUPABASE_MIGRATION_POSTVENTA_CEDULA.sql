-- ═══════════════════════════════════════════════════════════════════
-- MALE POSTVENTA IA — Cédula de la clienta
-- Con ella se buscan sus compras en Siigo (online y de tienda) sin
-- pedirle el nº de pedido. Aplicar en Supabase SQL Editor. Idempotente.
-- ═══════════════════════════════════════════════════════════════════

alter table postventa_cases
  add column if not exists customer_cedula text;

-- Para ver el historial de casos de una misma clienta.
create index if not exists idx_postventa_cases_cedula
  on postventa_cases(brand_id, customer_cedula);
