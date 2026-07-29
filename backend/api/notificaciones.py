"""
backend.api.notificaciones — Campanita de avisos internos.

Sin gate de permisos por módulo a propósito: cualquiera autenticado puede leer
LO SUYO. El aislamiento es por email en el servicio (filtra por
destinatario_email en cada query), no por rol.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query

from backend.core.security import CurrentUser, get_current_user
from backend.services import notificaciones as svc


log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/notificaciones", tags=["notificaciones"])


@router.get("")
def listar(
    solo_no_leidas: bool = Query(False, description="Solo las pendientes"),
    limite: int = Query(svc.LIMITE_DEFAULT, ge=1, le=100),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Mis avisos + cuántos sin leer.

    El frontend consulta esto cada ~20s. Devuelve las dos cosas de una para no
    gastar dos viajes en cada poll.
    """
    items = svc.listar(user.email, limite=limite, solo_no_leidas=solo_no_leidas)
    return {
        "ok": True,
        "no_leidas": svc.contar_no_leidas(user.email),
        "total": len(items),
        "notificaciones": items,
    }


@router.post("/{notif_id}/leida")
def marcar_leida(
    notif_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    ok = svc.marcar_leida(notif_id, user.email)
    return {"ok": ok, "no_leidas": svc.contar_no_leidas(user.email)}


@router.post("/leer-todas")
def leer_todas(user: CurrentUser = Depends(get_current_user)) -> dict:
    n = svc.marcar_todas_leidas(user.email)
    return {"ok": True, "marcadas": n, "no_leidas": svc.contar_no_leidas(user.email)}
