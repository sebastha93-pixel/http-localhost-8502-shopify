-- ═══════════════════════════════════════════════════════════════════════════
-- PRECOSTEO — campo de descripción libre
-- ═══════════════════════════════════════════════════════════════════════════
--
-- Sebastián (2026-09-24): en los precosteos falta una descripción libre para
-- anotar el detalle de la referencia (lo que la foto y las líneas de costo no
-- dicen). Se guarda por referencia, editable por el diseñador mientras sea
-- borrador y por quien autoriza si ya está bloqueada — igual candado que la
-- composición/instrucciones_lavado.
--
-- Idempotente. Se aplica en Supabase por MCP.
-- ═══════════════════════════════════════════════════════════════════════════

ALTER TABLE referencias_precosteo
  ADD COLUMN IF NOT EXISTS descripcion text;
