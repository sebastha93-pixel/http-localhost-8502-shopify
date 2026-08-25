"""Devoluciones y cambios — vista 5 del handoff.

DOS TABLAS Y NO UNA, por la misma razón que `ventas` y `venta_lineas`: lo que
hay que poder preguntar es «¿cuánto queda por devolver de ESTA referencia de
ESTA venta?», y eso se responde sumando líneas. Con un JSON en una columna esa
consulta se vuelve un recorrido en Python y la regla que impide pagar dos
veces la misma prenda (INV-D1) pasa a depender de que nadie se salte el
recorrido.

`sesion_id` ES NULO A PROPÓSITO. Una devolución al método original o a crédito
de tienda no toca ningún cajón, así que no pertenece a ningún turno; sólo la
de efectivo lo exige (INV-D4). Ponerlo NOT NULL habría obligado a inventarle
un turno a un trámite que no mueve caja — y ese turno falso reaparecería
después sumando en un arqueo.

LO QUE ESTA TABLA NO GUARDA: la nota crédito. La emite POSTVENTA, que es donde
vive el motor fiscal en producción. Aquí sólo queda `caso_postventa` con el
número del caso, que es el hilo para ir a buscarla. Guardar aquí un segundo
estado fiscal sería tener dos versiones de la misma verdad, y el día que no
coincidan no hay forma de saber cuál manda.

Revision ID: 0020
Revises: 0019
"""
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE retail.devoluciones (
            id                  retail.ulid PRIMARY KEY,
            venta_id            retail.ulid NOT NULL REFERENCES retail.ventas(id),
            -- Copiado de la venta, no deducido por JOIN: es lo que la cajera
            -- tecleó para encontrarla y lo que lee en el papel.
            numero_venta        text NOT NULL,
            tienda_id           text NOT NULL REFERENCES retail.tiendas(id),
            caja_id             text REFERENCES retail.cajas(id),
            -- Nulo cuando el reembolso no toca el cajón. Ver la cabecera.
            sesion_id           retail.ulid REFERENCES retail.sesiones_caja(id),
            usuario_id          text NOT NULL,
            motivo              text NOT NULL
                CHECK (motivo IN ('talla','defecto','no_le_gusto','cambio_modelo')),
            reembolso           text NOT NULL
                CHECK (reembolso IN ('efectivo','metodo_original','credito_tienda')),
            base_gravable       retail.centavos NOT NULL DEFAULT 0,
            iva_total           retail.centavos NOT NULL DEFAULT 0,
            total               retail.centavos NOT NULL DEFAULT 0,
            unidades            integer NOT NULL DEFAULT 0,
            moneda              char(3) NOT NULL DEFAULT 'COP',
            -- El hilo hacia el caso que emite la nota crédito. Llega VACÍO y
            -- lo llena el consumidor del outbox: la devolución no espera a
            -- Postventa para registrarse (ADR-002), igual que la venta no
            -- espera a Siigo.
            caso_postventa      text,
            creada_en           timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE retail.devolucion_lineas (
            id                  bigserial PRIMARY KEY,
            devolucion_id       retail.ulid NOT NULL
                REFERENCES retail.devoluciones(id) ON DELETE CASCADE,
            sku                 text NOT NULL,
            variante_id         retail.ulid REFERENCES retail.variantes(id),
            cantidad            integer NOT NULL CHECK (cantidad > 0),
            -- El precio de CUANDO SE VENDIÓ, copiado de `venta_lineas`. Si la
            -- referencia subió de precio desde entonces, devolver al precio de
            -- hoy sería regalarle plata a la clienta — o quitársela.
            precio_unitario_con_iva retail.centavos NOT NULL
        )
    """)

    # El índice que hace barata la pregunta de INV-D1: se consulta en CADA
    # búsqueda de ticket, antes de dejar marcar nada.
    op.execute("""
        CREATE INDEX devolucion_lineas_por_venta
            ON retail.devolucion_lineas (devolucion_id, sku)
    """)
    op.execute("""
        CREATE INDEX devoluciones_por_venta ON retail.devoluciones (venta_id)
    """)
    # Para el arqueo: qué devoluciones en efectivo tocaron ESTE turno.
    op.execute("""
        CREATE INDEX devoluciones_por_sesion ON retail.devoluciones (sesion_id)
         WHERE sesion_id IS NOT NULL
    """)

    # ── LA DEVOLUCIÓN ES UN TIPO PROPIO DE MOVIMIENTO DE CAJA ───────────────
    #
    # Cabía forzarla en `retiro` o en `ajuste` y no tocar el CHECK. Sería
    # mentira, y una que se paga dos veces:
    #
    #   · `retiro` es plata que sale de la tienda hacia el banco. Mezclarla con
    #     devoluciones hace que el reporte de retiros deje de servir para lo
    #     único que sirve, que es cuadrar con la consignación.
    #   · `ajuste` es «apareció una diferencia y alguien la explicó». Una
    #     devolución no es una diferencia: es una operación prevista, con su
    #     documento y su motivo.
    #
    # Y con tipo propio, el cierre del turno puede enseñar «Devoluciones» como
    # su propia línea —que es justo lo que pide la vista 7 del handoff— sin
    # tener que adivinar qué retiros eran en realidad devoluciones.
    op.execute("""
        ALTER TABLE retail.movimientos_caja
          DROP CONSTRAINT IF EXISTS movimientos_caja_tipo_check
    """)
    op.execute("""
        ALTER TABLE retail.movimientos_caja
          ADD CONSTRAINT movimientos_caja_tipo_check CHECK (tipo IN
            ('base_inicial','venta','anulacion','retiro','ingreso','gasto',
             'ajuste','devolucion'))
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS retail.devolucion_lineas")
    op.execute("DROP TABLE IF EXISTS retail.devoluciones")

    # ⚠️ EL CHECK **NO** VUELVE A SU FORMA ESTRECHA, Y ES DELIBERADO.
    #
    # El primer intento sí lo estrechaba, y reventó en la primera prueba: los
    # movimientos de tipo 'devolucion' viven en `movimientos_caja`, que esta
    # migración no creó y por tanto no borra. Estrechar el CHECK con esas filas
    # dentro es una `CheckViolation`, o sea una migración que no se puede
    # revertir — y este repo prueba `revertir → aplicar` en CI justamente
    # porque «una migración que no se puede revertir es una que nadie se atreve
    # a desplegar un viernes».
    #
    # Las dos salidas que sí funcionaban eran peores:
    #   · borrar esas filas → un arqueo al que se le quitan movimientos deja de
    #     cuadrar, y nadie sabe por qué;
    #   · reclasificarlas como 'ajuste' → reescribir el libro para que encaje
    #     con el esquema, que es exactamente al revés de para qué existe.
    #
    # Así que el CHECK se queda ancho. No cuesta nada: un CHECK es una guarda
    # contra erratas, no el sitio donde vive el significado. Con las tablas
    # borradas ya no hay código que escriba ese tipo, y las filas que ya
    # existían siguen contando en su arqueo, que es lo único que importa.
    pass
