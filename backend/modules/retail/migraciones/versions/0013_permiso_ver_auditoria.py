"""Quién puede leer la auditoría.

La cadena de hash existe desde la migración 0001 y ya tiene eventos críticos
dentro —descuentos aplicados, ventas anuladas, retiros de caja, cierres
descuadrados—. `verificar_cadena` está escrito y sólo lo llama una prueba. No
hay endpoint ni pantalla.

O sea: se está registrando todo con mucho cuidado, encadenado con SHA-256 para
que una modificación a mano se note, y **nadie puede mirarlo**. Un control que
no se puede consultar no es un control; es un archivo.

El permiso es propio y no se deduce de otros. Ver quién descontó, quién anuló y
quién sacó plata es exactamente la información con la que se supervisa a un
equipo — y darla por sentado porque alguien ya puede cerrar con descuadre sería
mezclar dos cosas distintas.

Revision ID: 0013
Revises: 0012
"""
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE retail.permisos_pos
            ADD COLUMN puede_ver_auditoria boolean NOT NULL DEFAULT false
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE retail.permisos_pos DROP COLUMN IF EXISTS puede_ver_auditoria
    """)
