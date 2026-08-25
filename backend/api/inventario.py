"""
backend.api.inventario — Gestión del catálogo Shopify.

Diferencia con backend.api.comercial:
- /comercial: analítica de ventas (cómo estamos vendiendo)
- /inventario: estado del catálogo (qué tengo, qué falta, qué publicar)
"""
from __future__ import annotations

import sys
from pathlib import Path

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.core.security import CurrentUser, require_role, require_permission


router = APIRouter(prefix="/api/inventario", tags=["inventario"])


def _sm():
    _SRC = Path(__file__).resolve().parent.parent.parent / "src"
    if str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))
    import shopify_metrics as sm
    return sm


@router.get("/resumen")
def resumen(
    _: CurrentUser = Depends(require_permission("operaciones", "ver")),
) -> dict:
    """KPIs del catálogo: activos, borrador, archivados, stock total, sin stock."""
    try:
        return _sm().inventario_shopify()
    except Exception as e:
        raise HTTPException(503, f"Error: {str(e)[:200]}")


@router.get("/productos")
def productos(
    status: str = Query("active", pattern="^(active|draft|archived)$"),
    limit: Optional[int] = Query(None, ge=1, le=5000,
                                 description="Sin valor = todo el catálogo"),
    _: CurrentUser = Depends(require_permission("operaciones", "ver")),
) -> dict:
    """Lista productos con stock por variante.

    Por defecto trae TODO el catálogo. Antes el default era 250 y con 859
    productos activos la pantalla mostraba el 29% reportando `total: 250` —
    la cifra confirmaba el recorte en lugar de delatarlo.
    """
    try:
        items = _sm().listar_productos(status=status, limit=limit)
        return {"status": status, "total": len(items), "productos": items,
                # Explícito: si se pidió un tope y se alcanzó, hay más detrás.
                "truncado": bool(limit) and len(items) >= limit}
    except Exception as e:
        raise HTTPException(503, f"Error: {str(e)[:200]}")


@router.get("/por-tienda")
def por_tienda(
    force: bool = Query(False),
    _: CurrentUser = Depends(require_permission("operaciones", "ver")),
) -> dict:
    """RF-06 — Inventario disponible por tienda/bodega (Florida, Arrayanes, Melonn…)."""
    from backend.services import siigo
    if not siigo.siigo_configurado():
        raise HTTPException(503, "Siigo no configurado.")
    try:
        return siigo.inventario_por_bodega(force=force)
    except Exception as e:
        raise HTTPException(503, f"siigo: {str(e)[:200]}")


@router.get("/siigo/descubrir")
def siigo_descubrir(_: CurrentUser = Depends(require_role("admin"))) -> dict:
    """RF-06/RF-03 — Diagnóstico: estructura cruda de Siigo (bodegas, centros de
    costo, muestra de productos y facturas) para confirmar cómo están modeladas
    Florida y Arrayanes antes de construir los reportes por tienda."""
    from backend.services import siigo
    if not siigo.siigo_configurado():
        raise HTTPException(503, "Siigo no configurado (faltan SIIGO_* en Railway).")
    try:
        return siigo.descubrir_estructura_tiendas()
    except Exception as e:
        raise HTTPException(503, f"siigo: {str(e)[:200]}")
