"""La cola de stock a Shopify no era un pendiente: era código muerto.

Cada venta encolaba `publicar_stock_shopify` con `{ubicacion_id, variantes}`.
Nunca hubo consumidor, y no podía haberlo: `retail.ubicaciones` no tiene
`shopify_location_id`, así que no existe el mapeo tienda↔location. La cola sólo
acumulaba mensajes inejecutables.

Y NO HACÍA FALTA. Shopify vende contra el inventario de MELONN (bodega 32 de
Siigo); el stock de la tienda física es un pozo distinto. Lo que se venda en
Florida no cambia lo que la web puede vender.

LAS DOS FORMAS OBVIAS DE CONSUMIRLA HABRÍAN HECHO DAÑO, y vale dejarlo escrito
para que nadie las reintente:

  · Cantidad ABSOLUTA — borra del stock de Shopify las ventas web, porque nada
    mete esas ventas al inventario del POS (`movimientos_inventario` sólo tiene
    `venta` y `anulacion`, las dos de tienda).
  · DELTA — una cola con reintentos aplica el mismo descuento dos veces y deja
    stock fantasma. El payload no lleva delta, justamente.

SE MARCAN, NO SE BORRAN. Es la misma regla que rige los permisos y los medios
de pago en este módulo: una fila que explica qué hizo el sistema no se
desaparece. Quedan como `fallido` con su motivo, así que dentro de un año se
puede leer por qué hay 16 mensajes que nadie procesó.

Si algún día MALE quiere mostrar «disponible en tienda» en la web, esto vuelve
con mapeo de ubicación y con una sincronización de ENTRADA — no reactivando el
encolado.

Revision ID: 0017
Revises: 0016
"""
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE retail.outbox
           SET estado = 'fallido',
               procesado_en = now(),
               ultimo_error = 'descartado: la web vende contra el inventario de '
                              'Melonn, no contra el de la tienda. Sin consumidor '
                              'y sin mapeo tienda-location. Ver migracion 0017.'
         WHERE tipo = 'publicar_stock_shopify' AND estado = 'pendiente'
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE retail.outbox
           SET estado = 'pendiente', procesado_en = NULL, ultimo_error = NULL
         WHERE tipo = 'publicar_stock_shopify' AND estado = 'fallido'
    """)
