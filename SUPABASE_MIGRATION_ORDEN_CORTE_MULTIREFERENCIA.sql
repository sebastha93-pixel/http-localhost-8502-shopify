-- ═══════════════════════════════════════════════════════════════════════
-- Orden de corte con VARIAS referencias (un tendido, varias referencias).
-- ═══════════════════════════════════════════════════════════════════════
-- El tendido (rollos, tela, capas, consumo real, fechas) sigue en
-- `ordenes_corte`. Cada referencia del tendido pasa a una fila de esta tabla
-- hija, con SU propia curva de tallas, precio de corte, cantidad programada,
-- promedio técnico y unidades cortadas (cierre).
--
-- Es idempotente: se puede correr varias veces sin duplicar nada.
-- ═══════════════════════════════════════════════════════════════════════

create table if not exists orden_corte_referencias (
  id                  uuid primary key default gen_random_uuid(),
  orden_corte_id      uuid not null references ordenes_corte(id) on delete cascade,
  referencia_id       uuid not null references referencias_precosteo(id),
  curva_trazo         jsonb not null default '{}'::jsonb,
  unidades_cortadas   jsonb,
  precio_corte        numeric,
  cantidad_programada integer,
  promedio_tecnico    numeric,
  orden               integer not null default 0,
  created_at          timestamptz not null default now()
);

create index if not exists idx_ocr_orden on orden_corte_referencias(orden_corte_id);
create index if not exists idx_ocr_ref   on orden_corte_referencias(referencia_id);

-- Backfill: cada orden que ya existe pasa a tener UNA referencia (la que tenía),
-- copiando su curva, precio, cantidad, promedio y unidades cortadas.
insert into orden_corte_referencias
  (orden_corte_id, referencia_id, curva_trazo, unidades_cortadas,
   precio_corte, cantidad_programada, promedio_tecnico, orden)
select oc.id,
       oc.referencia_id,
       coalesce(oc.curva_trazo, '{}'::jsonb),
       oc.unidades_cortadas,
       oc.precio_corte,
       oc.cantidad_programada,
       oc.promedio_tecnico,
       0
from ordenes_corte oc
where oc.referencia_id is not null
  and not exists (
    select 1 from orden_corte_referencias r where r.orden_corte_id = oc.id
  );
