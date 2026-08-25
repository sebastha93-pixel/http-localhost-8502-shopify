"""Addi, Sumas y el QR de Wompi — y arreglar lo que había debajo.

LA PREGUNTA ERA «faltan tres medios de pago». Debajo había esto:

**Con tarjeta no se podía cobrar.** La pantalla mandaba `datafono_florida` y en
la base el medio se llama `datafono`: la llave foránea lo rechaza. Las ocho
ventas de prueba fueron en efectivo, por eso nunca saltó. Un POS que no cobra
con tarjeta no es un POS.

**La lista de medios estaba QUEMADA en el frontend**, así que esta tabla era
decorativa: `activo`, `orden`, `entra_al_arqueo` y `exige_referencia` no los
leía nadie. Añadir Addi habría sido tocar código. Ahora la lista sale de aquí.

**`12245` para «Transferencia / QR» parece inventado.** Los ids verificados en
el descubrimiento de Siigo son 12243 (caja) y 12244 (datáfono) para Florida;
12245 no aparece en ninguna parte y es 12244+1. El propio repo lo advierte —«no
se factura con ids adivinados»— y ya pasó con la bodega «5», que Siigo rechazó.
Se pone en NULO: es más barato volver a escribirlo si resulta que existe que
emitir la primera factura con la forma de pago equivocada.

TRES MEDIOS, TRES COMPORTAMIENTOS DISTINTOS:

  · **QR Wompi** es una transferencia: la plata cae en la cuenta de Bancolombia
    y se concilia contra el informe de Wompi. Hasta hoy caía en el cajón de
    sastre «Transferencia / QR» junto a un Nequi y a una transferencia normal,
    y por eso NINGUNO de los tres se podía cuadrar contra su propio informe.

  · **Addi y Sumas son FINANCIACIÓN**, y no son crédito de la tienda. La
    diferencia importa: en el crédito a 30 días el riesgo lo lleva MALE y no
    hay nada que cuadrar, por eso ese medio no entra al arqueo. Aquí el
    tercero ya aprobó y garantizó la compra, y entrega un informe diario — o
    sea que SÍ hay que declararlo, igual que el datáfono. Si no, una venta que
    el POS registró pero que Addi nunca aprobó no la descubre nadie.

Por eso `financiacion` es un tipo propio y no `otro`: `tipo` es lo que decide
si algo es efectivo y cómo se arquea, y meterlo en el cajón de sastre habría
sido perder justo el dato que distingue estos casos.

LOS TRES NACEN SIN ID DE SIIGO Y ESO ES DELIBERADO. No me los puedo inventar:
son por cuenta y por punto de venta. La venta funciona igual —la caja nunca se
bloquea por Siigo, ADR-002— y la factura espera, que es lo que ya hace el
outbox cuando Siigo se cae.

Revision ID: 0015
Revises: 0014
"""
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # `financiacion` como tipo propio. Ver el docstring: no es crédito de la
    # tienda ni un «otro» cualquiera.
    op.execute("""
        ALTER TABLE retail.medios_pago
            DROP CONSTRAINT IF EXISTS medios_pago_tipo_check
    """)
    op.execute("""
        ALTER TABLE retail.medios_pago
            ADD CONSTRAINT medios_pago_tipo_check
            CHECK (tipo IN ('efectivo','tarjeta','transferencia',
                            'financiacion','credito','otro'))
    """)

    # El id de Siigo pasa a ser opcional. Un medio sin id se puede COBRAR
    # —nunca se bloquea una venta por Siigo— y su factura queda pendiente.
    op.execute("""
        ALTER TABLE retail.medios_pago
            ALTER COLUMN siigo_forma_pago_id DROP NOT NULL
    """)

    # El id inventado. Mejor nulo y visible que plausible y equivocado.
    op.execute("""
        UPDATE retail.medios_pago
           SET siigo_forma_pago_id = NULL,
               nombre = 'Transferencia'
         WHERE id = 'transferencia' AND siigo_forma_pago_id = 12245
    """)

    # El orden es el de uso real en una tienda de ropa: primero lo que más se
    # cobra. La cajera no debería tener que buscar el botón de efectivo.
    op.execute("UPDATE retail.medios_pago SET orden = 1 WHERE id = 'efectivo'")
    op.execute("UPDATE retail.medios_pago SET orden = 2 WHERE id = 'datafono'")

    op.execute("""
        INSERT INTO retail.medios_pago
            (id, nombre, tipo, siigo_forma_pago_id, entra_al_arqueo,
             exige_referencia, permite_vuelto, orden, activo)
        VALUES
            -- REFERENCIA OBLIGATORIA en los tres. Es el único hilo que une una
            -- línea del POS con una línea del informe del proveedor: sin ella,
            -- cuadrar el día es comparar dos totales y encogerse de hombros
            -- cuando no dan. Y es lo que la clienta necesita para reclamar.
            ('wompi_qr', 'QR Wompi',  'transferencia', NULL, true, true,  false, 3, true),
            ('addi',     'Addi',      'financiacion',  NULL, true, true,  false, 4, true),
            ('sumas',    'Sumas Pay', 'financiacion',  NULL, true, true,  false, 5, true)
    """)

    op.execute("UPDATE retail.medios_pago SET orden = 6 WHERE id = 'transferencia'")


def downgrade() -> None:
    """SE DESACTIVA, NO SE BORRA — la misma regla que ya rige los permisos.

    Un medio de pago que ya cobró una venta explica movimientos de caja y
    líneas de arqueo. Borrarlo deja la contabilidad de ese turno llena de
    identificadores sin nombre, y de hecho ni siquiera se puede: hay llaves
    foráneas desde `movimientos_caja` y `venta_pagos`. Se apagan.

    La columna se queda ADMITIENDO NULO al bajar. Es deliberado: volver a
    ponerla obligatoria exigiría inventarle un número de Siigo a los medios que
    no lo tienen, que es justo el error que esta migración corrige. Un esquema
    algo más permisivo no rompe el código viejo —que siempre escribió un valor—
    y no destruye nada.
    """
    op.execute("""
        UPDATE retail.medios_pago
           SET activo = false
         WHERE id IN ('wompi_qr','addi','sumas')
    """)
    op.execute("""
        UPDATE retail.medios_pago
           SET siigo_forma_pago_id = 12245, nombre = 'Transferencia / QR'
         WHERE id = 'transferencia' AND siigo_forma_pago_id IS NULL
    """)
    # `financiacion` desaparece del CHECK, así que las filas que lo usan pasan
    # a 'otro'. Pierden el matiz, pero siguen explicando de dónde salió la
    # plata — que es para lo que están.
    op.execute("""
        UPDATE retail.medios_pago SET tipo = 'otro' WHERE tipo = 'financiacion'
    """)
    op.execute("""
        ALTER TABLE retail.medios_pago
            DROP CONSTRAINT IF EXISTS medios_pago_tipo_check
    """)
    op.execute("""
        ALTER TABLE retail.medios_pago
            ADD CONSTRAINT medios_pago_tipo_check
            CHECK (tipo IN ('efectivo','tarjeta','transferencia','credito','otro'))
    """)
