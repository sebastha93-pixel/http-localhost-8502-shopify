-- ═══════════════════════════════════════════════════════════════════════════
-- INSUMOS: catálogo con reglas explícitas + cambios propuestos por diseño
-- ═══════════════════════════════════════════════════════════════════════════
--
-- POR QUÉ (2026-07-31):
--
-- 1) El nombre del insumo es TEXTO LIBRE y todas las reglas del negocio se
--    deciden leyendo ese texto: si contiene "CIERRE" o "MARQUILLA" se separa
--    talla por talla; si contiene "boton", "remache" o "pretin" lleva el 1% de
--    merma. Un insumo mal escrito NO dispara ninguna regla y nadie se entera.
--    Ya está pasando: de los 3 insumos de confección que existen, uno es
--    "ELAASTICO" (doble A) y por eso no cae en ninguna regla.
--    → El catálogo declara las propiedades en columnas, no en el nombre.
--
-- 2) Las 19 referencias están AUTORIZADAS y BLOQUEADAS, y solo quien tiene
--    `puede_autorizar_precosteo` (Sebastián / María Alejandra) puede editarlas.
--    Cuando diseño necesita agregar un insumo (cierre de nylon, elástico, botón
--    de pasta, hombrera) no puede: tiene que pedirlo por fuera del sistema.
--    → Diseño PROPONE el cambio, queda pendiente, y el costo firmado NO se
--      toca hasta que se apruebe.
--
-- Correr completo en el SQL Editor de Supabase. Es idempotente.
-- ═══════════════════════════════════════════════════════════════════════════

-- ── 1. Catálogo de insumos ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS insumos_catalogo (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre        text NOT NULL,
    categoria     text NOT NULL,          -- 'INSUMO CONFECCION' | 'INSUMO TERMINACION'
    -- Cómo se mide. Cambia cómo se separa y cómo se redondea:
    --   unidad → discreto, se redondea hacia arriba
    --   metro  → continuo, admite decimales (elástico, cordón, sesgo)
    --   par    → discreto pero se pide en pares (hombreras)
    unidad        text NOT NULL DEFAULT 'unidad',
    -- Se separa talla por talla (cierres, marquillas) o en bloque.
    por_talla     boolean NOT NULL DEFAULT false,
    -- Merma al separar. Antes era una lista fija en el código.
    merma_pct     numeric NOT NULL DEFAULT 0,
    -- Nombre de la tabla de medidas que aplica, si necesita una.
    -- 'cierres_jean' = la tabla por tiro (Alto/Medio/Cruzado) que ya existe.
    -- NULL = no lleva medida por talla.
    tabla_medidas text,
    activo        boolean NOT NULL DEFAULT true,
    notas         text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    created_by    text
);

CREATE UNIQUE INDEX IF NOT EXISTS insumos_catalogo_nombre_uniq
    ON insumos_catalogo (lower(trim(nombre)));

-- Semilla. Son los insumos REALES que hoy usan los 19 precosteos (verificado
-- contra precosteo_items el 2026-07-31) más los 4 que pide diseño. Las columnas
-- `por_talla` y `merma_pct` reproducen EXACTAMENTE lo que el código hacía por
-- substring, para que correr esta migración no cambie ningún cálculo existente.
INSERT INTO insumos_catalogo (nombre, categoria, unidad, por_talla, merma_pct, tabla_medidas, notas)
VALUES
  -- ── CONFECCIÓN · lo que ya existe ────────────────────────────────────────
  ('Cierre',                'INSUMO CONFECCION',  'unidad', true,  0, 'cierres_jean',
   'Largo por talla según el tiro. Tabla en frontend/lib/cierres.ts'),
  ('Marquilla talla',       'INSUMO CONFECCION',  'unidad', true,  0, NULL,
   'Una por prenda, separada por talla (cada talla lleva su número).'),
  ('Elástico',              'INSUMO CONFECCION',  'metro',  false, 1, NULL,
   'Se mide en METROS. Reemplaza el "ELAASTICO" (doble A) que por el error de escritura no caía en ninguna regla.'),
  -- ── CONFECCIÓN · lo que pide diseño (2026-07-31) ─────────────────────────
  ('Cierre de nylon',       'INSUMO CONFECCION',  'unidad', true,  0, NULL,
   'OJO: tabla_medidas en NULL a propósito. NO usa la tabla de tiro del jean; si necesita largos por talla hay que definir su propia tabla y ponerla acá.'),
  ('Botón de pasta',        'INSUMO CONFECCION',  'unidad', false, 1, NULL, NULL),
  ('Hombrera',              'INSUMO CONFECCION',  'par',    false, 1, NULL,
   'Se pide en PARES, no en unidades sueltas.'),
  -- ── TERMINACIÓN · lo que ya existe ───────────────────────────────────────
  ('Código de barras',      'INSUMO TERMINACION', 'unidad', false, 0, NULL,
   'Sticker que imprime la Honeywell.'),
  ('Instrucción de lavado', 'INSUMO TERMINACION', 'unidad', false, 1, NULL,
   'Una por prenda + 1%. La imprime la SAT.'),
  ('Bolsa',                 'INSUMO TERMINACION', 'unidad', false, 0, NULL, NULL),
  ('Botón 27 L',            'INSUMO TERMINACION', 'unidad', false, 1, NULL, NULL),
  ('Remache',               'INSUMO TERMINACION', 'unidad', false, 1, NULL,
   '2 por prenda en la mayoría de referencias.'),
  ('Garra',                 'INSUMO TERMINACION', 'unidad', false, 0, NULL, NULL),
  ('Pretinera',             'INSUMO TERMINACION', 'unidad', false, 1, NULL, NULL),
  ('Taches',                'INSUMO TERMINACION', 'unidad', false, 1, NULL,
   'Aparece en 1 precosteo escrito en minúscula ("taches").')
ON CONFLICT (lower(trim(nombre))) DO NOTHING;

-- ── 2. Cambios propuestos sobre un precosteo autorizado ───────────────────
CREATE TABLE IF NOT EXISTS precosteo_cambios_propuestos (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    referencia_id  uuid NOT NULL REFERENCES referencias_precosteo(id) ON DELETE CASCADE,
    estado         text NOT NULL DEFAULT 'pendiente',   -- pendiente | aprobado | rechazado
    -- Foto COMPLETA de los items antes y después. Se guarda entera a propósito:
    -- un diff parcial no permite reconstruir qué se aprobó si el precosteo
    -- cambió por otro lado mientras la propuesta esperaba.
    items_antes    jsonb NOT NULL,
    items_despues  jsonb NOT NULL,
    -- Impacto en el costo, calculado al proponer para que quien autoriza no
    -- tenga que sacarlo a mano.
    costo_antes    numeric,
    costo_despues  numeric,
    motivo         text,
    propuesto_por  text NOT NULL,
    propuesto_at   timestamptz NOT NULL DEFAULT now(),
    revisado_por   text,
    revisado_at    timestamptz,
    comentario     text
);

CREATE INDEX IF NOT EXISTS precosteo_cambios_pendientes_idx
    ON precosteo_cambios_propuestos (estado, propuesto_at DESC);
CREATE INDEX IF NOT EXISTS precosteo_cambios_ref_idx
    ON precosteo_cambios_propuestos (referencia_id, estado);

-- ── 3. Normalizar nombres mal escritos ────────────────────────────────────
-- Se hace acá y no desde la app porque toca precosteos ya AUTORIZADOS. Solo
-- cambia el NOMBRE; no toca cantidades ni valores, así que el costo firmado
-- no se mueve ni un peso.
--
-- "ELAASTICO" (doble A) es el caso que destapó todo: por el error de escritura
-- no coincidía con ninguna regla y se separaba sin merma y en la unidad
-- equivocada, sin que nada lo advirtiera.
UPDATE precosteo_items
   SET item = 'Elástico'
 WHERE lower(trim(item)) IN ('elaastico', 'elastico', 'elaástico');

UPDATE precosteo_items
   SET item = 'Taches'
 WHERE lower(trim(item)) = 'taches' AND item <> 'Taches';

UPDATE precosteo_items
   SET item = 'Entretela'
 WHERE lower(trim(item)) = 'entretela' AND item <> 'Entretela';

-- ── Comprobación ──────────────────────────────────────────────────────────
-- SELECT nombre, unidad, por_talla, merma_pct, tabla_medidas FROM insumos_catalogo ORDER BY categoria, nombre;
-- SELECT item, count(*) FROM precosteo_items WHERE categoria = 'INSUMO CONFECCION' GROUP BY item;
