"""Contar la plata, en vez de teclear cuánta hay.

DOS AGUJEROS, UN MECANISMO.

**La apertura supone.** La base sale de `tiendas.base_caja` y nadie mira el
cajón. Si amaneció con $280.000 en vez de $300.000 —alguien sacó vueltas la
noche anterior, el cierre anterior dejó de menos, el sobre de la caja fuerte
venía corto—, ese faltante aparece ocho horas después en el arqueo de quien
cerró. La persona equivocada, el momento equivocado, y ya sin forma de saber
dónde ocurrió.

**Y teclear un total es la forma más débil de conteo ciego.** El cierre es
ciego (INV-C4): la cajera no ve lo esperado hasta que declara. Pero declarar
es escribir un número, y quien lleva el día en la cabeza puede escribir una
cifra plausible sin abrir el cajón. Meter CANTIDADES POR DENOMINACIÓN obliga a
que el dato de entrada sea el conteo físico: el total lo saca el sistema, y la
cajera nunca lo escribe.

Sólo el EFECTIVO. Un datáfono no tiene denominaciones y su cifra se lee del
cierre del terminal, que ya es un conteo de otra cosa.

POR QUÉ UNA TABLA Y NO UNA CONSTANTE. La moneda de $50 no circula y la de $100
casi tampoco: contar una fila que siempre da cero, dos veces al día, en cada
tienda, es un impuesto sobre el turno. Una tienda la apaga. Y el día que el
Banco de la República cambie la familia de billetes esto no es un despliegue.

Revision ID: 0014
Revises: 0013
"""
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE retail.denominaciones (
            valor_centavos  retail.centavos PRIMARY KEY,
            tipo            text NOT NULL CHECK (tipo IN ('billete','moneda')),
            activa          boolean NOT NULL DEFAULT true,
            CONSTRAINT denominacion_positiva CHECK (valor_centavos::bigint > 0)
        )
    """)

    # El cajón colombiano de 2026. Se ordena por valor descendente al leer, que
    # es como se cuenta: los billetes grandes primero.
    op.execute("""
        INSERT INTO retail.denominaciones (valor_centavos, tipo, activa) VALUES
            (10000000,'billete',true), (5000000,'billete',true),
            (2000000,'billete',true),  (1000000,'billete',true),
            (500000,'billete',true),   (200000,'billete',true),
            (100000,'moneda',true),    (50000,'moneda',true),
            (20000,'moneda',true),     (10000,'moneda',true),
            -- La de $50 nace apagada: no circula. Existe la fila para que una
            -- tienda que todavía las recibe pueda encenderla sin migración.
            (5000,'moneda',false)
    """)

    # El conteo. `momento` distingue las dos puntas del turno: la misma tabla
    # sirve para la base de la mañana y para el arqueo de la noche, y así el
    # supervisor ve el turno completo en una sola consulta.
    op.execute("""
        CREATE TABLE retail.conteos_denominacion (
            sesion_id       retail.ulid NOT NULL
                            REFERENCES retail.sesiones_caja(id),
            momento         text NOT NULL CHECK (momento IN ('apertura','cierre')),
            valor_centavos  retail.centavos NOT NULL
                            REFERENCES retail.denominaciones(valor_centavos),
            cantidad        integer NOT NULL CHECK (cantidad >= 0),
            usuario_id      text NOT NULL,
            creado_en       timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (sesion_id, momento, valor_centavos)
        )
    """)

    # LO QUE SE CONTÓ AL ABRIR, y en cuánto difirió de lo que la tienda tiene
    # configurado. Va en la sesión y no se deriva al leer: `tiendas.base_caja`
    # puede cambiar mañana, y entonces la diferencia de este turno —que ya se
    # justificó y se firmó— dejaría de reproducirse.
    op.execute("""
        ALTER TABLE retail.sesiones_caja
            ADD COLUMN base_esperada     retail.centavos,
            ADD COLUMN base_justificacion text
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE retail.sesiones_caja
            DROP COLUMN IF EXISTS base_justificacion,
            DROP COLUMN IF EXISTS base_esperada
    """)
    op.execute("DROP TABLE IF EXISTS retail.conteos_denominacion")
    op.execute("DROP TABLE IF EXISTS retail.denominaciones")
