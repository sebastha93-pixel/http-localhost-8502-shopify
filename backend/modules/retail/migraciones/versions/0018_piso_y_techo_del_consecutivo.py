"""Dónde empieza y dónde se acaba la numeración.

EL POS EMPEZARÍA EN 1 Y SIIGO YA VA POR 1536. El bloque se arrienda desde
`max(último repartido, último vendido) + 1`, y en una base nueva las dos cosas
valen cero. La primera venta saldría como `FL-1` — un número que Siigo ya emitió
hace meses bajo la MISMA resolución. Dos documentos distintos con el mismo
número no es un error de software: es un problema con la DIAN.

Y HAY TECHO. La autorización dice «prefijo FL desde el número 1 al 10000».
Emitir el 10001 es emitir fuera de resolución. Con 1536 gastados quedan ~8.400,
que a ritmo de tienda son un par de años — o sea que nadie se va a acordar el
día que se acabe, y por eso tiene que avisar solo.

LOS DOS DATOS VIVEN EN `tiendas`, junto al resto de la resolución (que llegó en
la 0016). Es donde alguien va a buscarlos. El arriendo los lee siguiendo
caja → tienda.

`consecutivo_externo` se llama así a propósito: es el último número consumido
FUERA de este POS. Mientras Siigo POS siga facturando en paralelo durante el
piloto, hay que subirlo. El día que el POS sea el único que emite, deja de
moverse solo.

Revision ID: 0018
Revises: 0017
"""
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE retail.tiendas
            ADD COLUMN IF NOT EXISTS consecutivo_externo integer NOT NULL DEFAULT 0
    """)
    op.execute("""
        COMMENT ON COLUMN retail.tiendas.consecutivo_externo IS
        'Último consecutivo consumido FUERA del POS (Siigo POS). El arriendo de '
        'bloques nunca reparte por debajo de este número.'
    """)

    # Florida: la factura real de la foto es FL-1536.
    op.execute("""
        UPDATE retail.tiendas SET consecutivo_externo = 1536
         WHERE nit = '901680460-1' AND consecutivo_externo = 0
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE retail.tiendas DROP COLUMN IF EXISTS consecutivo_externo
    """)
