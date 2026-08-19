"""Las formas de pago de Siigo, leídas de la cuenta real.

Se consultaron con `railway run` contra el servicio `backend`, o sea con las
credenciales cargadas en el proceso y sin que salieran de la infraestructura.
Sólo lectura: `GET /v1/payment-types?document_type=FV`.

LOS TRES DE LA TIENDA SON INEQUÍVOCOS, y lo que los delata es que son
consecutivos: 12243 «Caja general Florida», 12244 «Datafono Florida», 12245
«ADDI FLORIDA». Los tres se dieron de alta juntos, para el mismo punto.

  · efectivo  → 12243  (ya estaba)
  · datafono  → 12244  (ya estaba)
  · addi      → 12245  «ADDI FLORIDA»
  · sumas     → 12218  «SUMAS PAY TIENDA»

`SUMAS PAY TIENDA` (12218) y no `SUMAS PAY CREDITO 30 DIAS` (12217): el nombre
distingue el cobro en mostrador del crédito a 30 días, que es otra cosa.
Confirmado también que el nombre comercial correcto es **Sumas Pay**.

DOS SE QUEDAN EN NULO A PROPÓSITO, porque la cuenta tiene más de un candidato y
elegir mal manda la venta a la cuenta contable equivocada — un error que no
revienta, sale en el balance:

  · **wompi_qr** — hay `8353 WOMPI` y `8844 WOMPI CREDITO UN DIA`. Ninguno dice
    «Florida» ni «tienda». Sospecho 8353, pero sospechar no basta para mover
    plata de sitio.
  · **transferencia** — el candidato sería `2719 BANCOLOMBIA CUENTA DE AHORROS`,
    pero ese nombre es la cuenta bancaria, no un medio de cobro en mostrador.

Un medio sin id se COBRA igual y su factura queda pendiente (ADR-002). Es el
mismo comportamiento que ya tenían: mejor pendiente que mal imputada.

Revision ID: 0019
Revises: 0018
"""
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE retail.medios_pago SET siigo_forma_pago_id = 12245,
               nombre = 'Addi'
         WHERE id = 'addi'
    """)
    op.execute("""
        UPDATE retail.medios_pago SET siigo_forma_pago_id = 12218,
               nombre = 'Sumas Pay'
         WHERE id = 'sumas'
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE retail.medios_pago SET siigo_forma_pago_id = NULL
         WHERE id IN ('addi', 'sumas')
    """)
