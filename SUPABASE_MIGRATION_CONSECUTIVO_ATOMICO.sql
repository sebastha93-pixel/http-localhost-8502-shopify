-- Consecutivos atómicos: elimina la race condition del read→upsert.
-- Dos requests concurrentes reciben números distintos garantizado.
-- Correr en Supabase SQL Editor.

CREATE OR REPLACE FUNCTION next_consecutivo_atomico(p_prefijo TEXT, p_anio INT)
RETURNS INT
LANGUAGE sql
AS $$
  INSERT INTO produccion_consecutivos (prefijo, anio, ultimo, updated_at)
  VALUES (p_prefijo, p_anio, 1, NOW())
  ON CONFLICT (prefijo, anio)
  DO UPDATE SET ultimo = produccion_consecutivos.ultimo + 1, updated_at = NOW()
  RETURNING ultimo;
$$;
