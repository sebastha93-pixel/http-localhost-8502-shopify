"""La moneda de $50 entra al conteo del cajón.

Nació apagada en la 0014 («no circula»). En las tiendas sí aparece en el
cajón, y sin su renglón el conteo de cierre no cuadra con lo que la cajera
tiene en la mano: le sobran monedas que no puede declarar.

Revision ID: 0029
Revises: 0028
"""
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO retail.denominaciones (valor_centavos, tipo, activa)
        VALUES (5000, 'moneda', true)
        ON CONFLICT (valor_centavos) DO UPDATE SET activa = true
    """)


def downgrade() -> None:
    op.execute("UPDATE retail.denominaciones SET activa = false "
               "WHERE valor_centavos = 5000")
