-- ═══════════════════════════════════════════════════════════════════════════
-- EL CORTADOR DE UNA ORDEN DE CORTE ES UN USUARIO, NO UN TEXTO ESCRITO A MANO
-- ═══════════════════════════════════════════════════════════════════════════
--
-- QUÉ PASÓ (2026-08-06): la orden 2608-0001 quedó invisible para el cortador y
-- no pudo hacer el informe. El campo "Cortador responsable" es texto libre, y
-- justo al lado está el campo de correos: quien creó la orden escribió el correo
-- donde va el nombre. El permiso compara ese texto contra el NOMBRE del usuario:
--
--     responsable = 'johnj2397@hotmail.com'   vs   nombre = 'JHON JAIRO BARRETO'
--
-- Ninguno contiene al otro, así que la orden no era de nadie. Ese día hubo que
-- borrarla y volverla a crear (2608-0002) porque tampoco había forma de corregir
-- el dato desde la app.
--
-- Las otras 15 órdenes funcionaban por CASUALIDAD: alguien escribía 'BARRETO' y
-- eso sí es un pedazo de 'JHON JAIRO BARRETO'. Con un solo cortador la
-- coincidencia por texto parece funcionar; con dos empieza a fallar en silencio,
-- y el modo de falla es el peor posible: el cortador simplemente no ve su orden.
--
-- LA SOLUCIÓN (definida por Sebastián): que el responsable se ELIJA de una lista
-- de cortadores inscritos en el portal, y que su identidad —el correo— viaje con
-- la orden por todo el proceso. `responsable` sigue existiendo para mostrar el
-- nombre; `responsable_email` es quién es de verdad.
--
-- Así, el día que entren dos cortadores más, basta con darles acceso a la
-- plataforma: aparecen solos en el selector, sin tocar una línea de código.
--
-- Idempotente. Correr en el SQL Editor de Supabase.
-- ═══════════════════════════════════════════════════════════════════════════

ALTER TABLE ordenes_corte
    ADD COLUMN IF NOT EXISTS responsable_email text;

COMMENT ON COLUMN ordenes_corte.responsable_email IS
    'Correo del cortador responsable, elegido del selector de usuarios con '
    'acceso de cortador. Es la identidad que manda para los permisos; '
    '`responsable` es solo el nombre que se muestra. Antes de 2026-08-06 el '
    'responsable era texto libre y una orden quedó invisible para su cortador.';

-- ── Backfill de las órdenes viejas ────────────────────────────────────────
-- Solo se llena cuando el texto escrito a mano identifica a UN ÚNICO usuario.
-- Si es ambiguo (dos usuarios coinciden) se deja NULL a propósito: el permiso
-- cae al comparador de nombres de siempre y nadie pierde acceso. Adivinar la
-- identidad de una orden ajena sería peor que no llenarla.
UPDATE ordenes_corte oc
   SET responsable_email = u.email
  FROM usuarios u
 WHERE oc.responsable_email IS NULL
   AND coalesce(btrim(oc.responsable), '') <> ''
   AND oc.responsable NOT LIKE '%@%'
   AND upper(btrim(u.nombre)) LIKE '%' || upper(btrim(oc.responsable)) || '%'
   AND (SELECT count(*)
          FROM usuarios u2
         WHERE upper(btrim(u2.nombre)) LIKE '%' || upper(btrim(oc.responsable)) || '%'
       ) = 1;

-- Caso aparte: órdenes donde el texto libre quedó siendo un CORREO (el error de
-- 2608-0001). Ahí el dato está mal puesto pero no está mal: se puede resolver.
UPDATE ordenes_corte oc
   SET responsable_email = u.email,
       responsable       = u.nombre
  FROM usuarios u
 WHERE oc.responsable_email IS NULL
   AND lower(btrim(oc.responsable)) = lower(btrim(u.email));

-- ── Comprobación ──────────────────────────────────────────────────────────
-- SELECT consecutivo, estado, responsable, responsable_email
--   FROM ordenes_corte ORDER BY created_at DESC LIMIT 20;
--
-- Cuántas quedaron sin identidad (usan el comparador de nombres):
-- SELECT count(*) FROM ordenes_corte
--  WHERE responsable_email IS NULL AND coalesce(btrim(responsable),'') <> '';
