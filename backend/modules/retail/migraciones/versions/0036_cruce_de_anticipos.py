"""El cruce del anticipo con la factura que lo gasta, anotado en su uso.

La nota crédito de un cambio deja un anticipo a nombre de la clienta, y la
factura de la prenda nueva se paga con ese anticipo. Siigo NO los aplica uno
contra otro: la factura queda con saldo pendiente y el anticipo abierto, hasta
que un asiento los cruza. Ese asiento lo hace ahora el POS, uno por cada uso
de un saldo, y aquí queda cuál fue (`CC-1-5600`).

Revision ID: 0036
Revises: 0035
"""
from alembic import op

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE retail.saldo_usos
            ADD COLUMN IF NOT EXISTS cruce_estado text
                CHECK (cruce_estado IN ('enviando','cruzado','rechazado',
                                        'ya_cruzada')),
            ADD COLUMN IF NOT EXISTS cruce_numero text,
            ADD COLUMN IF NOT EXISTS cruce_siigo_id text,
            ADD COLUMN IF NOT EXISTS cruce_error text,
            ADD COLUMN IF NOT EXISTS cruzado_en timestamptz
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE retail.saldo_usos
            DROP COLUMN IF EXISTS cruce_estado,
            DROP COLUMN IF EXISTS cruce_numero,
            DROP COLUMN IF EXISTS cruce_siigo_id,
            DROP COLUMN IF EXISTS cruce_error,
            DROP COLUMN IF EXISTS cruzado_en
    """)
