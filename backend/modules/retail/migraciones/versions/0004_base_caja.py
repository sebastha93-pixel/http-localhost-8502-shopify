"""Base de caja por tienda, y avatar/rol de quien opera.

VIENE DEL DISENO. El login del handoff tiene dos pasos: elegir usuaria y
teclear el PIN. NO pide la base de caja — el README la lista como parametro
del prototipo ("base de caja (COP)"), o sea configuracion de la tienda, no
algo que la cajera digite cada manana.

Es la decision correcta: la base casi nunca cambia, y pedirla a diario es un
paso que se responde en automatico hasta que un dia se responde mal.

Tambien entran `rol` y `activo` en permisos_pos: la rejilla de usuarias del
login muestra nombre y rol, y necesita saber a quien ofrecer.

Revision ID: 0004
Revises: 0003
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE retail.tiendas
            ADD COLUMN base_caja retail.centavos NOT NULL DEFAULT 20000000
    """)
    op.execute("""
        ALTER TABLE retail.permisos_pos
            ADD COLUMN rol text NOT NULL DEFAULT 'Cajera'
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE retail.permisos_pos DROP COLUMN IF EXISTS rol")
    op.execute("ALTER TABLE retail.tiendas DROP COLUMN IF EXISTS base_caja")
