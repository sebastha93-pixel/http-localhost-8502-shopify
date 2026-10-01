"""La auditoría se quedó sin particiones y el POS dejó de poder vender.

LO QUE PASÓ, y es el fallo más caro que ha tenido este módulo. `retail.auditoria`
está particionada por mes y la 0001 creó DOS particiones: agosto y septiembre de
2026. El 1 de octubre, a las 00:00, toda escritura de auditoría empezó a
devolver:

    no partition of relation "auditoria" found for row

Y como la constancia se escribe en la MISMA transacción que la venta (ADR-004,
que es justo lo que hace que no exista una venta sin rastro), eso no degrada el
POS: lo apaga. No se puede abrir turno, no se puede cobrar, no se puede
devolver. Se descubrió corriendo las pruebas: 72 fallos y 81 errores donde el
día anterior había 0.

Nadie lo notó antes porque la base de producción nunca se había usado, y en
desarrollo las fechas caían dentro de las dos particiones sembradas.

QUÉ SE HACE AQUÍ, en dos capas y a propósito:

  1. **Particiones mensuales hasta diciembre de 2027.** Lo que tocaba.
  2. **Una partición POR DEFECTO.** Es la que importa: con ella, una fila
     fuera de todo rango se guarda igual en vez de tumbar la caja. Una tienda
     no puede dejar de cobrar porque un calendario se acabó.

La capa 2 no sustituye a la 1: una `DEFAULT` que acumula meses impide crear
después la partición de ese mes (Postgres encuentra filas en conflicto). Por
eso `asegurar_particiones` —que corre con el verificador, cada seis horas— va
creando los meses por delante, y la de por defecto debería quedarse vacía.
Si algún día tiene filas, es la señal de que el job lleva meses dormido.

Revision ID: 0021
Revises: 0020
"""
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None

#  Desde octubre de 2026 (el mes que faltaba) hasta el cierre de 2027.
DESDE = (2026, 10)
HASTA = (2027, 12)
POR_DEFECTO = "auditoria_sin_rango"


def _meses():
    y, m = DESDE
    while (y, m) <= HASTA:
        sy, sm = (y + 1, 1) if m == 12 else (y, m + 1)
        yield (f"auditoria_{y}_{m:02d}",
               f"{y}-{m:02d}-01", f"{sy}-{sm:02d}-01")
        y, m = sy, sm


def upgrade() -> None:
    for nombre, desde, hasta in _meses():
        op.execute(f"""
            CREATE TABLE IF NOT EXISTS retail.{nombre}
                PARTITION OF retail.auditoria
                FOR VALUES FROM ('{desde}') TO ('{hasta}')
        """)
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS retail.{POR_DEFECTO}
            PARTITION OF retail.auditoria DEFAULT
    """)


def downgrade() -> None:
    #  OJO: esto BORRA los eventos de octubre de 2026 en adelante, porque el
    #  esquema al que se vuelve —dos particiones, agosto y septiembre— no
    #  tiene dónde ponerlos. Revertir aquí es una decisión de quien la ejecuta,
    #  no un paso rutinario. `DROP TABLE` ya desengancha la partición.
    for nombre, _, _ in _meses():
        op.execute(f"DROP TABLE IF EXISTS retail.{nombre}")
    op.execute(f"DROP TABLE IF EXISTS retail.{POR_DEFECTO}")
