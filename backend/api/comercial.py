"""
backend.api.comercial — Métricas comerciales de Shopify para el módulo Comercial.

Usa shopify_metrics (en src/) que ya tiene caché interno de 3-5 min.
Los datos vienen LIVE de Shopify con TTL corto, así que el API es rápido
en hits repetidos pero refresca cada pocos minutos.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.core.security import CurrentUser, require_role, require_permission


router = APIRouter(prefix="/api/comercial", tags=["comercial"])


def _shopify_metrics():
    """Lazy import de src/shopify_metrics para que el backend no rompa si Shopify falla."""
    _SRC = Path(__file__).resolve().parent.parent.parent / "src"
    if str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))
    import shopify_metrics as sm
    return sm


async def _run(fn, *args, **kwargs):
    """Corre una función sync en un thread para no bloquear el event loop."""
    return await asyncio.to_thread(fn, *args, **kwargs)


@router.get("/overview")
async def overview(
    _: CurrentUser = Depends(require_permission("comercial", "modificar")),
) -> dict:
    """
    Overview comercial completo en una sola llamada.
    Las 4 sub-queries corren EN PARALELO via asyncio.gather. Antes eran
    secuenciales (~80s en cold start); ahora el endpoint termina en lo
    que tarda la más lenta (~20-30s frío, <1s con cache caliente).
    """
    try:
        sm = _shopify_metrics()
    except Exception as e:
        raise HTTPException(503, f"Shopify metrics no disponible: {e}")

    ventas_hoy, delta, serie_12d, top_productos = await asyncio.gather(
        _run(sm.ventas_del_dia),
        _run(sm.delta_vs_ayer),
        _run(sm.ventas_serie, dias_atras=12),
        _run(sm.top_productos, n=5, dias=30),
        return_exceptions=True,
    )

    payload: dict = {
        "ventas_hoy":   {},
        "delta":        {},
        "serie_12d":    [],
        "top_productos": [],
        "errores":      [],
    }
    for nombre, slot, res in [
        ("ventas_hoy",    "ventas_hoy",    ventas_hoy),
        ("delta",         "delta",         delta),
        ("serie",         "serie_12d",     serie_12d),
        ("top_productos", "top_productos", top_productos),
    ]:
        if isinstance(res, Exception):
            payload["errores"].append(f"{nombre}: {str(res)[:120]}")
        else:
            payload[slot] = res
    return payload


@router.get("/ventas")
def ventas(
    dias: int = Query(12, ge=1, le=60),
    _: CurrentUser = Depends(require_permission("comercial", "modificar")),
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
    _: CurrentUser = Depends(require_permission("comercial", "modificar")),
) -> dict:
    """Top N productos por revenue de los últimos `dias`."""
    try:
        sm = _shopify_metrics()
        return {"n": n, "dias": dias, "productos": sm.top_productos(n=n, dias=dias)}
    except Exception as e:
        raise HTTPException(503, f"Error consultando Shopify: {str(e)[:200]}")


@router.get("/comparativas")
def comparativas(
    _: CurrentUser = Depends(require_permission("comercial", "modificar")),
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
    _: CurrentUser = Depends(require_permission("comercial", "modificar")),
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


@router.get("/asesores-map")
def asesores_map(_: CurrentUser = Depends(require_role("admin"))) -> dict:
    """RF-01 — Diagnóstico: muestra el mapa actual SHOPIFY_USERS_MAP y los
    user_id de Shopify vistos en pedidos recientes con el nombre que resuelven.
    Sirve para identificar cuál id muestra 'Nombre 4' y corregirlo en Railway."""
    import os as _os, json as _json
    from datetime import timedelta
    sm = _shopify_metrics()
    try:
        mapa_actual = _json.loads(_os.environ.get("SHOPIFY_USERS_MAP", "").strip() or "{}")
    except Exception:
        mapa_actual = {"__error__": "SHOPIFY_USERS_MAP no es JSON válido"}

    vistos: dict = {}
    try:
        from shopify_client import _get
        hoy = sm.hoy_bogota()
        d = hoy - timedelta(days=45)
        while d <= hoy:
            try:
                resp = _get("/orders.json", {
                    "status": "any",
                    "created_at_min": sm._iso_inicio(d),
                    "created_at_max": sm._iso_fin(d),
                    "limit": 250, "fields": "id,user_id",
                })
                for o in (resp.get("orders") or []):
                    uid = o.get("user_id")
                    if uid:
                        vistos[str(uid)] = vistos.get(str(uid), 0) + 1
            except Exception:
                pass
            d += timedelta(days=1)
    except Exception as e:
        return {"mapa_actual": mapa_actual, "error": str(e)[:200]}

    asesores = [
        {"user_id": uid, "pedidos_45d": n,
         "nombre_actual": sm._nombre_asesor(uid),
         "mapeado": uid in mapa_actual}
        for uid, n in sorted(vistos.items(), key=lambda x: -x[1])
    ]
    return {
        "mapa_actual": mapa_actual,
        "asesores_vistos": asesores,
        "instruccion": "Edita SHOPIFY_USERS_MAP en Railway: reemplaza el nombre del user_id que muestre 'Nombre 4' por 'Manuela Gómez'.",
    }


@router.get("/debug/ordenes-hoy")
def debug_ordenes_hoy(_: CurrentUser = Depends(require_role("admin"))) -> dict:
    """
    DEBUG: lista todas las órdenes de HOY con sus campos crudos para
    comparar contra Shopify Home y entender de dónde sale la diferencia.
    """
    import sys
    from pathlib import Path
    from datetime import date, datetime, timedelta, timezone
    _SRC = Path(__file__).resolve().parent.parent.parent / "src"
    if str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))
    import shopify_metrics as sm

    hoy = sm.hoy_bogota()
    # Para debug: pedir TODOS los fields relevantes
    try:
        params = {
            "status": "any",
            "created_at_min": sm._iso_inicio(hoy),
            "created_at_max": sm._iso_fin(hoy),
            "limit": 250,
            "fields": "id,name,source_name,source_identifier,channel_id,test,total_price,subtotal_price,total_tax,taxes_included,total_discounts,financial_status,cancelled_at,confirmed,closed_at",
        }
        from shopify_client import _get
        resp = _get("/orders.json", params)
        orders = resp.get("orders", []) if resp else []
    except Exception as e:
        raise HTTPException(503, f"Error: {e}")

    rows = []
    suma_total_price       = 0.0
    suma_subtotal_price    = 0.0
    suma_total_tax         = 0.0
    suma_total_discounts   = 0.0
    suma_revenue_sin_iva   = 0.0
    incluidos = 0
    excluidos_cancel = 0

    for o in orders:
        total_price = float(o.get("total_price") or 0)
        subtotal    = float(o.get("subtotal_price") or 0)
        tax         = float(o.get("total_tax") or 0)
        discounts   = float(o.get("total_discounts") or 0)
        cancelled   = bool(o.get("cancelled_at"))
        rev         = sm._revenue_sin_iva(o)
        rows.append({
            "id":               o.get("id"),
            "name":             o.get("name"),
            "source_name":      o.get("source_name"),
            "source_id":        o.get("source_identifier"),
            "channel_id":       o.get("channel_id"),
            "test":             o.get("test"),
            "confirmed":        o.get("confirmed"),
            "closed_at":        o.get("closed_at"),
            "financial":        o.get("financial_status"),
            "cancelled":        cancelled,
            "taxes_included":   o.get("taxes_included"),
            "total_price":      total_price,
            "subtotal_price":   subtotal,
            "total_tax":        tax,
            "total_discounts":  discounts,
            "revenue_sin_iva":  rev,
        })
        if cancelled:
            excluidos_cancel += 1
            continue
        suma_total_price     += total_price
        suma_subtotal_price  += subtotal
        suma_total_tax       += tax
        suma_total_discounts += discounts
        suma_revenue_sin_iva += rev
        incluidos += 1

    return {
        "fecha": hoy.isoformat(),
        "total_ordenes": len(orders),
        "incluidos": incluidos,
        "excluidos_cancelled": excluidos_cancel,
        "sumas": {
            "total_price":      round(suma_total_price, 0),
            "subtotal_price":   round(suma_subtotal_price, 0),
            "total_tax":        round(suma_total_tax, 0),
            "total_discounts":  round(suma_total_discounts, 0),
            "revenue_sin_iva":  round(suma_revenue_sin_iva, 0),
        },
        "ordenes": rows,
    }


@router.get("/desglose")
def desglose(
    periodo: str = Query("30d", pattern="^(hoy|ayer|7d|30d|mes|ytd|custom)$"),
    desde:   str = Query("", description="ISO YYYY-MM-DD (solo si periodo=custom)"),
    hasta:   str = Query("", description="ISO YYYY-MM-DD (solo si periodo=custom)"),
    _: CurrentUser = Depends(require_permission("comercial", "modificar")),
) -> dict:
    """Desglose de ventas: bruto, neto, descuentos, por canal y por asesor.
    Al canal se le suman las tiendas físicas (Florida/Arrayanes) desde las
    facturas de Siigo por centro de costo — Shopify no las ve."""
    try:
        sm = _shopify_metrics()
        data = sm.desglose_ventas(periodo=periodo, desde_custom=desde, hasta_custom=hasta)
    except Exception as e:
        raise HTTPException(503, f"Error: {str(e)[:200]}")

    try:
        from backend.services import siigo
        if siigo.siigo_configurado():
            tiendas = siigo.ventas_tiendas(data.get("desde"), data.get("hasta"))
            if tiendas:
                # COPIAR siempre: `data` es el objeto cacheado de shopify_metrics
                # y mutarlo duplicaba las tiendas en cada petición.
                data = dict(data)
                canales = [dict(c) for c in (data.get("por_canal") or [])
                           if not str(c.get("label", "")).startswith("Tienda ")]
                canales.extend(dict(t) for t in tiendas)
                total = sum(float(c.get("ventas") or 0) for c in canales) or 1.0
                for c in canales:
                    c["pct"] = round(float(c.get("ventas") or 0) / total * 100, 1)
                canales.sort(key=lambda c: float(c.get("ventas") or 0), reverse=True)
                data["por_canal"] = canales
                data["tiendas_siigo"] = True

                # Consolidar los KPIs del período: tiendas + canales digitales
                t_neto = sum(float(t.get("ventas") or 0) for t in tiendas)
                t_bruto = sum(float(t.get("bruto") or 0) for t in tiendas)
                t_desc = sum(float(t.get("descuentos") or 0) for t in tiendas)
                t_ped = sum(int(t.get("num_pedidos") or 0) for t in tiendas)
                t_und = sum(int(t.get("unidades") or 0) for t in tiendas)
                data["neto"] = round(float(data.get("neto") or 0) + t_neto, 0)
                data["bruto"] = round(float(data.get("bruto") or 0) + t_bruto, 0)
                data["descuentos"] = round(float(data.get("descuentos") or 0) + t_desc, 0)
                data["num_pedidos"] = int(data.get("num_pedidos") or 0) + t_ped
                data["unidades"] = int(data.get("unidades") or 0) + t_und
                if data["num_pedidos"]:
                    data["ticket_promedio"] = round(data["neto"] / data["num_pedidos"], 0)
    except Exception as e:
        # Siigo caído no debe tumbar el desglose de Shopify
        import logging
        logging.getLogger("comercial").warning(f"ventas_tiendas siigo: {e}")

    return data


@router.get("/fit-talla")
def fit_talla(
    periodo: str = Query("30d", pattern="^(hoy|ayer|7d|30d|mes|ytd|custom)$"),
    desde:   str = Query(""),
    hasta:   str = Query(""),
    canal:   str = Query(""),
    _: CurrentUser = Depends(require_permission("comercial", "modificar")),
) -> dict:
    """RF-05 — Ventas por Fit y Talla (netas, unidades, participación, ticket)."""
    try:
        sm = _shopify_metrics()
        return sm.ventas_por_fit_talla(
            periodo=periodo, desde_custom=desde, hasta_custom=hasta,
            canal=canal or None,
        )
    except Exception as e:
        raise HTTPException(503, f"Error: {str(e)[:200]}")


@router.get("/fit-ciudad")
def fit_ciudad(
    periodo: str = Query("30d", pattern="^(hoy|ayer|7d|30d|mes|ytd|custom)$"),
    desde:   str = Query(""),
    hasta:   str = Query(""),
    _: CurrentUser = Depends(require_permission("comercial", "modificar")),
) -> dict:
    """Fit más vendido por ciudad de envío (Shopify)."""
    try:
        sm = _shopify_metrics()
        return sm.ventas_fit_por_ciudad(periodo=periodo, desde_custom=desde, hasta_custom=hasta)
    except Exception as e:
        raise HTTPException(503, f"Error: {str(e)[:200]}")


@router.get("/ubicacion")
def ubicacion(
    periodo: str = Query("30d", pattern="^(hoy|ayer|7d|30d|mes|ytd|custom)$"),
    desde:   str = Query(""),
    hasta:   str = Query(""),
    _: CurrentUser = Depends(require_permission("comercial", "modificar")),
) -> dict:
    """% de ventas por ciudad y por departamento (separados)."""
    try:
        sm = _shopify_metrics()
        return sm.ventas_por_ubicacion(periodo=periodo, desde_custom=desde, hasta_custom=hasta)
    except Exception as e:
        raise HTTPException(503, f"Error: {str(e)[:200]}")


@router.get("/inventario")
def inventario(
    _: CurrentUser = Depends(require_permission("comercial", "modificar")),
) -> dict:
    """
    Inventario Shopify: productos activos / borrador / archivados +
    stock total + SKUs sin stock y con stock bajo.
    """
    try:
        sm = _shopify_metrics()
        return sm.inventario_shopify()
    except Exception as e:
        raise HTTPException(503, f"Error: {str(e)[:200]}")


@router.get("/ventas-periodo")
def ventas_periodo(
    periodo: str = Query("30d", pattern="^(7d|30d|90d|ytd)$"),
    _: CurrentUser = Depends(require_permission("comercial", "modificar")),
) -> dict:
    """Ventas para un período preset: 7d, 30d, 90d, ytd."""
    try:
        sm = _shopify_metrics()
        return sm.ventas_por_periodo(periodo=periodo)
    except Exception as e:
        raise HTTPException(503, f"Error: {str(e)[:200]}")
