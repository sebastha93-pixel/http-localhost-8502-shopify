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
from datetime import datetime, date, timedelta, timezone
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
# Colombia es UTC-5 todo el año. Usamos esto para que "hoy" en el servidor
# (UTC) coincida con "hoy" del usuario en Colombia.
_TZ_BOGOTA = timezone(timedelta(hours=-5))


def hoy_bogota() -> date:
    """Fecha actual en zona horaria Colombia (no UTC del servidor)."""
    return datetime.now(_TZ_BOGOTA).date()


def _iso_inicio(d: date) -> str:
    return f"{d.isoformat()}T00:00:00-05:00"   # UTC-5 = Colombia


def _iso_fin(d: date) -> str:
    return f"{d.isoformat()}T23:59:59-05:00"


def _fetch_orders_dia(d: date, status: str = "any") -> list:
    """
    Trae TODAS las órdenes del día (creadas, sin filtrar por pago).
    Incluye total_tax y taxes_included para poder calcular ventas
    SIN IVA en Shopify Colombia (donde precios vienen con IVA incluido).
    """
    orders = []
    params = {
        "status": status,
        "created_at_min": _iso_inicio(d),
        "created_at_max": _iso_fin(d),
        "limit": 250,
        "fields": "id,total_price,subtotal_price,total_tax,taxes_included,total_discounts,line_items,created_at,financial_status,cancelled_at",
    }
    resp = _get("/orders.json", params)
    orders.extend(resp.get("orders", []))
    return orders


def _fetch_orders_rango(desde: date, hasta: date, fields: str,
                        status: str = "any") -> list:
    """Trae TODAS las órdenes del rango [desde, hasta] en UNA pasada con
    paginación por cursor — en vez de una llamada por día. Antes: 1 request
    por día (30 para 30d, 365 para YTD) y truncaba en 250 si un día tenía
    más. Ahora ~N/250 requests para todo el rango, sin truncar."""
    from shopify_client import paginar
    out: list = []
    params = {
        "status": status,
        "created_at_min": _iso_inicio(desde),
        "created_at_max": _iso_fin(hasta),
        "limit": 250,
        "fields": fields,
    }
    try:
        for page in paginar("/orders.json", "orders", params):
            out.extend(page)
    except Exception as e:
        import logging as _lg
        _lg.getLogger("shopify_metrics").warning(f"rango fetch: {e}")
        try:
            out = _get("/orders.json", params).get("orders", []) or []
        except Exception:
            pass
    return out


def _revenue_sin_iva(o: dict) -> float:
    """
    Revenue de UN orden SIN IVA — alineado con "Total sales" de Shopify Home.

    Fórmula: total_price - total_tax
    - total_price: TODO lo cobrado al cliente (productos + envío - descuentos
      + impuestos si taxes_not_included)
    - total_tax: monto de impuestos

    Resultado: lo facturado realmente, menos solo los impuestos. Incluye
    envío. Coincide con la métrica "Ventas totales" de Shopify reports.

    Funciona tanto en Shopify CO (taxes_included=true) como USA
    (taxes_included=false) porque total_tax siempre representa el tax
    aplicado, independiente de si vino dentro o fuera del precio.
    """
    total = float(o.get("total_price") or 0)
    tax   = float(o.get("total_tax")   or 0)
    return max(0.0, total - tax)


def _factor_sin_iva(o: dict) -> float:
    """
    Factor para convertir cualquier monto del orden de "con IVA" a "sin IVA".
    Útil para descontar IVA proporcional a descuentos.

    Basado en la relación total_price → revenue_sin_iva:
      factor = (total - tax) / total
    """
    total = float(o.get("total_price") or 0)
    if total <= 0:
        return 1.0
    tax = float(o.get("total_tax") or 0)
    return (total - tax) / total if total > tax else 1.0


# ── API pública ────────────────────────────────────────────────────────────────
def ventas_del_dia(d: Optional[date] = None) -> dict:
    """
    Retorna métricas de ventas de un día (default = hoy):
      { fecha, total, num_pedidos, ticket_promedio }
    """
    d = d or hoy_bogota()
    key = f"vd_{d.isoformat()}"

    def _calc():
        orders = _fetch_orders_dia(d)
        # Revenue SIN IVA: en Shopify Colombia los precios tienen IVA
        # incluido, así que subtotal_price - total_tax = neto real.
        # Excluir cancelados.
        validos = [o for o in orders if not o.get("cancelled_at")]
        total = sum(_revenue_sin_iva(o) for o in validos)
        n = len(validos)
        return {
            "fecha": d.isoformat(),
            "total": total,
            "num_pedidos": n,
            "ticket_promedio": (total / n) if n else 0.0,
        }
    # Cache corto para hoy (datos cambian), largo para días pasados
    ttl = 180 if d == hoy_bogota() else 86400
    return _cached(key, _calc, ttl=ttl)


def ventas_serie(dias_atras: int = 12) -> list:
    """
    Lista de totales de ventas para los últimos `dias_atras` días (incluyendo hoy).
    Útil para el sparkline. El día más reciente queda al final.
    """
    key = f"vs_{dias_atras}_{hoy_bogota().isoformat()}"

    def _calc():
        out = []
        hoy = hoy_bogota()
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
    hoy   = ventas_del_dia(hoy_bogota())["total"]
    ayer  = ventas_del_dia(hoy_bogota() - timedelta(days=1))["total"]
    pct   = ((hoy - ayer) / ayer * 100) if ayer else 0
    return {"hoy": hoy, "ayer": ayer, "pct": pct, "up": pct >= 0}


def top_productos(n: int = 5, dias: int = 30) -> list:
    """
    Top N productos por revenue acumulado en los últimos `dias`.
    Retorna lista de dicts: { sku, nombre, revenue, unidades, pct_del_total }
    """
    key = f"top_{n}_{dias}_{hoy_bogota().isoformat()}"

    def _calc():
        hoy = hoy_bogota()
        agregado: dict = defaultdict(lambda: {"revenue": 0.0, "unidades": 0, "nombre": "", "sku": ""})

        desde_tp = hoy - timedelta(days=max(dias - 1, 0))
        orders = _fetch_orders_rango(desde_tp, hoy, "id,line_items,cancelled_at")
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
    hoy = hoy_bogota()

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
def _fetch_orders_periodo(desde: date, hasta: date, fields: str = "id,total_price,subtotal_price,total_tax,taxes_included,total_discounts,customer,created_at,cancelled_at") -> list:
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
    key = f"ac_{dias}_{hoy_bogota().isoformat()}"

    def _calc():
        hoy = hoy_bogota()
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
            # Revenue del cliente SIN IVA (Shopify CO: subtotal - total_tax)
            if o.get("cancelled_at"):
                continue
            por_cliente[cid]["revenue"] += _revenue_sin_iva(o)
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


# ─── Desglose de ventas: bruto / neto / canal / asesor ────────────────────────
_USER_CACHE: dict = {}   # id → nombre


def _cargar_users_map() -> dict:
    """
    Mapeo manual user_id (Shopify) → nombre, vía env var SHOPIFY_USERS_MAP.
    Formato JSON: {"110649442624": "Juan Pérez", "110649344320": "María García"}

    El endpoint /users/{id}.json solo está en Shopify Plus, así que para
    cuentas regulares (la mayoría) usamos este mapa manual. Editar la env
    var en Railway y redeploy.
    """
    import json as _json, os as _os
    raw = _os.environ.get("SHOPIFY_USERS_MAP", "").strip()
    if not raw:
        return {}
    try:
        return _json.loads(raw)
    except Exception:
        return {}


def _nombre_asesor(user_id) -> str:
    """
    Resuelve el nombre del staff member que creó un draft order.
    Orden de búsqueda:
      1) Cache en memoria (ya resuelto antes en esta sesión)
      2) SHOPIFY_USERS_MAP (mapeo manual desde env var, recomendado)
      3) /users/{id}.json (solo funciona en Shopify Plus)
      4) Fallback: "User {id}"
    """
    if not user_id:
        return ""
    uid = str(user_id)
    if uid in _USER_CACHE:
        return _USER_CACHE[uid]

    # Mapa manual (Shopify NO Plus)
    mapa = _cargar_users_map()
    if uid in mapa:
        _USER_CACHE[uid] = mapa[uid]
        return mapa[uid]

    # API /users (solo Shopify Plus — falla en cuentas regulares)
    try:
        r = _get(f"/users/{uid}.json")
        u = r.get("user") or {}
        nombre = f"{u.get('first_name','')} {u.get('last_name','')}".strip() or u.get("email", "") or f"User {uid}"
    except Exception:
        nombre = f"User {uid}"
    _USER_CACHE[uid] = nombre
    return nombre


def asesores_raw_ids() -> list[str]:
    """Devuelve los user_ids únicos vistos hasta ahora — útil para descubrir
    qué IDs hay que mapear en SHOPIFY_USERS_MAP."""
    return sorted(_USER_CACHE.keys())


def _canal_label(source_name: str) -> str:
    """Normaliza source_name de Shopify a etiqueta legible."""
    s = (source_name or "").lower()
    if "draft" in s:        return "Draft (manual)"
    if "web" in s:          return "Online store"
    if "pos" in s:          return "POS"
    if "mobile" in s:       return "App móvil"
    if "shopify_draft" in s: return "Draft (manual)"
    return source_name or "Otros"


def desglose_ventas(
    periodo: str = "30d",
    desde_custom: Optional[str] = None,
    hasta_custom: Optional[str] = None,
) -> dict:
    """
    Desglose de ventas por canal y asesor en el período pedido.

    `periodo`: hoy | ayer | 7d | 30d | mes | ytd | custom
    Si periodo=custom, usa desde_custom y hasta_custom (ISO YYYY-MM-DD).
    """
    hoy = hoy_bogota()
    if periodo == "hoy":
        desde = hoy
        hasta = hoy
    elif periodo == "ayer":
        desde = hoy - timedelta(days=1)
        hasta = desde
    elif periodo == "7d":
        desde = hoy - timedelta(days=6); hasta = hoy
    elif periodo == "30d":
        desde = hoy - timedelta(days=29); hasta = hoy
    elif periodo == "mes":
        desde = hoy.replace(day=1); hasta = hoy
    elif periodo == "ytd":
        desde = date(hoy.year, 1, 1); hasta = hoy
    elif periodo == "custom":
        try:
            desde = datetime.fromisoformat((desde_custom or "")[:10]).date()
            hasta = datetime.fromisoformat((hasta_custom or "")[:10]).date()
        except Exception:
            desde = hoy - timedelta(days=29); hasta = hoy
        if hasta < desde:
            desde, hasta = hasta, desde
        # Cap a 365 días para no explotar
        if (hasta - desde).days > 365:
            desde = hasta - timedelta(days=365)
    else:
        desde = hoy - timedelta(days=29); hasta = hoy

    key = f"dv_{periodo}_{desde.isoformat()}_{hasta.isoformat()}"

    def _calc():
        bruto = 0.0
        neto  = 0.0
        descuentos = 0.0
        num = 0
        # RF-02: además de ventas y pedidos, contamos unidades para el UPT.
        canal_agg: dict = defaultdict(lambda: {"ventas": 0.0, "num_pedidos": 0, "unidades": 0})
        asesor_agg: dict = defaultdict(lambda: {"ventas": 0.0, "num_pedidos": 0, "unidades": 0})
        unidades_total = 0

        # Optimizado: UNA pasada por todo el rango (paginación por cursor).
        _orders_rango = _fetch_orders_rango(
            desde, hasta,
            "id,total_price,subtotal_price,total_tax,taxes_included,total_discounts,source_name,user_id,cancelled_at,line_items",
        )
        d = hasta
        while d <= hasta:
            orders = _orders_rango

            for o in orders:
                # Excluir cancelados del cálculo de revenue
                if o.get("cancelled_at"):
                    continue

                # En Shopify Colombia (taxes_included=true), los precios y
                # descuentos vienen con IVA. Aplicamos factor proporcional
                # para sacar el IVA de TODO consistentemente.
                f = _factor_sin_iva(o)  # 1.0 si taxes NOT included
                sub_neto  = _revenue_sin_iva(o)  # subtotal sin IVA
                desc_neto = float(o.get("total_discounts") or 0) * f

                bruto      += sub_neto + desc_neto
                neto       += sub_neto
                descuentos += desc_neto
                num        += 1

                # Unidades vendidas del pedido (suma de cantidades de líneas)
                unidades_orden = sum(
                    int(li.get("quantity") or 0) for li in (o.get("line_items") or [])
                )
                unidades_total += unidades_orden

                canal = _canal_label(o.get("source_name", ""))
                canal_agg[canal]["ventas"]       += sub_neto
                canal_agg[canal]["num_pedidos"]  += 1
                canal_agg[canal]["unidades"]     += unidades_orden

                # Solo los draft orders tienen user_id (creados por staff)
                uid = o.get("user_id")
                if uid:
                    nombre = _nombre_asesor(uid)
                    asesor_agg[nombre]["ventas"]      += sub_neto
                    asesor_agg[nombre]["num_pedidos"] += 1
                    asesor_agg[nombre]["unidades"]    += unidades_orden

            d += timedelta(days=1)

        # Ordenar por ventas desc y calcular pct + UPT (unidades por pedido)
        def _rankear(agg: dict, key_nombre: str) -> list:
            items = [{key_nombre: k, **v} for k, v in agg.items()]
            items.sort(key=lambda x: x["ventas"], reverse=True)
            for it in items:
                it["pct"] = round(it["ventas"] / neto * 100, 1) if neto else 0
                # RF-02: UPT = unidades / número de pedidos, con un decimal
                it["upt"] = round(it["unidades"] / it["num_pedidos"], 1) if it["num_pedidos"] else 0
            return items

        return {
            "periodo":     periodo,
            "desde":       desde.isoformat(),
            "hasta":       hasta.isoformat(),
            "bruto":       round(bruto, 0),
            "neto":        round(neto, 0),
            "descuentos":  round(descuentos, 0),
            "num_pedidos": num,
            "unidades":    unidades_total,
            "upt":         round(unidades_total / num, 1) if num else 0,
            "ticket_promedio": round(neto / num, 0) if num else 0,
            "por_canal":   _rankear(canal_agg, "label"),
            "por_asesor":  _rankear(asesor_agg, "nombre"),
        }

    # Cache 10 min para hoy, 30 min para periodos cerrados
    ttl = 600 if periodo == "hoy" else 1800
    return _cached(key, _calc, ttl=ttl)


# ─── RF-05: Ventas por Fit y Talla ────────────────────────────────────────────
def _resolver_periodo(periodo: str, desde_custom: Optional[str],
                      hasta_custom: Optional[str]) -> tuple:
    """Devuelve (desde, hasta) para un período nombrado o custom."""
    hoy = hoy_bogota()
    if periodo == "hoy":      return hoy, hoy
    if periodo == "ayer":     return hoy - timedelta(days=1), hoy - timedelta(days=1)
    if periodo == "7d":       return hoy - timedelta(days=6), hoy
    if periodo == "mes":      return hoy.replace(day=1), hoy
    if periodo == "ytd":      return date(hoy.year, 1, 1), hoy
    if periodo == "custom":
        try:
            d = datetime.fromisoformat((desde_custom or "")[:10]).date()
            h = datetime.fromisoformat((hasta_custom or "")[:10]).date()
            if h < d: d, h = h, d
            if (h - d).days > 365: d = h - timedelta(days=365)
            return d, h
        except Exception:
            pass
    return hoy - timedelta(days=29), hoy   # 30d default


def _fit_de_nombre(nombre: str) -> str:
    """Fit derivado del nombre cuando el producto no tiene 'tipo' en Shopify.
    Toma las 2 primeras palabras (ej. 'Jean flare', 'Jean wide') para agrupar."""
    palabras = (nombre or "").strip().split()
    if not palabras:
        return "Sin tipo"
    base = " ".join(palabras[:2]).strip(" .,-")
    return base[:1].upper() + base[1:] if base else "Sin tipo"


def _mapa_tipos_producto() -> dict:
    """product_id (str) → {fit, nombre}. Cache 30 min. Fit = product_type de
    Shopify; si está vacío, se deriva del nombre (RF-05)."""
    key = f"ptypes_{hoy_bogota().isoformat()}"

    def _calc():
        from shopify_client import paginar
        m: dict = {}
        # OJO: /products.json NO acepta status='any' (solo active/draft/archived);
        # con 'any' devolvía vacío y el Fit caía siempre al nombre. Traemos los 3.
        for status in ("active", "draft", "archived"):
            try:
                for page in paginar("/products.json", "products",
                                    {"status": status, "limit": 250,
                                     "fields": "id,product_type,title"}):
                    for p in page:
                        titulo = p.get("title") or ""
                        tipo = (p.get("product_type") or "").strip()
                        m[str(p.get("id"))] = {
                            "fit": tipo or _fit_de_nombre(titulo),
                            "nombre": titulo,
                        }
            except Exception:
                continue
        return m
    return _cached(key, _calc, ttl=1800)


def ventas_por_fit_talla(periodo: str = "30d",
                         desde_custom: Optional[str] = None,
                         hasta_custom: Optional[str] = None,
                         canal: Optional[str] = None) -> dict:
    """RF-05 — ventas netas, unidades, participación y ticket promedio por
    Fit (tipo de producto) y por Talla (variante). Filtro opcional por canal."""
    desde, hasta = _resolver_periodo(periodo, desde_custom, hasta_custom)
    key = f"vft_{periodo}_{desde.isoformat()}_{hasta.isoformat()}_{canal or ''}"

    def _calc():
        tipos = _mapa_tipos_producto()

        def _nuevo():
            return {"ventas": 0.0, "unidades": 0, "pedidos": set()}
        fit_agg: dict = defaultdict(_nuevo)
        talla_agg: dict = defaultdict(_nuevo)
        matriz: dict = defaultdict(lambda: {"ventas": 0.0, "unidades": 0})
        neto_total = 0.0
        unid_total = 0
        canales_vistos: set = set()

        _orders_rango = _fetch_orders_rango(
            desde, hasta,
            "id,total_price,total_tax,source_name,cancelled_at,line_items",
        )
        d = hasta
        while d <= hasta:
            orders = _orders_rango

            for o in orders:
                if o.get("cancelled_at"):
                    continue
                canal_o = _canal_label(o.get("source_name", ""))
                canales_vistos.add(canal_o)
                if canal and canal_o != canal:
                    continue
                f = _factor_sin_iva(o)
                oid = o.get("id")
                for li in (o.get("line_items") or []):
                    qty = int(li.get("quantity") or 0)
                    if qty <= 0:
                        continue
                    linea_neto = float(li.get("price") or 0) * qty * f
                    pid = str(li.get("product_id") or "")
                    info = tipos.get(pid) or {}
                    fit = info.get("fit") or _fit_de_nombre(li.get("title") or "") or "Sin tipo"
                    talla = (li.get("variant_title") or "").strip() or "Única"

                    fit_agg[fit]["ventas"] += linea_neto
                    fit_agg[fit]["unidades"] += qty
                    fit_agg[fit]["pedidos"].add(oid)
                    talla_agg[talla]["ventas"] += linea_neto
                    talla_agg[talla]["unidades"] += qty
                    talla_agg[talla]["pedidos"].add(oid)
                    mk = f"{fit}||{talla}"
                    matriz[mk]["ventas"] += linea_neto
                    matriz[mk]["unidades"] += qty
                    neto_total += linea_neto
                    unid_total += qty
            d += timedelta(days=1)

        def _lista(agg: dict, campo: str) -> list:
            out = []
            for k, v in agg.items():
                npd = len(v["pedidos"])
                out.append({
                    campo: k,
                    "ventas": round(v["ventas"], 0),
                    "unidades": v["unidades"],
                    "num_pedidos": npd,
                    "participacion": round(v["ventas"] / neto_total * 100, 1) if neto_total else 0,
                    "ticket_promedio": round(v["ventas"] / npd, 0) if npd else 0,
                })
            out.sort(key=lambda x: x["ventas"], reverse=True)
            return out

        matriz_out = [
            {"fit": mk.split("||")[0], "talla": mk.split("||")[1],
             "ventas": round(mv["ventas"], 0), "unidades": mv["unidades"]}
            for mk, mv in matriz.items()
        ]
        matriz_out.sort(key=lambda x: x["ventas"], reverse=True)

        return {
            "periodo": periodo,
            "desde": desde.isoformat(),
            "hasta": hasta.isoformat(),
            "canal": canal or "todos",
            "canales": sorted(canales_vistos),
            "neto": round(neto_total, 0),
            "unidades": unid_total,
            "por_fit": _lista(fit_agg, "fit"),
            "por_talla": _lista(talla_agg, "talla"),
            "matriz": matriz_out,
        }

    ttl = 600 if periodo == "hoy" else 1800
    return _cached(key, _calc, ttl=ttl)


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
    key = f"inv_{hoy_bogota().isoformat()}"

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
    Lista productos con stock por variante + precios + descuentos + lanzamiento.

    Por variante:
      - precio              (lo que cuesta hoy)
      - precio_full         (compare_at_price si hay; precio tachado)
      - descuento_pct       (calculado si precio_full > precio)

    Por producto:
      - precio_min / precio_max  (rango entre variantes con precio > 0)
      - descuento_max_pct        (mayor descuento de sus variantes)
      - published_at, dias_publicado  (lanzamiento en Shopify)

    Cache 30 min.
    """
    key = f"prods_{status}_{hoy_bogota().isoformat()}"

    def _calc():
        from shopify_client import paginar
        # Cruzar con stock real Melonn por SKU (vacío si falla la API)
        try:
            import sys as _sys
            from pathlib import Path as _Path
            _src = _Path(__file__).resolve().parent
            if str(_src) not in _sys.path:
                _sys.path.insert(0, str(_src))
            from melonn_client import stock_por_warehouse
            stock_melonn = stock_por_warehouse("MED-2")
        except Exception:
            stock_melonn = {}

        productos = []
        try:
            fields = "id,title,status,vendor,product_type,handle,image,variants,created_at,updated_at,published_at"
            for page in paginar(
                "/products.json",
                "products",
                {"status": status, "limit": min(limit, 250), "fields": fields},
            ):
                for p in page:
                    variantes = p.get("variants") or []
                    total_stock = sum(max(int(v.get("inventory_quantity") or 0), 0) for v in variantes)
                    sin_stock = all(int(v.get("inventory_quantity") or 0) <= 0 for v in variantes)

                    # Precios + descuento + cruce con stock Melonn por variante
                    vars_enriched = []
                    precios: list[float] = []
                    descuento_max = 0.0
                    total_stock_melonn = 0
                    melonn_match = False
                    for v in variantes:
                        precio = float(v.get("price") or 0)
                        compare_raw = v.get("compare_at_price")
                        precio_full = float(compare_raw) if compare_raw else 0.0
                        if precio_full > precio > 0:
                            desc_pct = round((precio_full - precio) / precio_full * 100, 1)
                        else:
                            desc_pct = 0.0
                            precio_full = 0.0
                        descuento_max = max(descuento_max, desc_pct)
                        if precio > 0:
                            precios.append(precio)

                        # Match SKU contra stock Melonn
                        sku_norm = (v.get("sku") or "").strip()
                        stock_m = stock_melonn.get(sku_norm)
                        if stock_m is not None:
                            melonn_match = True
                            total_stock_melonn += max(stock_m, 0)
                        vars_enriched.append({
                            "id":             v.get("id"),
                            "sku":            sku_norm,
                            "titulo":         v.get("title") or "",
                            "precio":         precio,
                            "precio_full":    precio_full,
                            "descuento_pct":  desc_pct,
                            "stock":          int(v.get("inventory_quantity") or 0),
                            "stock_melonn":   stock_m,  # None si no hay match
                        })

                    # Fecha de lanzamiento + días publicado
                    pub_at = p.get("published_at") or ""
                    dias_pub = None
                    if pub_at:
                        try:
                            pub_d = datetime.fromisoformat(pub_at.replace("Z", "+00:00")).date()
                            dias_pub = (hoy_bogota() - pub_d).days
                        except Exception:
                            pass

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
                        "precio_min":    min(precios) if precios else 0,
                        "precio_max":    max(precios) if precios else 0,
                        "descuento_max_pct": descuento_max,
                        "published_at":   pub_at,
                        "dias_publicado": dias_pub,
                        "updated_at":    p.get("updated_at") or "",
                        # Match Melonn — None si no se cruzó ninguna variante
                        "stock_melonn":          total_stock_melonn if melonn_match else None,
                        "diferencia_shopify_melonn": (total_stock - total_stock_melonn) if melonn_match else None,
                        "variantes":     vars_enriched,
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
    hoy = hoy_bogota()
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
