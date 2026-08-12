"""Siembra de desarrollo del POS.

POR QUÉ EXISTE. Las pruebas de integración borran y recrean el esquema en cada
corrida, así que después de un `pytest` la base local queda vacía y el POS no
tiene qué mostrar. Sin esto, la siembra vive como un bloque de SQL en el
historial de alguien — que es como decir que no existe.

    RETAIL_DATABASE_URL=postgresql+psycopg://localhost/retail_pos_test \\
        python -m backend.modules.retail.semilla

SE NIEGA A CORRER CONTRA UNA BASE QUE NO SEA LOCAL. Borra tablas enteras: un
default apuntando a producción es la clase de error que se descubre después.
"""
from __future__ import annotations

import os
import sys
from sqlalchemy import create_engine, text

TIENDA = "florida"
CAJA = "florida_caja1"
UBICACION = "tienda:florida"
SESION = "01JQ8X4T5N6P7R8S9V0W1X2Y3Z"

# Catálogo de muestra. Los precios son los de VITRINA, con IVA, y así se
# guardan: el impuesto se deriva de ellos. Guardar la base y volver a sumar
# hacía que $139.900 saliera como $139.900,01 en la rejilla.
CATALOGO = [
    ("92611-1", "Jean Skinny Azul",     "Azul",    "Jeans",     16990000),
    ("92611-2", "Jean Skinny Negro",    "Negro",   "Jeans",     16990000),
    ("93634-1", "Jean Mom Índigo",      "Índigo",  "Jeans",     18990000),
    ("94120-1", "Short Denim Claro",    "Claro",   "Shorts",    10990000),
    ("95330-1", "Falda Midi Denim",     "Medio",   "Faldas",    13990000),
    ("96010-1", "Chaqueta Denim Oversize", "Azul", "Chaquetas", 24990000),
    ("97220-1", "Top Blanco Algodón",   "Blanco",  "Tops",       7990000),
]
TALLAS = ["4", "6", "8", "10", "12"]


def sembrar(url: str) -> dict:
    if "localhost" not in url and "127.0.0.1" not in url:
        raise SystemExit(
            f"La siembra BORRA datos y sólo corre contra una base local.\n"
            f"Recibió: {url[:50]}…"
        )


    # Aplica las migraciones primero. Las pruebas dejan el esquema BORRADO al
    # terminar, así que sembrar sin esto falla con «relation does not exist» —
    # y obliga a recordar dos comandos en vez de uno. Si ya está al día, no
    # hace nada.
    from backend.modules.retail.migraciones.runner import aplicar
    aplicar(url)

    motor = create_engine(url, future=True)
    with motor.begin() as c:
        c.execute(text("""
            TRUNCATE retail.venta_pagos, retail.venta_lineas, retail.ventas,
                     retail.documentos_fiscales, retail.arqueo_conteos,
                     retail.movimientos_caja, retail.sesiones_caja,
                     retail.stock_ubicacion, retail.movimientos_inventario,
                     retail.catalogo_busqueda, retail.variantes,
                     retail.medios_pago, retail.ubicaciones, retail.cajas,
                     retail.tiendas, retail.permisos_pos, retail.outbox
            RESTART IDENTITY CASCADE
        """))

        c.execute(text("""
            INSERT INTO retail.tiendas
                (id, nombre, siigo_bodega_id, siigo_centro_costo_id,
                 razon_social, nit, direccion, telefono, mensaje_tirilla)
            VALUES (:t, 'Tienda Principal', 48, 774,
                    'Dirty Jeans S.A.S.', '900000000-0',
                    'Direccion pendiente', '(604) 000 0000',
                    'Cambios dentro de 30 dias presentando esta tirilla.')
        """), {"t": TIENDA})
        # NIT y direccion de RELLENO a proposito: los reales van en la
        # configuracion de la tienda, no en una semilla de desarrollo. Y
        # `resolucion_dian` queda NULL: sin ella la tirilla se imprime como
        # comprobante interno y lo dice, que es lo correcto hasta la Fase 3.
        c.execute(text("""
            INSERT INTO retail.cajas (id, tienda_id, nombre, prefijo_factura)
            VALUES (:c, :t, 'Caja 01', 'FV-20')
        """), {"c": CAJA, "t": TIENDA})
        c.execute(text("""
            INSERT INTO retail.ubicaciones
                (id, tipo, nombre, tienda_id, siigo_bodega_id)
            VALUES (:u, 'tienda', 'Tienda Principal', :t, 48)
        """), {"u": UBICACION, "t": TIENDA})

        for mid, nombre, tipo, siigo, vuelto in [
            ("efectivo", "Efectivo", "efectivo", 12243, True),
            ("datafono", "Tarjeta", "tarjeta", 12244, False),
            ("transferencia", "Transferencia / QR", "transferencia", 12245, False),
        ]:
            c.execute(text("""
                INSERT INTO retail.medios_pago
                    (id, nombre, tipo, siigo_forma_pago_id, permite_vuelto)
                VALUES (:i, :n, :tp, :s, :v)
            """), {"i": mid, "n": nombre, "tp": tipo, "s": siigo, "v": vuelto})

        # El turno NO se abre aquí: se abre desde la pantalla, que es justo el
        # flujo que hay que poder probar. Dejarlo abierto haría que la pantalla
        # de acceso siempre lo reanudara y nunca se ejercitara.

        # Ya no hay PIN. Lo que cada quien puede hacer sale de SU fila, y la
        # identidad viene del login del ERP con correo y contraseña.
        c.execute(text("""
            INSERT INTO retail.permisos_pos
                (usuario_id, nombre, rol, tiendas, tope_descuento_pct,
                 puede_anular_venta, puede_cerrar_con_descuadre,
                 puede_ver_esperado)
            VALUES ('laura', 'Laura M.', 'Supervisora', ARRAY[:t], 35,
                    true, true, true)
        """), {"t": TIENDA})
        c.execute(text("""
            INSERT INTO retail.permisos_pos
                (usuario_id, nombre, rol, tiendas, tope_descuento_pct)
            VALUES ('maria', 'María R.', 'Cajera', ARRAY[:t], 10)
        """), {"t": TIENDA})
        c.execute(text("""
            INSERT INTO retail.permisos_pos
                (usuario_id, nombre, rol, tiendas, tope_descuento_pct)
            VALUES ('sofia', 'Sofía L.', 'Cajera', ARRAY[:t], 10)
        """), {"t": TIENDA})

        n = 0
        for ref, nombre, color, categoria, con_iva in CATALOGO:
            for i, talla in enumerate(TALLAS):
                n += 1
                # ULID determinista: la misma siembra da los mismos ids, así
                # que un enlace guardado sigue funcionando tras re-sembrar.
                vid = f"{abs(hash(ref + talla)):026d}"[:26].upper()
                vid = "".join("0123456789ABCDEFGHJKMNPQRSTVWXYZ"[int(d)] for d in vid)
                c.execute(text("""
                    INSERT INTO retail.variantes
                        (id, sku, referencia, talla, color, nombre, categoria,
                         precio_con_iva, codigo_barras)
                    VALUES (:id, :sku, :ref, :talla, :color, :nom, :cat, :p, :cb)
                """), {"id": vid, "sku": f"{ref}T{talla}", "ref": ref,
                       "talla": talla, "color": color, "nom": nombre,
                       "cat": categoria, "p": con_iva,
                       "cb": f"770{n:010d}"})
                # Stock variado a propósito: hace falta ver el chip agotado y
                # el «último» en la pantalla, no sólo el caso feliz.
                cantidad = [4, 2, 0, 5, 1][i % 5]
                c.execute(text("""
                    INSERT INTO retail.stock_ubicacion
                        (ubicacion_id, variante_id, cantidad)
                    VALUES (:u, :v, :c)
                """), {"u": UBICACION, "v": vid, "c": cantidad})

        c.execute(text("""
            INSERT INTO retail.catalogo_busqueda
                (variante_id, texto_busqueda, referencia, talla, color,
                 categoria, precio_con_iva)
            SELECT v.id,
                   retail.norm(concat_ws(' ', v.sku, v.referencia, v.nombre,
                                         v.color, v.talla, v.codigo_barras,
                                         v.categoria)),
                   v.referencia, v.talla, v.color, v.categoria, v.precio_con_iva
              FROM retail.variantes v
        """))

        resumen = c.execute(text("""
            SELECT (SELECT count(*) FROM retail.variantes) AS variantes,
                   (SELECT count(DISTINCT referencia) FROM retail.variantes) AS refs,
                   (SELECT count(DISTINCT categoria) FROM retail.variantes) AS cats,
                   (SELECT sum(cantidad) FROM retail.stock_ubicacion) AS unidades
        """)).mappings().one()

    motor.dispose()
    return dict(resumen)


if __name__ == "__main__":
    url = os.environ.get("RETAIL_DATABASE_URL", "").strip()
    if not url:
        sys.exit("Falta RETAIL_DATABASE_URL. Va explícita: esto borra datos.")
    r = sembrar(url)
    print(f"✅ {r['refs']} referencias · {r['variantes']} variantes · "
          f"{r['cats']} categorías · {r['unidades']} unidades")
    print("   maria/sofia: tope 10 %  ·  laura: tope 35 %, cierra con descuadre")
    print("   sin turno abierto: se abre desde /pos/acceso")
