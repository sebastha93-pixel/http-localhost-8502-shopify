-- ═══════════════════════════════════════════════════════════════════════
-- Personal · vigencia en el mapeo de IDs del dispositivo
-- ═══════════════════════════════════════════════════════════════════════
--
-- POR QUÉ
-- ───────
-- El Dahua REUSA los identificadores de usuario. Verificado en el equipo de
-- MALE DENIM el 2026-08-18, leyendo los 4785 registros:
--
--     UserID 007 · Hilary Zapata               13 marcaciones · abr 6 → abr 10
--     UserID 007 · Alejandra Valencia Alvarez 117 marcaciones · abr 11 → jun 4
--
-- Son dos personas distintas con el MISMO id externo. Cuando Hilary salió, el
-- 007 se reasignó. Hoy el 007 está libre otra vez, así que volverá a pasar.
--
-- El esquema actual no lo admite:
--
--     CREATE UNIQUE INDEX idx_personal_mapeo_unico
--         ON personal_mapeo_externo(dispositivo_id, id_externo_empleado);
--
-- Solo una persona puede tener el 007. Las consecuencias, ninguna de las
-- cuales da error:
--
--   · si se mapea al titular nuevo, las marcaciones del anterior se le
--     atribuyen a él — horas de otra persona en su banco;
--   · si se mapea al anterior, pasa lo mismo al revés;
--   · si se desactiva y se crea el nuevo, el histórico del anterior queda
--     huérfano y sus jornadas ya calculadas no se pueden reproducir.
--
-- La tabla ya tenía `activo BOOLEAN`, que sirve para apagar un mapeo pero no
-- para preguntar "¿de quién era el 007 el 8 de abril?". Eso es una vigencia,
-- y una vigencia son fechas.
--
-- QUÉ HACE
-- ────────
-- Agrega `valido_desde` / `valido_hasta` (NULL = sin límite por ese lado) y
-- reemplaza el índice único por una restricción de NO SOLAPE: el mismo id
-- externo puede pertenecer a varias personas a lo largo del tiempo, pero
-- JAMÁS a dos a la vez. La base lo hace cumplir; no depende de que el
-- servicio se acuerde.
--
-- Idempotente: se puede correr dos veces.
-- Reversible: ver SUPABASE_MIGRATION_PERSONAL_ROLLBACK.sql
-- ═══════════════════════════════════════════════════════════════════════

-- btree_gist permite mezclar `=` (uuid, text) con `&&` (rango) en un mismo
-- EXCLUDE. Sin esta extensión, la restricción de abajo no se puede crear.
CREATE EXTENSION IF NOT EXISTS btree_gist;

ALTER TABLE personal_mapeo_externo
    ADD COLUMN IF NOT EXISTS valido_desde DATE,
    ADD COLUMN IF NOT EXISTS valido_hasta DATE;

COMMENT ON COLUMN personal_mapeo_externo.valido_desde IS
    'Primer día en que este id externo pertenece a este empleado. NULL = desde siempre.';
COMMENT ON COLUMN personal_mapeo_externo.valido_hasta IS
    'Último día inclusive. NULL = sigue vigente. El Dahua reusa ids: ver la migración.';

-- Una vigencia al revés no tiene sentido y arruinaría el rango.
ALTER TABLE personal_mapeo_externo
    DROP CONSTRAINT IF EXISTS personal_mapeo_vigencia_coherente;
ALTER TABLE personal_mapeo_externo
    ADD CONSTRAINT personal_mapeo_vigencia_coherente
    CHECK (valido_desde IS NULL OR valido_hasta IS NULL OR valido_hasta >= valido_desde);

-- Fuera el índice que impedía la reutilización.
DROP INDEX IF EXISTS idx_personal_mapeo_unico;

-- El mismo id externo, en el mismo dispositivo, no puede estar asignado a dos
-- personas en fechas que se cruzan.
--
--   `daterange(desde, hasta, '[]')` → rango con ambos extremos incluidos; un
--   NULL es un extremo abierto (desde siempre / para siempre).
--   `WHERE (activo)` → un mapeo apagado no estorba para crear el siguiente.
ALTER TABLE personal_mapeo_externo
    DROP CONSTRAINT IF EXISTS personal_mapeo_sin_solape;
ALTER TABLE personal_mapeo_externo
    ADD CONSTRAINT personal_mapeo_sin_solape
    EXCLUDE USING gist (
        dispositivo_id      WITH =,
        id_externo_empleado WITH =,
        daterange(valido_desde, valido_hasta, '[]') WITH &&
    ) WHERE (activo);

-- Para resolver "¿de quién era este id en esta fecha?" sin recorrer la tabla.
CREATE INDEX IF NOT EXISTS idx_personal_mapeo_vigencia
    ON personal_mapeo_externo(dispositivo_id, id_externo_empleado,
                              valido_desde, valido_hasta)
    WHERE activo;


-- ═══════════════════════════════════════════════════════════════════════
-- VERIFICACIÓN
-- ═══════════════════════════════════════════════════════════════════════
-- Debe devolver 4 filas: las 2 columnas, el CHECK y el EXCLUDE.

SELECT 'columna' AS objeto, column_name AS nombre
  FROM information_schema.columns
 WHERE table_name = 'personal_mapeo_externo'
   AND column_name IN ('valido_desde', 'valido_hasta')
UNION ALL
SELECT 'restriccion', conname
  FROM pg_constraint
 WHERE conrelid = 'personal_mapeo_externo'::regclass
   AND conname IN ('personal_mapeo_vigencia_coherente', 'personal_mapeo_sin_solape')
 ORDER BY 1, 2;
