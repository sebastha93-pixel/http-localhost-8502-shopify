"""El saldo a favor que deja un cambio, y el medio de pago que lo consume.

Un cambio con «crédito de tienda» no dejaba nada que la clienta pudiera usar:
el crédito era una frase en la pantalla y un caso en Postventa. Si la prenda
nueva valía menos —o no se llevaba nada— no había papel que entregarle ni
forma de cobrarle la siguiente compra con ese saldo (Florida, 2026-10-10).

  · `saldos_a_favor`: uno por devolución, con un código corto (`SF-00012`)
    que va impreso en el comprobante. `usado` nunca pasa de `monto`.
  · `saldo_usos`: qué venta consumió cuánto. Es lo que permite devolver el
    saldo si esa venta se anula.
  · El medio de pago `saldo_a_favor`: en Siigo es ANTICIPO CLIENTES (8316),
    la misma forma con la que Postventa hace la nota crédito y cruza el
    reemplazo. No es plata que entre al cajón: no va al arqueo.

Revision ID: 0031
Revises: 0030
"""
from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE IF NOT EXISTS retail.saldo_a_favor_seq")
    op.execute("""
        CREATE TABLE retail.saldos_a_favor (
            id             text PRIMARY KEY,
            codigo         text NOT NULL UNIQUE,
            devolucion_id  text NOT NULL UNIQUE
                           REFERENCES retail.devoluciones(id),
            numero_origen  text NOT NULL,
            cliente_id     text REFERENCES retail.clientes(id),
            tienda_id      text NOT NULL REFERENCES retail.tiendas(id),
            monto          bigint NOT NULL CHECK (monto > 0),
            usado          bigint NOT NULL DEFAULT 0
                           CHECK (usado >= 0 AND usado <= monto),
            creado_por     text NOT NULL,
            creado_en      timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_saldos_cliente ON retail.saldos_a_favor "
               "(cliente_id) WHERE cliente_id IS NOT NULL")
    op.execute("""
        CREATE TABLE retail.saldo_usos (
            saldo_id   text NOT NULL REFERENCES retail.saldos_a_favor(id),
            venta_id   text NOT NULL REFERENCES retail.ventas(id),
            monto      bigint NOT NULL CHECK (monto > 0),
            creado_en  timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (saldo_id, venta_id)
        )
    """)
    op.execute("""
        INSERT INTO retail.medios_pago
            (id, nombre, tipo, siigo_forma_pago_id, entra_al_arqueo,
             exige_referencia, permite_vuelto, orden, activo)
        VALUES ('saldo_a_favor', 'Saldo a favor', 'credito', 8316, false,
                true, false, 6, true)
        ON CONFLICT (id) DO UPDATE SET activo = true
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS retail.saldo_usos")
    op.execute("DROP TABLE IF EXISTS retail.saldos_a_favor")
    op.execute("DROP SEQUENCE IF EXISTS retail.saldo_a_favor_seq")
    # Si ya hubo cobros con él no se puede borrar: se apaga.
    op.execute("UPDATE retail.medios_pago SET activo = false "
               "WHERE id = 'saldo_a_favor'")
    op.execute("""
        DELETE FROM retail.medios_pago m WHERE m.id = 'saldo_a_favor'
           AND NOT EXISTS (SELECT 1 FROM retail.venta_pagos p
                            WHERE p.medio_pago_id = m.id)
           AND NOT EXISTS (SELECT 1 FROM retail.movimientos_caja c
                            WHERE c.medio_pago_id = m.id)
    """)
