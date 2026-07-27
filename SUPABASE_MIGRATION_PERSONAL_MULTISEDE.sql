-- ═══════════════════════════════════════════════════════════════════════
-- MALE'DENIM OS · Módulo Personal · Empleados que rotan entre sedes
-- ═══════════════════════════════════════════════════════════════════════
-- Aplicar DESPUÉS de SUPABASE_MIGRATION_PERSONAL.sql
-- Idempotente: ADD COLUMN IF NOT EXISTS. Re-ejecutar es seguro.
--
-- Por qué
-- ───────
-- El organigrama trajo un caso que el diseño inicial no cubría: Sandra es
-- supernumeraria de CC Plaza Arrayanes Y CC Florida. Con `sede_id` único en
-- personal_empleados no hay dónde ponerla honestamente.
--
-- La solución respeta el principio del módulo: separar el PLAN del HECHO.
--
--   personal_turnos_planificados.sede_id  → dónde DEBÍA estar (plan)
--   personal_jornadas.sede_id             → dónde ESTUVO (hecho, derivado
--                                            del dispositivo que la registró)
--
-- personal_empleados.sede_id pasa a significar "sede administrativa o base",
-- no "la única sede donde trabaja". Para Sandra sería su sede de nómina.
--
-- Sin esto, cada día de Sandra sería una incidencia: marcaría en un
-- dispositivo que no corresponde a "su" sede.
-- ═══════════════════════════════════════════════════════════════════════


-- ── 1. El plan: en qué sede se programó el turno ────────────────────────
ALTER TABLE personal_turnos_planificados
    ADD COLUMN IF NOT EXISTS sede_id UUID REFERENCES personal_sedes(id) ON DELETE SET NULL;

COMMENT ON COLUMN personal_turnos_planificados.sede_id IS
    'Sede donde se programó el turno. NULL = la sede base del empleado.';

CREATE INDEX IF NOT EXISTS idx_personal_turno_sede
    ON personal_turnos_planificados(sede_id);


-- ── 2. El hecho: en qué sede ocurrió realmente la jornada ───────────────
ALTER TABLE personal_jornadas
    ADD COLUMN IF NOT EXISTS sede_id UUID REFERENCES personal_sedes(id) ON DELETE SET NULL;

COMMENT ON COLUMN personal_jornadas.sede_id IS
    'Sede donde ocurrió la jornada, derivada del dispositivo que registró la '
    'primera entrada. Puede diferir de la sede base del empleado y de la '
    'planificada: eso es un dato, no un error.';

CREATE INDEX IF NOT EXISTS idx_personal_jornada_sede
    ON personal_jornadas(sede_id);


-- ── 3. Marcar quién rota entre sedes ────────────────────────────────────
-- Con esto el motor sabe que marcar en otra sede es NORMAL para esta persona
-- y no debe levantar incidencia `marcacion_sin_jornada`.
ALTER TABLE personal_empleados
    ADD COLUMN IF NOT EXISTS rota_entre_sedes BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN personal_empleados.rota_entre_sedes IS
    'TRUE para supernumerarios y personal itinerante. Evita que marcar en '
    'una sede distinta a la base genere incidencia.';

COMMENT ON COLUMN personal_empleados.sede_id IS
    'Sede base o administrativa. Para quien rota (rota_entre_sedes=TRUE) es '
    'su sede de nómina, NO la única donde trabaja.';


-- ── 4. Verificación ─────────────────────────────────────────────────────
-- Debe devolver 3 filas.
--
-- SELECT table_name, column_name FROM information_schema.columns
--  WHERE table_schema='public'
--    AND (   (table_name='personal_turnos_planificados' AND column_name='sede_id')
--         OR (table_name='personal_jornadas'            AND column_name='sede_id')
--         OR (table_name='personal_empleados'           AND column_name='rota_entre_sedes'))
--  ORDER BY table_name;
