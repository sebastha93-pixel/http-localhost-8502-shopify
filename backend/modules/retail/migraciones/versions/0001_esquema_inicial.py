"""Esquema inicial del módulo retail (POS).

El DDL va escrito a mano y no autogenerado. Este esquema usa cosas que el
autogenerate de Alembic no modela: dominios (`retail.centavos`), índices
únicos PARCIALES —que son los que hacen cumplir invariantes—, índices GIN de
trigramas, particionado por rango y REVOKE sobre las tablas append-only.

Las invariantes que la BASE hace cumplir, y no un `if` que alguien puede
olvidar:

  ux_sesion_abierta  · una sola sesión de caja abierta por caja      (INV-C1)
  ux_venta_numero    · un ticket no se repite en la misma caja       (INV-V10)
  ux_doc_emitido     · máximo un documento fiscal emitido por venta  (INV-F1)
  CHECK pagado>=total en ventas cerradas                             (INV-V3)
  CHECK precio>0 salvo obsequio autorizado                           (INV-V7)

Revision ID: 0001
Revises:
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS retail")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gin")

    # `unaccent` no es IMMUTABLE, así que no se puede indexar directamente.
    # Este envoltorio sí lo es y permite el índice de búsqueda del catálogo.
    op.execute("""
        CREATE OR REPLACE FUNCTION retail.norm(t text) RETURNS text
          LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
        $$ SELECT lower(public.unaccent('public.unaccent'::regdictionary,
                                        coalesce(t, ''))) $$
    """)

    # ADR-008: el dinero SIEMPRE en centavos enteros. Nunca numeric, nunca float.
    op.execute("CREATE DOMAIN retail.centavos AS bigint")
    op.execute("""
        CREATE DOMAIN retail.ulid AS char(26)
          CHECK (VALUE ~ '^[0-9A-HJKMNP-TV-Z]{26}$')
    """)

    # ── Estructura física ───────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE retail.tiendas (
            id                      text PRIMARY KEY,
            nombre                  text NOT NULL,
            activa                  boolean NOT NULL DEFAULT true,
            siigo_bodega_id         integer,
            siigo_centro_costo_id   integer,
            permite_stock_negativo  boolean NOT NULL DEFAULT true,
            cierre_ciego            boolean NOT NULL DEFAULT true,
            umbral_descuadre        retail.centavos NOT NULL DEFAULT 500000,
            zona_horaria            text NOT NULL DEFAULT 'America/Bogota',
            creada_en               timestamptz NOT NULL DEFAULT now()
        )
    """)

    op.execute("""
        CREATE TABLE retail.cajas (
            id                      text PRIMARY KEY,
            tienda_id               text NOT NULL REFERENCES retail.tiendas(id),
            nombre                  text NOT NULL,
            -- NULL mientras no se confirme por API. El sistema se niega a
            -- facturar con un id adivinado: saldría con el prefijo de otro
            -- punto y descuadraría la numeración DIAN.
            prefijo_factura         text,
            siigo_documento_id      integer,
            tipo_documento_fiscal   text NOT NULL DEFAULT 'factura_electronica'
                CHECK (tipo_documento_fiscal IN ('factura_electronica','pos_electronico')),
            activa                  boolean NOT NULL DEFAULT true,
            creada_en               timestamptz NOT NULL DEFAULT now()
        )
    """)

    op.execute("""
        CREATE TABLE retail.dispositivos (
            id                  retail.ulid PRIMARY KEY,
            caja_id             text NOT NULL REFERENCES retail.cajas(id),
            nombre              text NOT NULL,
            token_hash          text NOT NULL,
            activo              boolean NOT NULL DEFAULT true,
            registrado_por      text NOT NULL,
            registrado_en       timestamptz NOT NULL DEFAULT now(),
            ultimo_visto_en     timestamptz,
            ultimo_desfase_ms   integer,
            version_app         text,
            revocado_en         timestamptz,
            revocado_por        text
        )
    """)

    op.execute("""
        CREATE TABLE retail.ubicaciones (
            id              text PRIMARY KEY,
            tipo            text NOT NULL
                CHECK (tipo IN ('tienda','bodega','transito','externa')),
            nombre          text NOT NULL,
            tienda_id       text REFERENCES retail.tiendas(id),
            siigo_bodega_id integer,
            activa          boolean NOT NULL DEFAULT true
        )
    """)

    op.execute("""
        CREATE TABLE retail.medios_pago (
            id                  text PRIMARY KEY,
            nombre              text NOT NULL,
            tipo                text NOT NULL
                CHECK (tipo IN ('efectivo','tarjeta','transferencia','credito','otro')),
            tienda_id           text REFERENCES retail.tiendas(id),
            siigo_forma_pago_id integer NOT NULL,
            entra_al_arqueo     boolean NOT NULL DEFAULT true,
            exige_referencia    boolean NOT NULL DEFAULT false,
            permite_vuelto      boolean NOT NULL DEFAULT false,
            orden               integer NOT NULL DEFAULT 0,
            activo              boolean NOT NULL DEFAULT true
        )
    """)

    op.execute("""
        CREATE TABLE retail.clientes (
            id                  retail.ulid PRIMARY KEY,
            tipo_documento      text NOT NULL DEFAULT 'CC'
                CHECK (tipo_documento IN ('CC','NIT','CE','PP','TI')),
            numero_documento    text NOT NULL,
            dv                  char(1),
            nombre              text NOT NULL,
            apellido            text NOT NULL DEFAULT '',
            telefono            text,
            correo              text,
            ciudad              text,
            direccion           text,
            siigo_customer_id   text,
            notas               text,
            creado_por          text,
            creado_en           timestamptz NOT NULL DEFAULT now(),
            actualizado_en      timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX ux_cliente_doc
            ON retail.clientes (tipo_documento, numero_documento)
    """)
    op.execute("""
        CREATE INDEX ix_cliente_busqueda ON retail.clientes
            USING gin ((retail.norm(nombre || ' ' || apellido || ' '
                        || numero_documento || ' ' || coalesce(telefono,'')))
                       gin_trgm_ops)
    """)

    op.execute("""
        CREATE TABLE retail.variantes (
            id                  retail.ulid PRIMARY KEY,
            -- Formato MALE'DENIM: <referencia>T<talla>. En '92611-1T10' la
            -- referencia es '92611-1' y la talla es '10'. Igual que
            -- siigo._parse_ref_talla; desviarse le daría a la misma prenda dos
            -- identidades dentro del mismo sistema.
            sku                 text NOT NULL,
            referencia          text NOT NULL,
            talla               text NOT NULL,
            color               text NOT NULL DEFAULT '',
            nombre              text NOT NULL,
            codigo_barras       text,
            -- SIEMPRE sin IVA (INV-CAT1). Guardarlo al revés es exactamente
            -- cómo un cambio salió facturado por 67.960 en vez de 169.900.
            precio_base         retail.centavos NOT NULL,
            tasa_iva            numeric(5,2) NOT NULL DEFAULT 19.00,
            siigo_code          text,
            shopify_variant_id  text,
            imagen_url          text,
            activa              boolean NOT NULL DEFAULT true,
            actualizado_en      timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE UNIQUE INDEX ux_variante_sku ON retail.variantes (sku)")
    op.execute("""
        CREATE UNIQUE INDEX ux_variante_barras ON retail.variantes (codigo_barras)
            WHERE codigo_barras IS NOT NULL
    """)
    op.execute("CREATE INDEX ix_variante_delta ON retail.variantes (actualizado_en)")

    op.execute("""
        CREATE TABLE retail.catalogo_busqueda (
            variante_id      retail.ulid PRIMARY KEY REFERENCES retail.variantes(id),
            texto_busqueda   text NOT NULL,
            referencia       text NOT NULL,
            talla            text NOT NULL,
            color            text NOT NULL,
            precio_base      retail.centavos NOT NULL,
            stock_por_tienda jsonb NOT NULL DEFAULT '{}',
            actualizado_en   timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE INDEX ix_catalogo_trgm ON retail.catalogo_busqueda
            USING gin (texto_busqueda gin_trgm_ops)
    """)

    # ── Consecutivos: lo que hace posible el offline ────────────────────────
    op.execute("""
        CREATE TABLE retail.bloques_consecutivo (
            id              bigserial PRIMARY KEY,
            caja_id         text NOT NULL REFERENCES retail.cajas(id),
            prefijo         text NOT NULL,
            desde           bigint NOT NULL,
            hasta           bigint NOT NULL,
            siguiente       bigint NOT NULL,
            arrendado_en    timestamptz NOT NULL DEFAULT now(),
            arrendado_a     retail.ulid REFERENCES retail.dispositivos(id),
            agotado         boolean NOT NULL DEFAULT false,
            CHECK (desde <= siguiente AND siguiente <= hasta + 1)
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX ux_bloque_vigente
            ON retail.bloques_consecutivo (caja_id) WHERE NOT agotado
    """)

    # ── Caja ────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE retail.sesiones_caja (
            id                  retail.ulid PRIMARY KEY,
            tienda_id           text NOT NULL REFERENCES retail.tiendas(id),
            caja_id             text NOT NULL REFERENCES retail.cajas(id),
            numero_turno        bigint NOT NULL,
            estado              text NOT NULL DEFAULT 'abierta'
                CHECK (estado IN ('abierta','en_arqueo','cerrada')),
            base_inicial        retail.centavos NOT NULL CHECK (base_inicial >= 0),
            abierta_por         text NOT NULL,
            abierta_en          timestamptz NOT NULL DEFAULT now(),
            cerrada_por         text,
            cerrada_en          timestamptz,
            diferencia_total    retail.centavos,
            justificacion       text,
            autorizada_por      text,
            dispositivo_id      retail.ulid REFERENCES retail.dispositivos(id),
            CHECK (estado <> 'cerrada' OR cerrada_en IS NOT NULL)
        )
    """)
    # INV-C1: garantizado por la BASE, no por un if. Una regla comprobada en
    # Python tiene una ventana de carrera; el índice no.
    op.execute("""
        CREATE UNIQUE INDEX ux_sesion_abierta
            ON retail.sesiones_caja (caja_id) WHERE estado <> 'cerrada'
    """)

    op.execute("""
        CREATE TABLE retail.movimientos_caja (
            id              retail.ulid PRIMARY KEY,
            sesion_id       retail.ulid NOT NULL REFERENCES retail.sesiones_caja(id),
            tipo            text NOT NULL CHECK (tipo IN
                ('base_inicial','venta','anulacion','retiro','ingreso','gasto','ajuste')),
            medio_pago_id   text REFERENCES retail.medios_pago(id),
            monto           retail.centavos NOT NULL,
            motivo          text NOT NULL DEFAULT '',
            venta_id        retail.ulid,
            usuario_id      text NOT NULL,
            autorizado_por  text,
            creado_en       timestamptz NOT NULL DEFAULT now(),
            CHECK (tipo NOT IN ('retiro','gasto') OR motivo <> '')
        )
    """)
    op.execute("""
        CREATE INDEX ix_mov_caja_sesion
            ON retail.movimientos_caja (sesion_id, creado_en)
    """)

    op.execute("""
        CREATE TABLE retail.arqueo_conteos (
            sesion_id       retail.ulid NOT NULL REFERENCES retail.sesiones_caja(id),
            medio_pago_id   text NOT NULL REFERENCES retail.medios_pago(id),
            declarado       retail.centavos NOT NULL,
            -- Congelado al declarar: una venta offline que entre después no
            -- puede cambiar una diferencia que la cajera ya firmó.
            esperado        retail.centavos NOT NULL,
            declarado_por   text NOT NULL,
            declarado_en    timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (sesion_id, medio_pago_id)
        )
    """)

    # ── Ventas ──────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE retail.ventas (
            id                  retail.ulid PRIMARY KEY,
            numero              text NOT NULL,
            prefijo             text NOT NULL,
            consecutivo         bigint NOT NULL,
            tienda_id           text NOT NULL REFERENCES retail.tiendas(id),
            caja_id             text NOT NULL REFERENCES retail.cajas(id),
            sesion_id           retail.ulid NOT NULL REFERENCES retail.sesiones_caja(id),
            dispositivo_id      retail.ulid REFERENCES retail.dispositivos(id),
            cajera_id           text NOT NULL,
            cliente_id          retail.ulid REFERENCES retail.clientes(id),
            estado              text NOT NULL DEFAULT 'borrador'
                CHECK (estado IN ('borrador','cerrada','anulada','descartada')),
            estado_fiscal       text NOT NULL DEFAULT 'no_aplica'
                CHECK (estado_fiscal IN ('no_aplica','pendiente','enviando','emitido',
                                         'rechazado','fallido','discrepante')),
            origen              text NOT NULL DEFAULT 'en_linea'
                CHECK (origen IN ('en_linea','fuera_de_linea')),
            subtotal            retail.centavos NOT NULL DEFAULT 0,
            descuento_total     retail.centavos NOT NULL DEFAULT 0,
            base_gravable       retail.centavos NOT NULL DEFAULT 0,
            iva_total           retail.centavos NOT NULL DEFAULT 0,
            total               retail.centavos NOT NULL DEFAULT 0,
            pagado              retail.centavos NOT NULL DEFAULT 0,
            vuelto              retail.centavos NOT NULL DEFAULT 0,
            moneda              char(3) NOT NULL DEFAULT 'COP',
            creada_en           timestamptz NOT NULL DEFAULT now(),
            creada_en_dispositivo timestamptz,
            cerrada_en          timestamptz,
            sincronizada_en     timestamptz,
            sesion_desfasada    boolean NOT NULL DEFAULT false,
            anulada_en          timestamptz,
            anulada_por         text,
            motivo_anulacion    text,
            documento_origen_id retail.ulid,
            CHECK (total >= 0),
            CHECK (estado <> 'cerrada' OR cerrada_en IS NOT NULL),
            CHECK (estado <> 'cerrada' OR pagado >= total),
            CHECK (estado <> 'anulada' OR motivo_anulacion IS NOT NULL)
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX ux_venta_numero
            ON retail.ventas (caja_id, prefijo, consecutivo)
    """)
    op.execute("""
        CREATE INDEX ix_ventas_sesion ON retail.ventas (sesion_id)
            WHERE estado = 'cerrada'
    """)
    op.execute("""
        CREATE INDEX ix_ventas_tienda ON retail.ventas (tienda_id, cerrada_en DESC)
    """)
    op.execute("""
        CREATE INDEX ix_ventas_cliente ON retail.ventas (cliente_id, cerrada_en DESC)
            WHERE cliente_id IS NOT NULL
    """)
    op.execute("""
        CREATE INDEX ix_ventas_fiscal ON retail.ventas (estado_fiscal)
            WHERE estado_fiscal IN ('pendiente','enviando','rechazado','fallido','discrepante')
    """)

    op.execute("""
        CREATE TABLE retail.venta_lineas (
            id                  retail.ulid PRIMARY KEY,
            venta_id            retail.ulid NOT NULL
                                REFERENCES retail.ventas(id) ON DELETE CASCADE,
            orden               integer NOT NULL,
            variante_id         retail.ulid NOT NULL REFERENCES retail.variantes(id),
            -- Congelados: si el catálogo cambia mañana, esta línea no cambia.
            sku                 text NOT NULL,
            descripcion         text NOT NULL,
            cantidad            integer NOT NULL CHECK (cantidad > 0),
            precio_unitario     retail.centavos NOT NULL CHECK (precio_unitario >= 0),
            descuento_tipo      text CHECK (descuento_tipo IN ('porcentaje','valor')),
            descuento_valor     numeric(10,4),
            descuento_monto     retail.centavos NOT NULL DEFAULT 0,
            descuento_motivo    text,
            autorizado_por      text,
            obsequio            boolean NOT NULL DEFAULT false,
            tasa_iva            numeric(5,2) NOT NULL DEFAULT 19.00,
            base_gravable       retail.centavos NOT NULL DEFAULT 0,
            iva_monto           retail.centavos NOT NULL DEFAULT 0,
            total_linea         retail.centavos NOT NULL DEFAULT 0,
            creada_en           timestamptz NOT NULL DEFAULT now(),
            CHECK (precio_unitario > 0 OR (obsequio AND autorizado_por IS NOT NULL)),
            CHECK (descuento_monto = 0 OR descuento_motivo IS NOT NULL)
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX ux_linea_orden ON retail.venta_lineas (venta_id, orden)
    """)
    op.execute("CREATE INDEX ix_linea_variante ON retail.venta_lineas (variante_id)")

    op.execute("""
        CREATE TABLE retail.venta_pagos (
            id              retail.ulid PRIMARY KEY,
            venta_id        retail.ulid NOT NULL
                            REFERENCES retail.ventas(id) ON DELETE CASCADE,
            medio_pago_id   text NOT NULL REFERENCES retail.medios_pago(id),
            monto           retail.centavos NOT NULL CHECK (monto > 0),
            referencia      text,
            registrado_en   timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_pagos_venta ON retail.venta_pagos (venta_id)")
    op.execute("""
        CREATE INDEX ix_pagos_medio
            ON retail.venta_pagos (medio_pago_id, registrado_en)
    """)

    # ── Inventario ──────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE retail.stock_ubicacion (
            ubicacion_id    text NOT NULL REFERENCES retail.ubicaciones(id),
            variante_id     retail.ulid NOT NULL REFERENCES retail.variantes(id),
            cantidad        integer NOT NULL DEFAULT 0,
            reservado       integer NOT NULL DEFAULT 0 CHECK (reservado >= 0),
            stock_minimo    integer NOT NULL DEFAULT 0,
            actualizado_en  timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (ubicacion_id, variante_id)
        )
    """)
    op.execute("""
        CREATE INDEX ix_stock_bajo ON retail.stock_ubicacion (ubicacion_id)
            WHERE cantidad <= stock_minimo
    """)

    op.execute("""
        CREATE TABLE retail.movimientos_inventario (
            id              bigserial PRIMARY KEY,
            ubicacion_id    text NOT NULL REFERENCES retail.ubicaciones(id),
            variante_id     retail.ulid NOT NULL REFERENCES retail.variantes(id),
            delta           integer NOT NULL CHECK (delta <> 0),
            saldo_despues   integer NOT NULL,
            motivo          text NOT NULL CHECK (motivo IN (
                'venta','anulacion','ingreso_compra','ajuste_conteo','merma',
                'traslado_salida','traslado_entrada','devolucion','sincronizacion_inicial')),
            referencia_tipo text NOT NULL,
            referencia_id   text NOT NULL,
            usuario_id      text NOT NULL,
            detalle         text NOT NULL DEFAULT '',
            creado_en       timestamptz NOT NULL DEFAULT now(),
            CHECK (referencia_id <> '')
        )
    """)
    op.execute("""
        CREATE INDEX ix_mov_inv_variante ON retail.movimientos_inventario
            (ubicacion_id, variante_id, creado_en DESC)
    """)
    op.execute("""
        CREATE INDEX ix_mov_inv_ref
            ON retail.movimientos_inventario (referencia_tipo, referencia_id)
    """)
    # Libro mayor: append-only. Corregir es un movimiento contrario (INV-I5).
    op.execute("REVOKE UPDATE, DELETE ON retail.movimientos_inventario FROM PUBLIC")

    # ── Fiscal y outbox ─────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE retail.documentos_fiscales (
            id                  retail.ulid PRIMARY KEY,
            venta_id            retail.ulid NOT NULL REFERENCES retail.ventas(id),
            tipo                text NOT NULL CHECK (tipo IN
                ('factura_electronica','pos_electronico','nota_credito')),
            proveedor           text NOT NULL DEFAULT 'siigo',
            estado              text NOT NULL DEFAULT 'pendiente'
                CHECK (estado IN ('pendiente','enviando','verificando','emitido',
                                  'rechazado','fallido','discrepante')),
            numero              text,
            cufe                text,
            documento_externo_id text,
            pdf_url             text,
            xml_url             text,
            payload_snapshot    jsonb NOT NULL,
            respuesta_cruda     jsonb,
            verificacion        jsonb,
            intentos            integer NOT NULL DEFAULT 0,
            ultimo_error        text,
            proximo_intento_en  timestamptz,
            creado_en           timestamptz NOT NULL DEFAULT now(),
            emitido_en          timestamptz
        )
    """)
    # INV-F1: máximo un documento emitido por venta. Con esto, dos workers
    # emitiendo a la vez producen un error, no una factura duplicada ante la DIAN.
    op.execute("""
        CREATE UNIQUE INDEX ux_doc_emitido ON retail.documentos_fiscales (venta_id)
            WHERE estado = 'emitido' AND tipo <> 'nota_credito'
    """)
    op.execute("""
        CREATE INDEX ix_doc_cola ON retail.documentos_fiscales (proximo_intento_en)
            WHERE estado IN ('pendiente','rechazado')
    """)

    op.execute("""
        CREATE TABLE retail.outbox (
            id                  bigserial PRIMARY KEY,
            tipo                text NOT NULL,
            agregado_tipo       text NOT NULL,
            agregado_id         text NOT NULL,
            payload             jsonb NOT NULL,
            estado              text NOT NULL DEFAULT 'pendiente'
                CHECK (estado IN ('pendiente','procesando','procesado','fallido')),
            intentos            integer NOT NULL DEFAULT 0,
            max_intentos        integer NOT NULL DEFAULT 8,
            proximo_intento_en  timestamptz NOT NULL DEFAULT now(),
            ultimo_error        text,
            creado_en           timestamptz NOT NULL DEFAULT now(),
            procesado_en        timestamptz
        )
    """)
    op.execute("""
        CREATE INDEX ix_outbox_cola ON retail.outbox (proximo_intento_en, id)
            WHERE estado = 'pendiente'
    """)

    # ── Auditoría encadenada (ADR-010) ──────────────────────────────────────
    op.execute("""
        CREATE TABLE retail.auditoria (
            id              bigserial,
            ocurrido_en     timestamptz NOT NULL DEFAULT now(),
            tienda_id       text,
            caja_id         text,
            sesion_id       retail.ulid,
            usuario_id      text,
            dispositivo_id  retail.ulid,
            evento          text NOT NULL,
            severidad       text NOT NULL DEFAULT 'info'
                CHECK (severidad IN ('info','aviso','critico')),
            agregado_tipo   text,
            agregado_id     text,
            payload         jsonb NOT NULL DEFAULT '{}',
            ip              inet,
            hash_anterior   text,
            hash            text NOT NULL,
            PRIMARY KEY (id, ocurrido_en)
        ) PARTITION BY RANGE (ocurrido_en)
    """)
    op.execute("""
        CREATE TABLE retail.auditoria_2026_08 PARTITION OF retail.auditoria
            FOR VALUES FROM ('2026-08-01') TO ('2026-09-01')
    """)
    op.execute("""
        CREATE TABLE retail.auditoria_2026_09 PARTITION OF retail.auditoria
            FOR VALUES FROM ('2026-09-01') TO ('2026-10-01')
    """)
    op.execute("""
        CREATE INDEX ix_audit_evento ON retail.auditoria (evento, ocurrido_en DESC)
    """)
    op.execute("""
        CREATE INDEX ix_audit_usuario ON retail.auditoria (usuario_id, ocurrido_en DESC)
    """)
    op.execute("""
        CREATE INDEX ix_audit_critico ON retail.auditoria (ocurrido_en DESC)
            WHERE severidad = 'critico'
    """)
    op.execute("REVOKE UPDATE, DELETE ON retail.auditoria FROM PUBLIC")


def downgrade() -> None:
    """Reversible de verdad: CI corre upgrade y downgrade en cada build.

    Una migración que no se puede revertir es una que nadie se atreve a
    desplegar un viernes.
    """
    for tabla in [
        "auditoria", "outbox", "documentos_fiscales",
        "movimientos_inventario", "stock_ubicacion",
        "venta_pagos", "venta_lineas", "ventas",
        "arqueo_conteos", "movimientos_caja", "sesiones_caja",
        "bloques_consecutivo", "catalogo_busqueda", "variantes",
        "clientes", "medios_pago", "ubicaciones", "dispositivos",
        "cajas", "tiendas",
    ]:
        op.execute(f"DROP TABLE IF EXISTS retail.{tabla} CASCADE")
    op.execute("DROP DOMAIN IF EXISTS retail.ulid")
    op.execute("DROP DOMAIN IF EXISTS retail.centavos")
    op.execute("DROP FUNCTION IF EXISTS retail.norm(text)")
