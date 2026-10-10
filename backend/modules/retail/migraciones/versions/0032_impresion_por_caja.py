"""El ajuste de la impresora se guarda POR CAJA, en el servidor.

Vivía sólo en el navegador del equipo donde se movía. Quien lo ajustaba desde
su propio computador veía la vista previa cambiar y la caja de la tienda
seguía imprimiendo igual: eran dos navegadores distintos (Florida,
2026-10-10). Y un navegador que borra sus datos al cerrar lo perdía cada día.

Revision ID: 0032
Revises: 0031
"""
from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE retail.cajas ADD COLUMN IF NOT EXISTS impresion jsonb")


def downgrade() -> None:
    op.execute("ALTER TABLE retail.cajas DROP COLUMN IF EXISTS impresion")
