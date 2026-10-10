"""Dejar el inventario del POS igual al de Siigo, tienda por tienda.

POR QUÉ. El catálogo de una tienda se cargó UNA vez, como una foto. Desde ese
momento el POS descuenta lo que él vende, pero no ve la mercancía que llega,
los traslados entre tiendas ni un precio que cambió: a los pocos días la
cajera ofrece lo que no hay y no encuentra lo que sí. El inventario de verdad
de cada tienda es su bodega en Siigo, y esto lo trae cada hora.

    python -m backend.modules.retail.sincronizar_inventario            # ensayo
    python -m backend.modules.retail.sincronizar_inventario --aplicar

TRES COSAS QUE ESTO NO PUEDE HACER MAL:

1. **Poner en cero media tienda por una lectura cortada.** Una lista paginada
   que se interrumpe se ve igual que una completa. `_traer_productos` exige
   que lo leído cuadre con el total que dice Siigo, y aquí además se frena si
   una tienda saldría con menos de la mitad de las referencias que tenía.

2. **Devolverle al estante lo que se acaba de vender.** Una venta del POS le
   baja el inventario a Siigo cuando SU FACTURA entra allá. Entre el cobro y
   la factura Siigo todavía cuenta esa prenda; copiar su número la haría
   reaparecer. Por eso a lo de Siigo se le restan las ventas que aún no se
   han facturado.

3. **Escribir el saldo sin su asiento.** `movimientos_inventario` es el libro
   y es append-only: cada cambio de saldo deja el suyo, con el motivo. Es lo
   que después permite explicar una diferencia.

Lo que ya no tiene existencia en Siigo queda en cero aquí. No se borra: la
prenda sigue en el catálogo para las ventas y devoluciones que la nombran.
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Dict, List, Optional

from sqlalchemy import create_engine, text

from backend.modules.retail.cargar_catalogo import _id_de
from backend.modules.retail.catalogo_desde_siigo import (
    filas_de_productos,
    sin_precio_en_siigo,
)
from backend.modules.retail.infrastructure.persistencia.unidad_de_trabajo import (
    normalizar_url,
)

log = logging.getLogger("retail.inventario")

__all__ = ["sincronizar", "LecturaSospechosa"]


class LecturaSospechosa(Exception):
    """Lo que devolvió Siigo no se parece a la tienda: no se aplica."""


def sincronizar(url: str, *, productos: Optional[List[dict]] = None,
                aplicar: bool = False,
                usuario_id: str = "sincronizacion_siigo",
                precios_de_lista=None) -> dict:
    """Devuelve un resumen por tienda. En ensayo calcula todo y no escribe.

    `precios_de_lista(códigos) -> {código: pesos}`: a quién preguntarle el
    precio de lo que Siigo tiene en $0. Por defecto, la tienda en línea.
    """
    if productos is None:
        from backend.modules.retail.catalogo_desde_siigo import _traer_productos
        productos = _traer_productos()
    if precios_de_lista is None:
        from backend.modules.retail.infrastructure.precios_tienda_en_linea import (
            precios_de_lista,
        )

    resumen: dict = {"aplicado": aplicar, "productos_leidos": len(productos),
                     "tiendas": {}}
    motor = create_engine(normalizar_url(url), future=True)
    try:
        with motor.connect() as c:
            tx = c.begin()
            ubicaciones = c.execute(text("""
                SELECT id, tienda_id, siigo_bodega_id FROM retail.ubicaciones
                 WHERE tipo = 'tienda' AND siigo_bodega_id IS NOT NULL
                 ORDER BY id
            """)).mappings().all()
            # Lo que tiene existencia en alguna tienda y Siigo trae sin precio:
            # se le pregunta UNA vez a la tienda en línea, por todos.
            bodegas = {int(u["siigo_bodega_id"]) for u in ubicaciones}
            faltan = sin_precio_en_siigo(productos, bodegas)
            respaldo = precios_de_lista(faltan) if faltan else {}
            resumen["sin_precio_en_siigo"] = len(faltan)
            for u in ubicaciones:
                resumen["tiendas"][u["tienda_id"]] = _una_tienda(
                    c, u, productos, usuario_id, respaldo)
            if aplicar:
                tx.commit()
            else:
                tx.rollback()
    finally:
        motor.dispose()
    return resumen


def _una_tienda(c, u, productos: List[dict], usuario_id: str,
                respaldo: Optional[Dict[str, int]] = None) -> dict:
    filas, problemas = filas_de_productos(
        productos, int(u["siigo_bodega_id"]), respaldo)
    por_sku: Dict[str, dict] = {}
    for f in filas:
        # Un SKU repetido en Siigo: se queda el primero. Ya va en `problemas`.
        por_sku.setdefault(f["sku"].upper(), f)

    saldos = {r["sku"].upper(): (r["id"], int(r["cantidad"]))
              for r in c.execute(text("""
                  SELECT v.sku, v.id, s.cantidad
                    FROM retail.stock_ubicacion s
                    JOIN retail.variantes v ON v.id = s.variante_id
                   WHERE s.ubicacion_id = :u
              """), {"u": u["id"]}).mappings()}
    habia = sum(1 for _, n in saldos.values() if n > 0)
    if habia >= 20 and len(por_sku) < habia / 2:
        raise LecturaSospechosa(
            f"{u['tienda_id']}: Siigo devolvió {len(por_sku)} referencias con "
            f"existencia y el POS tenía {habia}. No se pone en cero media "
            f"tienda por una lectura dudosa.")

    variantes = {r["sku"].upper(): dict(r) for r in c.execute(text("""
        SELECT sku, id, nombre, categoria, precio_con_iva, codigo_barras,
               activa
          FROM retail.variantes
    """)).mappings()}
    barras_de = {v["codigo_barras"].upper(): k for k, v in variantes.items()
                 if v["codigo_barras"]}

    # Lo cobrado en el POS que Siigo todavía no sabe: ventas sin facturar.
    pendientes = {r["sku"].upper(): int(r["n"]) for r in c.execute(text("""
        SELECT l.sku, sum(l.cantidad) AS n
          FROM retail.venta_lineas l
          JOIN retail.ventas v ON v.id = l.venta_id
         WHERE v.tienda_id = :t AND v.estado = 'cerrada'
           AND v.estado_fiscal IN ('pendiente', 'enviando')
         GROUP BY l.sku
    """), {"t": u["tienda_id"]}).mappings()}

    r = {"en_siigo": len(por_sku), "nuevos": 0, "datos_actualizados": 0,
         "saldos_cambiados": 0, "puestos_en_cero": 0,
         "unidades": 0, "sin_facturar_descontadas": 0,
         "fuera": len(problemas), "problemas": problemas[:20],
         # Lo que entró con un precio que NO es el de Siigo: hay que
         # corregirlo allá. Se lista para que no pase por normal.
         "precio_prestado": sorted(
             f"{f['sku']} ${f['precio']:,} ({f['precio_origen']})".replace(",", ".")
             for f in por_sku_previo(filas) if f["precio_origen"] != "siigo")}
    tocados: List[str] = []

    for sku, f in por_sku.items():
        precio = int(f["precio"]) * 100
        barras = (f.get("codigo_barras") or "").strip() or None
        # El código de la etiqueta es único en la tabla. Si otra prenda ya lo
        # tiene, no se le quita: esta se queda sin él y se sigue buscando por
        # su SKU.
        if barras and barras_de.get(barras.upper(), sku) != sku:
            barras = None
        v = variantes.get(sku)
        if v is None:
            vid = c.execute(text("""
                INSERT INTO retail.variantes
                    (id, sku, referencia, talla, color, nombre, categoria,
                     precio_con_iva, codigo_barras)
                VALUES (:id, :sku, :ref, :talla, '', :nom, :cat, :p, :barras)
                RETURNING id
            """), {"id": _id_de(f["sku"]), "sku": f["sku"],
                   "ref": f["referencia"], "talla": f["talla"],
                   "nom": f["nombre"], "cat": f["categoria"], "p": precio,
                   "barras": barras}).scalar()
            variantes[sku] = {"id": vid, "nombre": f["nombre"],
                              "categoria": f["categoria"], "activa": True,
                              "precio_con_iva": precio, "codigo_barras": barras}
            if barras:
                barras_de[barras.upper()] = sku
            r["nuevos"] += 1
            tocados.append(f["sku"])
        else:
            vid = v["id"]
            if (v["nombre"], v["categoria"], int(v["precio_con_iva"])) != (
                    f["nombre"], f["categoria"], precio) or (
                    barras and not v["codigo_barras"]) or not v["activa"]:
                # `activa = true`: una prenda que entró APAGADA —traída con
                # una factura vieja de Siigo para recibirle un cambio— y que
                # ahora tiene existencia, se vende.
                c.execute(text("""
                    UPDATE retail.variantes
                       SET nombre = :nom, categoria = :cat, precio_con_iva = :p,
                           codigo_barras = coalesce(codigo_barras, :barras),
                           activa = true, actualizado_en = now()
                     WHERE id = :id
                """), {"id": vid, "nom": f["nombre"], "cat": f["categoria"],
                       "p": precio, "barras": barras})
                v["activa"] = True
                r["datos_actualizados"] += 1
                tocados.append(f["sku"])

        sin_facturar = min(pendientes.get(sku, 0), int(f["cantidad"]))
        objetivo = int(f["cantidad"]) - sin_facturar
        r["sin_facturar_descontadas"] += sin_facturar
        r["unidades"] += objetivo
        antes = saldos.get(sku, (None, 0))[1]
        if objetivo != antes or sku not in saldos:
            _fijar(c, u["id"], vid, antes, objetivo, usuario_id, f["sku"],
                   existe=sku in saldos)
            if objetivo != antes:
                r["saldos_cambiados"] += 1

    # Lo que el POS creía tener y Siigo ya no: a cero.
    for sku, (vid, antes) in saldos.items():
        if sku in por_sku or antes == 0:
            continue
        _fijar(c, u["id"], vid, antes, 0, usuario_id, sku, existe=True)
        r["puestos_en_cero"] += 1

    if tocados:
        # Sin esto el producto EXISTE pero el buscador no lo encuentra.
        c.execute(text("""
            INSERT INTO retail.catalogo_busqueda
                (variante_id, texto_busqueda, referencia, talla, color,
                 categoria, precio_con_iva)
            SELECT v.id,
                   retail.norm(concat_ws(' ', v.sku, v.referencia, v.nombre,
                                         v.color, v.talla, v.codigo_barras,
                                         v.categoria)),
                   v.referencia, v.talla, v.color, v.categoria, v.precio_con_iva
              FROM retail.variantes v WHERE v.sku = ANY(:skus)
            ON CONFLICT (variante_id) DO UPDATE
               SET texto_busqueda = EXCLUDED.texto_busqueda,
                   precio_con_iva = EXCLUDED.precio_con_iva,
                   categoria = EXCLUDED.categoria, color = EXCLUDED.color
        """), {"skus": tocados})
    return r


def por_sku_previo(filas: List[dict]) -> List[dict]:
    """Una fila por SKU (la primera), como las usa `_una_tienda`."""
    vistos, salida = set(), []
    for f in filas:
        if f["sku"].upper() not in vistos:
            vistos.add(f["sku"].upper())
            salida.append(f)
    return salida


def _fijar(c, ubicacion_id: str, variante_id: str, antes: int, despues: int,
           usuario_id: str, sku: str, *, existe: bool) -> None:
    c.execute(text("""
        INSERT INTO retail.stock_ubicacion (ubicacion_id, variante_id, cantidad)
        VALUES (:u, :v, :c)
        ON CONFLICT (ubicacion_id, variante_id) DO UPDATE
           SET cantidad = EXCLUDED.cantidad, actualizado_en = now()
    """), {"u": ubicacion_id, "v": variante_id, "c": despues})
    if despues == antes:
        return
    # `ajuste_conteo`: el conteo que manda es el de Siigo. El origen queda en
    # `referencia_tipo`, para distinguirlo de un ajuste hecho a mano.
    c.execute(text("""
        INSERT INTO retail.movimientos_inventario
            (ubicacion_id, variante_id, delta, saldo_despues, motivo,
             referencia_tipo, referencia_id, usuario_id, detalle)
        VALUES (:u, :v, :d, :s, 'ajuste_conteo', 'sincronizacion_siigo',
                :ref, :usr, :det)
    """), {"u": ubicacion_id, "v": variante_id, "d": despues - antes,
           "s": despues, "ref": sku, "usr": usuario_id,
           "det": f"sincronización con Siigo · {sku}: {antes} → {despues}"})


def main(argv: List[str]) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    url = os.environ.get("RETAIL_DATABASE_URL", "").strip()
    if not url:
        print("Falta RETAIL_DATABASE_URL.", file=sys.stderr)
        return 2
    r = sincronizar(url, aplicar="--aplicar" in argv)
    print(f"\n  productos leídos de Siigo: {r['productos_leidos']}")
    for tienda, t in r["tiendas"].items():
        print(f"\n  {tienda}: {t['en_siigo']} referencias · {t['unidades']} und")
        print(f"    nuevas {t['nuevos']} · saldos cambiados "
              f"{t['saldos_cambiados']} · en cero {t['puestos_en_cero']} · "
              f"datos {t['datos_actualizados']} · sin facturar "
              f"{t['sin_facturar_descontadas']} · fuera {t['fuera']}")
        for p in t["problemas"]:
            print(f"      · {p}")
    print("\n  APLICADO.\n" if r["aplicado"]
          else "\n  ENSAYO — no se escribió nada. Repite con --aplicar.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
