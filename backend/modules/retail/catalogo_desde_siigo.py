"""El catálogo de una tienda, sacado del inventario de Siigo.

POR QUÉ VIVE EN EL REPO Y NO EN UN SCRIPT SUELTO: se escribió dos veces en un
directorio temporal y se perdió las dos. Cargar el catálogo de una tienda no
es una tarea de una sola vez —entra mercancía, cambian precios, se abre una
tienda nueva— y cada vez que se rehace a mano se vuelven a cometer los mismos
errores. Aquí quedan escritos, con sus pruebas.

    python -m backend.modules.retail.catalogo_desde_siigo Arrayanes tienda.csv
    python -m backend.modules.retail.cargar_catalogo tienda.csv          # ensayo
    RETAIL_UBICACION=tienda:arrayanes \\
        python -m backend.modules.retail.cargar_catalogo tienda.csv --aplicar

LO QUE SE APRENDIÓ CARGANDO ARRAYANES (681 SKU, 2026-10-01), y que esto hace:

* **El precio de Siigo viene CON IVA sólo si el producto está marcado
  `tax_included`.** De 682 prendas, 681 lo traían y UNA no: su precio salía
  ×1,19 y era el único que no terminaba en 900. Se marca como problema en vez
  de cargarlo: un precio adivinado se descubre cobrando.

* **El código de barras NO siempre es el SKU.** A once etiquetas les falta la
  «T» (`42606-110`) o llevan el código de otra referencia. Va en su columna:
  sin eso, la pistola escanea y no pasa nada.

* **Hay códigos que no son prendas** (`5353` bolsa pequeña, `5354` bolsa
  grande, `P004` pañoleta). No tienen talla que extraer, pero SE VENDEN: la
  bolsa va cobrada en casi todas las facturas de la tienda. Entran con su
  código tal cual como SKU —es el que Siigo espera en la factura— y talla
  «U». Los que no tienen precio, o lo tienen sin IVA incluido (`010`, `101`),
  se siguen reportando.

* Sólo entra lo que TIENE EXISTENCIA en esa bodega. Un catálogo con todo el
  inventario de la marca hace que la cajera ofrezca lo que no tiene.
"""
from __future__ import annotations

import csv
import re
import sys
import time
from typing import Dict, List, Tuple

__all__ = ["filas_de_productos", "escribir_csv", "ref_talla", "IVA_PORCENTAJE",
           "PRECIO_MINIMO",
           "precios_por_referencia", "sin_precio_en_siigo"]

IVA_PORCENTAJE = 19.0
#  Tallas numéricas (4, 10, 12) o de letra (S, M, XL). Lo que no calce no es
#  una prenda vendible por talla y se reporta en vez de inventarle una.
_SKU = re.compile(r"^(.*?)T([0-9]{1,3}|[A-Z]{1,3})$", re.I)


def ref_talla(code: str) -> Tuple[str, str]:
    """`92633-1T6` → `('92633-1', '6')`. Vacíos si no es un SKU de prenda."""
    m = _SKU.match((code or "").strip())
    if not m:
        return "", ""
    return m.group(1).rstrip("-"), m.group(2).upper()


def _precio_con_iva(producto: dict):
    """El precio de la ETIQUETA. Devuelve `(pesos, venía_con_iva)`.

    `None` si el producto no tiene precio: sin precio NO se carga. Un cambio
    de 169.900 salió por 67.960 por tomar el precio de otra fuente.
    """
    for lista in (producto.get("prices") or []):
        for item in (lista.get("price_list") or []):
            valor = item.get("value")
            if valor:
                v = float(valor)
                con_iva = bool(producto.get("tax_included"))
                return (v if con_iva else v * (1 + IVA_PORCENTAJE / 100)), con_iva
    return None, None


def _nombre_limpio(producto: dict, code: str) -> str:
    """Siigo repite el código dentro del nombre: «26602-1T6 JEAN FLARE…»."""
    nombre = (producto.get("name") or "").strip()
    if nombre.upper().startswith(code.upper()):
        nombre = nombre[len(code):].strip(" .-")
    return nombre.rstrip(".").strip() or code


#  Por debajo de esto no es un precio de venta: es un código de control
#  (`002LLAVERO` a $1). El mismo piso que usa `cargar_catalogo`.
PRECIO_MINIMO = 1_000


def _precio_propio(pr: dict):
    """El precio de etiqueta que Siigo tiene para ESE producto, o `None` si
    no sirve: en $0, marcado sin IVA incluido, o por debajo del piso."""
    precio, con_iva = _precio_con_iva(pr)
    if not precio or not con_iva or precio < PRECIO_MINIMO:
        return None
    return int(round(precio))


def precios_por_referencia(productos: List[dict]) -> Dict[str, int]:
    """El precio de cada referencia según SUS OTRAS TALLAS.

    Una referencia vale lo mismo en todas sus tallas. Si a la talla 28 le
    falta el precio en Siigo y la 30 lo tiene, ése es. Sólo cuando todas las
    que lo tienen coinciden: con dos precios distintos no se elige.
    """
    vistos: Dict[str, set] = {}
    for pr in productos:
        ref, talla = ref_talla((pr.get("code") or "").strip())
        precio = _precio_propio(pr)
        if ref and talla and precio:
            vistos.setdefault(ref, set()).add(precio)
    return {ref: next(iter(p)) for ref, p in vistos.items() if len(p) == 1}


def sin_precio_en_siigo(productos: List[dict], bodegas) -> List[str]:
    """Los códigos con existencia en esas bodegas a los que Siigo no les da
    un precio útil ni por sus otras tallas. Son los que hay que ir a
    preguntarle a otra fuente."""
    por_ref = precios_por_referencia(productos)
    faltan = []
    for pr in productos:
        if not pr.get("stock_control"):
            continue
        if not any(float(w.get("quantity") or 0) > 0
                   and (w.get("id") in bodegas or w.get("name") in bodegas)
                   for w in (pr.get("warehouses") or [])):
            continue
        code = (pr.get("code") or "").strip()
        if not code or _precio_propio(pr) or _precio_con_iva(pr)[0]:
            continue           # tiene precio (aunque esté mal marcado)
        if ref_talla(code)[0] in por_ref:
            continue
        faltan.append(code)
    return faltan


def filas_de_productos(productos: List[dict], bodega,
                       precios_de_respaldo: Dict[str, int] = None,
                       ) -> Tuple[List[dict], List[str]]:
    """Las filas del catálogo y los problemas, SIN tocar la red.

    `bodega` es el NOMBRE de la bodega en Siigo («Arrayanes») o su id (37).

    Devuelve los dos: un cargador que sólo devuelve filas esconde lo que dejó
    fuera, y lo que queda fuera es justo lo que alguien tiene que mirar.

    UNA PRENDA CON EXISTENCIA NO SE QUEDA FUERA POR UN PRECIO MAL PUESTO EN
    SIIGO. Pasó con `94609-1`: 26 unidades en Arrayanes, 26 en Florida, y el
    precio en $0. La tienda la tenía colgada y la caja no la encontraba. El
    precio se busca en este orden, y la fila dice de dónde salió:

      1. el de Siigo, si sirve;
      2. el de las otras tallas de la misma referencia;
      3. `precios_de_respaldo[código]` — el precio de lista de la tienda en
         línea, que quien llama trae de Shopify.

    Sólo si ninguno lo da se reporta y se deja fuera: una prenda no se vende
    a un precio inventado.
    """
    filas: List[dict] = []
    problemas: List[str] = []
    vistos: Dict[str, int] = {}
    por_ref = precios_por_referencia(productos)
    respaldo = {k.upper(): v for k, v in (precios_de_respaldo or {}).items()}

    for pr in productos:
        if not pr.get("stock_control"):
            continue
        cantidad = sum(float(w.get("quantity") or 0)
                       for w in (pr.get("warehouses") or [])
                       if bodega in (w.get("name"), w.get("id")))
        if cantidad <= 0:
            continue

        code = (pr.get("code") or "").strip()
        ref, talla = ref_talla(code)
        es_prenda = bool(ref and talla)
        if not code:
            continue

        precio, origen = _precio_propio(pr), "siigo"
        if not precio and ref in por_ref:
            precio, origen = por_ref[ref], "otras_tallas"
        # El respaldo es SÓLO para lo que Siigo tiene en $0. Si Siigo trae un
        # precio y lo raro es cómo está marcado (la caja regalo: $5.950 «sin
        # IVA incluido», y $5.000 en la tienda en línea), hay dos precios
        # distintos sobre la mesa y no le toca a este código elegir.
        if (not precio and not _precio_con_iva(pr)[0]
                and respaldo.get(code.upper(), 0) >= PRECIO_MINIMO):
            precio, origen = int(respaldo[code.upper()]), "tienda_en_linea"
        if not precio:
            crudo, con_iva = _precio_con_iva(pr)
            if not crudo:
                motivo = "precio en $0 en Siigo"
            elif not con_iva:
                motivo = "Siigo lo tiene SIN IVA incluido, a diferencia del resto"
            else:
                motivo = f"precio de ${round(crudo)}, no es un precio de venta"
            problemas.append(f"{code}: {motivo}, y no hay de dónde más "
                             f"tomarlo. Hay que ponérselo en Siigo.")
            continue

        if es_prenda:
            sku = f"{ref}T{talla}"
        else:
            # Bolsas, pañoletas: el código de Siigo ES el SKU. Inventarle una
            # «T» haría que la factura pidiera un producto que no existe.
            sku, ref, talla = code, code, "U"
        vistos[sku] = vistos.get(sku, 0) + 1
        filas.append({
            "sku": sku,
            "referencia": ref,
            "nombre": _nombre_limpio(pr, code),
            "color": "",          # Siigo no lo tiene aparte: va en el nombre.
            "categoria": ((pr.get("account_group") or {}).get("name")
                          or "Sin categoría").strip().title(),
            "talla": talla,
            "precio": int(round(precio)),
            # De dónde salió el precio. Lo que no viene de Siigo es un dato
            # que contabilidad tiene que corregir allá.
            "precio_origen": origen,
            "cantidad": int(round(cantidad)),
            "codigo_barras": ((pr.get("additional_fields") or {})
                              .get("barcode") or "").strip(),
        })

    for sku, n in vistos.items():
        if n > 1:
            problemas.append(f"{sku}: aparece {n} veces en Siigo")
    return filas, problemas


def escribir_csv(filas: List[dict], ruta: str) -> None:
    with open(ruta, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, extrasaction="ignore", fieldnames=[
            "referencia", "nombre", "color", "categoria", "talla", "precio",
            "cantidad", "codigo_barras", "sku"])
        w.writeheader()
        w.writerows(filas)


def _traer_productos(max_paginas: int = 200) -> List[dict]:
    """Todo el catálogo de Siigo, paginado — COMPLETO o nada.

    Una lectura que se corta a la mitad se ve igual que una completa, y quien
    sincroniza con ella pone en cero media tienda. Por eso se compara lo leído
    contra `pagination.total_results` y, si no cuadra, se lanza.

    Import LOCAL: `backend.services.siigo` es del ERP y el módulo retail tiene
    que poder cargarse sin él.
    """
    from backend.services.siigo import siigo_get

    todos: List[dict] = []
    total = None
    pagina = 1
    while pagina <= max_paginas:
        datos = siigo_get("/products", {"page": pagina, "page_size": 100})
        resultados = datos.get("results") or []
        if total is None:
            total = (datos.get("pagination") or {}).get("total_results")
        todos.extend(resultados)
        if len(resultados) < 100:
            break
        pagina += 1
        time.sleep(0.4)       # la cuenta de Siigo tiene límite de peticiones
    if total is None or len(todos) < int(total):
        raise RuntimeError(
            f"Siigo dice que hay {total} productos y se leyeron {len(todos)}: "
            f"lectura incompleta, no se usa.")
    return todos


def main(argv: List[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    bodega = argv[0]
    salida = argv[1] if len(argv) > 1 else f"catalogo_{bodega.lower()}.csv"

    productos = _traer_productos()
    filas, problemas = filas_de_productos(productos, bodega)
    escribir_csv(filas, salida)

    unidades = sum(f["cantidad"] for f in filas)
    refs = len({f["referencia"] for f in filas})
    valor = sum(f["precio"] * f["cantidad"] for f in filas)
    raros = sorted({f["codigo_barras"] for f in filas
                    if f["codigo_barras"]
                    and f["codigo_barras"].upper() != f["sku"].upper()})

    print(f"\n  bodega {bodega}: {len(filas)} SKU · {refs} referencias · "
          f"{unidades} unidades")
    print(f"  valor a precio de etiqueta: ${valor:,}".replace(",", "."))
    print(f"  productos leídos de Siigo: {len(productos)}")
    print(f"  etiquetas cuyo código NO es el SKU: {len(raros)}")
    if problemas:
        print(f"\n  FUERA DEL CSV ({len(problemas)}):")
        for p in problemas:
            print(f"    · {p}")
    print(f"\n  CSV: {salida}")
    print("  Siguiente: cargar_catalogo (ensayo) y luego --aplicar.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
