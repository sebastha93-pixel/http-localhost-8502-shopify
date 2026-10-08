"""El prefijo que ampara la resolución de cada tienda.

La tirilla de una factura electrónica tiene que llevar impresa la autorización
de numeración: número, fecha, prefijo, rango y vigencia. Los otros cuatro
datos ya estaban en `tiendas`; el prefijo no, porque `cajas.prefijo_factura`
es OTRA cosa —el del número interno del POS (`FLPOS`, `ARRPOS`)—.

Sirve además de candado: el papel sólo imprime la resolución cuando la factura
que devolvió Siigo trae ESTE prefijo. Si un día la caja queda apuntando a otro
comprobante, la tirilla no le pega la resolución de la tienda a un número que
esa resolución no ampara.

Revision ID: 0025
Revises: 0024
"""
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE retail.tiendas "
               "ADD COLUMN IF NOT EXISTS autorizacion_prefijo text")
    # Atado al NÚMERO de la autorización, no al id de la tienda: si alguien
    # cambió la resolución a mano, no se le pone el prefijo de la anterior.
    op.execute("UPDATE retail.tiendas SET autorizacion_prefijo = 'FL' "
               "WHERE autorizacion_numero = '18764108303738'")
    op.execute("UPDATE retail.tiendas SET autorizacion_prefijo = 'TARR' "
               "WHERE autorizacion_numero = '18764083761292'")


def downgrade() -> None:
    op.execute("ALTER TABLE retail.tiendas "
               "DROP COLUMN IF EXISTS autorizacion_prefijo")
