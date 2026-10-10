"""Las ventas del sistema anterior pueden entrar al POS para hacerles un cambio.

Las tiendas facturaron con Siigo POS hasta el 2026-10-08. Las clientas de esas
semanas van a volver a cambiar prendas, y el POS no tiene esas ventas: el
cambio no se podía hacer desde la caja.

Una factura de Siigo POS se trae como una venta más, marcada con su origen
(`siigo_pos`) para que nunca se confunda con una que la caja cobró:

  · no movió inventario del POS ni entró a ningún arqueo;
  · cuelga de un turno HISTÓRICO, cerrado y en cero, uno por caja —
    `ventas.sesion_id` es obligatorio y no se le quita esa garantía a las
    ventas de verdad por acomodar a las importadas.

Revision ID: 0030
Revises: 0029
"""
from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE retail.ventas DROP CONSTRAINT IF EXISTS ventas_origen_check")
    op.execute("""
        ALTER TABLE retail.ventas ADD CONSTRAINT ventas_origen_check
            CHECK (origen IN ('en_linea', 'fuera_de_linea', 'siigo_pos'))
    """)
    # Para no traer dos veces la misma factura: el id de Siigo es único entre
    # las facturas. Parcial, porque las notas crédito tienen el suyo aparte.
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_doc_externo
            ON retail.documentos_fiscales (documento_externo_id)
            WHERE documento_externo_id IS NOT NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS retail.ix_doc_externo")
    op.execute("ALTER TABLE retail.ventas DROP CONSTRAINT IF EXISTS ventas_origen_check")
    op.execute("""
        ALTER TABLE retail.ventas ADD CONSTRAINT ventas_origen_check
            CHECK (origen IN ('en_linea', 'fuera_de_linea')) NOT VALID
    """)
