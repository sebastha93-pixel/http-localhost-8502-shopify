"""
backend.api.inventario — Gestión del catálogo Shopify.

Diferencia con backend.api.comercial:
- /comercial: analítica de ventas (cómo estamos vendiendo)
- /inventario: estado del catálogo (qué tengo, qué falta, qué publicar)
"""
from __future__ import annotations

import sys
from pathlib import Path

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
    _: CurrentUser = Depends(require_permission("operaciones", "modificar")),
) -> dict:
    """KPIs del catálogo: activos, borrador, archivados, stock total, sin stock."""
    try:
        return _sm().inventario_shopify()
    except Exception as e:
        raise HTTPException(503, f"Error: {str(e)[:200]}")


@router.get("/productos")
def productos(
    status: str = Query("active", pattern="^(active|draft|archived)$"),
    limit: int = Query(250, ge=1, le=500),
    _: CurrentUser = Depends(require_permission("operaciones", "modificar")),
) -> dict:
    """Lista productos con stock por variante."""
    try:
        items = _sm().listar_productos(status=status, limit=limit)
        return {"status": status, "total": len(items), "productos": items}
    except Exception as e:
        raise HTTPException(503, f"Error: {str(e)[:200]}")


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
