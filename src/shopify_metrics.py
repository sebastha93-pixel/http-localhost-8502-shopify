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
