"""Constancia de las alertas diarias que ya salieron.

El correo de «vendido sin existencia» sale una vez al día. El backend corre
con varios procesos y se reinicia en cada despliegue: sin una marca en la
base, un reinicio a las 7:05 lo mandaría dos veces y dos procesos a la vez,
también. La llave (tipo, fecha) es el candado: quien logra insertar, envía.

Revision ID: 0028
Revises: 0027
"""
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS retail.alertas_enviadas (
            tipo          text NOT NULL,
            fecha         date NOT NULL,
            casos         integer NOT NULL DEFAULT 0,
            destinatarios text NOT NULL DEFAULT '',
            resultado     text NOT NULL DEFAULT '',
            enviada_en    timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (tipo, fecha)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS retail.alertas_enviadas")
