"""Addi y Wompi van a sus cuentas de crédito en Siigo.

Sebastián, 2026-11-05: todo lo que se venda por Addi o por Wompi va a
`13050502 ADDI - CREDITO 30 DIAS` y `13050506 WOMPI CREDITO UN DIA`, que son
las formas de pago `8298` y `8844` (las mismas que ya usa la tienda online).
Antes iban a `12245 ADDI FLORIDA` y `8353 WOMPI` (ver 0019 y 0022).

El datáfono de la feria es de Wompi: también va a 8844.

Las dos formas piden fecha de vencimiento; `factura_venta._pagos` ya la manda
(la fecha de la factura, como las facturas online). Lo ya facturado no se
toca: sólo cambia lo que se emita de aquí en adelante.

Sólo se mueve lo que sigue en el valor anterior, para no pisar una corrección
hecha a mano.

Revision ID: 0041
Revises: 0040
"""
from alembic import op

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None

ADDI, WOMPI = 8298, 8844
CAMBIOS = [  # medio, antes, ahora
    ("addi", 12245, ADDI),
    ("wompi_qr", 8353, WOMPI),
    ("datafono_feria", 12143, WOMPI),
]


def upgrade() -> None:
    for medio, antes, ahora in CAMBIOS:
        op.execute(f"""
            UPDATE retail.medios_pago SET siigo_forma_pago_id = {ahora}
             WHERE id = '{medio}' AND siigo_forma_pago_id = {antes}
        """)


def downgrade() -> None:
    for medio, antes, ahora in CAMBIOS:
        op.execute(f"""
            UPDATE retail.medios_pago SET siigo_forma_pago_id = {antes}
             WHERE id = '{medio}' AND siigo_forma_pago_id = {ahora}
        """)
