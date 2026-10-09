"""La resolución de facturación pasa a ser de la CAJA, no de la tienda.

Las tiendas estrenan resoluciones (2026-10-09) y Florida recibió DOS: una por
caja (`TFL` y `TFP`). La autorización que va impresa en la factura ya no se
puede guardar por tienda — la caja 2 imprimiría la resolución de la caja 1,
que no ampara su número.

Los datos de `tiendas.autorizacion_*` (las resoluciones viejas, `FL` y `TARR`)
se dejan donde están: siguen siendo las de las facturas que emitió Siigo POS.
La tirilla lee primero la caja.

Aquí sólo se pone el PREFIJO de cada caja, que es lo que se sabe. El número
de autorización, la fecha, el rango y la vigencia quedan NULOS a propósito:
mientras falten, la tirilla no se presenta como factura. Es mejor que imprimir
una resolución a medias.

Revision ID: 0027
Revises: 0026
"""
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None

_PREFIJOS = {"arrayanes_caja1": "ARRT", "florida_caja1": "TFL",
             "florida_caja2": "TFP"}


def upgrade() -> None:
    op.execute("""
        ALTER TABLE retail.cajas
            ADD COLUMN IF NOT EXISTS autorizacion_numero   text,
            ADD COLUMN IF NOT EXISTS autorizacion_prefijo  text,
            ADD COLUMN IF NOT EXISTS autorizacion_desde    integer,
            ADD COLUMN IF NOT EXISTS autorizacion_hasta    integer,
            ADD COLUMN IF NOT EXISTS autorizacion_aprobada date,
            ADD COLUMN IF NOT EXISTS autorizacion_meses    integer
    """)
    for caja, prefijo in _PREFIJOS.items():
        op.execute(f"UPDATE retail.cajas SET autorizacion_prefijo = '{prefijo}' "
                   f"WHERE id = '{caja}' AND autorizacion_prefijo IS NULL")


def downgrade() -> None:
    op.execute("""
        ALTER TABLE retail.cajas
            DROP COLUMN IF EXISTS autorizacion_meses,
            DROP COLUMN IF EXISTS autorizacion_aprobada,
            DROP COLUMN IF EXISTS autorizacion_hasta,
            DROP COLUMN IF EXISTS autorizacion_desde,
            DROP COLUMN IF EXISTS autorizacion_prefijo,
            DROP COLUMN IF EXISTS autorizacion_numero
    """)
