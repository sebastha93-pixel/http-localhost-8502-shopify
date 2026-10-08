"""El QR de Wompi va a la forma de pago «WOMPI» de Siigo.

La 0019 lo dejó en nulo A PROPÓSITO: la cuenta tiene dos candidatos —`8353
WOMPI` y `8844 WOMPI CREDITO UN DIA`— y elegir mal manda la venta a la cuenta
contable equivocada, que es un error que no revienta: sale en el balance.

El 2026-10-08 lo confirmó Sebastián: el QR de la tienda se lleva a WOMPI. Es
el 8353; el otro es el crédito a un día, que es otra cosa.

Sólo se toca si sigue en nulo, para no pisar una corrección hecha a mano.

Revision ID: 0022
Revises: 0021
"""
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

WOMPI = 8353


def upgrade() -> None:
    op.execute(f"""
        UPDATE retail.medios_pago SET siigo_forma_pago_id = {WOMPI}
         WHERE id = 'wompi_qr' AND siigo_forma_pago_id IS NULL
    """)


def downgrade() -> None:
    op.execute(f"""
        UPDATE retail.medios_pago SET siigo_forma_pago_id = NULL
         WHERE id = 'wompi_qr' AND siigo_forma_pago_id = {WOMPI}
    """)
