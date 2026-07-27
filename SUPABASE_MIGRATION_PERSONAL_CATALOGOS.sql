-- ═══════════════════════════════════════════════════════════════════════
-- MALE'DENIM OS · Módulo Personal · Catálogos base
-- ═══════════════════════════════════════════════════════════════════════
-- Aplicar DESPUÉS de SUPABASE_MIGRATION_PERSONAL.sql
--
-- Esto NO son datos demo: son datos de PRODUCCIÓN.
--   · Tipos de permiso  → el catálogo con el que Talento Humano clasifica
--   · Festivos          → afectan recargos dominicales/festivos
--
-- Los datos de demostración (empleados, eventos) van en
-- SUPABASE_MIGRATION_PERSONAL_SEEDS.sql y NO deben cargarse en producción.
--
-- Idempotente: ON CONFLICT DO NOTHING. Re-ejecutar es seguro.
--
-- ⚠️  VALIDACIÓN LEGAL PENDIENTE
-- Los tipos de permiso de abajo son un punto de partida basado en el Código
-- Sustantivo del Trabajo. DEBEN revisarse con un abogado laboral colombiano
-- antes del lanzamiento, junto con el reglamento interno de MALE DENIM.
-- El software no es asesoría jurídica.
-- ═══════════════════════════════════════════════════════════════════════


-- ── 1. Tipos de permiso ─────────────────────────────────────────────────
-- Regla dura que ya impone el esquema: categoria='legal_remunerado' NO puede
-- ser compensable. Un permiso de ley jamás se convierte en deuda de tiempo.

INSERT INTO personal_tipos_permiso
    (codigo, nombre, categoria, es_remunerado, es_compensable,
     requiere_soporte, requiere_validacion_th, afecta_nomina,
     minutos_max_solicitud, base_legal, descripcion)
VALUES
    -- Legales remunerados — NUNCA compensables
    ('LUTO', 'Licencia por luto', 'legal_remunerado',
     TRUE, FALSE, TRUE, TRUE, FALSE, NULL,
     'CST Art. 57 num. 10 (Ley 1280 de 2009)',
     '5 días hábiles por fallecimiento de familiar hasta grado de ley'),

    ('CALAMIDAD', 'Calamidad doméstica', 'legal_remunerado',
     TRUE, FALSE, TRUE, TRUE, FALSE, NULL,
     'CST Art. 57 num. 6',
     'Hecho grave e imprevisto que afecta al trabajador o su familia'),

    ('VOTACION', 'Ejercicio del sufragio', 'legal_remunerado',
     TRUE, FALSE, TRUE, FALSE, FALSE, NULL,
     'Ley 403 de 1997',
     'Media jornada compensatoria por votar; requiere certificado electoral'),

    ('CITA_JUDICIAL', 'Citación judicial o administrativa', 'legal_remunerado',
     TRUE, FALSE, TRUE, TRUE, FALSE, NULL,
     'CST Art. 57 num. 6',
     'Comparecencia obligatoria ante autoridad'),

    ('LIC_MATERNIDAD', 'Licencia de maternidad', 'legal_remunerado',
     TRUE, FALSE, TRUE, TRUE, TRUE, NULL,
     'CST Art. 236 (Ley 1822 de 2017)',
     '18 semanas. Se registra para el calendario; la liquida la EPS'),

    ('LIC_PATERNIDAD', 'Licencia de paternidad', 'legal_remunerado',
     TRUE, FALSE, TRUE, TRUE, TRUE, NULL,
     'CST Art. 236 par. 1',
     '2 semanas. Requiere registro civil de nacimiento'),

    ('SINDICAL', 'Permiso sindical', 'legal_remunerado',
     TRUE, FALSE, TRUE, TRUE, FALSE, NULL,
     'CST Art. 57 num. 6',
     'Actividades sindicales según convención'),

    -- Empresariales remunerados — política interna, no ley
    ('CITA_MEDICA', 'Cita médica', 'empresarial_remunerado',
     TRUE, FALSE, TRUE, TRUE, FALSE, 240,
     'Política interna',
     'Cita con EPS o medicina prepagada; requiere constancia de asistencia'),

    ('DILIGENCIA_EMPRESA', 'Diligencia laboral externa', 'empresarial_remunerado',
     TRUE, FALSE, FALSE, FALSE, FALSE, NULL,
     'Política interna',
     'Salida en horario laboral por encargo de la empresa'),

    ('CAPACITACION', 'Capacitación o formación', 'empresarial_remunerado',
     TRUE, FALSE, FALSE, TRUE, FALSE, NULL,
     'Política interna',
     'Formación autorizada por la empresa'),

    -- Personal compensable — el caso que motivó el módulo
    ('PERSONAL_COMP', 'Permiso personal compensable', 'personal_compensable',
     TRUE, TRUE, FALSE, TRUE, FALSE, 480,
     'Política interna',
     'Asunto personal; el tiempo se repone mediante redistribución autorizada de la jornada'),

    -- No remunerado
    ('NO_REMUNERADO', 'Permiso no remunerado', 'no_remunerado',
     FALSE, FALSE, FALSE, TRUE, TRUE, NULL,
     'CST Art. 51 num. 4 (suspensión de común acuerdo)',
     'Ausencia acordada sin pago; genera novedad de descuento para revisión'),

    -- Estados que no son "permiso" pero ocupan el calendario
    ('INCAPACIDAD', 'Incapacidad médica', 'incapacidad',
     TRUE, FALSE, TRUE, TRUE, TRUE, NULL,
     'Decreto 1072 de 2015',
     'Requiere incapacidad expedida por EPS o ARL'),

    ('VACACIONES', 'Vacaciones', 'vacaciones',
     TRUE, FALSE, FALSE, TRUE, TRUE, NULL,
     'CST Art. 186',
     '15 días hábiles por año trabajado')
ON CONFLICT (codigo) DO NOTHING;


-- ── 2. Festivos de Colombia ─────────────────────────────────────────────
-- Calculados con la Ley Emiliani (Ley 51 de 1983): los trasladables se corren
-- al lunes siguiente. Los ligados a Pascua se derivan del algoritmo de Meeus.
-- Verificados: los 18 trasladables de cada año caen en lunes.
--
-- Fijos (NO se trasladan): 1 ene, 1 may, 20 jul, 7 ago, 8 dic, 25 dic.
-- Jueves y Viernes Santo tampoco se trasladan.

INSERT INTO personal_festivos (fecha, nombre, pais) VALUES
    ('2026-01-01', 'Año Nuevo', 'CO'),
    ('2026-01-12', 'Reyes Magos', 'CO'),
    ('2026-03-23', 'San José', 'CO'),
    ('2026-04-02', 'Jueves Santo', 'CO'),
    ('2026-04-03', 'Viernes Santo', 'CO'),
    ('2026-05-01', 'Día del Trabajo', 'CO'),
    ('2026-05-18', 'Ascensión del Señor', 'CO'),
    ('2026-06-08', 'Corpus Christi', 'CO'),
    ('2026-06-15', 'Sagrado Corazón', 'CO'),
    ('2026-06-29', 'San Pedro y San Pablo', 'CO'),
    ('2026-07-20', 'Independencia', 'CO'),
    ('2026-08-07', 'Batalla de Boyacá', 'CO'),
    ('2026-08-17', 'Asunción de la Virgen', 'CO'),
    ('2026-10-12', 'Día de la Raza', 'CO'),
    ('2026-11-02', 'Todos los Santos', 'CO'),
    ('2026-11-16', 'Independencia de Cartagena', 'CO'),
    ('2026-12-08', 'Inmaculada Concepción', 'CO'),
    ('2026-12-25', 'Navidad', 'CO'),
    ('2027-01-01', 'Año Nuevo', 'CO'),
    ('2027-01-11', 'Reyes Magos', 'CO'),
    ('2027-03-22', 'San José', 'CO'),
    ('2027-03-25', 'Jueves Santo', 'CO'),
    ('2027-03-26', 'Viernes Santo', 'CO'),
    ('2027-05-01', 'Día del Trabajo', 'CO'),
    ('2027-05-10', 'Ascensión del Señor', 'CO'),
    ('2027-05-31', 'Corpus Christi', 'CO'),
    ('2027-06-07', 'Sagrado Corazón', 'CO'),
    ('2027-07-05', 'San Pedro y San Pablo', 'CO'),
    ('2027-07-20', 'Independencia', 'CO'),
    ('2027-08-07', 'Batalla de Boyacá', 'CO'),
    ('2027-08-16', 'Asunción de la Virgen', 'CO'),
    ('2027-10-18', 'Día de la Raza', 'CO'),
    ('2027-11-01', 'Todos los Santos', 'CO'),
    ('2027-11-15', 'Independencia de Cartagena', 'CO'),
    ('2027-12-08', 'Inmaculada Concepción', 'CO'),
    ('2027-12-25', 'Navidad', 'CO'),
    ('2028-01-01', 'Año Nuevo', 'CO'),
    ('2028-01-10', 'Reyes Magos', 'CO'),
    ('2028-03-20', 'San José', 'CO'),
    ('2028-04-13', 'Jueves Santo', 'CO'),
    ('2028-04-14', 'Viernes Santo', 'CO'),
    ('2028-05-01', 'Día del Trabajo', 'CO'),
    ('2028-05-29', 'Ascensión del Señor', 'CO'),
    ('2028-06-19', 'Corpus Christi', 'CO'),
    ('2028-06-26', 'Sagrado Corazón', 'CO'),
    ('2028-07-03', 'San Pedro y San Pablo', 'CO'),
    ('2028-07-20', 'Independencia', 'CO'),
    ('2028-08-07', 'Batalla de Boyacá', 'CO'),
    ('2028-08-21', 'Asunción de la Virgen', 'CO'),
    ('2028-10-16', 'Día de la Raza', 'CO'),
    ('2028-11-06', 'Todos los Santos', 'CO'),
    ('2028-11-13', 'Independencia de Cartagena', 'CO'),
    ('2028-12-08', 'Inmaculada Concepción', 'CO'),
    ('2028-12-25', 'Navidad', 'CO')
ON CONFLICT (pais, fecha) DO NOTHING;


-- ── 3. Verificación ─────────────────────────────────────────────────────
-- Debe devolver: 14 tipos de permiso, 18 festivos por año.
--
-- SELECT 'tipos_permiso' AS tabla, COUNT(*) FROM personal_tipos_permiso
-- UNION ALL
-- SELECT 'festivos_' || EXTRACT(YEAR FROM fecha)::text, COUNT(*)
--   FROM personal_festivos GROUP BY 2 ORDER BY 1;
--
-- Y esta NO debe devolver ninguna fila (permiso legal marcado compensable):
-- SELECT codigo FROM personal_tipos_permiso
--  WHERE categoria = 'legal_remunerado' AND es_compensable;
