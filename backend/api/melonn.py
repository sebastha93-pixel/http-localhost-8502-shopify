"""
backend.api.melonn — Endpoints REST de logística (Melonn).
"""
from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.services import melonn as svc


router = APIRouter(prefix="/api/melonn", tags=["melonn"])


# ── Modelos de respuesta (Pydantic — auto-doc en /docs) ──────────────────────

class PedidoListResponse(BaseModel):
    pedidos: list[dict]
    total: int
    fuente: str
    stale: bool
    fetched_at: str


class CacheInfoResponse(BaseModel):
    total: Optional[int]      = None
    age_seconds: Optional[int]= None
    fetched_at: Optional[str] = None
    stale: Optional[bool]     = None
    fuente: Optional[str]     = None
    backend: Optional[str]    = None


class StatusResponse(BaseModel):
    credenciales_ok: bool
    cache: Optional[CacheInfoResponse] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/status", response_model=StatusResponse)
def status() -> StatusResponse:
    """Estado de la integración Melonn — credenciales y caché."""
    return StatusResponse(
        credenciales_ok=svc.credenciales_ok(),
        cache=svc.cache_info() and CacheInfoResponse(**svc.cache_info()),
    )


@router.get("/pedidos", response_model=PedidoListResponse)
def pedidos(
    refresh: bool = Query(default=False, description="Forzar fetch a la API"),
) -> PedidoListResponse:
    """
    Lista de pedidos activos.

    - `refresh=true` → fetch en vivo a Melonn (lento, ~2-30s)
    - `refresh=false` → caché Supabase (instantáneo)
    """
    try:
        data = svc.obtener_pedidos(forzar_refresh=refresh)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Melonn API error: {exc}")
    return PedidoListResponse(**data)
