"""Cargar el conteo de una tienda EN EL POS, cuando Siigo no deja cargarlo.

POR QUÉ (29-oct-2026): Arrayanes contó su inventario y la página de Siigo no
guarda el ajuste. Sin esto la tienda vende con los números de antes del
conteo hasta que Siigo se arregle.

EL CONTEO ES UNA FOTO, NO UNA SUMA. Cada referencia contada queda en lo que
se contó. Con `completo`, lo que la tienda tenía y no aparece en el conteo
queda en cero — así se hace un conteo de verdad, y es justo lo que dejó las
bolsas de Florida en cero el 28-oct: por eso el ensayo separa aparte lo que
no es prenda (bolsas, caja regalo) y que el conteo dejaría en cero.

MIENTRAS ESTÉ PENDIENTE DE SIIGO la sincronización no toca esa tienda
(`ubicaciones_en_pausa`): si copiara Siigo, devolvería los números viejos.
Cuando alguien lo carga en Siigo lo marca y la tienda vuelve a la normalidad.
Lo que hay que cargar allá NO es el conteo sino el inventario de ESE momento
(`para_siigo`): las ventas desde el conteo ya bajaron Siigo con su factura.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

from sqlalchemy import text

__all__ = ["preparar", "aplicar", "marcar_en_siigo", "para_siigo",
           "ubicaciones_en_pausa", "resumen_pausado", "ConteoInvalido"]

_SKU_PRENDA = re.compile(r"^.+T([0-9]{1,3}|[A-Z]{1,3})$", re.I)


class ConteoInvalido(Exception):
    """El conteo no se puede cargar así. El mensaje es para la administradora."""


def _codigo(crudo: str) -> str:
    # La pistola en inglés sobre Windows en español escribe ' en vez de -.
    return re.sub(r"(\d)['´’](?=\d)", r"\1-", (crudo or "").strip()).upper()


async def _ubicacion(s, tienda_id: str) -> str:
    u = (await s.execute(text("""
        SELECT id FROM retail.ubicaciones WHERE tienda_id = :t AND tipo = 'tienda'
    """), {"t": tienda_id})).scalar()
    if not u:
        raise ConteoInvalido(f"La tienda «{tienda_id}» no tiene ubicación de venta.")
    return u


async def preparar(s, *, tienda_id: str, lineas: List[dict],
                   completo: bool) -> dict:
    """Lo que el conteo cambiaría, SIN escribir nada."""
    if not lineas:
        raise ConteoInvalido("El conteo está vacío.")
    ubicacion = await _ubicacion(s, tienda_id)

    variantes = (await s.execute(text("""
        SELECT id, sku, nombre, codigo_barras FROM retail.variantes
    """))).mappings().all()
    por_codigo: Dict[str, dict] = {}
    for v in variantes:
        por_codigo.setdefault(v["sku"].upper(), dict(v))
    for v in variantes:
        if v["codigo_barras"]:
            por_codigo.setdefault(v["codigo_barras"].upper(), dict(v))

    contado: Dict[str, int] = {}
    desconocidos: List[str] = []
    for l in lineas:
        codigo = _codigo(str(l.get("codigo", "")))
        try:
            n = int(l.get("cantidad"))
        except (TypeError, ValueError):
            raise ConteoInvalido(f"«{l.get('cantidad')}» no es una cantidad "
                                 f"(código {codigo or '¿?'}).")
        if not codigo:
            continue
        if n < 0:
            raise ConteoInvalido(f"{codigo}: la cantidad no puede ser negativa.")
        v = por_codigo.get(codigo)
        if v is None:
            desconocidos.append(codigo)
            continue
        # La misma prenda en dos filas (dos personas contando, o por código
        # de barras y por SKU): se suma.
        contado[v["sku"]] = contado.get(v["sku"], 0) + n
    if not contado:
        raise ConteoInvalido("Ningún código del conteo existe en el catálogo.")

    saldos = {r["sku"]: dict(r) for r in (await s.execute(text("""
        SELECT v.sku, v.id AS variante_id, v.nombre, s.cantidad
          FROM retail.stock_ubicacion s
          JOIN retail.variantes v ON v.id = s.variante_id
         WHERE s.ubicacion_id = :u
    """), {"u": ubicacion})).mappings()}
    vid = {v["sku"]: v["id"] for v in variantes}
    nombre = {v["sku"]: v["nombre"] for v in variantes}

    filas = []
    for sku, n in sorted(contado.items()):
        antes = int((saldos.get(sku) or {}).get("cantidad") or 0)
        filas.append({"sku": sku, "variante_id": vid[sku],
                      "nombre": nombre[sku], "antes": antes, "contado": n})
    a_cero = []
    if completo:
        for sku, r in sorted(saldos.items()):
            if sku not in contado and int(r["cantidad"]) > 0:
                a_cero.append({"sku": sku, "variante_id": r["variante_id"],
                               "nombre": r["nombre"],
                               "antes": int(r["cantidad"]), "contado": 0})

    cambios = [f for f in filas + a_cero if f["antes"] != f["contado"]]
    antes_total = sum(max(int(r["cantidad"]), 0) for r in saldos.values())
    despues_total = antes_total + sum(f["contado"] - f["antes"] for f in cambios)
    return {
        "tienda_id": tienda_id, "ubicacion_id": ubicacion, "completo": completo,
        "referencias_contadas": len(contado),
        "unidades_contadas": sum(contado.values()),
        "unidades_antes": antes_total, "unidades_despues": despues_total,
        "desconocidos": sorted(set(desconocidos)),
        "cambios": cambios,
        "a_cero": a_cero,
        # Bolsas, caja regalo, pañoleta: lo que un conteo de prendas olvida.
        "no_prendas_a_cero": [f for f in a_cero
                              if not _SKU_PRENDA.match(f["sku"])],
        "_lineas": filas + a_cero,
    }


async def aplicar(s, *, conteo_id: str, tienda_id: str, lineas: List[dict],
                  completo: bool, usuario_id: str) -> dict:
    """Deja la tienda como se contó. Idempotente por `conteo_id`."""
    ya = (await s.execute(text("""
        SELECT id, referencias, unidades FROM retail.conteos_inventario
         WHERE id = :i
    """), {"i": conteo_id})).mappings().first()
    if ya:
        return {"conteo_id": conteo_id, "ya_estaba": True,
                "referencias": ya["referencias"], "unidades": ya["unidades"]}

    p = await preparar(s, tienda_id=tienda_id, lineas=lineas, completo=completo)
    # Un conteo nuevo encima de uno pendiente: el viejo queda reemplazado.
    await s.execute(text("""
        UPDATE retail.conteos_inventario SET estado = 'reemplazado'
         WHERE ubicacion_id = :u AND estado = 'pendiente_siigo'
    """), {"u": p["ubicacion_id"]})
    await s.execute(text("""
        INSERT INTO retail.conteos_inventario
            (id, tienda_id, ubicacion_id, completo, referencias, unidades,
             creado_por)
        VALUES (:i, :t, :u, :c, :r, :n, :usr)
    """), {"i": conteo_id, "t": tienda_id, "u": p["ubicacion_id"],
           "c": completo, "r": p["referencias_contadas"],
           "n": p["unidades_contadas"], "usr": usuario_id})
    for f in p["_lineas"]:
        await s.execute(text("""
            INSERT INTO retail.conteo_lineas
                (conteo_id, sku, variante_id, antes, contado)
            VALUES (:i, :sku, :v, :a, :c)
        """), {"i": conteo_id, "sku": f["sku"], "v": f["variante_id"],
               "a": f["antes"], "c": f["contado"]})
        await s.execute(text("""
            INSERT INTO retail.stock_ubicacion (ubicacion_id, variante_id, cantidad)
            VALUES (:u, :v, :c)
            ON CONFLICT (ubicacion_id, variante_id) DO UPDATE
               SET cantidad = EXCLUDED.cantidad, actualizado_en = now()
        """), {"u": p["ubicacion_id"], "v": f["variante_id"], "c": f["contado"]})
        if f["contado"] != f["antes"]:
            await s.execute(text("""
                INSERT INTO retail.movimientos_inventario
                    (ubicacion_id, variante_id, delta, saldo_despues, motivo,
                     referencia_tipo, referencia_id, usuario_id, detalle)
                VALUES (:u, :v, :d, :c, 'ajuste_conteo', 'conteo_pos', :i,
                        :usr, :det)
            """), {"u": p["ubicacion_id"], "v": f["variante_id"],
                   "d": f["contado"] - f["antes"], "c": f["contado"],
                   "i": conteo_id, "usr": usuario_id,
                   "det": f"conteo en el POS · {f['sku']}: "
                          f"{f['antes']} → {f['contado']}"})
    resumen = {k: v for k, v in p.items() if not k.startswith("_")}
    resumen.update({"conteo_id": conteo_id, "ya_estaba": False})
    return resumen


async def marcar_en_siigo(s, *, conteo_id: str, usuario_id: str) -> None:
    n = (await s.execute(text("""
        UPDATE retail.conteos_inventario
           SET estado = 'en_siigo', en_siigo_por = :usr, en_siigo_en = now()
         WHERE id = :i AND estado = 'pendiente_siigo'
    """), {"i": conteo_id, "usr": usuario_id})).rowcount
    if not n:
        raise ConteoInvalido("Ese conteo no está pendiente de Siigo.")


async def para_siigo(s, *, conteo_id: str) -> dict:
    """Lo que hay que dejar en la bodega de Siigo: el inventario de AHORA.

    No es el conteo. Lo vendido después del conteo ya bajó Siigo con su
    factura; cargar el conteo tal cual devolvería esas prendas.
    """
    c = (await s.execute(text("""
        SELECT c.id, c.tienda_id, c.ubicacion_id, c.estado,
               u.siigo_bodega_id
          FROM retail.conteos_inventario c
          JOIN retail.ubicaciones u ON u.id = c.ubicacion_id
         WHERE c.id = :i
    """), {"i": conteo_id})).mappings().first()
    if c is None:
        raise ConteoInvalido("No existe ese conteo.")
    filas = [dict(r) for r in (await s.execute(text("""
        SELECT v.sku, v.nombre, s.cantidad
          FROM retail.stock_ubicacion s
          JOIN retail.variantes v ON v.id = s.variante_id
         WHERE s.ubicacion_id = :u AND s.cantidad > 0
         ORDER BY v.sku
    """), {"u": c["ubicacion_id"]})).mappings()]
    return {"conteo_id": conteo_id, "tienda_id": c["tienda_id"],
            "estado": c["estado"], "bodega_siigo": c["siigo_bodega_id"],
            "filas": filas, "unidades": sum(f["cantidad"] for f in filas)}


def ubicaciones_en_pausa(conexion) -> Dict[str, str]:
    """`{ubicación: conteo}` con un conteo pendiente de Siigo. SÍNCRONO: lo
    usa la sincronización, que corre con una conexión normal."""
    return {r[0]: r[1] for r in conexion.execute(text("""
        SELECT ubicacion_id, id FROM retail.conteos_inventario
         WHERE estado = 'pendiente_siigo'
    """))}


def resumen_pausado(conteo_id: Optional[str]) -> dict:
    """La fila del resumen de una tienda en pausa, con las mismas claves que
    una sincronizada (el reloj las lee)."""
    return {"en_siigo": 0, "nuevos": 0, "datos_actualizados": 0,
            "saldos_cambiados": 0, "puestos_en_cero": 0, "unidades": 0,
            "sin_facturar_descontadas": 0, "devueltas_sumadas": 0, "fuera": 0,
            "problemas": [], "precio_prestado": [],
            "en_pausa_por_conteo": conteo_id}
