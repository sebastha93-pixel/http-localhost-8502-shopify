-- Lotes archivados + huella de la remisión que llegó por WhatsApp.
--
-- 1) ARCHIVAR (Sebastián, 2026-10-30, "Archivar + limpiar viejos"): 30 lotes
--    llevaban 30-80 días "en proceso" sin que nadie los moviera en el OS
--    —la ropa ya estaba vendida, el lote solo no se cerró—. Eso tapaba los
--    estancados de verdad en el tablero, el resumen diario y el cierre de
--    bodega. Archivar NO borra nada ni cambia la etapa: el lote sale de las
--    listas de trabajo y queda en "Cerrados" con quién, cuándo y por qué.
--    Se puede desarchivar.
--
-- 2) remision_wa_message_id: el id del mensaje de WhatsApp cuya foto se
--    adjuntó como remisión. Meta reintenta el webhook; sin esta huella el
--    reintento llegaba cuando el lote ya no estaba pendiente y, si el
--    proveedor tenía OTRO lote esperando, se le pegaba la misma foto a ese.

alter table public.hoja_ruta_lote
  add column if not exists archivado_at      timestamptz,
  add column if not exists archivado_por     text,
  add column if not exists archivado_motivo  text,
  add column if not exists remision_wa_message_id text;

create index if not exists hoja_ruta_lote_remision_wa_idx
  on public.hoja_ruta_lote (remision_wa_message_id)
  where remision_wa_message_id is not null;

create index if not exists hoja_ruta_lote_activos_idx
  on public.hoja_ruta_lote (etapa)
  where archivado_at is null;
