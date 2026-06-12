"""
shopify_metrics.py — Métricas derivadas de Shopify Orders
Sin cambiar shopify_client.py (que ya tiene _get, paginar, etc.)

Provee:
  ventas_del_dia(fecha)        → total $ vendido en un día
  ventas_serie(dias_atras=12)  → lista de totales por día para sparkline
  top_productos(n=5, dias=30)  → top N SKUs por revenue

Cache local en memoria (5 min) para no golpear la API en cada navegación.
"""
from __future__ import annotations

import time
from datetime import datetime, date, timedelta
from typing import Optional
from collections import defaultdict

from shopify_client import _get


# ── Cache simple en memoria ────────────────────────────────────────────────────
_CACHE: dict = {}
_CACHE_TS: dict = {}
_TTL_S = 300   # 5 minutos


def _cached(key: str, fn, ttl: int = _TTL_S):
    """Cachea el resultado de fn() por `ttl` segundos."""
    now = time.time()
    if key in _CACHE and (now - _CACHE_TS.get(key, 0)) < ttl:
        return _CACHE[key]
    val = fn()
    _CACHE[key]    = val
    _CACHE_TS[key] = now
    return val


def invalidar_cache() -> None:
    _CACHE.clear()
    _CACHE_TS.clear()


# ── Helpers de fechas ──────────────────────────────────────────────────────────
def _iso_inicio(d: date) -> str:
    return f"{d.isoformat()}T00:00:00-05:00"   # UTC-5 = Colombia


def _iso_fin(d: date) -> str:
    return f"{d.isoformat()}T23:59:59-05:00"


def _fetch_orders_dia(d: date, status: str = "any") -> list:
    """Trae todas las órdenes (pagadas) de un día específico."""
    orders = []
    params = {
        "status": status,
        "financial_status": "paid",
        "created_at_min": _iso_inicio(d),
        "created_at_max": _iso_fin(d),
        "limit": 250,
        "fields": "id,total_price,subtotal_price,line_items,created_at,financial_status",
    }
    resp = _get("/orders.json", params)
    orders.extend(resp.get("orders", []))
    return orders


# ── API pública ────────────────────────────────────────────────────────────────
def ventas_del_dia(d: Optional[date] = None) -> dict:
    """
    Retorna métricas de ventas de un día (default = hoy):
      { fecha, total, num_pedidos, ticket_promedio }
    """
    d = d or date.today()
    key = f"vd_{d.isoformat()}"

    def _calc():
        orders = _fetch_orders_dia(d)
        total = sum(float(o.get("total_price") or 0) for o in orders)
        n = len(orders)
        return {
            "fecha": d.isoformat(),
            "total": total,
            "num_pedidos": n,
            "ticket_promedio": (total / n) if n else 0.0,
        }
    # Cache corto para hoy (datos cambian), largo para días pasados
    ttl = 180 if d == date.today() else 86400
    return _cached(key, _calc, ttl=ttl)


def ventas_serie(dias_atras: int = 12) -> list:
    """
    Lista de totales de ventas para los últimos `dias_atras` días (incluyendo hoy).
    Útil para el sparkline. El día más reciente queda al final.
    """
    key = f"vs_{dias_atras}_{date.today().isoformat()}"

    def _calc():
        out = []
        hoy = date.today()
        for i in range(dias_atras - 1, -1, -1):
            d = hoy - timedelta(days=i)
            try:
                out.append(ventas_del_dia(d)["total"])
            except Exception:
                out.append(0.0)
        return out
    return _cached(key, _calc, ttl=600)


def delta_vs_ayer() -> dict:
    """Compara ventas de hoy vs ayer. Retorna pct y dirección."""
    hoy   = ventas_del_dia(date.today())["total"]
    ayer  = ventas_del_dia(date.today() - timedelta(days=1))["total"]
    pct   = ((hoy - ayer) / ayer * 100) if ayer else 0
    return {"hoy": hoy, "ayer": ayer, "pct": pct, "up": pct >= 0}


def top_productos(n: int = 5, dias: int = 30) -> list:
    """
    Top N productos por revenue acumulado en los últimos `dias`.
    Retorna lista de dicts: { sku, nombre, revenue, unidades, pct_del_total }
    """
    key = f"top_{n}_{dias}_{date.today().isoformat()}"

    def _calc():
        hoy = date.today()
        agregado: dict = defaultdict(lambda: {"revenue": 0.0, "unidades": 0, "nombre": "", "sku": ""})

        for i in range(dias):
            d = hoy - timedelta(days=i)
            try:
                orders = _fetch_orders_dia(d)
            except Exception:
                continue
            for o in orders:
                for it in o.get("line_items") or []:
                    sku = (it.get("sku") or "").strip() or it.get("title") or "—"
                    nombre = it.get("title") or sku
                    precio = float(it.get("price") or 0)
                    qty    = int(it.get("quantity") or 0)
                    agregado[sku]["sku"]      = sku
                    agregado[sku]["nombre"]   = nombre
                    agregado[sku]["revenue"] += precio * qty
                    agregado[sku]["unidades"]+= qty

        ranked = sorted(agregado.values(), key=lambda x: x["revenue"], reverse=True)[:n]
        total = sum(p["revenue"] for p in agregado.values()) or 1.0
        for p in ranked:
            p["pct_del_total"] = round(p["revenue"] / total * 100, 1)
        return ranked
    return _cached(key, _calc, ttl=1800)   # 30 min — datos diarios estables


# ─── Comparativas temporales ──────────────────────────────────────────────────
def _suma_periodo(desde: date, hasta: date) -> dict:
    """Suma ventas + pedidos entre dos fechas inclusive. Cacheado por rango."""
    key = f"sp_{desde.isoformat()}_{hasta.isoformat()}"

    def _calc():
        total = 0.0
        pedidos = 0
        d = desde
        while d <= hasta:
            v = ventas_del_dia(d)
            total += v.get("total", 0.0)
            pedidos += v.get("num_pedidos", 0)
            d = d + timedelta(days=1)
        return {"total": total, "num_pedidos": pedidos,
                "ticket_promedio": (total / pedidos) if pedidos else 0.0}

    return _cached(key, _calc, ttl=1800)


def comparativas() -> dict:
    """
    Devuelve 3 comparativas temporales:
      - semana_actual vs semana_pasada (mismo día acumulado)
      - mes_actual vs mes_pasado (a la misma fecha del mes)
      - yoy: mes actual vs mismo mes año pasado
    Cada bloque: {actual, anterior, pct, up}
    """
    hoy = date.today()

    # Semana ISO: del lunes al día actual
    lunes_actual    = hoy - timedelta(days=hoy.weekday())
    lunes_pasado    = lunes_actual - timedelta(days=7)
    domingo_pasado  = lunes_actual - timedelta(days=1)
    dia_equivalente_pasado = lunes_pasado + timedelta(days=hoy.weekday())

    semana_act = _suma_periodo(lunes_actual, hoy)
    semana_pas = _suma_periodo(lunes_pasado, dia_equivalente_pasado)

    # Mes a la fecha vs mes anterior a la misma fecha
    primer_dia_mes = hoy.replace(day=1)
    mes_pasado_fin = primer_dia_mes - timedelta(days=1)
    mes_pasado_inicio = mes_pasado_fin.replace(day=1)
    mes_pasado_misma_fecha = min(
        mes_pasado_inicio + timedelta(days=hoy.day - 1),
        mes_pasado_fin,
    )
    mes_act = _suma_periodo(primer_dia_mes, hoy)
    mes_pas = _suma_periodo(mes_pasado_inicio, mes_pasado_misma_fecha)

    # YoY: mismo rango del año pasado
    try:
        primer_dia_mes_yoy = primer_dia_mes.replace(year=primer_dia_mes.year - 1)
        hoy_yoy = hoy.replace(year=hoy.year - 1)
        yoy_pas = _suma_periodo(primer_dia_mes_yoy, hoy_yoy)
    except ValueError:
        yoy_pas = {"total": 0.0, "num_pedidos": 0, "ticket_promedio": 0.0}

    def _delta(a, b):
        ta, tb = a.get("total", 0.0), b.get("total", 0.0)
        pct = ((ta - tb) / tb * 100) if tb else 0.0
        return {"actual": a, "anterior": b, "pct": round(pct, 1), "up": pct >= 0}

    return {
        "semana": _delta(semana_act, semana_pas),
        "mes":    _delta(mes_act, mes_pas),
        "yoy":    _delta(mes_act, yoy_pas),
    }


# ─── Análisis de clientes ─────────────────────────────────────────────────────
def _fetch_orders_periodo(desde: date, hasta: date, fields: str = "id,total_price,customer,created_at") -> list:
    """Fetch órdenes en un rango. Cacheado."""
    key = f"fop_{desde.isoformat()}_{hasta.isoformat()}_{fields}"

    def _calc():
        orders: list = []
        params = {
            "status": "any",
            "created_at_min": _iso_inicio(desde),
            "created_at_max": _iso_fin(hasta),
            "limit": 250,
            "fields": fields,
        }
        # Paginar con cursor — Shopify devuelve max 250 por página
        try:
            from shopify_client import paginar
            for page in paginar("/orders.json", "orders", params):
                orders.extend(page)
        except Exception:
            # Fallback sin paginar (limita a 250)
            r = _get("/orders.json", params)
            orders.extend(r.get("orders", []))
        return orders

    return _cached(key, _calc, ttl=1800)


def analisis_clientes(dias: int = 90) -> dict:
    """
    Métricas de clientes en los últimos `dias`:
      - total_clientes_unicos
      - pct_recurrentes: % de pedidos hechos por clientes con ≥ 2 órdenes
      - pct_nuevos: % de pedidos por clientes con 1 sola orden (en el período)
      - ltv_promedio: revenue total / clientes únicos
      - top_clientes: top 10 por revenue (anonimizado a nombre + ciudad si está)
      - tasa_recompra_60d: % de clientes con orden en [hoy-90, hoy-60] que volvió en [hoy-60, hoy]
    """
    key = f"ac_{dias}_{date.today().isoformat()}"

    def _calc():
        hoy = date.today()
        desde = hoy - timedelta(days=dias)
        orders = _fetch_orders_periodo(desde, hoy)

        # Agregar por cliente
        por_cliente: dict = defaultdict(lambda: {"revenue": 0.0, "ordenes": 0, "nombre": "", "ciudad": "", "email": ""})
        for o in orders:
            c = o.get("customer") or {}
            cid = c.get("id") or (c.get("email") or "").lower().strip()
            if not cid:
                continue
            nombre = f"{c.get('first_name','')} {c.get('last_name','')}".strip() or "—"
            por_cliente[cid]["revenue"] += float(o.get("total_price") or 0)
            por_cliente[cid]["ordenes"] += 1
            por_cliente[cid]["nombre"]   = nombre
            por_cliente[cid]["email"]    = c.get("email") or ""

        total_clientes = len(por_cliente)
        total_ordenes  = sum(c["ordenes"] for c in por_cliente.values())
        revenue_total  = sum(c["revenue"] for c in por_cliente.values())

        ordenes_recurrentes = sum(c["ordenes"] for c in por_cliente.values() if c["ordenes"] >= 2)
        ordenes_nuevos      = sum(c["ordenes"] for c in por_cliente.values() if c["ordenes"] == 1)

        top = sorted(por_cliente.values(), key=lambda x: x["revenue"], reverse=True)[:10]

        # Tasa de recompra: clientes con orden en ventana antigua que volvieron
        ventana_vieja_ini = hoy - timedelta(days=90)
        ventana_vieja_fin = hoy - timedelta(days=60)
        ventana_reciente_ini = hoy - timedelta(days=60)
        clientes_ventana_vieja = set()
        clientes_volvieron = set()
        for o in orders:
            c = o.get("customer") or {}
            cid = c.get("id") or (c.get("email") or "").lower().strip()
            if not cid:
                continue
            fecha_str = (o.get("created_at") or "")[:10]
            try:
                fecha = datetime.fromisoformat(fecha_str).date()
            except Exception:
                continue
            if ventana_vieja_ini <= fecha < ventana_vieja_fin:
                clientes_ventana_vieja.add(cid)
            if fecha >= ventana_reciente_ini:
                if cid in clientes_ventana_vieja:
                    clientes_volvieron.add(cid)

        tasa_recompra = (
            len(clientes_volvieron) / len(clientes_ventana_vieja) * 100
            if clientes_ventana_vieja else 0.0
        )

        return {
            "dias": dias,
            "total_clientes_unicos": total_clientes,
            "total_ordenes": total_ordenes,
            "revenue_total": round(revenue_total, 0),
            "pct_recurrentes": round(ordenes_recurrentes / total_ordenes * 100, 1) if total_ordenes else 0.0,
            "pct_nuevos":      round(ordenes_nuevos      / total_ordenes * 100, 1) if total_ordenes else 0.0,
            "ltv_promedio":    round(revenue_total / total_clientes, 0) if total_clientes else 0.0,
            "tasa_recompra_60d": round(tasa_recompra, 1),
            "top_clientes": [
                {**c, "revenue": round(c["revenue"], 0)} for c in top
            ],
        }

    return _cached(key, _calc, ttl=1800)


def inventario_shopify() -> dict:
    """
    Conteo de productos en Shopify por status:
      - activos:    visibles en la tienda
      - borrador:   draft (no publicados)
      - archivados: archived (descontinuados)
    Y métricas de inventario:
      - total_skus, total_unidades (sumando inventory_quantity de variantes)
      - sin_stock:  variantes con inventory_quantity = 0
      - stock_bajo: variantes con 1-5 unidades (umbral configurable)
    """
    key = f"inv_{date.today().isoformat()}"

    def _calc():
        from shopify_client import _get
        # /products/count?status=X — endpoint barato (1 llamada x status)
        try:
            activos     = _get("/products/count.json", {"status": "active"}).get("count", 0)
        except Exception:
            activos = 0
        try:
            borrador    = _get("/products/count.json", {"status": "draft"}).get("count", 0)
        except Exception:
            borrador = 0
        try:
            archivados  = _get("/products/count.json", {"status": "archived"}).get("count", 0)
        except Exception:
            archivados = 0

        # Inventario detallado: paginar productos activos para sumar variantes
        total_skus = 0
        total_unidades = 0
        sin_stock = 0
        stock_bajo = 0
        try:
            from shopify_client import paginar
            for page in paginar(
                "/products.json",
                "products",
                {"status": "active", "limit": 250, "fields": "id,variants"},
            ):
                for prod in page:
                    for var in prod.get("variants", []) or []:
                        total_skus += 1
                        qty = int(var.get("inventory_quantity") or 0)
                        total_unidades += max(qty, 0)
                        if qty <= 0:
                            sin_stock += 1
                        elif qty <= 5:
                            stock_bajo += 1
        except Exception:
            pass

        return {
            "activos":      activos,
            "borrador":     borrador,
            "archivados":   archivados,
            "total_skus":   total_skus,
            "total_unidades": total_unidades,
            "sin_stock":    sin_stock,
            "stock_bajo":   stock_bajo,
        }

    return _cached(key, _calc, ttl=3600)  # 1 hora — inventario cambia lento


def listar_productos(status: str = "active", limit: int = 250) -> list:
    """
    Lista productos con stock por variante. `status`: active | draft | archived.
    Cada producto: { id, titulo, sku_principal, status, vendor, product_type,
                     imagen, total_stock, num_variantes, sin_stock, variantes[] }
    Cache 30 min.
    """
    key = f"prods_{status}_{date.today().isoformat()}"

    def _calc():
        from shopify_client import paginar
        productos = []
        try:
            fields = "id,title,status,vendor,product_type,handle,image,variants,created_at,updated_at"
            for page in paginar(
                "/products.json",
                "products",
                {"status": status, "limit": min(limit, 250), "fields": fields},
            ):
                for p in page:
                    variantes = p.get("variants") or []
                    total_stock = sum(max(int(v.get("inventory_quantity") or 0), 0) for v in variantes)
                    sin_stock = all(int(v.get("inventory_quantity") or 0) <= 0 for v in variantes)
                    productos.append({
                        "id":            p.get("id"),
                        "titulo":        p.get("title") or "—",
                        "handle":        p.get("handle") or "",
                        "sku_principal": (variantes[0].get("sku") if variantes else "") or "",
                        "status":        p.get("status"),
                        "vendor":        p.get("vendor") or "",
                        "tipo":          p.get("product_type") or "",
                        "imagen":        (p.get("image") or {}).get("src") or "",
                        "total_stock":   total_stock,
                        "num_variantes": len(variantes),
                        "sin_stock":     sin_stock,
                        "stock_bajo":    not sin_stock and total_stock <= 5,
                        "updated_at":    p.get("updated_at") or "",
                        "variantes": [
                            {
                                "id":     v.get("id"),
                                "sku":    v.get("sku") or "",
                                "titulo": v.get("title") or "",
                                "precio": float(v.get("price") or 0),
                                "stock":  int(v.get("inventory_quantity") or 0),
                            }
                            for v in variantes
                        ],
                    })
                if len(productos) >= limit:
                    break
        except Exception as e:
            print(f"listar_productos error: {e}")
        return productos[:limit]

    return _cached(key, _calc, ttl=1800)


def ventas_por_periodo(periodo: str = "30d") -> dict:
    """
    Resumen de ventas para un período predefinido.
    `periodo`: "7d" | "30d" | "90d" | "ytd"
    """
    hoy = date.today()
    if periodo == "7d":
        desde = hoy - timedelta(days=6)
    elif periodo == "30d":
        desde = hoy - timedelta(days=29)
    elif periodo == "90d":
        desde = hoy - timedelta(days=89)
    elif periodo == "ytd":
        desde = date(hoy.year, 1, 1)
    else:
        desde = hoy - timedelta(days=29)

    resumen = _suma_periodo(desde, hoy)
    serie = []
    d = desde
    while d <= hoy:
        serie.append({"fecha": d.isoformat(), "total": ventas_del_dia(d).get("total", 0.0)})
        d = d + timedelta(days=1)
    return {
        "periodo": periodo,
        "desde":   desde.isoformat(),
        "hasta":   hoy.isoformat(),
        "resumen": resumen,
        "serie":   serie,
    }
