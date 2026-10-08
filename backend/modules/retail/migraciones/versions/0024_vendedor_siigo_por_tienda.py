"""El vendedor de Siigo de cada tienda.

`POST /invoices` exige `seller`: el id de un USUARIO de Siigo. No es la
cajera del POS —que entra con su cuenta del OS y puede no tener usuario en
Siigo—, es a nombre de quién queda la venta allá. Va por tienda.

Queda en NULO a propósito: sin él la factura no se emite, y eso es mejor que
emitirla a nombre de un vendedor adivinado. El emisor aplaza el trabajo y dice
qué falta.

Revision ID: 0024
Revises: 0023
"""
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE retail.tiendas "
               "ADD COLUMN IF NOT EXISTS siigo_vendedor_id integer")


def downgrade() -> None:
    op.execute("ALTER TABLE retail.tiendas DROP COLUMN IF EXISTS siigo_vendedor_id")
