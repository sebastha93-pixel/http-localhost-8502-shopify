"""Promoción de REGALO por monto: la pañoleta gratis desde $149.900.

En la página, desde el 20-oct-2026, las compras de $149.900 o más en prendas
llevan la pañoleta P004 en $0, una por compra. En las tiendas igual
(Sebastián, 2026-10-22).

  · `minimo_centavos`: desde cuánto, en lo que se paga por las prendas (ya
    con sus descuentos) y sin contar el regalo.
  · `referencias`: lo que se regala (`P004`).

Revision ID: 0039
Revises: 0038
"""
from alembic import op

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE retail.promociones
            DROP CONSTRAINT IF EXISTS promociones_tipo_check,
            DROP CONSTRAINT IF EXISTS promociones_valor_check,
            ADD COLUMN IF NOT EXISTS minimo_centavos bigint
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


def downgrade() -> None:
    op.execute("DELETE FROM retail.promociones WHERE tipo = 'regalo_por_monto'")
    op.execute("""
        ALTER TABLE retail.promociones
            DROP CONSTRAINT IF EXISTS promociones_valor_check,
            DROP CONSTRAINT IF EXISTS promociones_tipo_check,
            DROP COLUMN IF EXISTS minimo_centavos
    """)
    op.execute("""
        ALTER TABLE retail.promociones
            ADD CONSTRAINT promociones_tipo_check
                CHECK (tipo IN ('segunda_a_precio', 'porcentaje')),
            ADD CONSTRAINT promociones_valor_check CHECK (
                (tipo = 'segunda_a_precio' AND precio_centavos > 0)
             OR (tipo = 'porcentaje' AND porcentaje > 0 AND porcentaje < 100))
    """)
