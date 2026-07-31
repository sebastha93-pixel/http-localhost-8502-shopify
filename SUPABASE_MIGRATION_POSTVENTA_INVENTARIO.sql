-- ═══════════════════════════════════════════════════════════════════
-- MALE POSTVENTA IA — Inventario de tienda en NUESTRA base
--
-- POR QUÉ: la búsqueda de la prenda de reemplazo le pedía a Siigo el
-- catálogo completo — hasta 80 páginas a ~1 petición por segundo. Y el
-- backend corre con 4 workers de uvicorn, cada uno con su propio caché
-- en memoria: la búsqueda caía en un worker con caché caliente
-- (instantánea) y la verificación en otro con caché frío, que no
-- alcanzaba a recorrer el catálogo y respondía "no se pudo leer el
-- inventario" sobre una prenda que sí existía.
--
-- Con la tabla, los 4 workers leen lo mismo y la respuesta es inmediata.
-- Siigo se consulta una vez cada refresco, no en cada clic.
--
-- Aplicar en Supabase SQL Editor. Idempotente.
-- ═══════════════════════════════════════════════════════════════════

create table if not exists postventa_inventario (
  brand_id        text not null,
  code            text not null,
  referencia      text,
  talla           text,
  nombre          text,
  bodega          text not null,
  cantidad        numeric(12,2) not null default 0,
  actualizado_en  timestamptz not null default now(),
  primary key (brand_id, code, bodega)
);

-- Búsqueda por punto de venta (lo que hace la asesora todo el día).
create index if not exists idx_postventa_inv_bodega
  on postventa_inventario(brand_id, bodega);

-- Verificación de una referencia puntual antes de facturar.
create index if not exists idx_postventa_inv_code
  on postventa_inventario(brand_id, code);
