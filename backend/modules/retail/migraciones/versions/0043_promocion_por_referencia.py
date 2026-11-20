"""Promoción de PORCENTAJE POR REFERENCIA: la Black Week (2026-11-20).

Cada referencia lleva su propio descuento (70 %, 50 %, 30 %, 10 %) y cada
tienda su propia lista: Florida y Arrayanes no tienen el mismo saldo. Se crea
UNA promoción por tienda, con `tiendas = '{florida}'` y su lista.

  · `porcentajes`: `{"93634-1": 70, ...}`. Lo que no está, no lleva descuento.

Aditiva: la columna nueva tiene valor por omisión y las promociones viejas no
cambian.

Revision ID: 0043
Revises: 0042
"""
from alembic import op

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE retail.promociones
            DROP CONSTRAINT IF EXISTS promociones_tipo_check,
            DROP CONSTRAINT IF EXISTS promociones_valor_check,
            ADD COLUMN IF NOT EXISTS porcentajes jsonb NOT NULL DEFAULT '{}'
    """)
    op.execute("""
        ALTER TABLE retail.promociones
            ADD CONSTRAINT promociones_tipo_check CHECK (
                tipo IN ('segunda_a_precio', 'porcentaje', 'regalo_por_monto',
                         'porcentaje_por_referencia')),
            ADD CONSTRAINT promociones_valor_check CHECK (
                (tipo = 'segunda_a_precio' AND precio_centavos > 0)
             OR (tipo = 'porcentaje' AND porcentaje > 0 AND porcentaje < 100)
             OR (tipo = 'regalo_por_monto' AND minimo_centavos > 0
                 AND cardinality(referencias) > 0)
             OR (tipo = 'porcentaje_por_referencia'
                 AND jsonb_typeof(porcentajes) = 'object'
                 AND porcentajes <> '{}'::jsonb))
    """)


def downgrade() -> None:
    op.execute("DELETE FROM retail.promociones "
               "WHERE tipo = 'porcentaje_por_referencia'")
    op.execute("""
        ALTER TABLE retail.promociones
            DROP CONSTRAINT IF EXISTS promociones_valor_check,
            DROP CONSTRAINT IF EXISTS promociones_tipo_check,
            DROP COLUMN IF EXISTS porcentajes
    """)
    op.execute("""
        ALTER TABLE retail.promociones
            ADD CONSTRAINT promociones_tipo_check CHECK (
                tipo IN ('segunda_a_precio', 'porcentaje', 'regalo_por_monto')),
            ADD CONSTRAINT promociones_valor_check CHECK (
                (tipo = 'segunda_a_precio' AND precio_centavos > 0)
             OR (tipo = 'porcentaje' AND porcentaje > 0 AND porcentaje < 100)
             OR (tipo = 'regalo_por_monto' AND minimo_centavos > 0
                 AND cardinality(referencias) > 0))
    """)
