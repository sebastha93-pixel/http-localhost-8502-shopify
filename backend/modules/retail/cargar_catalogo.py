"""Cargar un catálogo REAL en el POS, desde un CSV.

POR QUÉ EXISTE. Hasta ahora la única forma de meter productos era
`semilla.py`, que es de desarrollo: trae siete prendas inventadas, hace
`TRUNCATE` de media base y **se niega a correr fuera de `localhost`**. O sea
que el POS podía desplegarse y quedarse sin nada que vender. Este archivo es
lo que faltaba entre «la base existe» y «la caja puede cobrar».

LA DIFERENCIA QUE IMPORTA CON `semilla.py`: **esto no borra nada.** Es
aditivo e idempotente — se puede correr diez veces con el mismo archivo y el
resultado es el mismo. Volver a cargarlo con un precio corregido actualiza ese
precio; no duplica la referencia ni resetea el stock de las demás.

    python -m backend.modules.retail.cargar_catalogo catalogo.csv            # ensayo
    python -m backend.modules.retail.cargar_catalogo catalogo.csv --aplicar  # escribe

**El ensayo es el modo por defecto, a propósito.** Esto escribe precios y
existencias: la dirección segura del error es no hacer nada. Hay que pedir
`--aplicar` con la mano.

FORMATO DEL CSV (cabecera obligatoria, en este orden o con estos nombres):

    referencia,nombre,color,categoria,talla,precio,cantidad
    92611-1,Jean Skinny Azul,Azul,Jeans,10,89900,4

`precio` va **EN PESOS**, como se escribe en una etiqueta: 89900. Adentro se
guarda en centavos, que es como vive todo el dinero de este módulo. Es el
error más fácil de cometer y el más caro —vender a $899 lo que vale $89.900—
así que hay una guarda explícita más abajo.
"""
from __future__ import annotations

import csv
import hashlib
import os
import sys
from typing import Dict, List, Tuple

from sqlalchemy import create_engine, text

__all__ = ["cargar", "leer_csv", "ProblemaCatalogo"]

COLUMNAS = ["referencia", "nombre", "color", "categoria", "talla",
            "precio", "cantidad"]

#  Crockford base32 SIN I, L, O ni U — el mismo alfabeto del dominio
#  `retail.ulid`. Las cuatro se excluyen para que nadie confunda un 1 con una
#  l leyendo un código en voz alta.
ALFABETO = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

#  Guardas de unidad. Una prenda de MALE no vale menos de $1.000 ni más de
#  $10.000.000; un número fuera de ese rango casi siempre es el precio
#  escrito en centavos por costumbre, o al revés.
PRECIO_MINIMO_PESOS = 1_000
PRECIO_MAXIMO_PESOS = 10_000_000


class ProblemaCatalogo(Exception):
    """El archivo no se puede cargar. Trae TODOS los problemas, no el primero."""


def _id_de(sku: str) -> str:
    """ULID determinista a partir del SKU.

    Determinista de verdad: `sha256`, no `hash()`. `semilla.py` usa
    `abs(hash(...))` y lo llama «ULID determinista», pero el hash de strings de
    Python va salteado por proceso (`PYTHONHASHSEED`), así que cambia en cada
    arranque. Aquí importa: es lo que hace que volver a cargar el mismo CSV
    apunte a las MISMAS filas en vez de crear duplicados.
    """
    h = hashlib.sha256(sku.encode("utf-8")).digest()
    n = int.from_bytes(h, "big")
    salida = []
    for _ in range(26):
        n, resto = divmod(n, 32)
        salida.append(ALFABETO[resto])
    return "".join(reversed(salida))


def leer_csv(ruta: str) -> Tuple[List[dict], List[str]]:
    """Devuelve (filas, problemas). Nunca lanza por una fila mala.

    Se recogen TODOS los problemas y se devuelven juntos. Fallar en el primero
    obliga a corregir de uno en uno un archivo de doscientas líneas, y eso lo
    que produce es que alguien acabe cargando a medias.
    """
    problemas: List[str] = []
    filas: List[dict] = []
    vistos: Dict[str, int] = {}

    with open(ruta, newline="", encoding="utf-8-sig") as f:
        lector = csv.DictReader(f)
        faltan = [c for c in COLUMNAS if c not in (lector.fieldnames or [])]
        if faltan:
            raise ProblemaCatalogo(
                f"Al CSV le faltan columnas: {', '.join(faltan)}.\n"
                f"Esperadas: {', '.join(COLUMNAS)}")

        for n, fila in enumerate(lector, start=2):   # 2 = primera tras cabecera
            ref = (fila.get("referencia") or "").strip().upper()
            talla = (fila.get("talla") or "").strip().upper()
            nombre = (fila.get("nombre") or "").strip()

            if not ref or not talla:
                problemas.append(f"línea {n}: falta referencia o talla")
                continue
            if not nombre:
                problemas.append(f"línea {n}: falta el nombre de {ref}")
                continue

            sku = f"{ref}T{talla}"
            if sku in vistos:
                problemas.append(
                    f"línea {n}: {sku} ya venía en la línea {vistos[sku]}. "
                    f"Dos filas del mismo SKU no se suman — se pisarían.")
                continue
            vistos[sku] = n

            try:
                precio = int(str(fila.get("precio") or "").replace(".", "")
                             .replace(",", "").strip())
            except ValueError:
                problemas.append(f"línea {n}: precio ilegible en {sku}")
                continue

            # LA GUARDA DE UNIDAD. Es la que evita vender a $899 lo que vale
            # $89.900 — un error que no revienta nada y se descubre al cerrar
            # la caja, cuando ya se entregó la mercancía.
            if precio < PRECIO_MINIMO_PESOS:
                problemas.append(
                    f"línea {n}: {sku} a ${precio}. El precio va EN PESOS "
                    f"(89900), no en miles ni en centavos.")
                continue
            if precio > PRECIO_MAXIMO_PESOS:
                problemas.append(
                    f"línea {n}: {sku} a ${precio:,}. Se pasa del tope; "
                    f"¿está en centavos por error?")
                continue

            try:
                cantidad = int(str(fila.get("cantidad") or "0").strip() or 0)
            except ValueError:
                problemas.append(f"línea {n}: cantidad ilegible en {sku}")
                continue
            if cantidad < 0:
                problemas.append(f"línea {n}: {sku} con cantidad negativa")
                continue

            filas.append({
                "sku": sku, "referencia": ref, "talla": talla, "nombre": nombre,
                "color": (fila.get("color") or "").strip() or None,
                "categoria": (fila.get("categoria") or "").strip() or "Sin categoría",
                "precio_con_iva": precio * 100,       # pesos → centavos
                "cantidad": cantidad,
            })

    if not filas and not problemas:
        problemas.append("el archivo no tiene ninguna fila de producto")
    return filas, problemas


def cargar(url: str, ruta_csv: str, *, ubicacion_id: str,
           usuario_id: str = "carga_catalogo", aplicar: bool = False) -> dict:
    filas, problemas = leer_csv(ruta_csv)
    if problemas:
        raise ProblemaCatalogo(
            f"{len(problemas)} problema(s) en {ruta_csv}:\n  - "
            + "\n  - ".join(problemas))

    resumen = {
        "archivo": ruta_csv,
        "skus": len(filas),
        "referencias": len({f["referencia"] for f in filas}),
        "categorias": sorted({f["categoria"] for f in filas}),
        "unidades": sum(f["cantidad"] for f in filas),
        "valor_inventario_centavos": sum(
            f["precio_con_iva"] * f["cantidad"] for f in filas),
        "aplicado": False,
        "nuevos": 0, "actualizados": 0, "ajustes_stock": 0,
    }
    if not aplicar:
        return resumen

    motor = create_engine(url, future=True)
    try:
        with motor.begin() as c:
            existe = c.execute(text(
                "SELECT 1 FROM retail.ubicaciones WHERE id = :u"),
                {"u": ubicacion_id}).first()
            if not existe:
                raise ProblemaCatalogo(
                    f"No existe la ubicación «{ubicacion_id}». Se siembra con "
                    f"la tienda, antes del catálogo.")

            for f in filas:
                vid = _id_de(f["sku"])

                # ON CONFLICT sobre `sku`, que tiene índice único: volver a
                # cargar corrige el precio o el nombre en vez de duplicar.
                nuevo = c.execute(text("""
                    INSERT INTO retail.variantes
                        (id, sku, referencia, talla, color, nombre, categoria,
                         precio_con_iva)
                    VALUES (:id, :sku, :ref, :talla, :color, :nom, :cat, :p)
                    ON CONFLICT (sku) DO UPDATE
                       SET nombre = EXCLUDED.nombre,
                           color = EXCLUDED.color,
                           categoria = EXCLUDED.categoria,
                           precio_con_iva = EXCLUDED.precio_con_iva,
                           actualizado_en = now()
                 RETURNING (xmax = 0) AS insertado, id
                """), {"id": vid, "sku": f["sku"], "ref": f["referencia"],
                       "talla": f["talla"], "color": f["color"],
                       "nom": f["nombre"], "cat": f["categoria"],
                       "p": f["precio_con_iva"]}).mappings().one()

                vid = nuevo["id"]     # si ya existía, manda SU id, no el mío
                if nuevo["insertado"]:
                    resumen["nuevos"] += 1
                else:
                    resumen["actualizados"] += 1

                # ── EL STOCK SE FIJA, Y EL LIBRO REGISTRA EL AJUSTE ─────────
                # `stock_ubicacion` es el saldo; `movimientos_inventario` es el
                # libro mayor y es APPEND-ONLY. Escribir el saldo sin su
                # asiento dejaría los dos sin cuadrar desde el primer día — y
                # el libro es lo que después permite explicar una diferencia.
                antes = c.execute(text("""
                    SELECT cantidad FROM retail.stock_ubicacion
                     WHERE ubicacion_id = :u AND variante_id = :v
                """), {"u": ubicacion_id, "v": vid}).scalar()
                antes = int(antes or 0)
                delta = f["cantidad"] - antes

                c.execute(text("""
                    INSERT INTO retail.stock_ubicacion
                        (ubicacion_id, variante_id, cantidad)
                    VALUES (:u, :v, :c)
                    ON CONFLICT (ubicacion_id, variante_id) DO UPDATE
                       SET cantidad = EXCLUDED.cantidad, actualizado_en = now()
                """), {"u": ubicacion_id, "v": vid, "c": f["cantidad"]})

                if delta != 0:
                    # `delta <> 0` es un CHECK de la tabla: un asiento de cero
                    # no es información, es ruido en el libro.
                    c.execute(text("""
                        INSERT INTO retail.movimientos_inventario
                            (ubicacion_id, variante_id, delta, saldo_despues,
                             motivo, referencia_tipo, referencia_id,
                             usuario_id, detalle)
                        VALUES (:u, :v, :d, :s, 'sincronizacion_inicial',
                                'carga_catalogo', :ref, :usr, :det)
                    """), {"u": ubicacion_id, "v": vid, "d": delta,
                           "s": f["cantidad"], "ref": os.path.basename(ruta_csv),
                           "usr": usuario_id,
                           "det": f"carga de catálogo · {f['sku']}"})
                    resumen["ajustes_stock"] += 1

            # El índice de búsqueda se reconstruye para lo cargado. Sin esto,
            # el producto EXISTE pero el buscador no lo encuentra — y desde el
            # mostrador eso es idéntico a que no exista.
            c.execute(text("""
                INSERT INTO retail.catalogo_busqueda
                    (variante_id, texto_busqueda, referencia, talla, color,
                     categoria, precio_con_iva)
                SELECT v.id,
                       retail.norm(concat_ws(' ', v.sku, v.referencia, v.nombre,
                                             v.color, v.talla, v.codigo_barras,
                                             v.categoria)),
                       v.referencia, v.talla, v.color, v.categoria,
                       v.precio_con_iva
                  FROM retail.variantes v
                 WHERE v.sku = ANY(:skus)
                ON CONFLICT (variante_id) DO UPDATE
                   SET texto_busqueda = EXCLUDED.texto_busqueda,
                       precio_con_iva = EXCLUDED.precio_con_iva,
                       categoria = EXCLUDED.categoria,
                       color = EXCLUDED.color
            """), {"skus": [f["sku"] for f in filas]})
    finally:
        motor.dispose()

    resumen["aplicado"] = True
    return resumen


def _pesos(centavos: int) -> str:
    return f"${centavos // 100:,}".replace(",", ".")


def main(argv: List[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0

    ruta = argv[0]
    aplicar = "--aplicar" in argv
    url = os.environ.get("RETAIL_DATABASE_URL", "").strip()
    ubicacion = os.environ.get("RETAIL_UBICACION", "tienda:florida").strip()

    if aplicar and not url:
        print("Falta RETAIL_DATABASE_URL.", file=sys.stderr)
        return 2

    try:
        r = cargar(url, ruta, ubicacion_id=ubicacion, aplicar=aplicar)
    except ProblemaCatalogo as e:
        print(f"\n{e}\n", file=sys.stderr)
        print("No se cargó nada.", file=sys.stderr)
        return 1

    print(f"\n  {r['skus']} SKU · {r['referencias']} referencias · "
          f"{r['unidades']} unidades")
    print(f"  categorías: {', '.join(r['categorias'])}")
    print(f"  valor del inventario: {_pesos(r['valor_inventario_centavos'])}")

    if r["aplicado"]:
        print(f"\n  APLICADO en {ubicacion}: {r['nuevos']} nuevos, "
              f"{r['actualizados']} actualizados, "
              f"{r['ajustes_stock']} ajustes de stock.\n")
    else:
        # El ensayo enseña el valor del inventario a propósito: es el número
        # con el que se detecta un precio de más o de menos ANTES de escribir.
        print("\n  ENSAYO — no se escribió nada. Si el valor de arriba cuadra "
              "con lo que esperas,\n  vuelve a correrlo con --aplicar.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
