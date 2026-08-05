-- ═══════════════════════════════════════════════════════════════════════════
-- PERMISO DE METRAJE: quién puede borrar un ingreso de tela o cambiar los metros
-- ═══════════════════════════════════════════════════════════════════════════
--
-- POR QUÉ (2026-08-05, pedido de Sebastián): "solo yo pueda borrarlos o
-- modificar el metraje".
--
-- El estado antes de esto:
--   · borrar un ingreso        → rol admin, que hoy son DOS personas
--   · cambiar los metros       → CUALQUIERA con el módulo produccion_ingreso
--   · ajuste manual de stock   → rol admin
--
-- El metraje no es un dato más del ingreso. Es la base del inventario y del
-- consumo por lote: un metro de más o de menos mueve el costo de cada prenda que
-- salga de ese rollo, y no se nota mirando la pantalla. Un tono mal escrito se
-- ve; 300 metros que en realidad eran 280, no.
--
-- FLAG POR USUARIO y no rol nuevo, por dos razones:
--   1. `admin` ya significa otras cosas y son dos personas.
--   2. No se clava un correo en el código: el día que Sebastián delegue esto, se
--      prende el flag y no se toca ni una línea.
--
-- Sigue el mismo patrón que `puede_autorizar_precosteo`, que ya existe en esta
-- misma tabla y se lee de la BASE en cada llamada (no del token), para que
-- revocarlo tenga efecto inmediato y no cuando expire la sesión.
--
-- Idempotente. Correr en el SQL Editor de Supabase.
-- ═══════════════════════════════════════════════════════════════════════════

ALTER TABLE usuarios
    ADD COLUMN IF NOT EXISTS puede_ajustar_metraje boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN usuarios.puede_ajustar_metraje IS
    'Puede borrar un ingreso de tela, cambiar los metros de un rollo y hacer '
    'ajustes manuales de stock. Arranca en false para TODOS: el metraje es la '
    'base del inventario y del costo por prenda.';

-- Arranca solo para Sebastián. Cualquier otro se habilita a mano y a propósito.
UPDATE usuarios
   SET puede_ajustar_metraje = true
 WHERE lower(email) = 'sebastian.hurtado@maledenim.com';

-- ── Comprobación ──────────────────────────────────────────────────────────
-- SELECT email, rol, puede_ajustar_metraje, puede_autorizar_precosteo
--   FROM usuarios ORDER BY puede_ajustar_metraje DESC, email;
