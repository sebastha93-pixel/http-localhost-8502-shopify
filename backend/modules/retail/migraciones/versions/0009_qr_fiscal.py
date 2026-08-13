"""Lo que va DENTRO del QR de la tirilla.

El QR de un documento electrónico colombiano no lleva el CUFE pelado: lleva una
URL con la que cualquiera verifica el documento contra el catálogo de la DIAN.
Esa cadena la define la DIAN y la construye el proveedor —Siigo—, así que se
guarda **tal como él la entregue** en vez de armarla nosotros.

Por qué importa: si la DIAN cambia el formato o Siigo usa uno propio y nosotros
lo tenemos escrito a mano, el QR sigue imprimiéndose y sigue pareciendo
correcto, pero lleva a ninguna parte. Un QR roto en un papel fiscal es peor que
no tener QR, porque nadie lo comprueba hasta que alguien lo escanea.

Mientras la columna esté vacía —hoy lo está, Fase 3 no existe— la tirilla arma
la URL estándar del catálogo a partir del CUFE. Es el formato que llevan
prácticamente todas las facturas electrónicas del país, pero es un respaldo: el
día que Siigo mande el suyo, manda el suyo.

Revision ID: 0009
Revises: 0008
"""
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE retail.documentos_fiscales
            ADD COLUMN qr_datos text
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE retail.documentos_fiscales DROP COLUMN IF EXISTS qr_datos
    """)
