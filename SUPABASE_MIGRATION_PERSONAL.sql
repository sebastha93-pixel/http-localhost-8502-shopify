-- ═══════════════════════════════════════════════════════════════════════
-- MALE'DENIM OS · Módulo Personal · Gestión de Tiempo, Asistencia y Permisos
-- Schema Fase 2 — DDL completo
-- ═══════════════════════════════════════════════════════════════════════
-- Correr UNA VEZ en Supabase → SQL Editor.
-- Idempotente: se puede re-ejecutar sin romper (IF NOT EXISTS en todo).
--
-- NO ejecutar hasta cerrar la Fase 1. Este archivo es el diseño revisable.
-- Rollback documentado en SUPABASE_MIGRATION_PERSONAL_ROLLBACK.sql
--
-- Convenciones (espeja SUPABASE_PRODUCCION.sql y SUPABASE_MIGRATION_POSTVENTA.sql):
--   · Prefijo personal_* en TODAS las tablas (convención del módulo postventa).
--   · UUID PK con gen_random_uuid() (pgcrypto).
--   · TEXT + CHECK para estados — el repo no usa CREATE TYPE.
--   · TIMESTAMPTZ NOT NULL DEFAULT NOW() para created_at/updated_at.
--   · updated_at se mantiene desde Python (el repo no tiene triggers).
--   · Sin RLS — el aislamiento es de aplicación (backend con service key).
-- ═══════════════════════════════════════════════════════════════════════

CREATE EXTENSION IF NOT EXISTS "pgcrypto";


-- ═══════════════════════════════════════════════════════════════════════
-- 1. ORGANIZACIÓN — sedes y áreas
-- ═══════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS personal_sedes (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre        TEXT NOT NULL,
    direccion     TEXT,
    -- IANA timezone. Colombia = 'America/Bogota' (UTC-5 fijo, sin DST).
    -- Explícito por sede para soportar una sede futura en otro huso.
    timezone      TEXT NOT NULL DEFAULT 'America/Bogota',
    activa        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_personal_sedes_nombre ON personal_sedes(LOWER(nombre));


CREATE TABLE IF NOT EXISTS personal_areas (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre        TEXT NOT NULL,
    sede_id       UUID REFERENCES personal_sedes(id) ON DELETE SET NULL,
    activa        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_personal_areas_nombre ON personal_areas(LOWER(nombre));
CREATE INDEX IF NOT EXISTS idx_personal_areas_sede ON personal_areas(sede_id);


-- ═══════════════════════════════════════════════════════════════════════
-- 2. EMPLEADOS
-- ═══════════════════════════════════════════════════════════════════════
-- DECISIÓN DE DISEÑO: tabla separada de `usuarios`.
--   `usuarios`           = credenciales de acceso al sistema (login).
--   `personal_empleados` = personas de la empresa (marquen o no en el Dahua,
--                          tengan o no login).
-- Se enlazan por usuario_id NULLABLE. Un operario puede existir como empleado
-- sin login; un usuario técnico puede existir sin ser empleado.
-- ═══════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS personal_empleados (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    codigo_empleado      TEXT UNIQUE NOT NULL,
    -- Enlace opcional con el login. ON DELETE SET NULL: borrar un usuario
    -- NUNCA debe borrar el histórico de asistencia de la persona.
    usuario_id           UUID UNIQUE REFERENCES usuarios(id) ON DELETE SET NULL,

    tipo_documento       TEXT NOT NULL DEFAULT 'CC'
                         CHECK (tipo_documento IN ('CC','CE','PA','PEP','PPT','TI','NIT')),
    numero_documento     TEXT NOT NULL,
    nombre_completo      TEXT NOT NULL,
    email                TEXT,
    telefono             TEXT,

    area_id              UUID REFERENCES personal_areas(id) ON DELETE SET NULL,
    sede_id              UUID REFERENCES personal_sedes(id) ON DELETE SET NULL,
    cargo                TEXT,
    supervisor_id        UUID REFERENCES personal_empleados(id) ON DELETE SET NULL,

    tipo_contrato        TEXT NOT NULL DEFAULT 'termino_indefinido'
                         CHECK (tipo_contrato IN ('termino_indefinido','termino_fijo',
                                                  'obra_labor','aprendizaje','prestacion_servicios')),
    estado_laboral       TEXT NOT NULL DEFAULT 'activo'
                         CHECK (estado_laboral IN ('activo','incapacidad','vacaciones',
                                                   'licencia','suspendido','retirado')),
    fecha_ingreso        DATE NOT NULL,
    fecha_retiro         DATE,

    -- CST Art. 162: dirección, confianza y manejo están EXCLUIDOS de la
    -- jornada máxima legal. A estos NO se les calcula tarde/extra.
    sujeto_a_jornada     BOOLEAN NOT NULL DEFAULT TRUE,

    -- Habeas data (Ley 1581/2012): el tratamiento de biométricos exige
    -- consentimiento explícito. Se registra la constancia, NO el biométrico.
    consentimiento_datos_at   TIMESTAMPTZ,
    consentimiento_documento  TEXT,

    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CHECK (fecha_retiro IS NULL OR fecha_retiro >= fecha_ingreso)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_personal_emp_documento
    ON personal_empleados(tipo_documento, numero_documento);
CREATE INDEX IF NOT EXISTS idx_personal_emp_usuario     ON personal_empleados(usuario_id);
CREATE INDEX IF NOT EXISTS idx_personal_emp_supervisor  ON personal_empleados(supervisor_id);
CREATE INDEX IF NOT EXISTS idx_personal_emp_area        ON personal_empleados(area_id);
CREATE INDEX IF NOT EXISTS idx_personal_emp_sede        ON personal_empleados(sede_id);
CREATE INDEX IF NOT EXISTS idx_personal_emp_estado      ON personal_empleados(estado_laboral);


-- ═══════════════════════════════════════════════════════════════════════
-- 3. DISPOSITIVOS Y MAPEO EXTERNO
-- ═══════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS personal_dispositivos (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sede_id              UUID REFERENCES personal_sedes(id) ON DELETE SET NULL,
    nombre               TEXT NOT NULL,
    fabricante           TEXT NOT NULL DEFAULT 'Dahua',
    modelo               TEXT,
    -- Serial e IP son datos técnicos sensibles: el API los devuelve
    -- ENMASCARADOS salvo a personal_dispositivos:ver.
    numero_serie         TEXT,
    version_firmware     TEXT,
    ip_local             TEXT,

    tipo_integracion     TEXT NOT NULL DEFAULT 'mock'
                         CHECK (tipo_integracion IN ('mock','csv','dahua_http',
                                                     'dahua_sdk','dss_express','dss_pro')),
    -- Cómo se determina si un evento es entrada o salida:
    --   dispositivo  = el equipo lo reporta (in/out)
    --   por_puerta   = se infiere del nombre de la puerta/lector
    --   alternado    = 1ra marca=entrada, 2da=salida... (el menos confiable)
    modo_direccion     TEXT NOT NULL DEFAULT 'dispositivo'
                       CHECK (modo_direccion IN ('dispositivo','por_puerta','alternado')),

    estado               TEXT NOT NULL DEFAULT 'sin_configurar'
                         CHECK (estado IN ('sin_configurar','en_linea','fuera_de_linea','error')),
    ultimo_contacto_at   TIMESTAMPTZ,
    ultimo_evento_at     TIMESTAMPTZ,
    version_conector     TEXT,

    -- Hash del token del conector. NUNCA se guarda el token en claro,
    -- igual que password_hash en usuarios.
    token_hash           TEXT,
    token_rotado_at      TIMESTAMPTZ,

    configuracion_json   JSONB NOT NULL DEFAULT '{}',
    activo               BOOLEAN NOT NULL DEFAULT TRUE,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_personal_disp_sede   ON personal_dispositivos(sede_id);
CREATE INDEX IF NOT EXISTS idx_personal_disp_estado ON personal_dispositivos(estado);


-- Traduce el identificador del Dahua → empleado de MALE DENIM.
-- Es el ÚNICO puente con el mundo biométrico. Aquí no hay plantillas faciales.
CREATE TABLE IF NOT EXISTS personal_mapeo_externo (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    empleado_id            UUID NOT NULL REFERENCES personal_empleados(id) ON DELETE CASCADE,
    dispositivo_id         UUID NOT NULL REFERENCES personal_dispositivos(id) ON DELETE CASCADE,
    id_externo_empleado    TEXT NOT NULL,
    numero_tarjeta_externo TEXT,
    activo                 BOOLEAN NOT NULL DEFAULT TRUE,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Un id externo identifica a UNA sola persona por dispositivo.
CREATE UNIQUE INDEX IF NOT EXISTS idx_personal_mapeo_unico
    ON personal_mapeo_externo(dispositivo_id, id_externo_empleado);
CREATE INDEX IF NOT EXISTS idx_personal_mapeo_empleado ON personal_mapeo_externo(empleado_id);


-- ═══════════════════════════════════════════════════════════════════════
-- 4. EVENTOS BRUTOS — INMUTABLES
-- ═══════════════════════════════════════════════════════════════════════
-- INVARIANTE 1: esta tabla es append-only.
--   · Nunca se hace UPDATE de event_timestamp, raw_payload_json ni de ningún
--     campo del hecho. Solo `estado_proceso`/`procesado_at`/`error_mensaje`
--     son mutables — son metadatos de procesamiento, no el hecho.
--   · Corregir una marcación NO edita aquí: crea una incidencia + un ajuste.
--   · Sin RLS ni triggers (el repo no los usa) → se hace cumplir en el
--     servicio y se verifica con test explícito (test_eventos_inmutables).
-- ═══════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS personal_eventos_crudos (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dispositivo_id         UUID NOT NULL REFERENCES personal_dispositivos(id) ON DELETE RESTRICT,

    -- Identificador del evento en el Dahua. Puede no existir según el modelo.
    id_evento_externo      TEXT,
    id_externo_empleado    TEXT,
    -- NULL cuando el evento llega de alguien sin mapeo → incidencia
    -- empleado_desconocido. El evento se GUARDA igual; nunca se descarta.
    empleado_id            UUID REFERENCES personal_empleados(id) ON DELETE SET NULL,

    -- Momento del hecho, en el dispositivo. Fuente de verdad temporal.
    event_timestamp        TIMESTAMPTZ NOT NULL,
    -- Momento en que llegó al servidor. La diferencia mide atraso del conector.
    received_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    tipo_evento            TEXT NOT NULL DEFAULT 'acceso',
    direccion_acceso       TEXT NOT NULL DEFAULT 'desconocida'
                           CHECK (direccion_acceso IN ('entrada','salida','desconocida')),
    resultado_acceso       TEXT NOT NULL DEFAULT 'concedido'
                           CHECK (resultado_acceso IN ('concedido','denegado','desconocido')),
    metodo_autenticacion   TEXT,
    nombre_puerta          TEXT,

    -- Referencia a la foto, NO la foto. Por defecto NO se almacena.
    referencia_snapshot    TEXT,

    -- El hecho original completo, tal cual llegó. Nunca se reescribe.
    raw_payload_json       JSONB NOT NULL DEFAULT '{}',
    -- sha256 del payload canónico. Cierra la idempotencia cuando el
    -- dispositivo no entrega id_evento_externo.
    payload_hash           TEXT NOT NULL,

    origen                 TEXT NOT NULL DEFAULT 'conector'
                           CHECK (origen IN ('conector','csv','manual','mock')),
    -- Para eventos manuales: quién los registró y por qué. Auditoría mínima.
    registrado_por         TEXT,
    motivo_manual          TEXT,

    estado_proceso         TEXT NOT NULL DEFAULT 'pendiente'
                           CHECK (estado_proceso IN ('pendiente','procesado','error','ignorado')),
    procesado_at           TIMESTAMPTZ,
    error_mensaje          TEXT,

    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- IDEMPOTENCIA NIVEL 1 — cuando el Dahua entrega id de evento.
-- Índice PARCIAL: solo aplica a las filas que tienen id_evento_externo.
CREATE UNIQUE INDEX IF NOT EXISTS idx_personal_ev_idem_externo
    ON personal_eventos_crudos(dispositivo_id, id_evento_externo)
    WHERE id_evento_externo IS NOT NULL;

-- IDEMPOTENCIA NIVEL 2 — cuando NO hay id de evento.
-- La combinación dispositivo + persona + instante + hash del payload es
-- suficiente para que un reenvío del conector no duplique.
CREATE UNIQUE INDEX IF NOT EXISTS idx_personal_ev_idem_hash
    ON personal_eventos_crudos(dispositivo_id, id_externo_empleado,
                               event_timestamp, payload_hash)
    WHERE id_evento_externo IS NULL;

CREATE INDEX IF NOT EXISTS idx_personal_ev_empleado_ts
    ON personal_eventos_crudos(empleado_id, event_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_personal_ev_estado
    ON personal_eventos_crudos(estado_proceso) WHERE estado_proceso <> 'procesado';
CREATE INDEX IF NOT EXISTS idx_personal_ev_dispositivo_ts
    ON personal_eventos_crudos(dispositivo_id, event_timestamp DESC);


-- ═══════════════════════════════════════════════════════════════════════
-- 5. HORARIOS Y TURNOS
-- ═══════════════════════════════════════════════════════════════════════
-- Tres realidades confirmadas por el cliente:
--   a) Administración → horario fijo         → plantilla semanal
--   b) Tienda         → turnos rotativos     → plantilla + turnos planificados
--   c) Producción     → horario propio       → otra plantilla semanal
--
-- Resolución del horario de un día, en orden de precedencia:
--   1. personal_turnos_planificados (override explícito para esa fecha)
--   2. personal_asignacion_horario vigente + personal_horario_dias
--   3. ninguno → incidencia `horario_no_encontrado` (NUNCA se asume un horario)
-- ═══════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS personal_horarios (
    id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre                    TEXT NOT NULL,
    sede_id                   UUID REFERENCES personal_sedes(id) ON DELETE SET NULL,
    tipo                      TEXT NOT NULL DEFAULT 'fijo'
                              CHECK (tipo IN ('fijo','rotativo','flexible')),
    horas_semanales           NUMERIC(5,2) NOT NULL DEFAULT 46,
    timezone                  TEXT NOT NULL DEFAULT 'America/Bogota',

    -- Minutos de gracia al ingresar antes de contar como tarde.
    tolerancia_ingreso_min    INTEGER NOT NULL DEFAULT 5 CHECK (tolerancia_ingreso_min >= 0),
    tolerancia_salida_min     INTEGER NOT NULL DEFAULT 5 CHECK (tolerancia_salida_min >= 0),
    minutos_descanso          INTEGER NOT NULL DEFAULT 60 CHECK (minutos_descanso >= 0),
    flexibilidad_inicio_min   INTEGER NOT NULL DEFAULT 0 CHECK (flexibilidad_inicio_min >= 0),

    activo                    BOOLEAN NOT NULL DEFAULT TRUE,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_personal_hor_sede ON personal_horarios(sede_id);


CREATE TABLE IF NOT EXISTS personal_horario_dias (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    horario_id           UUID NOT NULL REFERENCES personal_horarios(id) ON DELETE CASCADE,
    -- 0=lunes ... 6=domingo (ISO, coherente con Python weekday()).
    dia_semana           INTEGER NOT NULL CHECK (dia_semana BETWEEN 0 AND 6),
    es_dia_laboral       BOOLEAN NOT NULL DEFAULT TRUE,
    hora_inicio          TIME,
    hora_fin             TIME,
    -- TRUE cuando la jornada termina al día siguiente (turno nocturno).
    -- Con esto la jornada se ancla a la FECHA DE INICIO, no al reloj.
    cruza_medianoche     BOOLEAN NOT NULL DEFAULT FALSE,
    descanso_inicio      TIME,
    descanso_fin         TIME,
    minutos_esperados    INTEGER NOT NULL DEFAULT 0 CHECK (minutos_esperados >= 0),
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_personal_hordia_unico
    ON personal_horario_dias(horario_id, dia_semana);


CREATE TABLE IF NOT EXISTS personal_asignacion_horario (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    empleado_id   UUID NOT NULL REFERENCES personal_empleados(id) ON DELETE CASCADE,
    horario_id    UUID NOT NULL REFERENCES personal_horarios(id) ON DELETE RESTRICT,
    -- Vigencia. valid_to NULL = vigente indefinidamente.
    -- Un cambio de horario NO edita la fila: cierra la vigente y abre otra.
    -- Así un recálculo retroactivo usa el horario que REGÍA ese día.
    valid_from    DATE NOT NULL,
    valid_to      DATE,
    created_by    TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CHECK (valid_to IS NULL OR valid_to >= valid_from)
);

CREATE INDEX IF NOT EXISTS idx_personal_asighor_emp
    ON personal_asignacion_horario(empleado_id, valid_from DESC);


-- Turnos rotativos de tienda: override explícito por empleado y fecha.
CREATE TABLE IF NOT EXISTS personal_turnos_planificados (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    empleado_id         UUID NOT NULL REFERENCES personal_empleados(id) ON DELETE CASCADE,
    fecha               DATE NOT NULL,
    es_dia_laboral      BOOLEAN NOT NULL DEFAULT TRUE,
    hora_inicio         TIME,
    hora_fin            TIME,
    cruza_medianoche    BOOLEAN NOT NULL DEFAULT FALSE,
    descanso_inicio     TIME,
    descanso_fin        TIME,
    minutos_esperados   INTEGER NOT NULL DEFAULT 0 CHECK (minutos_esperados >= 0),
    notas               TEXT,
    created_by          TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_personal_turno_unico
    ON personal_turnos_planificados(empleado_id, fecha);
CREATE INDEX IF NOT EXISTS idx_personal_turno_fecha
    ON personal_turnos_planificados(fecha);


CREATE TABLE IF NOT EXISTS personal_festivos (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fecha       DATE NOT NULL,
    nombre      TEXT NOT NULL,
    pais        TEXT NOT NULL DEFAULT 'CO',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_personal_festivo_unico ON personal_festivos(pais, fecha);


-- ═══════════════════════════════════════════════════════════════════════
-- 6. JORNADAS CALCULADAS
-- ═══════════════════════════════════════════════════════════════════════
-- INVARIANTE 2: esta tabla es DERIVADA y DESECHABLE.
--   Se puede borrar completa y reconstruir desde personal_eventos_crudos
--   + horarios + permisos aprobados. El recálculo es determinista: mismos
--   insumos → mismo resultado, siempre.
--
-- Nótese la separación deliberada:
--   minutos_posible_extra   ← permanencia observada (un HECHO)
--   minutos_extra_aprobada  ← autorización previa    (una DECISIÓN)
-- Nunca el primero alimenta al segundo automáticamente.
-- ═══════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS personal_jornadas (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    empleado_id                 UUID NOT NULL REFERENCES personal_empleados(id) ON DELETE CASCADE,
    -- Fecha de NEGOCIO, no la fecha del reloj. Un turno que entra el lunes
    -- 22:00 y sale el martes 06:00 pertenece al lunes.
    work_date                   DATE NOT NULL,

    horario_id                  UUID REFERENCES personal_horarios(id) ON DELETE SET NULL,
    turno_planificado_id        UUID REFERENCES personal_turnos_planificados(id) ON DELETE SET NULL,
    inicio_programado           TIMESTAMPTZ,
    fin_programado              TIMESTAMPTZ,

    primera_entrada_at          TIMESTAMPTZ,
    ultima_salida_at            TIMESTAMPTZ,

    minutos_esperados           INTEGER NOT NULL DEFAULT 0,
    minutos_trabajados          INTEGER NOT NULL DEFAULT 0,
    minutos_permiso_autorizado  INTEGER NOT NULL DEFAULT 0,
    minutos_tarde               INTEGER NOT NULL DEFAULT 0,
    minutos_salida_anticipada   INTEGER NOT NULL DEFAULT 0,
    minutos_exceso_descanso     INTEGER NOT NULL DEFAULT 0,
    minutos_compensacion_aprob  INTEGER NOT NULL DEFAULT 0,

    -- HECHO observado: permaneció más allá de su jornada. NO es crédito.
    minutos_posible_extra       INTEGER NOT NULL DEFAULT 0,
    -- DECISIÓN: hora extra autorizada previamente y validada. Esto sí cuenta.
    minutos_extra_aprobada      INTEGER NOT NULL DEFAULT 0,

    -- Recargos (CST). Se calculan como insumo para nómina, no como saldo.
    minutos_recargo_nocturno    INTEGER NOT NULL DEFAULT 0,
    minutos_dominical_festivo   INTEGER NOT NULL DEFAULT 0,

    estado_asistencia           TEXT NOT NULL DEFAULT 'sin_datos'
                                CHECK (estado_asistencia IN (
                                    'sin_datos','completa','incompleta','tarde',
                                    'salida_anticipada','ausente','permiso',
                                    'vacaciones','incapacidad','festivo','descanso')),

    -- Trazabilidad del cálculo (exigencia de auditoría):
    version_calculo             TEXT NOT NULL DEFAULT 'v1',
    parametros_usados           JSONB NOT NULL DEFAULT '{}',
    -- Explicación legible: "Llegó 8:12, horario 8:00, tolerancia 5 min → 7 min tarde"
    explicacion                 TEXT,
    calculado_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    aprobado_at                 TIMESTAMPTZ,
    aprobado_por                TEXT,
    -- Una jornada bloqueada pertenece a un periodo cerrado: no se recalcula.
    bloqueado_at                TIMESTAMPTZ,

    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_personal_jornada_unica
    ON personal_jornadas(empleado_id, work_date);
CREATE INDEX IF NOT EXISTS idx_personal_jornada_fecha  ON personal_jornadas(work_date DESC);
CREATE INDEX IF NOT EXISTS idx_personal_jornada_estado ON personal_jornadas(estado_asistencia);


-- Tramos entrada→salida dentro de una jornada (salidas a almuerzo, reingresos).
CREATE TABLE IF NOT EXISTS personal_segmentos (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    jornada_id           UUID NOT NULL REFERENCES personal_jornadas(id) ON DELETE CASCADE,
    evento_entrada_id    UUID REFERENCES personal_eventos_crudos(id) ON DELETE SET NULL,
    evento_salida_id     UUID REFERENCES personal_eventos_crudos(id) ON DELETE SET NULL,
    entrada_at           TIMESTAMPTZ NOT NULL,
    salida_at            TIMESTAMPTZ,
    minutos_trabajados   INTEGER NOT NULL DEFAULT 0,
    tipo_segmento        TEXT NOT NULL DEFAULT 'trabajo'
                         CHECK (tipo_segmento IN ('trabajo','descanso','permiso',
                                                  'compensacion','extra')),
    estado               TEXT NOT NULL DEFAULT 'cerrado'
                         CHECK (estado IN ('abierto','cerrado','inferido')),
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_personal_seg_jornada ON personal_segmentos(jornada_id);


-- ═══════════════════════════════════════════════════════════════════════
-- 7. INCIDENCIAS
-- ═══════════════════════════════════════════════════════════════════════
-- El sistema NUNCA "arregla" una marcación en silencio. Cuando algo no
-- cuadra, levanta una incidencia y espera decisión humana.
-- ═══════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS personal_incidencias (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    empleado_id          UUID REFERENCES personal_empleados(id) ON DELETE CASCADE,
    jornada_id           UUID REFERENCES personal_jornadas(id) ON DELETE CASCADE,
    dispositivo_id       UUID REFERENCES personal_dispositivos(id) ON DELETE SET NULL,

    tipo_incidencia      TEXT NOT NULL
                         CHECK (tipo_incidencia IN (
                             'falta_entrada','falta_salida','evento_duplicado',
                             'empleado_desconocido','dispositivo_offline',
                             'secuencia_imposible','salida_anticipada_no_autorizada',
                             'llegada_tarde_no_autorizada','descanso_excedido',
                             'eventos_solapados','ajuste_manual_requerido',
                             'posible_hora_extra','horario_no_encontrado',
                             'evento_fuera_de_orden','marcacion_sin_jornada')),
    severidad            TEXT NOT NULL DEFAULT 'media'
                         CHECK (severidad IN ('baja','media','alta','critica')),

    detectada_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    work_date            DATE,
    descripcion          TEXT NOT NULL,

    estado               TEXT NOT NULL DEFAULT 'abierta'
                         CHECK (estado IN ('abierta','en_revision','resuelta',
                                           'rechazada','ignorada')),
    tipo_resolucion      TEXT
                         CHECK (tipo_resolucion IS NULL OR tipo_resolucion IN (
                             'ajuste_horario','marcacion_manual','permiso_creado',
                             'sin_accion','error_dispositivo','justificada')),
    notas_resolucion     TEXT,
    archivo_soporte      TEXT,

    reportada_por        TEXT,
    resuelta_por         TEXT,
    resuelta_at          TIMESTAMPTZ,

    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_personal_inc_empleado ON personal_incidencias(empleado_id);
CREATE INDEX IF NOT EXISTS idx_personal_inc_jornada  ON personal_incidencias(jornada_id);
CREATE INDEX IF NOT EXISTS idx_personal_inc_estado   ON personal_incidencias(estado)
    WHERE estado IN ('abierta','en_revision');
CREATE INDEX IF NOT EXISTS idx_personal_inc_tipo     ON personal_incidencias(tipo_incidencia);
CREATE INDEX IF NOT EXISTS idx_personal_inc_fecha    ON personal_incidencias(work_date DESC);


-- ═══════════════════════════════════════════════════════════════════════
-- 8. PERMISOS
-- ═══════════════════════════════════════════════════════════════════════
-- La clasificación es lo que impide que "permiso" sea una palabra ambigua.
-- Un permiso de votación (legal, remunerado, NO compensable) y un permiso
-- personal (empresarial, remunerado, SÍ compensable) son cosas distintas y
-- el sistema no debe poder confundirlas.
-- ═══════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS personal_tipos_permiso (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    codigo                   TEXT UNIQUE NOT NULL,
    nombre                   TEXT NOT NULL,
    descripcion              TEXT,

    categoria                TEXT NOT NULL
                             CHECK (categoria IN ('legal_remunerado','empresarial_remunerado',
                                                  'personal_compensable','no_remunerado',
                                                  'incapacidad','vacaciones')),
    es_remunerado            BOOLEAN NOT NULL DEFAULT TRUE,
    -- CLAVE: los permisos legales NUNCA son compensables. Convertir una
    -- licencia de luto en deuda de tiempo sería ilegal.
    es_compensable           BOOLEAN NOT NULL DEFAULT FALSE,
    requiere_soporte         BOOLEAN NOT NULL DEFAULT FALSE,
    requiere_validacion_th   BOOLEAN NOT NULL DEFAULT TRUE,
    afecta_nomina            BOOLEAN NOT NULL DEFAULT FALSE,
    minutos_max_solicitud    INTEGER,
    base_legal               TEXT,
    activo                   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Regla dura a nivel de base de datos: si es legal remunerado,
    -- es_compensable DEBE ser falso. La ley no se configura mal por accidente.
    CHECK (NOT (categoria = 'legal_remunerado' AND es_compensable = TRUE))
);


CREATE TABLE IF NOT EXISTS personal_solicitudes_permiso (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    consecutivo              TEXT UNIQUE,
    empleado_id              UUID NOT NULL REFERENCES personal_empleados(id) ON DELETE CASCADE,
    tipo_permiso_id          UUID NOT NULL REFERENCES personal_tipos_permiso(id) ON DELETE RESTRICT,

    inicio_solicitado_at     TIMESTAMPTZ NOT NULL,
    fin_solicitado_at        TIMESTAMPTZ NOT NULL,
    minutos_solicitados      INTEGER NOT NULL CHECK (minutos_solicitados > 0),
    motivo                   TEXT NOT NULL,
    archivo_soporte          TEXT,
    notas_cobertura          TEXT,

    estado                   TEXT NOT NULL DEFAULT 'borrador'
                             CHECK (estado IN ('borrador','enviada','pendiente_jefe',
                                               'pendiente_th','aprobada','rechazada',
                                               'cancelada','en_compensacion','completada',
                                               'vencida','enviada_a_nomina')),

    solicitada_at            TIMESTAMPTZ,
    supervisor_id            UUID REFERENCES personal_empleados(id) ON DELETE SET NULL,
    decision_jefe_at         TIMESTAMPTZ,
    notas_jefe               TEXT,
    revisor_th               TEXT,
    decision_th_at           TIMESTAMPTZ,
    notas_th                 TEXT,

    -- Clasificación FINAL, la que decide TH. Puede diferir de la solicitada:
    -- el empleado pide "permiso personal", TH lo reclasifica como "calamidad".
    clasificacion_final      TEXT,
    tratamiento_nomina       TEXT NOT NULL DEFAULT 'sin_efecto'
                             CHECK (tratamiento_nomina IN ('sin_efecto','descuento',
                                                           'compensacion','licencia_no_remunerada')),

    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CHECK (fin_solicitado_at > inicio_solicitado_at)
);

CREATE INDEX IF NOT EXISTS idx_personal_perm_empleado ON personal_solicitudes_permiso(empleado_id);
CREATE INDEX IF NOT EXISTS idx_personal_perm_estado   ON personal_solicitudes_permiso(estado);
CREATE INDEX IF NOT EXISTS idx_personal_perm_super    ON personal_solicitudes_permiso(supervisor_id);
CREATE INDEX IF NOT EXISTS idx_personal_perm_fecha    ON personal_solicitudes_permiso(inicio_solicitado_at DESC);


-- ═══════════════════════════════════════════════════════════════════════
-- 9. COMPENSACIONES
-- ═══════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS personal_planes_compensacion (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    solicitud_permiso_id   UUID NOT NULL UNIQUE
                           REFERENCES personal_solicitudes_permiso(id) ON DELETE CASCADE,
    empleado_id            UUID NOT NULL REFERENCES personal_empleados(id) ON DELETE CASCADE,

    minutos_a_compensar    INTEGER NOT NULL CHECK (minutos_a_compensar > 0),
    minutos_compensados    INTEGER NOT NULL DEFAULT 0 CHECK (minutos_compensados >= 0),
    -- Derivado; se recalcula, no se edita a mano.
    minutos_pendientes     INTEGER NOT NULL DEFAULT 0,

    fecha_limite           DATE NOT NULL,
    fecha_limite_original  DATE,
    prorroga_motivo        TEXT,
    prorroga_aprobada_por  TEXT,

    estado                 TEXT NOT NULL DEFAULT 'activo'
                           CHECK (estado IN ('activo','completado','vencido',
                                             'cancelado','convertido_a_nomina')),
    aprobado_por           TEXT,
    aprobado_at            TIMESTAMPTZ,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_personal_plan_empleado ON personal_planes_compensacion(empleado_id);
CREATE INDEX IF NOT EXISTS idx_personal_plan_estado   ON personal_planes_compensacion(estado);
CREATE INDEX IF NOT EXISTS idx_personal_plan_limite   ON personal_planes_compensacion(fecha_limite)
    WHERE estado = 'activo';


-- Bloques programados de reposición. Se validan contra marcaciones REALES:
-- programar no es compensar; solo el tiempo efectivamente trabajado cuenta.
CREATE TABLE IF NOT EXISTS personal_bloques_compensacion (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id               UUID NOT NULL REFERENCES personal_planes_compensacion(id) ON DELETE CASCADE,
    fecha_programada      DATE NOT NULL,
    inicio_planeado_at    TIMESTAMPTZ NOT NULL,
    fin_planeado_at       TIMESTAMPTZ NOT NULL,
    minutos_planeados     INTEGER NOT NULL CHECK (minutos_planeados > 0),
    -- Se llena SOLO desde la jornada calculada. Nunca se digita.
    minutos_reales        INTEGER NOT NULL DEFAULT 0,
    jornada_id            UUID REFERENCES personal_jornadas(id) ON DELETE SET NULL,
    estado                TEXT NOT NULL DEFAULT 'programado'
                          CHECK (estado IN ('programado','cumplido','parcial',
                                            'incumplido','cancelado')),
    notas_validacion      TEXT,
    validado_at           TIMESTAMPTZ,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CHECK (fin_planeado_at > inicio_planeado_at)
);

CREATE INDEX IF NOT EXISTS idx_personal_bloque_plan  ON personal_bloques_compensacion(plan_id);
CREATE INDEX IF NOT EXISTS idx_personal_bloque_fecha ON personal_bloques_compensacion(fecha_programada);


-- ═══════════════════════════════════════════════════════════════════════
-- 10. LIBRO MAYOR DE TIEMPO — APPEND ONLY
-- ═══════════════════════════════════════════════════════════════════════
-- INVARIANTE 3: NUNCA se hace UPDATE de `minutos` ni `direccion`.
--   Corregir un asiento = asiento de reversión + asiento nuevo.
--   El saldo es SUM(), jamás una columna almacenada. No hay "saldo editable".
--
-- Se hace cumplir en el servicio (no hay triggers en este repo) y se verifica
-- con test explícito: test_libro_tiempo_no_editable.
-- ═══════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS personal_libro_tiempo (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    empleado_id         UUID NOT NULL REFERENCES personal_empleados(id) ON DELETE CASCADE,

    tipo_asiento        TEXT NOT NULL
                        CHECK (tipo_asiento IN ('permiso_debito','compensacion_credito',
                                                'ajuste_manual','conversion_nomina',
                                                'cancelacion','reversion')),
    direccion           TEXT NOT NULL CHECK (direccion IN ('debito','credito')),
    minutos             INTEGER NOT NULL CHECK (minutos > 0),

    -- Origen del movimiento. Todo asiento es rastreable hasta un hecho.
    tipo_origen         TEXT NOT NULL
                        CHECK (tipo_origen IN ('solicitud_permiso','plan_compensacion',
                                               'bloque_compensacion','jornada',
                                               'novedad_nomina','manual')),
    origen_id           UUID,

    -- Asiento que este reversa. Solo se llena en tipo_asiento='reversion'.
    reversa_a_id        UUID REFERENCES personal_libro_tiempo(id) ON DELETE RESTRICT,

    fecha_efectiva      DATE NOT NULL,
    estado              TEXT NOT NULL DEFAULT 'vigente'
                        CHECK (estado IN ('vigente','reversado','anulado')),
    descripcion         TEXT NOT NULL,

    creado_por_sistema  BOOLEAN NOT NULL DEFAULT TRUE,
    aprobado_por        TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Un ajuste manual SIEMPRE necesita un aprobador humano identificado.
    CHECK (tipo_asiento <> 'ajuste_manual' OR aprobado_por IS NOT NULL),
    -- Una reversión SIEMPRE apunta al asiento que corrige.
    CHECK (tipo_asiento <> 'reversion' OR reversa_a_id IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_personal_libro_empleado
    ON personal_libro_tiempo(empleado_id, fecha_efectiva DESC);
CREATE INDEX IF NOT EXISTS idx_personal_libro_origen
    ON personal_libro_tiempo(tipo_origen, origen_id);
CREATE INDEX IF NOT EXISTS idx_personal_libro_estado
    ON personal_libro_tiempo(estado) WHERE estado = 'vigente';


-- ═══════════════════════════════════════════════════════════════════════
-- 11. HORAS EXTRAS
-- ═══════════════════════════════════════════════════════════════════════
-- Tabla separada del libro de tiempo A PROPÓSITO: la hora extra se paga,
-- no se acumula como saldo compensable. Mezclarlas sería el error clásico.
-- ═══════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS personal_solicitudes_extra (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    empleado_id           UUID NOT NULL REFERENCES personal_empleados(id) ON DELETE CASCADE,
    fecha                 DATE NOT NULL,
    inicio_at             TIMESTAMPTZ NOT NULL,
    fin_at                TIMESTAMPTZ NOT NULL,
    minutos_solicitados   INTEGER NOT NULL CHECK (minutos_solicitados > 0),
    motivo                TEXT NOT NULL,

    -- Autorización PREVIA por regla. 'posterior' solo para contingencias
    -- y queda marcado como tal para revisión de TH.
    momento_autorizacion  TEXT NOT NULL DEFAULT 'previa'
                          CHECK (momento_autorizacion IN ('previa','posterior')),

    estado                TEXT NOT NULL DEFAULT 'solicitada'
                          CHECK (estado IN ('solicitada','aprobada','rechazada',
                                            'ejecutada','cancelada','enviada_a_nomina')),
    aprobado_por          TEXT,
    aprobado_at           TIMESTAMPTZ,

    -- Minutos EFECTIVOS según las marcaciones, no los solicitados.
    -- Se paga el mínimo entre autorizado y trabajado.
    minutos_reales        INTEGER NOT NULL DEFAULT 0,
    jornada_id            UUID REFERENCES personal_jornadas(id) ON DELETE SET NULL,

    -- Clasificación CST para el cálculo de recargo.
    clase_extra           TEXT
                          CHECK (clase_extra IS NULL OR clase_extra IN (
                              'diurna','nocturna','dominical_diurna','dominical_nocturna',
                              'festiva_diurna','festiva_nocturna')),

    estado_nomina         TEXT NOT NULL DEFAULT 'pendiente'
                          CHECK (estado_nomina IN ('pendiente','exportada','pagada','descartada')),
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CHECK (fin_at > inicio_at)
);

CREATE INDEX IF NOT EXISTS idx_personal_extra_empleado ON personal_solicitudes_extra(empleado_id);
CREATE INDEX IF NOT EXISTS idx_personal_extra_estado   ON personal_solicitudes_extra(estado);
CREATE INDEX IF NOT EXISTS idx_personal_extra_fecha    ON personal_solicitudes_extra(fecha DESC);


-- ═══════════════════════════════════════════════════════════════════════
-- 12. NOVEDADES DE NÓMINA Y PERIODOS
-- ═══════════════════════════════════════════════════════════════════════
-- INVARIANTE 4: una novedad nace en estado 'propuesta'. Nada llega a nómina
-- sin que una persona la revise. El sistema NO descuenta solo.
-- ═══════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS personal_periodos (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre            TEXT NOT NULL,
    tipo              TEXT NOT NULL DEFAULT 'quincenal'
                      CHECK (tipo IN ('semanal','quincenal','mensual')),
    fecha_inicio      DATE NOT NULL,
    fecha_fin         DATE NOT NULL,
    estado            TEXT NOT NULL DEFAULT 'abierto'
                      CHECK (estado IN ('abierto','en_revision','cerrado','reabierto','exportado')),

    cerrado_por       TEXT,
    cerrado_at        TIMESTAMPTZ,
    reabierto_por     TEXT,
    reabierto_at      TIMESTAMPTZ,
    -- Reabrir un periodo exige motivo. Sin excepción.
    motivo_reapertura TEXT,
    exportado_at      TIMESTAMPTZ,

    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CHECK (fecha_fin >= fecha_inicio),
    CHECK (estado <> 'reabierto' OR motivo_reapertura IS NOT NULL)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_personal_periodo_rango
    ON personal_periodos(tipo, fecha_inicio, fecha_fin);


CREATE TABLE IF NOT EXISTS personal_novedades_nomina (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    empleado_id       UUID NOT NULL REFERENCES personal_empleados(id) ON DELETE CASCADE,
    periodo_id        UUID REFERENCES personal_periodos(id) ON DELETE SET NULL,

    tipo_novedad      TEXT NOT NULL
                      CHECK (tipo_novedad IN (
                          'hora_extra_diurna','hora_extra_nocturna',
                          'recargo_nocturno','dominical_festivo',
                          'descuento_ausencia','descuento_permiso_no_remunerado',
                          'compensacion_vencida','licencia_no_remunerada',
                          'incapacidad','vacaciones','ajuste_manual')),
    tipo_origen       TEXT NOT NULL
                      CHECK (tipo_origen IN ('jornada','solicitud_permiso',
                                             'plan_compensacion','solicitud_extra','manual')),
    origen_id         UUID,

    minutos           INTEGER NOT NULL DEFAULT 0,
    valor             NUMERIC(12,2),

    estado            TEXT NOT NULL DEFAULT 'propuesta'
                      CHECK (estado IN ('propuesta','revisada','aprobada',
                                        'rechazada','exportada')),
    revisada_por      TEXT,
    revisada_at       TIMESTAMPTZ,
    exportada_at      TIMESTAMPTZ,
    notas             TEXT,

    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_personal_nov_empleado ON personal_novedades_nomina(empleado_id);
CREATE INDEX IF NOT EXISTS idx_personal_nov_periodo  ON personal_novedades_nomina(periodo_id);
CREATE INDEX IF NOT EXISTS idx_personal_nov_estado   ON personal_novedades_nomina(estado);


-- ═══════════════════════════════════════════════════════════════════════
-- 13. REGLAS CONFIGURABLES
-- ═══════════════════════════════════════════════════════════════════════
-- Las reglas NO viven como constantes en el código. Se resuelven por
-- especificidad, de la más específica a la más general:
--   empleado > horario > tipo_contrato > area > sede > empresa
-- ═══════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS personal_reglas (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clave          TEXT NOT NULL,
    valor          JSONB NOT NULL,

    ambito         TEXT NOT NULL DEFAULT 'empresa'
                   CHECK (ambito IN ('empresa','sede','area','tipo_contrato',
                                     'horario','empleado')),
    ambito_id      UUID,
    -- Una excepción a nivel empleado SIEMPRE exige motivo auditado.
    motivo         TEXT,

    activa         BOOLEAN NOT NULL DEFAULT TRUE,
    creada_por     TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CHECK (ambito = 'empresa' OR ambito_id IS NOT NULL),
    CHECK (ambito <> 'empleado' OR motivo IS NOT NULL)
);

-- Índice funcional: el COALESCE colapsa NULL a un UUID centinela para que
-- ('tolerancia_ingreso','empresa',NULL) sea único. Sin él, Postgres permitiría
-- varias reglas de empresa con la misma clave (NULL nunca colisiona con NULL).
CREATE UNIQUE INDEX IF NOT EXISTS idx_personal_regla_unica
    ON personal_reglas(clave, ambito,
                       (COALESCE(ambito_id, '00000000-0000-0000-0000-000000000000'::uuid)));


-- ═══════════════════════════════════════════════════════════════════════
-- 14. AUDITORÍA DEL MÓDULO
-- ═══════════════════════════════════════════════════════════════════════
-- NOTA: MALE DENIM OS no tiene hoy una tabla de auditoría global.
-- /api/auditoria hace merge en memoria de `acciones` + `notas`, y su único
-- writer real está en el Streamlit legacy. Construir auditoría global es un
-- proyecto aparte; aquí se resuelve con alcance de módulo, igual que
-- postventa_timeline. El día que exista una auditoría global, esta tabla
-- migra con un INSERT ... SELECT.
-- ═══════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS personal_auditoria (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    actor           TEXT NOT NULL,
    actor_id        UUID,
    accion          TEXT NOT NULL,
    entidad         TEXT NOT NULL,
    entidad_id      UUID,
    valores_antes   JSONB,
    valores_despues JSONB,
    motivo          TEXT,
    origen          TEXT NOT NULL DEFAULT 'api'
                    CHECK (origen IN ('api','conector','cron','importacion','sistema')),
    ip              TEXT,
    user_agent      TEXT,
    correlation_id  TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_personal_aud_entidad ON personal_auditoria(entidad, entidad_id);
CREATE INDEX IF NOT EXISTS idx_personal_aud_actor   ON personal_auditoria(actor);
CREATE INDEX IF NOT EXISTS idx_personal_aud_fecha   ON personal_auditoria(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_personal_aud_corr    ON personal_auditoria(correlation_id);


-- ═══════════════════════════════════════════════════════════════════════
-- 15. VERIFICACIÓN
-- ═══════════════════════════════════════════════════════════════════════
-- Las migraciones de este repo se aplican a mano en la consola de Supabase.
-- Correr esto DESPUÉS para confirmar que las 24 tablas quedaron creadas.
-- Debe devolver exactamente 24 filas.
-- ═══════════════════════════════════════════════════════════════════════

-- SELECT table_name
--   FROM information_schema.tables
--  WHERE table_schema = 'public' AND table_name LIKE 'personal_%'
--  ORDER BY table_name;
