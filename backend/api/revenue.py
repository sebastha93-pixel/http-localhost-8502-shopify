"""
backend.api.revenue — Endpoints del módulo Revenue Intelligence.

F1: sync con Kommo + stats. F2 agregará endpoints de IA. F3+ los del
dashboard.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone, timedelta

import requests
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse

from backend.core.security import CurrentUser, require_role
from backend.services import kommo as kommo_svc
from backend.services import revenue_db as db
from backend.services import audit_ia
from backend.services import informe_consultor as informe_svc


log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/revenue", tags=["revenue"])


# ── OAuth2 con Kommo (necesario para scope de chats) ─────────────────────────
@router.get("/oauth/start")
def oauth_start() -> RedirectResponse:
    """
    Inicia el flujo OAuth2 redirigiendo al usuario al consentimiento de Kommo.
    PÚBLICO: el endpoint solo redirige a Kommo, no expone info sensible.
    El intercambio del code por tokens en /oauth/callback sí valida.
    """
    client_id    = os.environ.get("KOMMO_CLIENT_ID", "").strip()
    redirect_uri = os.environ.get("KOMMO_REDIRECT_URI", "").strip()
    subdomain    = os.environ.get("KOMMO_SUBDOMAIN", "").strip()
    if not client_id or not redirect_uri or not subdomain:
        raise HTTPException(503, "Falta KOMMO_CLIENT_ID / KOMMO_REDIRECT_URI / KOMMO_SUBDOMAIN")

    # Kommo OAuth URL: para integraciones tipo Server-side NO usar
    # mode=post_message (es para widgets en iframe). El flow estándar es
    # solo client_id + state. Kommo redirige al redirect_uri con ?code=XXX.
    url = (
        f"https://www.kommo.com/oauth?"
        f"client_id={client_id}&"
        f"state=revenue"
    )
    return RedirectResponse(url)


@router.get("/oauth/callback")
def oauth_callback(
    code: str = Query(..., description="Code temporal devuelto por Kommo"),
    referer: str = Query("", description="Subdomain.kommo.com de la cuenta"),
    state: str = Query(""),
) -> dict:
    """
    Recibe el authorization code de Kommo y lo intercambia por access_token
    + refresh_token. Los guarda en Supabase (tabla kommo_oauth_tokens).

    Endpoint público — no requiere auth de Male Denim OS porque Kommo
    redirige aquí externamente.
    """
    client_id     = os.environ.get("KOMMO_CLIENT_ID", "").strip()
    client_secret = os.environ.get("KOMMO_CLIENT_SECRET", "").strip()
    redirect_uri  = os.environ.get("KOMMO_REDIRECT_URI", "").strip()
    subdomain     = os.environ.get("KOMMO_SUBDOMAIN", "").strip()
    if not client_id or not client_secret or not redirect_uri:
        raise HTTPException(503, "Falta config OAuth (CLIENT_ID / CLIENT_SECRET / REDIRECT_URI)")

    # 1. Intercambiar code por tokens
    url_token = f"https://{subdomain}.kommo.com/oauth2/access_token"
    try:
        r = requests.post(url_token, json={
            "client_id":     client_id,
            "client_secret": client_secret,
            "grant_type":    "authorization_code",
            "code":          code,
            "redirect_uri":  redirect_uri,
