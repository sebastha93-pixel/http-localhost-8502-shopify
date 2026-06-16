"""
backend.api.clientes — Clasificación de clientes basada en historial Shopify.
"""
from __future__ import annotations

from typing import List
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from backend.core.security import CurrentUser, require_role
from backend.services import clientes as svc


router = APIRouter(prefix="/api/clientes", tags=["clientes"])


@router.get("/clasificacion")
def clasificacion(
    email: str = Query(..., description="Email del cliente"),
    _: CurrentUser = Depends(require_role("admin", "operador")),
) -> dict:
    """Clasifica un cliente individual."""
    return svc.clasificar(email)


class BulkReq(BaseModel):
    emails: List[str]


@router.post("/clasificacion/bulk")
def clasificacion_bulk(
    body: BulkReq,
    _: CurrentUser = Depends(require_role("admin", "operador")),
) -> dict:
    """Clasifica varios clientes (un email por pedido). Max 100 por llamada."""
    emails = body.emails[:100]
    return {"clasificaciones": svc.clasificar_bulk(emails)}
