"""Cuándo la prenda devuelta ya está en la bodega de Siigo.

El inventario del POS se iguala al de Siigo, y Siigo no sabe de una prenda
devuelta hasta que Postventa emite su nota crédito. Entre una cosa y la otra
la sincronización la ponía en cero: la prenda estaba en el estante de Florida
y la caja no la veía (2026-10-10, 12612-1T12).

Mientras esta columna esté vacía, la sincronización SUMA esa prenda a lo que
dice Siigo. Se llena cuando la nota crédito del caso ya salió.

Revision ID: 0033
Revises: 0032
"""
from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE retail.devoluciones "
               "ADD COLUMN IF NOT EXISTS entro_a_siigo_en timestamptz")


def downgrade() -> None:
    op.execute("ALTER TABLE retail.devoluciones "
               "DROP COLUMN IF EXISTS entro_a_siigo_en")
