"""Permisos del POS: PIN de acceso y topes de descuento.

DESVIACION DEL DISENO. El documento 04 §3 proponia estas columnas sobre
`public.usuarios`, siguiendo el precedente de `puede_autorizar_precosteo`.
Al implementarlo se vio que no sirve: `public.usuarios` la administra el ERP y
vive en Supabase, asi que el modulo retail no podria migrarla, ni probarla
contra una base limpia, ni desplegarse sin coordinar con el resto del sistema.

Va en `retail.permisos_pos`, referenciando al usuario por id SIN llave foranea
entre esquemas — quien manda sobre el usuario sigue siendo el ERP. El modulo
retail queda autocontenido, que es lo que permite que sus 181 pruebas corran
contra una base vacia en 4 segundos.

EL PIN. Cuatro a seis digitos es debil por si solo, y por eso NUNCA vale solo:
sirve unicamente combinado con un dispositivo registrado (ADR-006), se bloquea
a los 5 intentos, y jamas da acceso al ERP.

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE retail.permisos_pos (
            usuario_id          text PRIMARY KEY,
            nombre              text NOT NULL,
            -- bcrypt, igual que las contrasenas del ERP. Nunca el PIN en claro.
            pin_hash            text,
            tiendas             text[] NOT NULL DEFAULT '{}',
            -- Configurable por rol y tienda, en la BASE y no en el codigo: una
            -- campana de fin de temporada no deberia necesitar un deploy.
            tope_descuento_pct  numeric(5,2) NOT NULL DEFAULT 0
                CHECK (tope_descuento_pct >= 0 AND tope_descuento_pct <= 100),
            puede_autorizar_descuento   boolean NOT NULL DEFAULT false,
            puede_anular_venta          boolean NOT NULL DEFAULT false,
            puede_cerrar_con_descuadre  boolean NOT NULL DEFAULT false,
            puede_ver_esperado          boolean NOT NULL DEFAULT false,
            activo              boolean NOT NULL DEFAULT true,
            -- Bloqueo por intentos: un PIN de 4 digitos sin freno se adivina
            -- en minutos.
            intentos_fallidos   integer NOT NULL DEFAULT 0,
            bloqueado_hasta     timestamptz,
            creado_en           timestamptz NOT NULL DEFAULT now(),
            actualizado_en      timestamptz NOT NULL DEFAULT now()
        )
    """)
    # Quien puede autorizar tiene que tener PIN: sin el, la pantalla ofreceria
    # una firma que nadie puede dar y la cajera quedaria en un callejon.
    op.execute("""
        ALTER TABLE retail.permisos_pos ADD CONSTRAINT ck_autorizador_con_pin
            CHECK (NOT puede_autorizar_descuento OR pin_hash IS NOT NULL)
    """)
    op.execute("""
        CREATE INDEX ix_permisos_autorizadores ON retail.permisos_pos (usuario_id)
            WHERE puede_autorizar_descuento AND activo
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS retail.permisos_pos CASCADE")
