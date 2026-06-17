"""
kommo_client.py — Cliente low-level de la API de Kommo CRM.

Patrón mismo de melonn_client/shopify_client: rate limiter token-bucket,
retry con backoff exponencial en 429/503, helpers paginados.

Doc oficial: https://developers.kommo.com/reference
Base URL:    https://{subdomain}.kommo.com/api/v4

Auth: long-lived token via header Authorization: Bearer X
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Iterator, Optional

import requests


log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
_TIMEOUT     = 30
_RETRY_MAX   = 3
_RETRY_BACKOFF = [2, 5, 12]  # s, total max ~20s

# Kommo permite ~7 req/s en plan business. Usamos 5 para tener margen.
_MAX_RPS      = 5.0
_MIN_INTERVAL = 1.0 / _MAX_RPS


class _RateLimiter:
    """Token bucket simple thread-safe."""
    def __init__(self):
        self._lock = threading.Lock()
        self._last_call = 0.0

    def wait(self):
        with self._lock:
            now = time.monotonic()
            delta = now - self._last_call
            if delta < _MIN_INTERVAL:
                time.sleep(_MIN_INTERVAL - delta)
            self._last_call = time.monotonic()


_rate_limiter = _RateLimiter()


def _subdomain() -> str:
    s = os.environ.get("KOMMO_SUBDOMAIN", "").strip().lower()
    if not s:
        raise RuntimeError("KOMMO_SUBDOMAIN no configurado")
    return s


def _token() -> str:
    t = os.environ.get("KOMMO_API_TOKEN", "").strip()
    if not t:
        raise RuntimeError("KOMMO_API_TOKEN no configurado")
    return t


def _base_url() -> str:
    return f"https://{_subdomain()}.kommo.com/api/v4"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_token()}",
        "Accept":        "application/json",
        "Content-Type":  "application/json",
    }


# ── HTTP helpers ──────────────────────────────────────────────────────────────
def _get(path: str, params: Optional[dict] = None) -> Optional[dict]:
    """GET con rate limit + retry en 429/503. Retorna None en error final."""
    url = f"{_base_url()}/{path.lstrip('/')}"
    for attempt, backoff in enumerate([0] + _RETRY_BACKOFF):
        if backoff:
            log.warning(f"Kommo retry — esperando {backoff}s (intento {attempt+1})")
            time.sleep(backoff)
        _rate_limiter.wait()
        try:
            r = requests.get(url, headers=_headers(), params=params, timeout=_TIMEOUT)
            if r.status_code == 204:
                return {}  # No content (lista vacía)
            if r.status_code in (429, 503):
                ra = r.headers.get("Retry-After")
                wait = int(ra) if (ra and ra.isdigit() and int(ra) <= 60) else _RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF)-1)]
                log.warning(f"Kommo {r.status_code} — Retry-After {wait}s")
                if attempt < _RETRY_MAX:
                    time.sleep(wait)
                    continue
                return None
            if not r.ok:
                log.warning(f"Kommo {r.status_code} en {url}: {r.text[:200]}")
                return None
            return r.json()
        except Exception as e:
            log.warning(f"Kommo error en {url}: {e}")
            if attempt < _RETRY_MAX:
                continue
            return None
    return None


def _paginar(path: str, embedded_key: str, params: Optional[dict] = None,
             max_paginas: int = 500) -> Iterator[list]:
    """
    Itera todas las páginas de un endpoint Kommo.

    Kommo paginación: usa query param `page` (1-indexed) y `limit` (max 250).
    El _embedded.{embedded_key} contiene los items. Cuando no hay más páginas,
    el response no incluye _links.next.

    Yields: lista de items de cada página.
    """
    params = dict(params or {})
    params.setdefault("limit", 250)
    page = 1
    while page <= max_paginas:
        params["page"] = page
        data = _get(path, params)
        if not data:
            return
        items = ((data.get("_embedded") or {}).get(embedded_key)) or []
        if not items:
            return
        yield items
        # Si no hay link "next", terminamos
        links = data.get("_links") or {}
        if not links.get("next"):
            return
        page += 1


# ── Endpoints públicos ────────────────────────────────────────────────────────
def verificar_conexion() -> dict:
    """
    Health check: llama GET /account y devuelve info básica.
    Útil para validar credenciales sin disparar sync completo.
    """
    try:
        info = _get("account")
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    if not info:
        return {"ok": False, "error": "Sin respuesta de Kommo (credencial inválida o subdomain mal)"}
    return {
        "ok":              True,
        "subdomain":       info.get("subdomain"),
        "account_id":      info.get("id"),
        "account_name":    info.get("name"),
        "current_user_id": info.get("current_user_id"),
        "country":         info.get("country"),
        "currency":        info.get("currency"),
    }


def listar_usuarios() -> list[dict]:
    """Lista los usuarios (asesoras) del CRM. Para popular tabla advisors."""
    users = []
    for page in _paginar("users", "users", {"limit": 250}):
        users.extend(page)
    return users


def listar_pipelines() -> list[dict]:
    """Lista pipelines + stages. Útil para descubrir IDs."""
    data = _get("leads/pipelines")
    if not data:
        return []
    return ((data.get("_embedded") or {}).get("pipelines")) or []


def listar_leads(updated_after_ts: Optional[int] = None,
                 limit_total: int = 5000) -> Iterator[dict]:
    """
    Itera leads, opcionalmente filtrando por fecha de actualización.

    `updated_after_ts`: epoch seconds. Si se pasa, solo leads modificados
    después de ese momento. Si None, trae TODOS (full sync — usar con
    cuidado).

    Yields cada lead individualmente (no por página).
    """
    params: dict = {
        "limit": 250,
        "with": "contacts,catalog_elements,loss_reason",
    }
    if updated_after_ts:
        params["filter[updated_at][from]"] = int(updated_after_ts)

    enviados = 0
    for page_items in _paginar("leads", "leads", params):
        for lead in page_items:
            yield lead
            enviados += 1
            if enviados >= limit_total:
                return


def obtener_lead(lead_id: int) -> Optional[dict]:
    """Detalle completo de un lead específico."""
    return _get(f"leads/{lead_id}", {"with": "contacts,catalog_elements,loss_reason"})


def listar_contactos_de_lead(lead_id: int) -> list[dict]:
    """Contactos asociados a un lead."""
    d = _get(f"leads/{lead_id}/contacts")
    if not d:
        return []
    return ((d.get("_embedded") or {}).get("contacts")) or []


def obtener_contacto(contact_id: int) -> Optional[dict]:
    """Detalle de un contacto (incluye campos custom y teléfono)."""
    return _get(f"contacts/{contact_id}")


# ── Conversaciones / mensajes ─────────────────────────────────────────────────
# Kommo expone los chats vía endpoint /chats (Chats API) en el dominio
# api.kommo.com (no en el subdomain). Los mensajes históricos también se
# obtienen como "notes" del lead con note_type relacionado.
#
# Aproximación: usar /leads/{id}/notes que incluye mensajes de WhatsApp
# como notes de tipo amochat_message o similares.

def listar_notes_de_lead(lead_id: int,
                          updated_after_ts: Optional[int] = None) -> Iterator[dict]:
    """
    Itera notes (mensajes) de un lead. En Kommo, los mensajes de chat
    aparecen como notes con note_type específico.
    """
    params: dict = {"limit": 250}
    if updated_after_ts:
        params["filter[updated_at][from]"] = int(updated_after_ts)

    for page in _paginar(f"leads/{lead_id}/notes", "notes", params):
        for note in page:
            yield note


def listar_eventos_de_lead(lead_id: int) -> Iterator[dict]:
    """
    Eventos del lead (cambios de stage, asignaciones, etc.).
    Útil para entender el flujo cronológico.
    """
    params = {"filter[entity_id]": lead_id, "filter[entity_type]": "lead", "limit": 250}
    for page in _paginar("events", "events", params):
        for ev in page:
            yield ev
