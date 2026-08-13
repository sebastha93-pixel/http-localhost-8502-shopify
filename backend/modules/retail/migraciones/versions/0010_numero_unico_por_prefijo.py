"""El número del tiquete es único por PREFIJO, no por caja.

`ux_venta_numero` era `(caja_id, prefijo, consecutivo)`. Con el diseño fiscal
que ya está decidido —**un prefijo por tienda**, no por caja— eso deja pasar
justo lo que tiene que impedir: las dos cajas de Florida comparten el prefijo
FV-20, así que ambas podían emitir `FV-20-1` y el índice no decía nada. Dos
clientas saliendo de la misma tienda con el mismo número de tiquete, y al
cuadrar la numeración a fin de mes nadie entiende qué pasó.

El reparto de bloques ya evita que ocurra —cada caja recibe un rango distinto
del mismo prefijo—, pero eso es una garantía del código. Esta es la de la base,
que es la que sigue valiendo cuando alguien inserta a mano o cuando el código
tiene un error como el que tenía.

Revision ID: 0010
Revises: 0009
"""
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS retail.ux_venta_numero")
    op.execute("""
        CREATE UNIQUE INDEX ux_venta_numero
            ON retail.ventas (prefijo, consecutivo)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS retail.ux_venta_numero")
    op.execute("""
        CREATE UNIQUE INDEX ux_venta_numero
            ON retail.ventas (caja_id, prefijo, consecutivo)
    """)
