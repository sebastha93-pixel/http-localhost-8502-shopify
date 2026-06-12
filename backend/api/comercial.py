"""
backend.api.comercial — Métricas comerciales de Shopify para el módulo Comercial.

Usa shopify_metrics (en src/) que ya tiene caché interno de 3-5 min.
Los datos vienen LIVE de Shopify con TTL corto, así que el API es rápido
en hits repetidos pero refresca cada pocos minutos.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.core.security import CurrentUser, require_role


router = APIRouter(prefix="/api/comercial", tags=["comercial"])


def _shopify_metrics():
    """Lazy import de src/shopify_metrics para que el backend no rompa si Shopify falla."""
    _SRC = Path(__file__).resolve().parent.parent.parent / "src"
    if str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))
    import shopify_metrics as sm
    return sm


@router.get("/overview")
def overview(
    _: CurrentUser = Depends(require_role("admin", "operador")),
) -> dict:
    """
    Overview comercial completo en una sola llamada.
    Devuelve: ventas hoy, ayer, delta, serie 12 días, top productos.
    """
    try:
        sm = _shopify_metrics()
    except Exception as e:
        raise HTTPException(503, f"Shopify metrics no disponible: {e}")

    payload: dict = {
        "ventas_hoy":   {},
        "delta":        {},
        "serie_12d":    [],
        "top_productos": [],
        "errores":      [],
    }

    # Cada bloque en try independiente — si uno falla, los otros funcionan
    try:
        payload["ventas_hoy"] = sm.ventas_del_dia()
    except Exception as e:
        payload["errores"].append(f"ventas_hoy: {str(e)[:100]}")

    try:
        payload["delta"] = sm.delta_vs_ayer()
    except Exception as e:
        payload["errores"].append(f"delta: {str(e)[:100]}")

    try:
        payload["serie_12d"] = sm.ventas_serie(dias_atras=12)
    except Exception as e:
        payload["errores"].append(f"serie: {str(e)[:100]}")

    try:
        payload["top_productos"] = sm.top_productos(n=5, dias=30)
    except Exception as e:
        payload["errores"].append(f"top_productos: {str(e)[:100]}")

    return payload


@router.get("/ventas")
def ventas(
    dias: int = Query(12, ge=1, le=60),
    _: CurrentUser = Depends(require_role("admin", "operador")),
) -> dict:
    """Serie diaria de ventas (default 12 días)."""
    try:
        sm = _shopify_metrics()
        return {
            "dias":  dias,
            "serie": sm.ventas_serie(dias_atras=dias),
            "hoy":   sm.ventas_del_dia(),
            "delta": sm.delta_vs_ayer(),
        }
    except Exception as e:
        raise HTTPException(503, f"Error consultando Shopify: {str(e)[:200]}")


@router.get("/top-productos")
def top_productos(
    n: int = Query(5, ge=1, le=20),
    dias: int = Query(30, ge=1, le=90),
    _: CurrentUser = Depends(require_role("admin", "operador")),
) -> dict:
    """Top N productos por revenue de los últimos `dias`."""
    try:
        sm = _shopify_metrics()
        return {"n": n, "dias": dias, "productos": sm.top_productos(n=n, dias=dias)}
    except Exception as e:
        raise HTTPException(503, f"Error consultando Shopify: {str(e)[:200]}")


@router.get("/comparativas")
def comparativas(
    _: CurrentUser = Depends(require_role("admin", "operador")),
) -> dict:
    """
    Comparativas temporales:
      - semana actual vs pasada (mismo día acumulado)
      - mes actual vs mes anterior (a la misma fecha)
      - YoY: mes actual vs mismo mes año pasado
    """
    try:
        sm = _shopify_metrics()
        return sm.comparativas()
    except Exception as e:
        raise HTTPException(503, f"Error: {str(e)[:200]}")


@router.get("/clientes")
def clientes(
    dias: int = Query(90, ge=30, le=365),
    _: CurrentUser = Depends(require_role("admin", "operador")),
) -> dict:
    """
    Análisis de clientes en los últimos `dias`:
    recurrentes vs nuevos, LTV, tasa de recompra, top 10 por revenue.
    """
    try:
        sm = _shopify_metrics()
        return sm.analisis_clientes(dias=dias)
    except Exception as e:
        raise HTTPException(503, f"Error: {str(e)[:200]}")


@router.get("/ventas-periodo")
def ventas_periodo(
    periodo: str = Query("30d", pattern="^(7d|30d|90d|ytd)$"),
    _: CurrentUser = Depends(require_role("admin", "operador")),
) -> dict:
    """Ventas para un período preset: 7d, 30d, 90d, ytd."""
    try:
        sm = _shopify_metrics()
        return sm.ventas_por_periodo(periodo=periodo)
    except Exception as e:
        raise HTTPException(503, f"Error: {str(e)[:200]}")
