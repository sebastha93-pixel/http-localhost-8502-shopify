"""Las tiendas no reciben transferencias.

El medio existía porque el diseño lo daba por hecho, y nunca tuvo forma de
pago en Siigo: el único candidato era la cuenta bancaria, que no es un medio
de cobro. Lo aclaró Sebastián el 2026-10-08: en tienda no se recibe.

SE DESACTIVA, NO SE BORRA. Si alguna venta lo usó, su fila sigue explicando
ese pago; y si un día se habilita, es volver a encenderlo.

Revision ID: 0023
Revises: 0022
"""
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE retail.medios_pago SET activo = false "
               "WHERE id = 'transferencia'")


def downgrade() -> None:
    op.execute("UPDATE retail.medios_pago SET activo = true "
               "WHERE id = 'transferencia'")
