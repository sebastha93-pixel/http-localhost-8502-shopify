"""
Sincronización Shopify → DB central — Male Denim OS

Entidades sincronizadas:
  - pedidos       : órdenes + transacciones de pago
  - productos     : catálogo completo (activos + borradores) + fechas lanzamiento
  - clientes      : base de clientes con historial

Uso CLI:
  python3 shopify_sync.py                    # sincroniza todo
  python3 shopify_sync.py --entidad pedidos  # solo pedidos
  python3 shopify_sync.py --dias 7           # pedidos de los últimos 7 días
  python3 shopify_sync.py --verificar        # solo prueba la conexión
"""

import json
import time
import argparse
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Dict, List
import sys

sys.path.insert(0, str(Path(__file__).parent))
from shopify_client import (
    paginar, _get, verificar_conexion,
    ShopifyError, contar_pedidos,
)
from db import get_conn, init_db


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _iso(dt_str: Optional[str]) -> Optional[str]:
    """Convierte fecha ISO 8601 de Shopify a YYYY-MM-DD."""
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00")).strftime("%Y-%m-%d")
    except Exception:
        return dt_str[:10] if dt_str else None


def _float(val) -> float:
    try:
        return float(val) if val else 0.0
    except (ValueError, TypeError):
        return 0.0


def _log_sync(entidad: str, api: int, ins: int, act: int, err: int,
              duracion: float, estado: str = "ok", msg: str = "") -> None:
    sql = """
    INSERT INTO shopify_sync_log
        (entidad, registros_api, insertados, actualizados, errores, duracion_seg, estado, mensaje)
    VALUES (?,?,?,?,?,?,?,?)
    """
    with get_conn() as conn:
        conn.execute(sql, (entidad, api, ins, act, err, round(duracion, 2), estado, msg))


# ─────────────────────────────────────────────────────────────────────────────
# SYNC PEDIDOS + TRANSACCIONES
# ─────────────────────────────────────────────────────────────────────────────

def _mapear_pedido_shopify(orden: dict) -> dict:
    """Convierte una orden de la API de Shopify al formato de la tabla pedidos."""
    cliente = orden.get("customer") or {}
    dir_env = (orden.get("shipping_address") or
               orden.get("billing_address") or {})

    # Método de pago
    pasarelas = orden.get("payment_gateway_names") or []
    metodo = pasarelas[0].lower() if pasarelas else "desconocido"

    # COD: en Shopify normalmente es "cash on delivery" o "cod"
    es_cod = any("cod" in p.lower() or "contra" in p.lower() or "cash" in p.lower()
                 for p in pasarelas)

    lineas = orden.get("line_items") or []
    skus   = [l.get("sku") for l in lineas if l.get("sku")]
    prods  = [l.get("name") for l in lineas if l.get("name")]
    cant   = sum(l.get("quantity", 0) for l in lineas)

    return {
        "orden_shopify":     str(orden.get("order_number") or orden.get("name", "")),
        "orden_melonn":      None,   # se cruza después con CSV Melonn
        "fecha_pedido":      _iso(orden.get("created_at")),
        "canal":             orden.get("source_name") or "shopify",
        "nombre_cliente":    (
            f"{cliente.get('first_name','')} {cliente.get('last_name','')}".strip()
            or orden.get("contact_email", "")
        ),
        "telefono_cliente":  (dir_env.get("phone") or
                              cliente.get("phone") or ""),
        "email_cliente":     (orden.get("email") or
                              cliente.get("email") or ""),
        "ciudad_destino":    dir_env.get("city") or "",
        "region_destino":    dir_env.get("province") or "",
        "sku":               ", ".join(skus) if skus else None,
        "producto":          ", ".join(prods) if prods else None,
        "cantidad":          cant,
        "precio_venta":      _float(orden.get("total_price")),
        "costo_producto":    None,
        "metodo_pago":       metodo,
        "plataforma_pago":   metodo,
        "valor_pagado":      _float(orden.get("total_price")),
        "estado_pago":       _mapear_estado_pago(orden.get("financial_status")),
        "es_contraentrega":  1 if es_cod else 0,
        "valor_cod":         _float(orden.get("total_price")) if es_cod else 0.0,
        "transportadora":    None,
        "fecha_despacho":    None,
        "fecha_promesa":     None,
        "fecha_entrega":     _iso(orden.get("closed_at")) if orden.get("fulfillment_status") == "fulfilled" else None,
        "estado_melonn":     None,
        "zona_logistica":    None,
        "dias_en_transito":  None,
        "score_riesgo":      None,
        "nivel_riesgo":      "NORMAL",
        "incidencia":        "NINGUNO",
        "categoria_incidencia": "OK",
        "link_melonn":       None,
        "fuente":            "shopify_api",
    }


def _mapear_estado_pago(financial_status: Optional[str]) -> str:
    mapa = {
        "paid":           "pagado",
        "partially_paid": "pagado",
        "pending":        "pendiente",
        "authorized":     "pendiente",
        "partially_refunded": "devuelto",
        "refunded":       "devuelto",
        "voided":         "fallido",
    }
    return mapa.get(str(financial_status).lower(), "pendiente")


def sincronizar_pedidos(dias: int = 30) -> Dict:
    """
    Jalá pedidos de Shopify de los últimos N días y los upserta en el DB.
    También trae las transacciones de pago de cada orden.
    """
    t0 = time.time()
    print(f"\n  Sincronizando pedidos (últimos {dias} días)...")

    desde = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()
    params = {
        "status":            "any",
        "created_at_min":    desde,
        "fields": (
            "id,order_number,name,created_at,closed_at,email,phone,"
            "financial_status,fulfillment_status,total_price,currency,"
            "payment_gateway_names,source_name,customer,shipping_address,"
            "billing_address,line_items,tags"
        ),
    }

    sql_upsert = """
    INSERT INTO pedidos (
        orden_shopify, orden_melonn, fecha_pedido, canal,
        nombre_cliente, telefono_cliente, email_cliente, ciudad_destino, region_destino,
        sku, producto, cantidad, precio_venta, costo_producto,
        metodo_pago, plataforma_pago, valor_pagado, estado_pago,
        es_contraentrega, valor_cod,
        transportadora, fecha_despacho, fecha_promesa, fecha_entrega,
        estado_melonn, zona_logistica, dias_en_transito,
        score_riesgo, nivel_riesgo, incidencia, categoria_incidencia,
        link_melonn, fuente, actualizado_en
    ) VALUES (
        :orden_shopify, :orden_melonn, :fecha_pedido, :canal,
        :nombre_cliente, :telefono_cliente, :email_cliente, :ciudad_destino, :region_destino,
        :sku, :producto, :cantidad, :precio_venta, :costo_producto,
        :metodo_pago, :plataforma_pago, :valor_pagado, :estado_pago,
        :es_contraentrega, :valor_cod,
        :transportadora, :fecha_despacho, :fecha_promesa, :fecha_entrega,
        :estado_melonn, :zona_logistica, :dias_en_transito,
        :score_riesgo, :nivel_riesgo, :incidencia, :categoria_incidencia,
        :link_melonn, :fuente, CURRENT_TIMESTAMP
    )
    ON CONFLICT(orden_shopify) DO UPDATE SET
        estado_pago        = excluded.estado_pago,
        valor_pagado       = excluded.valor_pagado,
        fecha_entrega      = excluded.fecha_entrega,
        nombre_cliente     = excluded.nombre_cliente,
        email_cliente      = excluded.email_cliente,
        telefono_cliente   = excluded.telefono_cliente,
        ciudad_destino     = excluded.ciudad_destino,
        fuente             = 'shopify_api',
        actualizado_en     = CURRENT_TIMESTAMP
    WHERE pedidos.orden_shopify = excluded.orden_shopify
    """

    # Crear índice único en orden_shopify si no existe
    with get_conn() as conn:
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_pedidos_shopify_unique
            ON pedidos(orden_shopify) WHERE orden_shopify IS NOT NULL
        """)

    total_api = insertados = actualizados = errores = 0

    sql_update = """
    UPDATE pedidos SET
        estado_pago      = :estado_pago,
        valor_pagado     = :valor_pagado,
        fecha_entrega    = :fecha_entrega,
        nombre_cliente   = :nombre_cliente,
        email_cliente    = :email_cliente,
        telefono_cliente = :telefono_cliente,
        ciudad_destino   = :ciudad_destino,
        precio_venta     = :precio_venta,
        fuente           = 'shopify_api',
        actualizado_en   = CURRENT_TIMESTAMP
    WHERE orden_shopify  = :orden_shopify
    """

    sql_insert = """
    INSERT OR IGNORE INTO pedidos (
        orden_shopify, orden_melonn, fecha_pedido, canal,
        nombre_cliente, telefono_cliente, email_cliente, ciudad_destino, region_destino,
        sku, producto, cantidad, precio_venta, costo_producto,
        metodo_pago, plataforma_pago, valor_pagado, estado_pago,
        es_contraentrega, valor_cod,
        transportadora, fecha_despacho, fecha_promesa, fecha_entrega,
        estado_melonn, zona_logistica, dias_en_transito,
        score_riesgo, nivel_riesgo, incidencia, categoria_incidencia,
        link_melonn, fuente, actualizado_en
    ) VALUES (
        :orden_shopify, :orden_melonn, :fecha_pedido, :canal,
        :nombre_cliente, :telefono_cliente, :email_cliente, :ciudad_destino, :region_destino,
        :sku, :producto, :cantidad, :precio_venta, :costo_producto,
        :metodo_pago, :plataforma_pago, :valor_pagado, :estado_pago,
        :es_contraentrega, :valor_cod,
        :transportadora, :fecha_despacho, :fecha_promesa, :fecha_entrega,
        :estado_melonn, :zona_logistica, :dias_en_transito,
        :score_riesgo, :nivel_riesgo, :incidencia, :categoria_incidencia,
        :link_melonn, 'shopify_api', CURRENT_TIMESTAMP
    )
    """

    for pagina in paginar("/orders.json", "orders", params):
        total_api += len(pagina)
        for orden in pagina:
            try:
                p = _mapear_pedido_shopify(orden)
                with get_conn() as conn:
                    cur = conn.execute(sql_insert, p)
                    if cur.rowcount > 0:
                        insertados += 1
                    else:
                        conn.execute(sql_update, p)
                        actualizados += 1
            except Exception as e:
                errores += 1
                print(f"    ⚠ Orden {orden.get('order_number','?')}: {e}")

        print(f"    Página procesada: {total_api} órdenes hasta ahora...")

    duracion = time.time() - t0
    _log_sync("pedidos", total_api, insertados, actualizados, errores, duracion)

    resultado = {
        "total_api": total_api,
        "insertados": insertados,
        "actualizados": actualizados,
        "errores": errores,
        "duracion_seg": round(duracion, 1),
    }
    print(f"  ✓ Pedidos: {insertados} nuevos · {actualizados} actualizados · {errores} errores ({duracion:.1f}s)")
    return resultado


# ─────────────────────────────────────────────────────────────────────────────
# SYNC PRODUCTOS
# ─────────────────────────────────────────────────────────────────────────────

def sincronizar_productos() -> Dict:
    """
    Sincroniza catálogo completo: activos + borradores.
    Captura fecha_publicacion como fecha de lanzamiento.
    """
    t0 = time.time()
    print("\n  Sincronizando productos...")

    sql_upsert = """
    INSERT INTO productos (
        shopify_id, titulo, tipo, proveedor, estado, tags,
        fecha_creacion, fecha_publicacion,
        precio_min, precio_max, inventario_total,
        variantes_json, imagenes_json, actualizado_en
    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
    ON CONFLICT(shopify_id) DO UPDATE SET
        titulo           = excluded.titulo,
        estado           = excluded.estado,
        tags             = excluded.tags,
        fecha_publicacion= excluded.fecha_publicacion,
        precio_min       = excluded.precio_min,
        precio_max       = excluded.precio_max,
        inventario_total = excluded.inventario_total,
        variantes_json   = excluded.variantes_json,
        imagenes_json    = excluded.imagenes_json,
        actualizado_en   = CURRENT_TIMESTAMP
    """

    total_api = insertados = actualizados = errores = 0

    for estado in ("active", "draft"):
        params = {
            "status": estado,
            "fields": "id,title,product_type,vendor,status,tags,created_at,published_at,variants,images",
        }
        for pagina in paginar("/products.json", "products", params):
            total_api += len(pagina)
            for prod in pagina:
                try:
                    variantes = prod.get("variants") or []
                    precios   = [_float(v.get("price")) for v in variantes if v.get("price")]
                    inventario= sum(v.get("inventory_quantity", 0) or 0 for v in variantes)
                    imagenes  = [i.get("src") for i in (prod.get("images") or []) if i.get("src")]

                    with get_conn() as conn:
                        existe = conn.execute(
                            "SELECT id FROM productos WHERE shopify_id=?",
                            (str(prod["id"]),)
                        ).fetchone()
                        conn.execute(sql_upsert, (
                            str(prod["id"]),
                            prod.get("title"),
                            prod.get("product_type"),
                            prod.get("vendor"),
                            prod.get("status"),
                            prod.get("tags"),
                            _iso(prod.get("created_at")),
                            _iso(prod.get("published_at")),   # ← fecha lanzamiento
                            min(precios) if precios else None,
                            max(precios) if precios else None,
                            inventario,
                            json.dumps([{
                                "sku": v.get("sku"),
                                "precio": v.get("price"),
                                "inventario": v.get("inventory_quantity"),
                                "titulo": v.get("title"),
                            } for v in variantes], ensure_ascii=False),
                            json.dumps(imagenes[:5], ensure_ascii=False),
                        ))
                        if existe:
                            actualizados += 1
                        else:
                            insertados += 1
                except Exception as e:
                    errores += 1
                    print(f"    ⚠ Producto {prod.get('id','?')}: {e}")

    duracion = time.time() - t0
    _log_sync("productos", total_api, insertados, actualizados, errores, duracion)

    resultado = {
        "total_api": total_api,
        "insertados": insertados,
        "actualizados": actualizados,
        "errores": errores,
        "duracion_seg": round(duracion, 1),
    }
    print(f"  ✓ Productos: {insertados} nuevos · {actualizados} actualizados · {errores} errores ({duracion:.1f}s)")
    return resultado


# ─────────────────────────────────────────────────────────────────────────────
# SYNC CLIENTES
# ─────────────────────────────────────────────────────────────────────────────

def sincronizar_clientes() -> Dict:
    """Sincroniza base de clientes con historial de compras."""
    t0 = time.time()
    print("\n  Sincronizando clientes...")

    sql_upsert = """
    INSERT INTO clientes (
        shopify_id, nombre, email, telefono,
        ciudad, region, pais,
        total_pedidos, total_gastado, acepta_marketing, tags,
        fecha_primer_pedido, fecha_ultimo_pedido, actualizado_en
    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
    ON CONFLICT(shopify_id) DO UPDATE SET
        nombre              = excluded.nombre,
        email               = excluded.email,
        telefono            = excluded.telefono,
        ciudad              = excluded.ciudad,
        total_pedidos       = excluded.total_pedidos,
        total_gastado       = excluded.total_gastado,
        acepta_marketing    = excluded.acepta_marketing,
        tags                = excluded.tags,
        fecha_ultimo_pedido = excluded.fecha_ultimo_pedido,
        actualizado_en      = CURRENT_TIMESTAMP
    """

    params = {
        "fields": (
            "id,first_name,last_name,email,phone,default_address,"
            "orders_count,total_spent,accepts_marketing,tags,"
            "created_at,updated_at"
        ),
    }

    total_api = insertados = actualizados = errores = 0

    for pagina in paginar("/customers.json", "customers", params):
        total_api += len(pagina)
        for cli in pagina:
            try:
                addr = cli.get("default_address") or {}
                nombre = f"{cli.get('first_name','')} {cli.get('last_name','')}".strip()

                with get_conn() as conn:
                    existe = conn.execute(
                        "SELECT id FROM clientes WHERE shopify_id=?",
                        (str(cli["id"]),)
                    ).fetchone()
                    conn.execute(sql_upsert, (
                        str(cli["id"]),
                        nombre,
                        cli.get("email"),
                        cli.get("phone") or addr.get("phone"),
                        addr.get("city"),
                        addr.get("province"),
                        addr.get("country_code") or "CO",
                        cli.get("orders_count", 0),
                        _float(cli.get("total_spent")),
                        1 if cli.get("accepts_marketing") else 0,
                        cli.get("tags"),
                        _iso(cli.get("created_at")),
                        _iso(cli.get("updated_at")),
                    ))
                    if existe:
                        actualizados += 1
                    else:
                        insertados += 1
            except Exception as e:
                errores += 1
                print(f"    ⚠ Cliente {cli.get('id','?')}: {e}")

        print(f"    {total_api} clientes procesados...")

    duracion = time.time() - t0
    _log_sync("clientes", total_api, insertados, actualizados, errores, duracion)

    resultado = {
        "total_api": total_api,
        "insertados": insertados,
        "actualizados": actualizados,
        "errores": errores,
        "duracion_seg": round(duracion, 1),
    }
    print(f"  ✓ Clientes: {insertados} nuevos · {actualizados} actualizados · {errores} errores ({duracion:.1f}s)")
    return resultado


# ─────────────────────────────────────────────────────────────────────────────
# SYNC COMPLETO
# ─────────────────────────────────────────────────────────────────────────────

def sincronizar_todo(dias_pedidos: int = 30) -> Dict:
    """Ejecuta la sincronización completa en el orden correcto."""
    t0 = time.time()
    print(f"\n{'═'*55}")
    print(f"  SHOPIFY SYNC — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"{'═'*55}")

    init_db()
    resultados = {}

    try:
        resultados["pedidos"]  = sincronizar_pedidos(dias=dias_pedidos)
    except ShopifyError as e:
        print(f"  ✗ Pedidos: {e}")
        resultados["pedidos"] = {"error": str(e)}

    try:
        resultados["productos"] = sincronizar_productos()
    except ShopifyError as e:
        print(f"  ✗ Productos: {e}")
        resultados["productos"] = {"error": str(e)}

    try:
        resultados["clientes"] = sincronizar_clientes()
    except ShopifyError as e:
        print(f"  ✗ Clientes: {e}")
        resultados["clientes"] = {"error": str(e)}

    duracion_total = time.time() - t0
    print(f"\n{'─'*55}")
    print(f"  Sync completo en {duracion_total:.1f}s")
    print(f"{'─'*55}\n")
    return resultados


def ultima_sync() -> Optional[Dict]:
    """Retorna info de la última sincronización exitosa."""
    sql = """
    SELECT fecha_sync, entidad, registros_api, insertados, actualizados, estado
    FROM shopify_sync_log
    ORDER BY fecha_sync DESC
    LIMIT 5
    """
    with get_conn() as conn:
        rows = conn.execute(sql).fetchall()
    return [dict(r) for r in rows] if rows else []


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Shopify Sync — Male Denim OS")
    ap.add_argument("--verificar",  action="store_true", help="Solo verifica la conexión")
    ap.add_argument("--entidad",    choices=["pedidos", "productos", "clientes"],
                    help="Sincronizar solo una entidad")
    ap.add_argument("--dias",       type=int, default=30,
                    help="Días hacia atrás para pedidos (default: 30)")
    args = ap.parse_args()

    if args.verificar:
        print("Verificando conexión con Shopify...")
        try:
            info = verificar_conexion()
            print("\n✓ Conexión exitosa:")
            for k, v in info.items():
                print(f"  {k:<12}: {v}")
            total = contar_pedidos()
            print(f"\n  Total pedidos en la tienda: {total:,}")
        except ShopifyError as e:
            print(f"\n✗ {e}")
        sys.exit(0)

    if args.entidad == "pedidos":
        sincronizar_pedidos(dias=args.dias)
    elif args.entidad == "productos":
        sincronizar_productos()
    elif args.entidad == "clientes":
        sincronizar_clientes()
    else:
        sincronizar_todo(dias_pedidos=args.dias)
