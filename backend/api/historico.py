"""
backend.api.historico — Histórico de pedidos entregados (lectura).

Aislado del flujo operativo. Sirve la página /historico y nada más.
NO entra en KPIs, listados activos ni dashboards.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.core.security import CurrentUser, require_role
from backend.services import archivo as archivo_svc


log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/historico", tags=["historico"])


@router.get("/pedidos")
def listar(
    q: str = Query("", description="Buscar en nombre/teléfono/ciudad/orden"),
    desde: Optional[str] = Query(None, description="ISO YYYY-MM-DD"),
    hasta: Optional[str] = Query(None, description="ISO YYYY-MM-DD"),
    limit: int = Query(200, ge=1, le=1000),
    _: CurrentUser = Depends(require_role("admin", "operador")),
) -> dict:
    """Lista pedidos archivados. Filtros opcionales."""
    items = archivo_svc.listar(q=q, desde=desde, hasta=hasta, limit=limit)
    return {"total": len(items), "pedidos": items}


@router.get("/stats")
def stats(_: CurrentUser = Depends(require_role("admin", "operador"))) -> dict:
    """Resumen del archivo: total registros, % con novedad, rango."""
    return archivo_svc.stats()


@router.post("/backfill")
def backfill(_: CurrentUser = Depends(require_role("admin"))) -> dict:
    """
    Carga inicial: recorre el caché actual de pedidos y archiva los que
    están en estado entregado. Idempotente (upsert por orden).

    Pensado para correr UNA vez tras desplegar el módulo. Después el
    webhook hace el archivado incremental.
    """
    from backend.services import melonn as melonn_svc

    data = melonn_svc.obtener_pedidos(forzar_refresh=False)
    pedidos = data.get("pedidos", [])

    archivados = 0
    errores = 0
    for p in pedidos:
        if archivo_svc.archivar_si_entregado(p):
            archivados += 1
        # archivar_si_entregado retorna False si no aplica (no es error)

    return {
        "ok":         True,
        "revisados":  len(pedidos),
        "archivados": archivados,
        "errores":    errores,
    }
