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
    email: str = Query("", description="Email del cliente (opcional si hay teléfono)"),
    telefono: str = Query("", description="Teléfono del cliente (opcional si hay email)"),
    _: CurrentUser = Depends(require_role("admin", "operador")),
) -> dict:
    """Clasifica un cliente. Busca por email primero, fallback a teléfono."""
    return svc.clasificar(email=email, telefono=telefono)


class BulkItem(BaseModel):
    email: str = ""
    telefono: str = ""


class BulkReq(BaseModel):
    items: List[BulkItem]


@router.post("/clasificacion/bulk")
def clasificacion_bulk(
    body: BulkReq,
    _: CurrentUser = Depends(require_role("admin", "operador")),
) -> dict:
    """Clasifica varios clientes. Cada item con email y/o teléfono. Max 100."""
    items = [{"email": i.email, "telefono": i.telefono} for i in body.items[:100]]
    return {"clasificaciones": svc.clasificar_bulk(items)}
