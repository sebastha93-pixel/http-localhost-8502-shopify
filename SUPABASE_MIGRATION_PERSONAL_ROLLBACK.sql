-- ═══════════════════════════════════════════════════════════════════════
-- MALE'DENIM OS · Módulo Personal · ROLLBACK
-- ═══════════════════════════════════════════════════════════════════════
--
-- ⚠️  ESTE ARCHIVO BORRA DATOS. Léelo entero antes de ejecutar nada.
--
-- Antes de llegar aquí, prueba los niveles menos destructivos:
--
--   NIVEL 1 — Apagar el módulo          (instantáneo, sin pérdida de datos)
--     En Railway: TIME_MANAGEMENT_ENABLED=false → redeploy.
--     El router deja de registrarse, el menú desaparece, los crons no corren.
--     Las tablas quedan intactas. ESTE ES EL ROLLBACK QUE VAS A QUERER.
--
--   NIVEL 2 — Revertir el código        (sin pérdida de datos)
--     git revert de los commits del módulo. Las tablas siguen ahí, huérfanas
--     pero inofensivas: ninguna otra parte del sistema las consulta.
--
--   NIVEL 3 — Borrar las tablas         (ESTE ARCHIVO · pérdida total)
--     Solo si quieres eliminar el módulo de raíz y estás seguro de que no
--     hay histórico de asistencia que valga la pena conservar.
--
-- ═══════════════════════════════════════════════════════════════════════
-- ¿Qué NO toca este rollback?
-- ═══════════════════════════════════════════════════════════════════════
-- Nada preexistente. La migración del módulo solo CREA tablas nuevas con
-- prefijo personal_*; no altera, no renombra y no borra ninguna columna ni
-- tabla del sistema actual.
--
-- El único vínculo con lo existente es personal_empleados.usuario_id →
-- usuarios(id) ON DELETE SET NULL. Es una FK saliente: borrar las tablas
-- personal_* no afecta a `usuarios` en absoluto.
--
-- Los permisos del grupo `personal` quedan como claves sueltas dentro del
-- JSON usuarios.permisos. Son inertes (ningún endpoint las lee ya). Si
-- quieres limpiarlas, hay un UPDATE opcional al final.
-- ═══════════════════════════════════════════════════════════════════════


-- ── PASO 0 — Respaldo (RECOMENDADO) ─────────────────────────────────────
-- Ejecuta esto ANTES de borrar. Copia las tablas con datos a un esquema
-- aparte, para poder recuperarlas si te arrepientes.
--
-- CREATE SCHEMA IF NOT EXISTS personal_backup;
-- CREATE TABLE personal_backup.empleados      AS SELECT * FROM personal_empleados;
-- CREATE TABLE personal_backup.eventos_crudos AS SELECT * FROM personal_eventos_crudos;
-- CREATE TABLE personal_backup.jornadas       AS SELECT * FROM personal_jornadas;
-- CREATE TABLE personal_backup.libro_tiempo   AS SELECT * FROM personal_libro_tiempo;
-- CREATE TABLE personal_backup.permisos       AS SELECT * FROM personal_solicitudes_permiso;
-- CREATE TABLE personal_backup.auditoria      AS SELECT * FROM personal_auditoria;


-- ── PASO 1 — Ver qué se va a perder ─────────────────────────────────────
-- Corre esto primero. Si devuelve números grandes, PARA y respalda.
--
-- SELECT 'empleados'      AS tabla, COUNT(*) FROM personal_empleados
-- UNION ALL SELECT 'eventos_crudos', COUNT(*) FROM personal_eventos_crudos
-- UNION ALL SELECT 'jornadas',       COUNT(*) FROM personal_jornadas
-- UNION ALL SELECT 'libro_tiempo',   COUNT(*) FROM personal_libro_tiempo
-- UNION ALL SELECT 'permisos',       COUNT(*) FROM personal_solicitudes_permiso
-- UNION ALL SELECT 'novedades',      COUNT(*) FROM personal_novedades_nomina;


-- ── PASO 2 — Borrado ────────────────────────────────────────────────────
-- Descomenta el bloque para ejecutarlo. Está comentado A PROPÓSITO: nadie
-- debe borrar 24 tablas por pegar un archivo sin leerlo.
--
-- El orden respeta las dependencias (hijas antes que padres). CASCADE está
-- puesto por si quedaran FKs que no anticipamos; con este orden no debería
-- hacer falta.

/*
BEGIN;

-- Dependientes de jornadas / permisos
DROP TABLE IF EXISTS personal_bloques_compensacion CASCADE;
DROP TABLE IF EXISTS personal_planes_compensacion  CASCADE;
DROP TABLE IF EXISTS personal_novedades_nomina     CASCADE;
DROP TABLE IF EXISTS personal_libro_tiempo         CASCADE;
DROP TABLE IF EXISTS personal_solicitudes_extra    CASCADE;
DROP TABLE IF EXISTS personal_solicitudes_permiso  CASCADE;
DROP TABLE IF EXISTS personal_incidencias          CASCADE;
DROP TABLE IF EXISTS personal_segmentos            CASCADE;
DROP TABLE IF EXISTS personal_jornadas             CASCADE;

-- Eventos y dispositivos
DROP TABLE IF EXISTS personal_eventos_crudos       CASCADE;
DROP TABLE IF EXISTS personal_mapeo_externo        CASCADE;
DROP TABLE IF EXISTS personal_dispositivos         CASCADE;

-- Horarios
DROP TABLE IF EXISTS personal_turnos_planificados  CASCADE;
DROP TABLE IF EXISTS personal_asignacion_horario   CASCADE;
DROP TABLE IF EXISTS personal_horario_dias         CASCADE;
DROP TABLE IF EXISTS personal_horarios             CASCADE;

-- Catálogos y configuración
DROP TABLE IF EXISTS personal_tipos_permiso        CASCADE;
DROP TABLE IF EXISTS personal_periodos             CASCADE;
DROP TABLE IF EXISTS personal_festivos             CASCADE;
DROP TABLE IF EXISTS personal_reglas               CASCADE;
DROP TABLE IF EXISTS personal_auditoria            CASCADE;

-- Empleados y organización (al final: casi todo apunta aquí)
DROP TABLE IF EXISTS personal_empleados            CASCADE;
DROP TABLE IF EXISTS personal_areas                CASCADE;
DROP TABLE IF EXISTS personal_sedes                CASCADE;

COMMIT;
*/


-- ── PASO 3 — Verificar ──────────────────────────────────────────────────
-- Debe devolver 0 filas.
--
-- SELECT table_name FROM information_schema.tables
--  WHERE table_schema = 'public' AND table_name LIKE 'personal_%';


-- ── PASO 4 — Limpiar permisos (OPCIONAL) ────────────────────────────────
-- Quita las claves del grupo `personal` del JSON de permisos de los usuarios.
-- Es cosmético: sin endpoints que las lean, esas claves no hacen nada.
--
-- UPDATE usuarios
--    SET permisos = permisos
--        - 'personal'              - 'personal_asistencia'
--        - 'personal_permisos'     - 'personal_dispositivos'
--        - 'personal_nomina'       - 'personal_config'
--  WHERE permisos IS NOT NULL;


-- ── PASO 5 — Revertir el código ─────────────────────────────────────────
-- El SQL no basta: hay que quitar también el grupo `personal` de
--   backend/services/usuarios.py  → MODULOS_GRUPOS
--   frontend/lib/auth.ts          → GRUPOS_PERMISOS, GRUPO_LABEL, MODULO_LABEL
--   frontend/lib/nav.ts           → NAV_GROUPS
--   frontend/app/usuarios/page.tsx→ SUBMODULOS
-- y el bloque de registro del router en backend/main.py.
--
-- En la práctica: git revert de los commits del módulo.
