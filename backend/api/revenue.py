"""
backend.api.revenue — Endpoints del módulo Revenue Intelligence.

F1: sync con Kommo + stats. F2 agregará endpoints de IA. F3+ los del
dashboard.
"""
from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, HTTPException, Query

from backend.core.security import CurrentUser, require_role
from backend.services import kommo as kommo_svc
from backend.services import revenue_db as db


log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/revenue", tags=["revenue"])


# ── Health ────────────────────────────────────────────────────────────────────
@router.get("/health")
def health(_: CurrentUser = Depends(require_role("admin", "operador"))) -> dict:
    """
    Valida la conexión con Kommo y devuelve info de la cuenta.
    Útil para confirmar que las env vars KOMMO_SUBDOMAIN/KOMMO_API_TOKEN
    están bien configuradas.
    """
    return kommo_svc.verificar_conexion()


@router.get("/stats")
def stats(_: CurrentUser = Depends(require_role("admin", "operador"))) -> dict:
    """KPIs del módulo: cuántos leads/conv/mensajes/audits."""
    return db.stats_revenue()


# ── Sync ──────────────────────────────────────────────────────────────────────
@router.post("/sync/advisors")
def sync_advisors_endpoint(
    _: CurrentUser = Depends(require_role("admin")),
) -> dict:
    """Trae asesoras de Kommo y las puebla en advisors. Idempotente."""
    return kommo_svc.sync_advisors()


@router.post("/sync/leads")
def sync_leads_endpoint(
    full: bool = Query(False, description="True = full sync (lento). False = solo cambios"),
    limit: int = Query(1000, ge=1, le=5000),
    _: CurrentUser = Depends(require_role("admin")),
) -> dict:
    """
    Sync de leads desde Kommo. Por defecto incremental (solo cambios
    desde el último sync). Con full=True trae todos.
    """
    return kommo_svc.sync_leads(full=full, limit_total=limit)


@router.post("/sync/lead/{lead_id}/messages")
def sync_messages_endpoint(
    lead_id: int,
    _: CurrentUser = Depends(require_role("admin")),
) -> dict:
    """Trae mensajes de un lead específico (por si quieres re-procesar uno)."""
    return kommo_svc.sync_messages_de_lead(lead_id)


@router.post("/sync/completo")
def sync_completo_endpoint(
    full: bool = Query(False),
    lead_limit: int = Query(200, ge=1, le=5000),
    msg_limit: int = Query(50, ge=1, le=500),
    _: CurrentUser = Depends(require_role("admin")),
) -> dict:
    """
    Pasada completa: asesoras + leads + mensajes.
    El cron de revenue_scheduler llama esto cada 15 min.
    """
    return kommo_svc.sync_completo(full=full, lead_limit=lead_limit, msg_limit_por_lead=msg_limit)


# ── Debug / introspección de Kommo (admin only) ──────────────────────────────
@router.get("/debug/pipelines")
def debug_pipelines(_: CurrentUser = Depends(require_role("admin"))) -> dict:
    """Lista pipelines + stages de Kommo. Útil para mapear el catálogo."""
    import sys
    from pathlib import Path
    _SRC = Path(__file__).resolve().parent.parent.parent / "src"
    if str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))
    import kommo_client as kc
    try:
        return {"pipelines": kc.listar_pipelines()}
    except Exception as e:
        raise HTTPException(503, f"Error: {str(e)[:200]}")


@router.get("/debug/lead/{lead_id}")
def debug_lead(lead_id: int, _: CurrentUser = Depends(require_role("admin"))) -> dict:
    """Detalle crudo de un lead de Kommo. Para inspeccionar campos."""
    import sys
    from pathlib import Path
    _SRC = Path(__file__).resolve().parent.parent.parent / "src"
    if str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))
    import kommo_client as kc
    try:
        return {"lead": kc.obtener_lead(lead_id)}
    except Exception as e:
        raise HTTPException(503, f"Error: {str(e)[:200]}")
