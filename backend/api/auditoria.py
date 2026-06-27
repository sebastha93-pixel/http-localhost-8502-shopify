"""
backend.api.auditoria — Log global de acciones y notas (solo admin).

Lee directamente las tablas `acciones` y `notas` de Supabase y las
unifica en un timeline ordenado por fecha descendente.
"""
from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from supabase import create_client, Client

from backend.core.security import CurrentUser, require_role, require_permission


router = APIRouter(prefix="/api/auditoria", tags=["auditoria"])

_client: Optional[Client] = None


def _sb() -> Optional[Client]:
    global _client
    if _client is not None:
        return _client
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_KEY", "").strip()
    if not url or not key:
        return None
    try:
        _client = create_client(url, key)
        return _client
    except Exception:
        return None


class EventoAuditoria(BaseModel):
    kind: str               # "accion" | "nota"
    orden: str
    tipo: str               # tipo de acción, o "nota"
    descripcion: str
    autor: str
    creada_en: Optional[str] = None


class AuditoriaResponse(BaseModel):
    eventos: list[EventoAuditoria]
    total: int
    autores: list[str]      # autores únicos (para el filtro de la UI)
    tipos: list[str]        # tipos únicos


@router.get("", response_model=AuditoriaResponse)
def listar_auditoria(
    autor: Optional[str] = Query(default=None, description="Filtrar por autor exacto"),
    tipo: Optional[str] = Query(default=None, description="Filtrar por tipo de acción"),
    orden: Optional[str] = Query(default=None, description="Filtrar por orden (parcial)"),
    limit: int = Query(default=300, le=1000),
    _: CurrentUser = Depends(require_role("admin")),
) -> AuditoriaResponse:
    """Timeline global de acciones + notas. Solo administradores."""
    sb = _sb()
    if sb is None:
        raise HTTPException(status_code=503, detail="Supabase no configurado")

    eventos: list[EventoAuditoria] = []

    # ── Acciones ──
    try:
        q = sb.table("acciones").select("orden,tipo,descripcion,autor,creada_en")
        if autor:
            q = q.eq("autor", autor)
        if tipo and tipo != "nota":
            q = q.eq("tipo", tipo)
        res = q.order("creada_en", desc=True).limit(limit).execute()
        for r in (res.data or []):
            eventos.append(EventoAuditoria(
                kind="accion",
                orden=r.get("orden") or "",
                tipo=r.get("tipo") or "",
                descripcion=r.get("descripcion") or "",
                autor=r.get("autor") or "",
                creada_en=r.get("creada_en"),
            ))
    except Exception as e:
        print(f"[auditoria] Error acciones: {e}")

    # ── Notas (solo si no se filtró por un tipo específico de acción) ──
    if not tipo or tipo == "nota":
        try:
            q = sb.table("notas").select("orden,autor,nota,creada_en")
            if autor:
                q = q.eq("autor", autor)
            res = q.order("creada_en", desc=True).limit(limit).execute()
            for r in (res.data or []):
                eventos.append(EventoAuditoria(
                    kind="nota",
                    orden=r.get("orden") or "",
                    tipo="nota",
                    descripcion=r.get("nota") or "",
                    autor=r.get("autor") or "",
                    creada_en=r.get("creada_en"),
                ))
        except Exception as e:
            print(f"[auditoria] Error notas: {e}")

    # Filtro por orden (parcial, cliente no puede hacerlo en supabase fácil)
    if orden:
        term = orden.strip().lower()
        eventos = [e for e in eventos if term in e.orden.lower()]

    # Ordenar unificado por fecha desc + limitar
    eventos.sort(key=lambda e: e.creada_en or "", reverse=True)
    eventos = eventos[:limit]

    autores = sorted({e.autor for e in eventos if e.autor})
    tipos = sorted({e.tipo for e in eventos if e.tipo})

    return AuditoriaResponse(
        eventos=eventos,
        total=len(eventos),
        autores=autores,
        tipos=tipos,
    )
