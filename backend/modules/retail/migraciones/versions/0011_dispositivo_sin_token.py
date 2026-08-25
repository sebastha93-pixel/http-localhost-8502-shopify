"""Un dispositivo ya no es una credencial, es una identidad.

`dispositivos.token_hash` era del esquema de ADR-006: cada equipo se registraba
con credenciales de administradora y recibía un token de larga vida. Ese ADR se
revisó —una sola credencial, correo y contraseña— y el token se quedó ahí,
obligatorio y sin nadie que lo llenara.

Lo que SÍ hace falta es que el equipo se identifique, por una razón que no
tiene nada que ver con seguridad: **los bloques de consecutivos se arriendan
por dispositivo**. Sin identidad, dos tabletas abriendo la misma caja reciben
el MISMO bloque vigente con el mismo `siguiente`, y las dos empiezan a numerar
desde ahí. Dos tiquetes con el mismo número, y una de las dos ventas rebotando
al sincronizar.

Así que el registro pasa a ser automático: el navegador genera su ULID la
primera vez, lo guarda, y lo manda al pedir bloque. No autentica nada —quien
autentica es el login del ERP— sólo dice «soy este equipo».

Revision ID: 0011
Revises: 0010
"""
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE retail.dispositivos DROP COLUMN IF EXISTS token_hash")
    # Quien tenía la sesión abierta cuando el equipo apareció. Deja de ser un
    # acto administrativo, así que puede faltar.
    op.execute("""
        ALTER TABLE retail.dispositivos ALTER COLUMN registrado_por DROP NOT NULL
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE retail.dispositivos
            ADD COLUMN token_hash text NOT NULL DEFAULT ''
    """)
    op.execute("ALTER TABLE retail.dispositivos ALTER COLUMN token_hash DROP DEFAULT")
    op.execute("""
        UPDATE retail.dispositivos SET registrado_por = coalesce(registrado_por, '')
    """)
    op.execute("""
        ALTER TABLE retail.dispositivos ALTER COLUMN registrado_por SET NOT NULL
    """)
