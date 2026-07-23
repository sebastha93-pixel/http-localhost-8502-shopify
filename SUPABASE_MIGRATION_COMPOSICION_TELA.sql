-- Composición de la tela (etiqueta de lavado): el diseñador la digita al
-- ingresar la tela al inventario; si la misma tela vuelve a llegar, se hereda.
ALTER TABLE rollos_tela ADD COLUMN IF NOT EXISTS composicion text;
