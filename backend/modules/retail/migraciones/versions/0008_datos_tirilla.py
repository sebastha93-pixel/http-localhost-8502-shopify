"""Los datos que van impresos en la tirilla.

Sin esto no se puede imprimir nada válido. En Colombia el comprobante que se
entrega en el mostrador lleva razón social, NIT y dirección del emisor; un
papel sin eso no es un soporte de nada, ni para la clienta que quiere cambiar
la prenda ni para la DIAN.

**Por qué en `tiendas` y no en una tabla de empresa.** Hoy razón social y NIT
son los mismos para las dos tiendas —Dirty Jeans S.A.S.—, así que esto está
denormalizado a propósito. La alternativa era una tabla `empresa` con una sola
fila, que es una tabla de configuración disfrazada. Si algún día una tienda
factura con otro NIT —una franquicia, una sociedad aparte— esto ya lo soporta
sin migración.

`resolucion_dian` y `mensaje_tirilla` nacen vacíos: la resolución todavía no
existe (Fase 3) y el mensaje del pie es texto comercial que cambia sin tocar
código. Mientras `resolucion_dian` esté vacía, la tirilla se imprime como
COMPROBANTE INTERNO y lo dice — imprimir algo con pinta de factura sin serlo
es un problema distinto y peor que no imprimir.

Revision ID: 0008
Revises: 0007
"""
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE retail.tiendas
            ADD COLUMN razon_social     text,
            ADD COLUMN nit              text,
            ADD COLUMN direccion        text,
            ADD COLUMN telefono         text,
            ADD COLUMN resolucion_dian  text,
            ADD COLUMN mensaje_tirilla  text
    """)


def downgrade() -> None:
    for columna in ("razon_social", "nit", "direccion", "telefono",
                    "resolucion_dian", "mensaje_tirilla"):
        op.execute(f"ALTER TABLE retail.tiendas DROP COLUMN IF EXISTS {columna}")
