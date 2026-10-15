-- ═══════════════════════════════════════════════════════════════════════════
-- COLOR POR LÍNEA DE PRECOSTEO (telas)
-- ═══════════════════════════════════════════════════════════════════════════
--
-- POR QUÉ. Una prenda lleva varias telas de MATERIA PRIMA —tela principal,
-- forro de bolsillo y, a veces, una tela complementaria— y cada una puede ir en
-- un COLOR distinto. Antes el precosteo solo guardaba un color de cabecera (el
-- de la prenda), así que el forro y la complementaria llegaban a la orden de
-- corte sin color. Esta columna deja que cada línea de tela lleve su propio
-- color, que la orden de corte arrastra como dato informativo para el cortador.
--
-- Nullable: solo las líneas de MATERIA PRIMA la usan; procesos e insumos la
-- dejan vacía. Idempotente. Se aplica en Supabase por MCP.
-- ═══════════════════════════════════════════════════════════════════════════

ALTER TABLE precosteo_items ADD COLUMN IF NOT EXISTS color text;
