"""
backend.api.notificaciones — Campanita de avisos internos.

Sin gate de permisos por módulo a propósito: cualquiera autenticado puede leer
LO SUYO. El aislamiento es por email en el servicio (filtra por
destinatario_email en cada query), no por rol.
"""
from __future__ import annotations

import logging

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.core.security import CurrentUser, get_current_user
from backend.services import notificaciones as svc


log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/notificaciones", tags=["notificaciones"])


@router.get("")
def listar(
    solo_no_leidas: bool = Query(False, description="Solo las pendientes"),
    limite: int = Query(svc.LIMITE_DEFAULT, ge=1, le=100),
    area: Optional[str] = Query(None, description="produccion | cartera | logistica | otros"),
    con_areas: bool = Query(False, description="Incluir sin leer por área (panel abierto)"),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Mis avisos + cuántos sin leer.

    El frontend consulta esto cada ~20s. Devuelve las dos cosas de una para no
    gastar dos viajes en cada poll. `no_leidas` es SIEMPRE el total (el número
    de la campanita); `area` solo filtra la lista. El conteo por área cuesta
    tres consultas, así que va solo cuando el panel está abierto (`con_areas`).
    """
    try:
        items = svc.listar(user.email, limite=limite, solo_no_leidas=solo_no_leidas,
                           area=area)
    except ValueError:
        raise HTTPException(400, "area_invalida")
    total = svc.contar_no_leidas(user.email)
    out = {
        "ok": True,
        "no_leidas": total,
        "total": len(items),
        "notificaciones": items,
    }
    if con_areas:
        out["por_area"] = svc.no_leidas_por_area(user.email, total)
    return out


@router.post("/{notif_id}/leida")
def marcar_leida(
    notif_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    ok = svc.marcar_leida(notif_id, user.email)
    return {"ok": ok, "no_leidas": svc.contar_no_leidas(user.email)}


@router.post("/leer-todas")
def leer_todas(
    area: Optional[str] = Query(None),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    try:
        n = svc.marcar_todas_leidas(user.email, area=area)
    except ValueError:
        raise HTTPException(400, "area_invalida")
    return {"ok": True, "marcadas": n, "no_leidas": svc.contar_no_leidas(user.email)}
