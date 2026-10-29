"""Conteos de inventario cargados EN EL POS, mientras Siigo no deja cargarlos.

Arrayanes hizo su conteo y la página de Siigo no lo deja guardar (29-oct).
La tienda no puede vender con el inventario viejo hasta que Siigo se arregle:
el conteo se carga en el POS y, MIENTRAS ESTÉ PENDIENTE de cargarse en Siigo,
la sincronización no toca el inventario de esa tienda (si lo hiciera, lo
pisaría con los números de antes del conteo).

  · `estado`: `pendiente_siigo` → `en_siigo` cuando alguien lo cargó allá y
    lo marca; `reemplazado` si se cargó otro conteo encima.
  · Un solo pendiente por ubicación (índice parcial).
  · `conteo_lineas`: lo que había y lo que se contó, referencia por
    referencia — incluidas las que el conteo dejó en cero.

Revision ID: 0040
Revises: 0039
"""
from alembic import op

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE retail.conteos_inventario (
            id              retail.ulid PRIMARY KEY,
            tienda_id       text NOT NULL REFERENCES retail.tiendas(id),
            ubicacion_id    text NOT NULL REFERENCES retail.ubicaciones(id),
            estado          text NOT NULL DEFAULT 'pendiente_siigo'
                            CHECK (estado IN ('pendiente_siigo', 'en_siigo',
                                              'reemplazado')),
            completo        boolean NOT NULL,
            referencias     integer NOT NULL,
            unidades        integer NOT NULL,
            creado_por      text NOT NULL,
            creado_en       timestamptz NOT NULL DEFAULT now(),
            en_siigo_por    text,
            en_siigo_en     timestamptz
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX ux_conteo_pendiente
            ON retail.conteos_inventario (ubicacion_id)
         WHERE estado = 'pendiente_siigo'
    """)
    op.execute("""
        CREATE TABLE retail.conteo_lineas (
            conteo_id    retail.ulid NOT NULL
                         REFERENCES retail.conteos_inventario(id),
            sku          text NOT NULL,
            variante_id  retail.ulid NOT NULL REFERENCES retail.variantes(id),
            antes        integer NOT NULL,
            contado      integer NOT NULL CHECK (contado >= 0),
            PRIMARY KEY (conteo_id, sku)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS retail.conteo_lineas")
    op.execute("DROP TABLE IF EXISTS retail.conteos_inventario")
