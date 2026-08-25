"""Fuera el PIN de autorización.

DECISIÓN DEL NEGOCIO, no técnica: a la plataforma se entra con correo y
contraseña, y no va a haber una segunda credencial. El PIN era eso — un
segundo secreto, de cuatro dígitos, compartido de hecho entre quienes lo
usaban, con su propio bloqueo por intentos y su propia superficie de fuga.

Lo que el PIN habilitaba pasa a resolverse con la identidad que ya existe:

  · Descuento sobre el tope → no pasa. El tope de quien tiene la sesión
    abierta es el límite; para más, entra alguien con un tope mayor.
  · Cierre con descuadre grande → `puede_cerrar_con_descuadre`, que ya existía
    en esta misma tabla y nunca se había usado.

`puede_autorizar_descuento` se va porque sin PIN no autoriza nada: era el
permiso de teclear la firma de un tercero, y ese flujo ya no existe. Dejarlo
sería una casilla en la administración que no hace nada.

Las columnas de bloqueo (`intentos_fallidos`, `bloqueado_hasta`) sólo servían
para frenar la adivinación de un PIN de cuatro dígitos. Sin PIN no frenan nada.

`down()` las devuelve todas —incluida la restricción de que quien autoriza
tenga PIN—, pero no los hashes: esos no se pueden reconstruir. Si el PIN
vuelve, hay que volver a asignarlos. En este módulo todavía no hay ninguno en
producción, así que hoy no se pierde nada.

Revision ID: 0007
Revises: 0006
"""
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE retail.permisos_pos
            DROP CONSTRAINT IF EXISTS ck_autorizador_con_pin
    """)
    for columna in ("pin_hash", "intentos_fallidos", "bloqueado_hasta",
                    "puede_autorizar_descuento"):
        op.execute(
            f"ALTER TABLE retail.permisos_pos DROP COLUMN IF EXISTS {columna}")


def downgrade() -> None:
    op.execute("""
        ALTER TABLE retail.permisos_pos
            ADD COLUMN pin_hash                 text,
            ADD COLUMN intentos_fallidos        integer NOT NULL DEFAULT 0,
            ADD COLUMN bloqueado_hasta          timestamptz,
            ADD COLUMN puede_autorizar_descuento boolean NOT NULL DEFAULT false
    """)
    op.execute("""
        ALTER TABLE retail.permisos_pos
            ADD CONSTRAINT ck_autorizador_con_pin
            CHECK (NOT puede_autorizar_descuento OR pin_hash IS NOT NULL)
    """)
