"""Categoría de la variante, para los chips de filtro del POS.

VIENE DEL DISEÑO. El handoff usa chips de categoría (Jeans / Shorts / Faldas /
Chaquetas / Tops) sobre el buscador — la forma de mirar el catálogo sin
escribir nada, que es lo que hace una cajera cuando la clienta dice "muéstrame
faldas".

El esquema no tenía dónde guardar eso: `variantes` sólo sabía de referencia,
talla y color. Los datos del prototipo eran mock; la columna no lo es.

Se llena desde Shopify (`product_type`) en la sincronización de catálogo. Sin
valor, la variante cae en 'Otros' y sigue siendo buscable por texto: una
prenda sin clasificar no puede desaparecer del POS.

Revision ID: 0003
Revises: 0002
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE retail.variantes
            ADD COLUMN categoria text NOT NULL DEFAULT 'Otros'
    """)
    op.execute("""
        ALTER TABLE retail.catalogo_busqueda
            ADD COLUMN categoria text NOT NULL DEFAULT 'Otros'
    """)
    # El filtro por categoría dentro de una tienda es la consulta que hace la
    # rejilla en cada toque de chip.
    op.execute("""
        CREATE INDEX ix_catalogo_categoria
            ON retail.catalogo_busqueda (categoria, referencia)
    """)
    # La categoría también entra al texto buscable: quien escribe "falda"
    # espera ver faldas aunque ninguna se llame así.
    op.execute("""
        UPDATE retail.catalogo_busqueda c
           SET texto_busqueda = c.texto_busqueda || ' ' || retail.norm(v.categoria),
               categoria = v.categoria
          FROM retail.variantes v
         WHERE v.id = c.variante_id
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS retail.ix_catalogo_categoria")
    op.execute("ALTER TABLE retail.catalogo_busqueda DROP COLUMN IF EXISTS categoria")
    op.execute("ALTER TABLE retail.variantes DROP COLUMN IF EXISTS categoria")
