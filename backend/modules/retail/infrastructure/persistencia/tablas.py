"""Tablas del schema `retail`, en SQLAlchemy Core.

DELIBERADAMENTE NO SE USA EL ORM DECLARATIVO sobre los agregados. Mapear
`Venta` a una clase declarativa metería SQLAlchemy dentro del dominio, y eso
rompe la única promesa que sostiene toda la arquitectura: que las reglas del
dinero se prueban sin base de datos, sin red y en milisegundos.

El precio es escribir el mapeo a mano en cada repositorio. Es más código, y a
cambio el dominio no tiene ni un import de infraestructura — verificado por
`test_guardas_arquitectura`.

La definición canónica del esquema es la migración de Alembic, no este
archivo: aquí sólo se declara lo que los repositorios necesitan tocar.
"""
from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    CHAR,
    Column,
    DateTime,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB

__all__ = ["metadata", "ventas", "venta_lineas", "venta_pagos", "sesiones_caja",
           "movimientos_caja", "arqueo_conteos", "stock_ubicacion",
           "movimientos_inventario", "outbox", "auditoria"]

metadata = MetaData(schema="retail")

_ULID = CHAR(26)
# ADR-008: el dinero es un entero de 64 bits. Nunca Numeric, nunca Float.
_CENTAVOS = BigInteger


ventas = Table(
    "ventas", metadata,
    Column("id", _ULID, primary_key=True),
    Column("numero", Text, nullable=False),
    Column("prefijo", Text, nullable=False),
    Column("consecutivo", BigInteger, nullable=False),
    Column("tienda_id", Text, nullable=False),
    Column("caja_id", Text, nullable=False),
    Column("sesion_id", _ULID, nullable=False),
    Column("dispositivo_id", _ULID),
    Column("cajera_id", Text, nullable=False),
    Column("cliente_id", _ULID),
    Column("estado", Text, nullable=False),
    Column("estado_fiscal", Text, nullable=False),
    Column("origen", Text, nullable=False),
    Column("subtotal", _CENTAVOS, nullable=False),
    Column("descuento_total", _CENTAVOS, nullable=False),
    Column("base_gravable", _CENTAVOS, nullable=False),
    Column("iva_total", _CENTAVOS, nullable=False),
    Column("total", _CENTAVOS, nullable=False),
    Column("pagado", _CENTAVOS, nullable=False),
    Column("vuelto", _CENTAVOS, nullable=False),
    Column("moneda", CHAR(3), nullable=False),
    Column("creada_en", DateTime(timezone=True)),
    Column("creada_en_dispositivo", DateTime(timezone=True)),
    Column("cerrada_en", DateTime(timezone=True)),
    Column("sincronizada_en", DateTime(timezone=True)),
    Column("sesion_desfasada", Boolean, nullable=False),
    Column("anulada_en", DateTime(timezone=True)),
    Column("anulada_por", Text),
    Column("motivo_anulacion", Text),
    Column("documento_origen_id", _ULID),
)

venta_lineas = Table(
    "venta_lineas", metadata,
    Column("id", _ULID, primary_key=True),
    Column("venta_id", _ULID, nullable=False),
    Column("orden", Integer, nullable=False),
    Column("variante_id", _ULID, nullable=False),
    Column("sku", Text, nullable=False),
    Column("descripcion", Text, nullable=False),
    Column("cantidad", Integer, nullable=False),
    Column("precio_unitario", _CENTAVOS, nullable=False),
    Column("descuento_tipo", Text),
    Column("descuento_valor", Numeric(10, 4)),
    Column("descuento_monto", _CENTAVOS, nullable=False),
    Column("descuento_motivo", Text),
    Column("autorizado_por", Text),
    Column("obsequio", Boolean, nullable=False),
    Column("tasa_iva", Numeric(5, 2), nullable=False),
    Column("base_gravable", _CENTAVOS, nullable=False),
    Column("iva_monto", _CENTAVOS, nullable=False),
    Column("total_linea", _CENTAVOS, nullable=False),
    Column("creada_en", DateTime(timezone=True)),
)

venta_pagos = Table(
    "venta_pagos", metadata,
    Column("id", _ULID, primary_key=True),
    Column("venta_id", _ULID, nullable=False),
    Column("medio_pago_id", Text, nullable=False),
    Column("monto", _CENTAVOS, nullable=False),
    Column("referencia", Text),
    Column("registrado_en", DateTime(timezone=True)),
)

sesiones_caja = Table(
    "sesiones_caja", metadata,
    Column("id", _ULID, primary_key=True),
    Column("tienda_id", Text, nullable=False),
    Column("caja_id", Text, nullable=False),
    Column("numero_turno", BigInteger, nullable=False),
    Column("estado", Text, nullable=False),
    Column("base_inicial", _CENTAVOS, nullable=False),
    Column("abierta_por", Text, nullable=False),
    Column("abierta_en", DateTime(timezone=True)),
    Column("cerrada_por", Text),
    Column("cerrada_en", DateTime(timezone=True)),
    Column("diferencia_total", _CENTAVOS),
    Column("justificacion", Text),
    Column("autorizada_por", Text),
    Column("dispositivo_id", _ULID),
)

movimientos_caja = Table(
    "movimientos_caja", metadata,
    Column("id", _ULID, primary_key=True),
    Column("sesion_id", _ULID, nullable=False),
    Column("tipo", Text, nullable=False),
    Column("medio_pago_id", Text),
    Column("monto", _CENTAVOS, nullable=False),
    Column("motivo", Text, nullable=False),
    Column("venta_id", _ULID),
    Column("usuario_id", Text, nullable=False),
    Column("autorizado_por", Text),
    Column("creado_en", DateTime(timezone=True)),
)

arqueo_conteos = Table(
    "arqueo_conteos", metadata,
    Column("sesion_id", _ULID, primary_key=True),
    Column("medio_pago_id", Text, primary_key=True),
    Column("declarado", _CENTAVOS, nullable=False),
    Column("esperado", _CENTAVOS, nullable=False),
    Column("declarado_por", Text, nullable=False),
    Column("declarado_en", DateTime(timezone=True)),
)

stock_ubicacion = Table(
    "stock_ubicacion", metadata,
    Column("ubicacion_id", Text, primary_key=True),
    Column("variante_id", _ULID, primary_key=True),
    Column("cantidad", Integer, nullable=False),
    Column("reservado", Integer, nullable=False),
    Column("stock_minimo", Integer, nullable=False),
    Column("actualizado_en", DateTime(timezone=True)),
)

movimientos_inventario = Table(
    "movimientos_inventario", metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("ubicacion_id", Text, nullable=False),
    Column("variante_id", _ULID, nullable=False),
    Column("delta", Integer, nullable=False),
    Column("saldo_despues", Integer, nullable=False),
    Column("motivo", Text, nullable=False),
    Column("referencia_tipo", Text, nullable=False),
    Column("referencia_id", Text, nullable=False),
    Column("usuario_id", Text, nullable=False),
    Column("detalle", Text, nullable=False),
    Column("creado_en", DateTime(timezone=True)),
)

outbox = Table(
    "outbox", metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("tipo", Text, nullable=False),
    Column("agregado_tipo", Text, nullable=False),
    Column("agregado_id", Text, nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("estado", Text, nullable=False),
    Column("intentos", Integer, nullable=False),
    Column("max_intentos", Integer, nullable=False),
    Column("proximo_intento_en", DateTime(timezone=True)),
    Column("ultimo_error", Text),
    Column("creado_en", DateTime(timezone=True)),
    Column("procesado_en", DateTime(timezone=True)),
)

auditoria = Table(
    "auditoria", metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("ocurrido_en", DateTime(timezone=True), primary_key=True),
    Column("tienda_id", Text),
    Column("caja_id", Text),
    Column("sesion_id", _ULID),
    Column("usuario_id", Text),
    Column("dispositivo_id", _ULID),
    Column("evento", Text, nullable=False),
    Column("severidad", Text, nullable=False),
    Column("agregado_tipo", Text),
    Column("agregado_id", Text),
    Column("payload", JSONB, nullable=False),
    Column("hash_anterior", Text),
    Column("hash", String, nullable=False),
)
