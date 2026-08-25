"""Los datos que salen impresos, tomados de la tirilla que MALE usa hoy.

Estaban de relleno —NIT `900000000-0`, teléfono `(604) 000 0000`— y salían en
CADA papel. Los reales vienen de una tirilla física de Siigo Nube de la tienda
Florida (14/08/2026), transcrita en `docs/retail-pos/tirilla-real-siigo.md`.

**EL PREFIJO ERA EL PROBLEMA GORDO.** Las cajas estaban sembradas con `FV-20` y
la factura real es `FL-1536`; la autorización dice literalmente «prefijo FL
desde el número 1 al 10000». Emitir con un prefijo que la resolución no ampara
es un documento rechazado por la DIAN — y se habría descubierto en la primera
factura del piloto, con la clienta esperando.

Ojo con el rango: 1 a 10000, y ya van por 1536. Quedan ~8.400 números, no
diez mil.

LA RESOLUCIÓN NO SE CARGA AQUÍ. `resolucion_dian` sigue nula a propósito:
mientras no exista el emisor, la tirilla tiene que seguir saliendo como
«COMPROBANTE DE VENTA · Documento interno». Poner la resolución ahora haría que
el papel se imprimiera con pinta de factura sin serlo, que es peor que no
imprimir nada. Los datos quedan guardados para cuando el emisor exista.

Revision ID: 0016
Revises: 0015
"""
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Datos de la resolución, guardados pero sin activar la impresión fiscal.
    op.execute("""
        ALTER TABLE retail.tiendas
            ADD COLUMN IF NOT EXISTS actividad_economica text,
            ADD COLUMN IF NOT EXISTS regimen_iva         text,
            ADD COLUMN IF NOT EXISTS autorizacion_numero text,
            ADD COLUMN IF NOT EXISTS autorizacion_desde  integer,
            ADD COLUMN IF NOT EXISTS autorizacion_hasta  integer,
            ADD COLUMN IF NOT EXISTS autorizacion_aprobada date,
            ADD COLUMN IF NOT EXISTS autorizacion_meses  integer
    """)

    op.execute("""
        UPDATE retail.tiendas
           SET razon_social = 'DIRTY JEANS S.A.S.',
               nit          = '901680460-1',
               direccion    = 'CALLE 71 65 150 SEGUNDA ETAPA LC 221',
               telefono     = '3122851520',
               actividad_economica = '4782',
               regimen_iva         = 'Responsable de IVA',
               autorizacion_numero = '18764108303738',
               autorizacion_desde  = 1,
               autorizacion_hasta  = 10000,
               autorizacion_aprobada = DATE '2026-04-10',
               autorizacion_meses  = 24
         WHERE nit IS NULL OR nit = '900000000-0'
    """)

    # EL PREFIJO. `FV-20` no existe en ninguna resolución de MALE.
    op.execute("""
        UPDATE retail.cajas SET prefijo_factura = 'FL'
         WHERE prefijo_factura = 'FV-20'
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE retail.cajas SET prefijo_factura = 'FV-20'
         WHERE prefijo_factura = 'FL'
    """)
    op.execute("""
        UPDATE retail.tiendas
           SET nit = '900000000-0', direccion = 'Cra 43A #1-50, Medellín',
               telefono = '(604) 000 0000'
         WHERE nit = '901680460-1'
    """)
    op.execute("""
        ALTER TABLE retail.tiendas
            DROP COLUMN IF EXISTS autorizacion_meses,
            DROP COLUMN IF EXISTS autorizacion_aprobada,
            DROP COLUMN IF EXISTS autorizacion_hasta,
            DROP COLUMN IF EXISTS autorizacion_desde,
            DROP COLUMN IF EXISTS autorizacion_numero,
            DROP COLUMN IF EXISTS regimen_iva,
            DROP COLUMN IF EXISTS actividad_economica
    """)
