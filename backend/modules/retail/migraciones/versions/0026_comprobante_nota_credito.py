"""El comprobante de nota crédito de cada tienda.

`POST /credit-notes` exige `document.id`. Va por tienda y nace NULO: sin él
la nota crédito espera, que es mejor que emitirla con un comprobante adivinado.

A las dos tiendas que ya existen se les pone 11817 —«Nota Crédito
Electrónica»—, el que usa el motor fiscal de Postventa desde hace meses y con
el que están hechas las notas crédito de anulación de la cuenta. Si
contabilidad quiere un consecutivo aparte para las tiendas, es cambiar este
dato; no hay que tocar código.

Revision ID: 0026
Revises: 0025
"""
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE retail.tiendas "
               "ADD COLUMN IF NOT EXISTS siigo_nc_documento_id integer")
    op.execute("UPDATE retail.tiendas SET siigo_nc_documento_id = 11817 "
               "WHERE id IN ('florida', 'arrayanes') "
               "AND siigo_nc_documento_id IS NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE retail.tiendas "
               "DROP COLUMN IF EXISTS siigo_nc_documento_id")
