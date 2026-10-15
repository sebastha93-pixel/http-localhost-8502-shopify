"""Promoción por PORCENTAJE: «10 % en todo», junto a la segunda a $1.000.

En la página, durante la actividad, todo lo que NO está en el listado de la
segunda prenda lleva 10 %, y lo que ya está rebajado queda por fuera. En las
tiendas igual (Sebastián, 2026-10-15), y se combinan en la misma compra: un
par del listado más una prenda de afuera = $1.000 + 10 %.

  · `porcentaje`: el descuento, para `tipo = 'porcentaje'`.
  · `excluidas`: referencias que NO lo llevan (las rebajadas). Las del
    listado de la segunda prenda quedan por fuera por regla, no por lista.

Revision ID: 0038
Revises: 0037
"""
from alembic import op

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE retail.promociones
            DROP CONSTRAINT IF EXISTS promociones_tipo_check,
            DROP CONSTRAINT IF EXISTS promociones_precio_centavos_check,
            ALTER COLUMN precio_centavos DROP NOT NULL,
            ADD COLUMN IF NOT EXISTS porcentaje numeric(5,2),
            ADD COLUMN IF NOT EXISTS excluidas text[] NOT NULL DEFAULT '{}'
    """)
    op.execute("""
        ALTER TABLE retail.promociones
            ADD CONSTRAINT promociones_tipo_check
                CHECK (tipo IN ('segunda_a_precio', 'porcentaje')),
            ADD CONSTRAINT promociones_valor_check CHECK (
                (tipo = 'segunda_a_precio' AND precio_centavos > 0)
             OR (tipo = 'porcentaje' AND porcentaje > 0 AND porcentaje < 100))
    """)


def downgrade() -> None:
    op.execute("DELETE FROM retail.promociones WHERE tipo = 'porcentaje'")
    op.execute("""
        ALTER TABLE retail.promociones
            DROP CONSTRAINT IF EXISTS promociones_valor_check,
            DROP CONSTRAINT IF EXISTS promociones_tipo_check,
            DROP COLUMN IF EXISTS excluidas,
            DROP COLUMN IF EXISTS porcentaje
    """)
    op.execute("""
        ALTER TABLE retail.promociones
            ALTER COLUMN precio_centavos SET NOT NULL,
            ADD CONSTRAINT promociones_tipo_check
                CHECK (tipo IN ('segunda_a_precio'))
    """)
