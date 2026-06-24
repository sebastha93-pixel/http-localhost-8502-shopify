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
    """
    Obtiene un access token válido para la API de Kommo.

    Prioridad:
      1. Token OAuth2 desde Supabase (tabla kommo_oauth_tokens) si está
         vigente. Estos tokens incluyen el scope `chat` necesario para
         /talks/{id}/messages.
      2. Refresh automático si el OAuth token expiró.
      3. Fallback al long-lived KOMMO_API_TOKEN (sin scope de chat).

    Si nada funciona, RuntimeError.
    """
    # 1. Intentar OAuth token vigente
    try:
        oauth = _leer_oauth_token_vigente()
        if oauth:
            return oauth
    except Exception as e:
        log.debug(f"OAuth token check fallo: {e}")

    # 3. Fallback long-lived
    t = os.environ.get("KOMMO_API_TOKEN", "").strip()
    if not t:
        raise RuntimeError("KOMMO_API_TOKEN no configurado y sin OAuth token")
    return t


def _leer_oauth_token_vigente() -> Optional[str]:
    """
    Lee el access_token OAuth de Supabase. Si está por expirar (<5 min),
    lo refresca automáticamente.
    """
    import os as _os
    from datetime import datetime, timezone, timedelta
    from supabase import create_client

    url = _os.environ.get("SUPABASE_URL", "").strip()
    key = _os.environ.get("SUPABASE_KEY", "").strip()
    if not url or not key:
        return None

    sb = create_client(url, key)
    r = sb.table("kommo_oauth_tokens").select("*").order("updated_at", desc=True).limit(1).execute()
    if not r.data:
        return None

    row = r.data[0]
    expires_at_str = row.get("expires_at") or ""
    try:
        expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
    except Exception:
        return None

    # Si quedan más de 5 min, usar el token actual
    if datetime.now(timezone.utc) + timedelta(minutes=5) < expires_at:
        return row.get("access_token")

    # Token a punto de expirar → refrescar
    refresh_token = row.get("refresh_token")
    if not refresh_token:
        return None

    nuevo = _refrescar_oauth_token(refresh_token, row.get("account_id"))
    return nuevo


def _refrescar_oauth_token(refresh_token: str, account_id: Optional[int] = None) -> Optional[str]:
    """
    Intercambia refresh_token por nuevo access_token + refresh_token.
    Guarda en Supabase y retorna el access_token nuevo.
    """
    import os as _os
    from datetime import datetime, timezone, timedelta
    from supabase import create_client

    client_id     = _os.environ.get("KOMMO_CLIENT_ID", "").strip()
    client_secret = _os.environ.get("KOMMO_CLIENT_SECRET", "").strip()
    redirect_uri  = _os.environ.get("KOMMO_REDIRECT_URI", "").strip()
    if not client_id or not client_secret:
        log.warning("Refresh OAuth: falta CLIENT_ID o CLIENT_SECRET")
        return None

    url_token = f"https://{_subdomain()}.kommo.com/oauth2/access_token"
    try:
        r = requests.post(url_token, json={
            "client_id":     client_id,
            "client_secret": client_secret,
            "grant_type":    "refresh_token",
            "refresh_token": refresh_token,
            "redirect_uri":  redirect_uri,
        }, timeout=15)
        if not r.ok:
            log.warning(f"Refresh OAuth fallo {r.status_code}: {r.text[:200]}")
            return None
        data = r.json()
    except Exception as e:
        log.warning(f"Refresh OAuth exception: {e}")
        return None

    access_token  = data.get("access_token")
    refresh_new   = data.get("refresh_token") or refresh_token
    expires_in    = int(data.get("expires_in") or 86400)
    scope         = data.get("scope") or ""
    new_expires_at = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()

    # Guardar
    url = _os.environ.get("SUPABASE_URL", "").strip()
    key = _os.environ.get("SUPABASE_KEY", "").strip()
    sb = create_client(url, key)

    # Si no nos pasaron account_id, decodificar del JWT o consultar /account
    if not account_id:
        try:
            test_r = requests.get(
                f"https://{_subdomain()}.kommo.com/api/v4/account",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10,
            )
            if test_r.ok:
                account_id = test_r.json().get("id")
        except Exception:
            pass

    if not account_id:
        log.warning("Refresh OAuth: no se pudo determinar account_id")
        return None

    sb.table("kommo_oauth_tokens").upsert({
        "account_id":     account_id,
        "access_token":   access_token,
        "refresh_token":  refresh_new,
        "expires_at":     new_expires_at,
        "scope":          scope,
        "updated_at":     datetime.now(timezone.utc).isoformat(),
    }, on_conflict="account_id").execute()

    log.info(f"OAuth token refrescado para account {account_id} (expira {new_expires_at})")
    return access_token


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


def _post(path: str, body: dict | list) -> Optional[dict]:
    """POST a Kommo con rate limit + retry. Retorna respuesta JSON o None."""
    url = f"{_base_url()}/{path.lstrip('/')}"
    for attempt, backoff in enumerate([0] + _RETRY_BACKOFF):
        if backoff:
            log.warning(f"Kommo POST retry — esperando {backoff}s (intento {attempt+1})")
            time.sleep(backoff)
        _rate_limiter.wait()
        try:
            r = requests.post(url, headers=_headers(), json=body, timeout=_TIMEOUT)
            if r.status_code in (429, 503):
                ra = r.headers.get("Retry-After")
                wait = int(ra) if (ra and ra.isdigit() and int(ra) <= 60) else _RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF)-1)]
                log.warning(f"Kommo POST {r.status_code} — Retry-After {wait}s")
                if attempt < _RETRY_MAX:
                    time.sleep(wait)
                    continue
                return None
            if not r.ok:
                log.warning(f"Kommo POST {r.status_code} en {url}: {r.text[:300]}")
                return None
            try:
                return r.json()
            except Exception:
                return {}
        except Exception as e:
            log.warning(f"Kommo POST error en {url}: {e}")
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
def buscar_leads_por_phone(phone: str, limit: int = 5) -> list[dict]:
    """Busca leads en Kommo cuyo contacto tenga ese teléfono.

    Kommo NO busca por phone en /leads?query=. Hay que buscar primero el
    contacto con /contacts?query=PHONE (sí indexa teléfono) y luego traer
    los leads asociados. Retorna lista de leads (puede ser vacía).

    `phone`: teléfono como string. Kommo es flexible con formato.
    """
    if not phone:
        return []
    try:
        # 1. Buscar contactos con ese teléfono, incluyendo leads asociados.
        d = _get("contacts", {
            "query": phone,
            "limit": limit,
            "with": "leads",
        })
        if not d:
            return []
        contactos = ((d.get("_embedded") or {}).get("contacts")) or []
        if not contactos:
            return []
        # 2. Recolectar lead_ids únicos de los contactos encontrados.
        lead_ids: list[int] = []
        seen: set = set()
        for c in contactos:
            for ld in ((c.get("_embedded") or {}).get("leads")) or []:
                lid = ld.get("id")
                if lid and lid not in seen:
                    seen.add(lid)
                    lead_ids.append(int(lid))
        if not lead_ids:
            return []
        # 3. Traer los leads completos (uno por uno; suelen ser pocos).
        leads: list[dict] = []
        for lid in lead_ids[:limit]:
            ld = obtener_lead(lid)
            if ld:
                leads.append(ld)
        return leads
    except Exception:
        return []

def crear_lead_con_contacto(
    phone: str,
    pipeline_id: Optional[int] = None,
    source_name: str = "WhatsApp",
) -> Optional[dict]:
    """Crea un lead en Kommo con un contacto que tiene el teléfono indicado.

    El sales bot de Kommo (si está configurado en el pipeline) asignará la
    asesora automáticamente. Retorna el lead creado (dict) o None si falla.

    `phone`: teléfono normalizado (solo dígitos, ej. '573102039183').
    `pipeline_id`: si None, Kommo usa el pipeline default.
    `source_name`: nombre descriptivo de la fuente.
    """
    if not phone:
        return None
    phone_plus = phone if phone.startswith("+") else f"+{phone}"
    # Nombre del lead: identificable rápido en Kommo
    lead_name = f"{source_name} {phone_plus}"
    contact_name = f"Cliente {source_name}"
    lead_body: dict = {
        "name": lead_name,
        "_embedded": {
            "contacts": [
                {
                    "first_name": contact_name,
                    "custom_fields_values": [
                        {
                            "field_code": "PHONE",
                            "values": [
                                {"value": phone_plus, "enum_code": "MOB"}
                            ],
                        }
                    ],
                }
            ]
        },
    }
    if pipeline_id:
        lead_body["pipeline_id"] = int(pipeline_id)

    res = _post("leads/complex", [lead_body])
    # La respuesta es una lista con el lead creado: [{"id": 12345, ...}]
    if not res:
        return None
    items = res if isinstance(res, list) else ((res.get("_embedded") or {}).get("leads")) or []
    if not items:
        return None
    lead_id_int = items[0].get("id")
    if not lead_id_int:
        return None
    # Traer el lead completo (con contactos y campos) para upsert
    return obtener_lead(int(lead_id_int))


def listar_contactos_de_lead(lead_id: int) -> list[dict]:
    """Contactos asociados a un lead."""
    d = _get(f"leads/{lead_id}/contacts")
    if not d:
        return []
    return ((d.get("_embedded") or {}).get("contacts")) or []


def obtener_contacto(contact_id: int) -> Optional[dict]:
    """Detalle de un contacto (incluye campos custom y teléfono)."""
    return _get(f"contacts/{contact_id}")


def listar_contactos_por_ids(contact_ids: list[int]) -> list[dict]:
    """Trae varios contactos en un solo request usando filter[id][]=X&filter[id][]=Y.
    Kommo soporta hasta ~250 por página. Hace batches de 100 para seguridad."""
    if not contact_ids:
        return []
    import requests as _rq
    sub = os.environ.get("KOMMO_SUBDOMAIN", "").strip()
    if not sub:
        return []
    base = f"https://{sub}.kommo.com/api/v4/contacts"
    result: list[dict] = []
    BATCH = 100
    for i in range(0, len(contact_ids), BATCH):
        chunk = contact_ids[i:i + BATCH]
        params: list = [("limit", "250")]
        for cid in chunk:
            params.append(("filter[id][]", str(cid)))
        try:
            tok = _token()
            r = _rq.get(base, params=params, headers={"Authorization": f"Bearer {tok}"}, timeout=30)
            if r.status_code != 200:
                continue
            data = r.json()
            contacts = ((data.get("_embedded") or {}).get("contacts") or [])
            result.extend(contacts)
        except Exception:
            continue
    return result


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


def listar_talks(updated_after_ts: Optional[int] = None,
                  limit_total: int = 5000) -> Iterator[dict]:
    """
    Itera talks (conversaciones de chat). Cada talk es un "thread" entre
    un asesor y un cliente, ligado a un lead/contacto.

    Para esta cuenta (integración Widget), NO podemos acceder a los
    mensajes individuales del talk, pero sí a su metadata:
      - talk_id, chat_id
      - contact_id, entity_id (lead), entity_type
      - rate (calificación)
      - origin (waba, instagram_business, etc.)
      - status, is_in_work, is_read
      - created_at, updated_at
      - source_id
    Suficiente para análisis de tiempo, abandono, ranking por asesor.

    `updated_after_ts`: epoch seconds para incremental.
    """
    params: dict = {"limit": 250}
    if updated_after_ts:
        params["filter[updated_at][from]"] = int(updated_after_ts)

    enviados = 0
    for page in _paginar("talks", "talks", params):
        for talk in page:
            yield talk
            enviados += 1
            if enviados >= limit_total:
                return


def listar_tasks(updated_after_ts: Optional[int] = None,
                  limit_total: int = 10000) -> Iterator[dict]:
    """
    Itera todas las tasks (recordatorios/pendientes) de la cuenta Kommo.

    Cada task tiene:
      - id, entity_id, entity_type (lead/contact/etc), text
      - is_completed (bool), complete_till (epoch deadline)
      - responsible_user_id (asesora dueña)
      - created_at, updated_at
      - result (si fue completada, el resultado escrito)

    Para el KPI 'Leads sin tareas' filtramos: entity_type='leads' y
    is_completed=false.
    """
    params: dict = {"limit": 250}
    if updated_after_ts:
        params["filter[updated_at][from]"] = int(updated_after_ts)
    enviados = 0
    for page in _paginar("tasks", "tasks", params):
        for t in page:
            yield t
            enviados += 1
            if enviados >= limit_total:
                return


def listar_eventos_de_lead(lead_id: int) -> Iterator[dict]:
    """
    Eventos del lead (cambios de stage, asignaciones, etc.).
    Útil para entender el flujo cronológico.
    """
    params = {"filter[entity_id]": lead_id, "filter[entity_type]": "lead", "limit": 250}
    for page in _paginar("events", "events", params):
        for ev in page:
            yield ev
