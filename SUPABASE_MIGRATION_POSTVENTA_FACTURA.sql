-- ═══════════════════════════════════════════════════════════════════
-- MALE POSTVENTA IA — Factura exacta de la compra que se cambia
--
-- POR QUÉ: hasta ahora la factura original se DEDUCÍA del nº de pedido
-- Shopify, buscando "Orden Nº: <pedido>" entre las facturas de venta
-- online. Eso NUNCA puede funcionar para una compra hecha en tienda:
-- las facturas FV-6/11/12 no llevan ese texto ni el document_id de la
-- venta online. Resultado: el motor fiscal no encontraba la factura y
-- no se podía emitir la nota crédito de un cambio presencial.
--
-- Como la asesora YA elige la compra exacta al buscar por cédula, se
-- guarda el id de esa factura y se trae directo de Siigo.
--
-- Aplicar en Supabase SQL Editor. Idempotente.
-- ═══════════════════════════════════════════════════════════════════

alter table postventa_cases
  add column if not exists siigo_invoice_id text;

-- Para no abrir dos casos sobre la misma factura sin darse cuenta.
create index if not exists idx_postventa_cases_siigo_invoice
  on postventa_cases(brand_id, siigo_invoice_id);
