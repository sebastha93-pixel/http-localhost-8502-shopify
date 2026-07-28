-- ═══════════════════════════════════════════════════════════════════════
-- MALE'DENIM OS · Módulo Personal · Empleados sin control de acceso
-- ═══════════════════════════════════════════════════════════════════════
-- Aplicar DESPUÉS de SUPABASE_MIGRATION_PERSONAL.sql
-- Idempotente: ADD COLUMN IF NOT EXISTS.
--
-- Por qué
-- ───────
-- Las tiendas todavía NO tienen dispositivo de control de acceso: el único
-- Dahua está en la oficina. Las cinco personas de tienda nunca van a marcar.
--
-- Sin esta bandera, el motor las daría por AUSENTES todos los días —una alerta
-- falsa diaria por cinco personas— o quedarían en `horario_no_encontrado` para
-- siempre. Ninguna de las dos cosas es cierta: sí trabajan, simplemente no hay
-- con qué medirlo.
--
-- La distinción importa
-- ─────────────────────
--   sujeto_a_jornada = false  → EXCLUSIÓN LEGAL (CST 162: dirección, confianza
--                               y manejo). No se les calcula jornada porque la
--                               ley no se las impone.
--   controla_asistencia = false → LIMITACIÓN OPERATIVA. Sí tienen jornada, pero
--                               todavía no hay dispositivo que la registre.
--
-- Son cosas distintas y por eso son dos columnas. Cuando la tienda tenga
-- lector, se pone en TRUE y la asistencia empieza a calcularse desde ese día.
-- ═══════════════════════════════════════════════════════════════════════

ALTER TABLE personal_empleados
    ADD COLUMN IF NOT EXISTS controla_asistencia BOOLEAN NOT NULL DEFAULT TRUE;

COMMENT ON COLUMN personal_empleados.controla_asistencia IS
    'FALSE cuando no hay dispositivo que registre las marcaciones de esta '
    'persona (p. ej. sedes sin lector todavía). El motor no calcula asistencia '
    'ni genera incidencias por ausencia. Distinto de sujeto_a_jornada, que es '
    'una exclusión legal, no una limitación técnica.';

CREATE INDEX IF NOT EXISTS idx_personal_emp_controla
    ON personal_empleados(controla_asistencia)
    WHERE controla_asistencia = FALSE;


-- ── Verificación ────────────────────────────────────────────────────────
-- SELECT nombre_completo, controla_asistencia
--   FROM personal_empleados WHERE NOT controla_asistencia
--  ORDER BY nombre_completo;
