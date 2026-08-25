-- ═══════════════════════════════════════════════════════════════════════════
-- RECUPERAR CONTRASEÑA — enlace de un solo uso al correo del propio usuario
-- ═══════════════════════════════════════════════════════════════════════════
--
-- QUÉ PASÓ (2026-08-18): Sebastián quedó afuera de la app. La contraseña que
-- tenía guardada en el Mac no coincidía con la almacenada, y la app NO tenía
-- forma de recuperarla: la única manera de cambiar una clave era que un admin
-- ya adentro la cambiara desde /usuarios. Si el admin es justamente el que no
-- puede entrar, no hay salida — y con 10 usuarios, tarde o temprano le pasa a
-- alguien más.
--
-- POR QUÉ UNA TABLA Y NO UN JWT. Un token firmado no se puede invalidar: si
-- alguien lo intercepta sigue sirviendo hasta que expire, y usarlo una vez no
-- lo apaga. Acá cada enlace es una fila que se marca `usado_en` al gastarse, y
-- al cambiar la clave se apagan TODOS los pendientes de esa persona.
--
-- SE GUARDA EL HASH, NO EL TOKEN. La fila no permite reconstruir el enlace: si
-- alguien leyera esta tabla no podría entrar a ninguna cuenta. Es la misma
-- razón por la que `usuarios` guarda `password_hash` y no la contraseña.
--
-- Idempotente. Correr en el SQL Editor de Supabase.
-- ═══════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS password_reset_tokens (
    -- SHA-256 del token que viaja en el enlace. El token en claro NUNCA se
    -- guarda: se manda al correo y se olvida.
    token_hash  text PRIMARY KEY,

    usuario_id  uuid NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,

    -- Ventana corta a propósito: un enlace de recuperación que vive horas es
    -- una llave de repuesto debajo del tapete.
    expira_en   timestamptz NOT NULL,

    -- Un solo uso. Al gastarse queda la marca y el mismo enlace ya no sirve.
    usado_en    timestamptz,

    -- Desde dónde se pidió. Sirve para ver un abuso ("alguien pidió 40
    -- enlaces"), no para autorizar nada.
    ip          text,

    creado_en   timestamptz NOT NULL DEFAULT now()
);

-- Para apagar de un golpe todos los pendientes de una persona al cambiar clave.
CREATE INDEX IF NOT EXISTS idx_prt_usuario
    ON password_reset_tokens (usuario_id);

-- Para la limpieza de vencidos.
CREATE INDEX IF NOT EXISTS idx_prt_expira
    ON password_reset_tokens (expira_en);

COMMENT ON TABLE password_reset_tokens IS
    'Enlaces de un solo uso para restablecer contraseña. Se guarda el SHA-256 '
    'del token, nunca el token: la tabla no permite reconstruir el enlace.';

COMMENT ON COLUMN password_reset_tokens.usado_en IS
    'Fecha en que se gastó el enlace. NOT NULL = ya no sirve. Al cambiar la '
    'contraseña se marcan todos los pendientes del usuario, no solo el usado.';

-- ── Comprobación ──────────────────────────────────────────────────────────
-- SELECT count(*) AS total,
--        count(*) FILTER (WHERE usado_en IS NULL AND expira_en > now()) AS vivos
--   FROM password_reset_tokens;
