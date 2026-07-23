-- Plantillas de etiqueta editables desde la app (editor visual arrastrable).
-- Una fila por plantilla (clave); el layout es JSON de elementos con posición.
CREATE TABLE IF NOT EXISTS plantillas_etiqueta (
    clave       text PRIMARY KEY,
    layout      jsonb NOT NULL,
    updated_at  timestamptz NOT NULL DEFAULT now(),
    updated_by  text
);
