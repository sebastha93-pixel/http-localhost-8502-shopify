"""Promociones de la tienda: «la segunda prenda en $1.000».

La primera es la actividad del 15 al 18 de octubre de 2026: de las prendas
del listado, por cada dos la más barata queda en $1.000. Las asesoras tienen
tope de descuento —60 %—, y la segunda prenda va al 99 %: hecha a mano no
pasaba, y aunque pasara cada asesora la calcularía distinto. La regla vive en
el servidor y la caja la aplica sola.

  · `referencias`: las referencias que participan (`93634-1`), las mismas que
    la tienda en línea marca con «2DA PRENDA X 1000».
  · `tiendas`: vacío = todas.

Revision ID: 0037
Revises: 0036
"""
from alembic import op

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # `descuento_valor` guarda un descuento EN PESOS en centavos, y con
    # numeric(10,4) no cabía nada de más de $10.000: la segunda prenda a
    # $1.000 de un jean de $129.900 son $128.900 de descuento.
    op.execute("ALTER TABLE retail.venta_lineas "
               "ALTER COLUMN descuento_valor TYPE numeric(16,4)")
    op.execute("""
        CREATE TABLE retail.promociones (
            id               text PRIMARY KEY,
            nombre           text NOT NULL,
            tipo             text NOT NULL DEFAULT 'segunda_a_precio'
                             CHECK (tipo IN ('segunda_a_precio')),
            precio_centavos  bigint NOT NULL CHECK (precio_centavos > 0),
            desde            timestamptz NOT NULL,
            hasta            timestamptz NOT NULL,
            activa           boolean NOT NULL DEFAULT true,
            tiendas          text[] NOT NULL DEFAULT '{}',
            referencias      text[] NOT NULL DEFAULT '{}',
            creada_en        timestamptz NOT NULL DEFAULT now(),
            CHECK (hasta > desde)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS retail.promociones")
    # La columna se deja ancha: angostarla fallaría con los descuentos que ya
    # se guardaron.
