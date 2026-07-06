"""
backend.api.clientes — Clasificación de clientes basada en historial Shopify.
"""
from __future__ import annotations

from typing import List
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from backend.core.security import (CurrentUser, require_role, require_permission,
                                    require_permission_any)
from backend.services import clientes as svc


router = APIRouter(prefix="/api/clientes", tags=["clientes"])


@router.get("/clasificacion")
def clasificacion(
    email: str = Query("", description="Email del cliente (opcional si hay teléfono)"),
    telefono: str = Query("", description="Teléfono del cliente (opcional si hay email)"),
    _: CurrentUser = Depends(require_permission_any(("operaciones", "comercial"), "ver")),
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
    _: CurrentUser = Depends(require_permission_any(("operaciones", "comercial"), "ver")),
) -> dict:
    """Clasifica varios clientes. Cada item con email y/o teléfono. Max 100."""
    items = [{"email": i.email, "telefono": i.telefono} for i in body.items[:100]]
    return {"clasificaciones": svc.clasificar_bulk(items)}


@router.post("/cache/purgar")
def cache_purgar(_: CurrentUser = Depends(require_role("admin"))) -> dict:
    """Borra TODO el caché de clasificaciones (admin only)."""
    return svc.purgar_cache()


@router.get("/debug/pedidos-crudos")
def debug_pedidos_crudos(
    email: str = Query("", description="Email del cliente"),
    telefono: str = Query("", description="Teléfono del cliente"),
    _: CurrentUser = Depends(require_role("admin")),
) -> dict:
    """DEBUG: lista todos los pedidos crudos de Shopify para un cliente.
    Útil para diagnosticar por qué hay 'otros' en el historial."""
    return svc.debug_pedidos_crudos(email=email, telefono=telefono)
