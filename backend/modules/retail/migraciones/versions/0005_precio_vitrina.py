"""El precio pasa a ser el de VITRINA. Vuelta al modelo correcto.

POR QUE. `precio_base` guardaba el precio SIN IVA y la pantalla se lo volvia a
sumar. Ese viaje no siempre regresa: para una prenda de $139.900 NINGUNA base
da ese total —el importe salta de 13.989.999 a 13.990.001— y la rejilla
mostraba $139.900,01. Uno de cada seis precios redondos es inalcanzable asi.

El modelo correcto es el que dice el handoff y el que usa el comercio
colombiano: el precio ES el de la etiqueta y el IVA se DERIVA de el
(`separar_iva`). Asi el total es exacto por definicion y base + IVA siempre
suman de vuelta.

LA CONVERSION. Los valores existentes estan sin IVA, asi que se les suma el
impuesto para volverlos precio de vitrina. Es reversible: el downgrade
deshace la suma.

Revision ID: 0005
Revises: 0004
"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for tabla in ("variantes", "catalogo_busqueda"):
        op.execute(f"""
            ALTER TABLE retail.{tabla}
                RENAME COLUMN precio_base TO precio_con_iva
        """)

    # Los datos venian SIN IVA: se les suma para volverlos precio de vitrina.
    op.execute("""
        UPDATE retail.variantes
           SET precio_con_iva = precio_con_iva
             + round(precio_con_iva * tasa_iva / 100)
    """)
    op.execute("""
        UPDATE retail.catalogo_busqueda c
           SET precio_con_iva = v.precio_con_iva
          FROM retail.variantes v WHERE v.id = c.variante_id
    """)

    op.execute("""
        COMMENT ON COLUMN retail.variantes.precio_con_iva IS
        'Precio de VITRINA, con IVA incluido. El impuesto se deriva de aqui, '
        'no al reves: guardar la base hacia que algunos precios no regresaran '
        'y la pantalla mostrara centavos que no existen.'
    """)
    op.execute("""
        COMMENT ON COLUMN retail.venta_lineas.precio_unitario IS
        'Precio de VITRINA congelado al vender, con IVA. base_gravable e '
        'iva_monto son una lectura de total_linea.'
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE retail.variantes
           SET precio_con_iva = round(precio_con_iva / (1 + tasa_iva / 100))
    """)
    op.execute("""
        UPDATE retail.catalogo_busqueda c
           SET precio_con_iva = v.precio_con_iva
          FROM retail.variantes v WHERE v.id = c.variante_id
    """)
    for tabla in ("variantes", "catalogo_busqueda"):
        op.execute(f"""
            ALTER TABLE retail.{tabla}
                RENAME COLUMN precio_con_iva TO precio_base
        """)
