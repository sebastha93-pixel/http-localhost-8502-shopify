"""Umbral de stock bajo por tienda.

`stock_ubicacion.stock_minimo` ya existe y es lo correcto para una prenda
concreta: la talla 10 de la referencia estrella se repone antes que la 4. Pero
nace en 0, y con 0 NINGUNA prenda sale nunca como «stock bajo» — la columna de
estado de la pantalla de inventario mostraría siempre OK hasta que alguien se
siente a configurar 35 variantes una por una. Es decir: nunca.

Este umbral es el piso por defecto de la tienda. `stock_minimo` sigue mandando
cuando está puesto; el default sólo cubre lo que nadie ha afinado todavía.

El 8 sale del handoff (`tot <= 8 ? 'Stock bajo'`). Es un número de arranque,
no una verdad: por eso queda en una columna y no en el código.

Revision ID: 0006_umbral_stock_bajo
Revises: 0005_precio_vitrina
"""
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE retail.tiendas
            ADD COLUMN umbral_stock_bajo integer NOT NULL DEFAULT 8
                CHECK (umbral_stock_bajo >= 0)
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE retail.tiendas DROP COLUMN umbral_stock_bajo")
