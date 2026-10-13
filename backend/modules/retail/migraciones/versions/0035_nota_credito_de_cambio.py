"""La nota crédito de un cambio la emite el POS, y la devolución la recuerda.

Hasta hoy la nota crédito de un cambio salía de un caso de Postventa que una
persona tenía que aprobar. En tres días hubo nueve cambios y ninguna nota
crédito: las clientas gastaron su saldo a favor contra un anticipo que en
Siigo no existía, y las facturas nuevas quedaron como cartera (2026-10-13).

`nota_credito_numero` es el número con el que quedó en Siigo (`NC-1-7520`).

Revision ID: 0035
Revises: 0034
"""
from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE retail.devoluciones "
               "ADD COLUMN IF NOT EXISTS nota_credito_numero text")


def downgrade() -> None:
    op.execute("ALTER TABLE retail.devoluciones "
               "DROP COLUMN IF EXISTS nota_credito_numero")
