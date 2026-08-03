-- ═══════════════════════════════════════════════════════════════════════════
-- HOJA DE RUTA: qué etapas NO lleva este lote
-- ═══════════════════════════════════════════════════════════════════════════
--
-- POR QUÉ (2026-08-03): la hoja de ruta era una secuencia FIJA
-- confección → lavandería → terminación → despacho, con lavandería SIEMPRE.
-- Pero hay prendas que no lavan por su base textil, y de las 19 referencias
-- autorizadas 6 ya lo declaraban: tienen el proceso Lavandería en VALOR 0
-- (las de base TECHNOVA y ATLAS). El dato estaba y la app lo ignoraba.
--
-- Consecuencia medida: un lote de esas referencias se quedaba parado en la etapa
-- `lavanderia` acumulando días por un proceso que nunca tuvo, y su costo cargaba
-- una lavandería inexistente.
--
-- REGLA (de Sebastián): proceso en 0 en el precosteo = la prenda no lo lleva.
-- Sin campo nuevo en el precosteo, sin tabla nueva — se usa lo que ya se digita.
--
-- Esta columna guarda la FOTO de esa decisión al crear la ruta. Se congela a
-- propósito: si mañana cambia el precosteo, el recorrido de un lote que ya
-- arrancó no puede cambiar por debajo. Mismo criterio que el precio de
-- confección, que también sale del precosteo firmado y queda fijo.
--
-- SIN DEFAULT a propósito:
--   NULL → nunca se calculó (rutas creadas antes de esta regla) → el backend lo
--          deduce del precosteo al leer, y NUNCA omite una etapa que ya tenga
--          timestamp, para no falsear el historial de un lote en curso.
--   []   → ya se calculó y no se omite nada.
-- Un default '[]' borraría esa diferencia y las rutas viejas nunca se
-- beneficiarían del arreglo.
--
-- Idempotente. Correr en el SQL Editor de Supabase.
-- ═══════════════════════════════════════════════════════════════════════════

ALTER TABLE hoja_ruta_lote
    ADD COLUMN IF NOT EXISTS etapas_omitidas jsonb;

COMMENT ON COLUMN hoja_ruta_lote.etapas_omitidas IS
    'Etapas que este lote NO recorre, congeladas al crear la ruta. Se derivan '
    'del precosteo: proceso en valor 0 = la prenda no lleva ese proceso. '
    'NULL = no calculado (ruta anterior a la regla), se deduce al leer.';

-- ── Comprobación ──────────────────────────────────────────────────────────
-- Referencias que declaran NO llevar lavandería (proceso en 0):
--   SELECT r.codigo_referencia, r.tela, i.valor_unitario
--     FROM precosteo_items i
--     JOIN referencias_precosteo r ON r.id = i.referencia_id
--    WHERE i.categoria ILIKE '%PROCESO%'
--      AND lower(i.item) LIKE '%lavander%'
--      AND COALESCE(i.valor_unitario, 0) = 0
--    ORDER BY r.tela, r.codigo_referencia;
--
-- Rutas que YA tienen la foto guardada:
--   SELECT etapa, etapas_omitidas, count(*)
--     FROM hoja_ruta_lote GROUP BY 1, 2 ORDER BY 3 DESC;
