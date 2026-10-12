"""El medio de pago «Tarjeta regalo».

Una clienta llegó a Arrayanes a pagar con una tarjeta regalo de la tienda en
línea y la caja no tenía con qué recibirla: se cobró «como datáfono», que es
decirle al arqueo y a Siigo algo que no pasó (2026-10-12).

  · Exige el CÓDIGO de la tarjeta: es lo único que deja saber cuál se usó.
  · No entra al arqueo: no es plata que llegue al cajón.
  · En Siigo va como ANTICIPO CLIENTES (8316): la plata de la tarjeta entró
    cuando se vendió, no ahora. Es la misma forma del saldo a favor.

Revision ID: 0034
Revises: 0033
"""
from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO retail.medios_pago
            (id, nombre, tipo, siigo_forma_pago_id, entra_al_arqueo,
             exige_referencia, permite_vuelto, orden, activo)
        VALUES ('tarjeta_regalo', 'Tarjeta regalo', 'otro', 8316, false,
                true, false, 7, true)
        ON CONFLICT (id) DO UPDATE SET activo = true
    """)


def downgrade() -> None:
    op.execute("UPDATE retail.medios_pago SET activo = false "
               "WHERE id = 'tarjeta_regalo'")
    op.execute("""
        DELETE FROM retail.medios_pago m WHERE m.id = 'tarjeta_regalo'
           AND NOT EXISTS (SELECT 1 FROM retail.venta_pagos p
                            WHERE p.medio_pago_id = m.id)
           AND NOT EXISTS (SELECT 1 FROM retail.movimientos_caja c
                            WHERE c.medio_pago_id = m.id)
    """)
