"""Venta con envío a domicilio: los cimientos.

Sebastián, 2026-11-13/17: las vendedoras de la feria tienen que poder vender lo
que está en la tienda en línea y que le llegue a la clienta a su casa, cobrando
en el datáfono de la caja y con la factura de la tienda. Diseño en
`docs/superpowers/specs/2026-11-13-pedido-con-envio-design.md`.

TODO ES ADITIVO Y NADA CAMBIA UNA VENTA DE MOSTRADOR: lo nuevo cuelga de
`ventas.canal = 'envio'`, que por defecto es `'mostrador'`.

`canal` Y NO `origen`. `origen` ya significa otra cosa —en línea / fuera de
línea / traída de Siigo— y tiene su CHECK (0030). Una venta con envío es además
`en_linea`: son dos preguntas distintas y dos columnas.

LA UBICACIÓN `bodega:en_linea`. La prenda de una venta con envío no sale del
estante de la tienda: sale de la bodega de la tienda en línea (Melonn, bodega
32 de Siigo). Con una ubicación propia el asiento de inventario dice de dónde
salió, y la factura y la nota crédito leen de ahí su bodega. Es `tipo='bodega'`
y sin tienda: la sincronización horaria sólo toca `tipo='tienda'`, así que su
saldo no pretende ser verdad —la existencia real la dice Shopify—; sólo
lleva la cuenta de lo que el POS vendió con envío.

`despachos` GUARDA LO JUSTO PARA ENTREGAR. Quién recibe y dónde. No es una
segunda ficha de la clienta: esa sigue en `clientes`.

Revision ID: 0042
Revises: 0041
"""
from alembic import op

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None

#  La bodega de Siigo de donde despacha la tienda en línea (MELONN).
BODEGA_EN_LINEA = 32


def upgrade() -> None:
    op.execute("""
        ALTER TABLE retail.ventas
            ADD COLUMN IF NOT EXISTS canal text NOT NULL DEFAULT 'mostrador'
    """)
    op.execute("""
        ALTER TABLE retail.ventas
            ADD CONSTRAINT ck_venta_canal CHECK (canal IN ('mostrador', 'envio'))
    """)
    op.execute("""
        ALTER TABLE retail.tiendas
            ADD COLUMN IF NOT EXISTS vende_con_envio boolean NOT NULL DEFAULT false
    """)
    op.execute(f"""
        INSERT INTO retail.ubicaciones (id, tipo, nombre, tienda_id, siigo_bodega_id)
        VALUES ('bodega:en_linea', 'bodega', 'Tienda en línea (Melonn)', NULL,
                {BODEGA_EN_LINEA})
        ON CONFLICT (id) DO NOTHING
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS retail.despachos (
            venta_id        retail.ulid PRIMARY KEY
                            REFERENCES retail.ventas(id),
            estado          text NOT NULL DEFAULT 'pendiente'
                CHECK (estado IN ('pendiente', 'en_melonn', 'despachado',
                                  'entregado', 'no_creado', 'cancelado')),
            destinatario    text NOT NULL CHECK (destinatario <> ''),
            telefono        text NOT NULL CHECK (telefono <> ''),
            direccion       text NOT NULL CHECK (direccion <> ''),
            complemento     text NOT NULL DEFAULT '',
            ciudad          text NOT NULL CHECK (ciudad <> ''),
            departamento    text NOT NULL CHECK (departamento <> ''),
            melonn_numero   text,
            melonn_estado   text,
            seguimiento_url text,
            ultimo_error    text,
            -- Cuando la oficina lo cancela: quién y cómo se le devolvió la
            -- plata a la clienta (otra prenda, transferencia, reverso).
            resuelto_por    text,
            resolucion      text,
            creado_en       timestamptz NOT NULL DEFAULT now(),
            actualizado_en  timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_despachos_estado
            ON retail.despachos (estado, creado_en)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS retail.despachos")
    # La ubicación no se puede ir con saldos y asientos colgando de ella.
    op.execute("DELETE FROM retail.stock_ubicacion "
               "WHERE ubicacion_id = 'bodega:en_linea'")
    op.execute("DELETE FROM retail.movimientos_inventario "
               "WHERE ubicacion_id = 'bodega:en_linea'")
    op.execute("DELETE FROM retail.ubicaciones WHERE id = 'bodega:en_linea'")
    op.execute("ALTER TABLE retail.tiendas DROP COLUMN IF EXISTS vende_con_envio")
    op.execute("ALTER TABLE retail.ventas DROP CONSTRAINT IF EXISTS ck_venta_canal")
    op.execute("ALTER TABLE retail.ventas DROP COLUMN IF EXISTS canal")
