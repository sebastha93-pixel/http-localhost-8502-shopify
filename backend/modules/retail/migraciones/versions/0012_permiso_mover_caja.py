"""Quién puede sacar plata del cajón.

`registrar_retiro` y `registrar_gasto` exigían `autorizado_por` —la firma por
PIN de un supervisor— y ese flujo se quitó cuando el negocio decidió que sólo
hubiera una credencial. Los métodos quedaron en el agregado, con sus pruebas,
sin nadie que pudiera llamarlos: no hay endpoint ni pantalla.

Y eso rompe el cierre TODOS LOS DÍAS. Sale plata del cajón para un domiciliario
o para bolsas, no hay dónde registrarlo, y el arqueo lo lee como faltante: la
cajera termina justificando y buscando un supervisor por algo rutinario. Un
control que salta con lo normal deja de mirarse en una semana.

El permiso sigue el mismo patrón que `puede_cerrar_con_descuadre`: lo trae el
usuario que tiene la sesión abierta. Un INGRESO no lo necesita —meter plata al
cajón no es la operación de la que hay que protegerse.

Revision ID: 0012
Revises: 0011
"""
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE retail.permisos_pos
            ADD COLUMN puede_mover_caja boolean NOT NULL DEFAULT false
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE retail.permisos_pos DROP COLUMN IF EXISTS puede_mover_caja
    """)
