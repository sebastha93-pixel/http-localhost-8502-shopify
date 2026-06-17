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


log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/revenue", tags=["revenue"])


# ── OAuth2 con Kommo (necesario para scope de chats) ─────────────────────────
@router.get("/oauth/start")
def oauth_start(
    user: CurrentUser = Depends(require_role("admin")),
) -> RedirectResponse:
    """
    Inicia el flujo OAuth2 redirigiendo al usuario al consentimiento de Kommo.
    Pide explícitamente el scope `chat` que el long-lived token no tiene.
    """
    client_id    = os.environ.get("KOMMO_CLIENT_ID", "").strip()
    redirect_uri = os.environ.get("KOMMO_REDIRECT_URI", "").strip()
    subdomain    = os.environ.get("KOMMO_SUBDOMAIN", "").strip()
    if not client_id or not redirect_uri or not subdomain:
        raise HTTPException(503, "Falta KOMMO_CLIENT_ID / KOMMO_REDIRECT_URI / KOMMO_SUBDOMAIN")

    # Kommo OAuth URL: el usuario aprueba en su CRM y Kommo redirige al
    # redirect_uri con ?code=XXX&referer=subdomain.kommo.com
    url = (
        f"https://{subdomain}.kommo.com/oauth?"
        f"client_id={client_id}&"
        f"state=revenue&"
        f"mode=post_message"
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
        }, timeout=15)
    except Exception as e:
        raise HTTPException(502, f"No se pudo contactar Kommo: {e}")

    if not r.ok:
        return {"ok": False, "status": r.status_code, "body": r.text[:400]}

    data = r.json()
    access_token  = data.get("access_token")
    refresh_token = data.get("refresh_token")
    expires_in    = int(data.get("expires_in") or 86400)
    scope         = data.get("scope") or ""

    # 2. Determinar account_id del nuevo token
    account_id = None
    try:
        info = requests.get(
            f"https://{subdomain}.kommo.com/api/v4/account",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        if info.ok:
            account_id = info.json().get("id")
    except Exception:
        pass

    if not account_id:
        return {"ok": False, "error": "No se pudo determinar account_id con el nuevo token"}

    # 3. Guardar en Supabase
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()
    sb = db._sb()
    if sb is None:
        raise HTTPException(503, "Supabase no configurado")
    sb.table("kommo_oauth_tokens").upsert({
        "account_id":    account_id,
        "access_token":  access_token,
        "refresh_token": refresh_token,
        "expires_at":    expires_at,
        "scope":         scope,
        "updated_at":    datetime.now(timezone.utc).isoformat(),
    }, on_conflict="account_id").execute()

    return {
        "ok":         True,
        "account_id": account_id,
        "scope":      scope,
        "expires_at": expires_at,
        "msg":        "Token guardado. El sync ahora puede leer mensajes de chats.",
    }


# ── Receptor de webhooks Kommo ────────────────────────────────────────────────
# Kommo POST eventos aquí. PÚBLICO (Kommo no soporta auth Bearer custom).
# Captura cualquier evento que se configure en Kommo → Ajustes → Webhooks.

_webhook_stats: dict = {
    "total":             0,
    "leads_evento":      0,
    "mensajes_evento":   0,
    "otros":             0,
    "mensajes_guardados": 0,
    "convs_upserteadas":  0,
    "leads_actualizados": 0,
    "errores_parser":     0,
    "primero_en":        None,
    "ultimo_en":         None,
    "ultimos_payloads":  [],
    "ultimos_errores":   [],
}


from fastapi import Request


def _kommo_form_to_nested(flat: dict) -> dict:
    """Convierte claves dot-notation tipo "message[add][0][text]" en estructura anidada.
    Después colapsa diccionarios con claves numéricas a listas."""
    out: dict = {}
    for k, v in flat.items():
        parts: list[str] = []
        buf = ""
        for c in k:
            if c == '[' or c == ']':
                if buf:
                    parts.append(buf)
                    buf = ""
            else:
                buf += c
        if buf:
            parts.append(buf)
        cur = out
        for j, p in enumerate(parts):
            if j == len(parts) - 1:
                cur[p] = v
            else:
                if p not in cur or not isinstance(cur[p], dict):
                    cur[p] = {}
                cur = cur[p]

    def listify(obj):
        if isinstance(obj, dict):
            keys = list(obj.keys())
            if keys and all(str(k).isdigit() for k in keys):
                return [listify(obj[k]) for k in sorted(keys, key=int)]
            return {k: listify(v) for k, v in obj.items()}
        return obj
    return listify(out)


def _sender_type_from(msg: dict) -> str:
    """Clasifica el mensaje: customer / advisor / system."""
    t = (msg.get("type") or "").lower()
    author = msg.get("author") or {}
    author_type = (author.get("type") or "").lower()
    if t == "incoming" or author_type == "external":
        return "customer"
    if t == "outgoing" or author_type in ("internal", "user", "bot"):
        return "advisor"
    return "system"


def _asegurar_lead_en_db(sb, lead_id: int) -> bool:
    """Si el lead no existe en kommo_leads, lo trae de Kommo y lo upsertea.
    Retorna True si existe (o quedó) en DB."""
    try:
        r = sb.table("kommo_leads").select("lead_id").eq("lead_id", lead_id).limit(1).execute()
        if r.data:
            return True
    except Exception:
        return False
    try:
        import sys
        from pathlib import Path
        _SRC = Path(__file__).resolve().parent.parent.parent / "src"
        if str(_SRC) not in sys.path:
            sys.path.insert(0, str(_SRC))
        import kommo_client as kc
        lead_data = kc.obtener_lead(lead_id)
        if lead_data:
            db.upsert_lead(lead_data)
            return True
    except Exception:
        pass
    return False


def _procesar_webhook(parsed: dict) -> dict:
    """Procesa un payload Kommo ya parseado a estructura anidada.
    Persiste mensajes, conversaciones y cambios de lead en Supabase.
    Retorna contadores."""
    from datetime import datetime as _dt, timezone as _tz
    sb = db._sb()
    if sb is None:
        return {"error": "supabase_no_configurado"}

    msgs_guardados = 0
    convs_up = 0
    leads_up = 0

    # 1) message[add] → tabla messages
    msg_block = (parsed.get("message") or {})
    adds = msg_block.get("add") or []
    if isinstance(adds, dict):
        adds = [adds]
    for m in adds:
        if not isinstance(m, dict):
            continue
        try:
            talk_id = m.get("talk_id")
            entity_id = m.get("entity_id") or m.get("element_id")
            entity_type = m.get("entity_type") or "lead"
            created = int(m.get("created_at") or 0) or None
            text = m.get("text") or ""
            conv_id = f"talk-{talk_id}" if talk_id else None

            # Asegurar conversation existe (FK)
            if conv_id and entity_type == "lead" and entity_id:
                _asegurar_lead_en_db(sb, int(entity_id))
                try:
                    existe = sb.table("conversations").select("conversation_id").eq("conversation_id", conv_id).limit(1).execute()
                    if not existe.data:
                        sb.table("conversations").upsert({
                            "conversation_id":  conv_id,
                            "lead_id":          int(entity_id),
                            "channel":          m.get("origin") or "unknown",
                            "started_at":       _dt.fromtimestamp(created, tz=_tz.utc).isoformat() if created else None,
                            "last_message_at":  _dt.fromtimestamp(created, tz=_tz.utc).isoformat() if created else None,
                            "status":           "in_work",
                            "audit_status":     "pending",
                            "synced_at":        _dt.now(tz=_tz.utc).isoformat(),
                        }, on_conflict="conversation_id").execute()
                        convs_up += 1
                except Exception:
                    pass

            if not conv_id or not m.get("id"):
                continue

            row = {
                "message_id":      str(m["id"]),
                "conversation_id": conv_id,
                "lead_id":         int(entity_id) if entity_id else None,
                "sender_type":     _sender_type_from(m),
                "sender_name":     (m.get("author") or {}).get("name") or "",
                "message_text":    text,
                "sent_at":         _dt.fromtimestamp(created, tz=_tz.utc).isoformat() if created else _dt.now(tz=_tz.utc).isoformat(),
                "topic":           m.get("message_type") or "text",
                "extension":       m.get("origin") or "",
                "event":           m.get("type") or "",
                "payload":         {
                    "author_id":   (m.get("author") or {}).get("id"),
                    "author_type": (m.get("author") or {}).get("type"),
                    "chat_id":     m.get("chat_id"),
                    "talk_id":     m.get("talk_id"),
                    "contact_id":  m.get("contact_id"),
                },
            }
            row = {k: v for k, v in row.items() if v is not None}
            sb.table("messages").upsert(row, on_conflict="message_id").execute()
            msgs_guardados += 1
        except Exception as e:
            _webhook_stats["errores_parser"] += 1
            _webhook_stats["ultimos_errores"] = ([f"msg: {str(e)[:200]}"] + _webhook_stats["ultimos_errores"])[:5]

    # 2) talk[add|update] → tabla conversations
    talk_block = (parsed.get("talk") or {})
    for accion in ("add", "update"):
        talks = talk_block.get(accion) or []
        if isinstance(talks, dict):
            talks = [talks]
        for t in talks:
            if not isinstance(t, dict):
                continue
            try:
                talk_id = t.get("talk_id")
                entity_id = t.get("entity_id")
                entity_type = t.get("entity_type") or "lead"
                if not talk_id or entity_type != "lead" or not entity_id:
                    continue
                _asegurar_lead_en_db(sb, int(entity_id))
                created = int(t.get("created_at") or 0) or None
                updated = int(t.get("updated_at") or 0) or None
                row = {
                    "conversation_id":  f"talk-{talk_id}",
                    "lead_id":          int(entity_id),
                    "channel":          t.get("origin") or "unknown",
                    "started_at":       _dt.fromtimestamp(created, tz=_tz.utc).isoformat() if created else None,
                    "last_message_at":  _dt.fromtimestamp(updated, tz=_tz.utc).isoformat() if updated else None,
                    "status":           "in_work" if (t.get("is_in_work") in ("1", 1, True)) else "closed",
                    "audit_status":     "pending",
                    "synced_at":        _dt.now(tz=_tz.utc).isoformat(),
                }
                sb.table("conversations").upsert(row, on_conflict="conversation_id").execute()
                convs_up += 1
            except Exception as e:
                _webhook_stats["errores_parser"] += 1
                _webhook_stats["ultimos_errores"] = ([f"talk: {str(e)[:200]}"] + _webhook_stats["ultimos_errores"])[:5]

    # 3) leads[status|update|add] → tabla kommo_leads (refrescar estado)
    # Si cambia a won/lost, encolar conversations para audit IA automático
    conv_ids_para_auditar: list[str] = []
    leads_block = (parsed.get("leads") or {})
    for accion in ("status", "update", "add"):
        items = leads_block.get(accion) or []
        if isinstance(items, dict):
            items = [items]
        for ld in items:
            if not isinstance(ld, dict):
                continue
            try:
                lead_id = ld.get("id")
                if not lead_id:
                    continue
                nuevo_status = db._map_status(ld.get("status_id"))
                row = {
                    "lead_id":    int(lead_id),
                    "pipeline_id": int(ld["pipeline_id"]) if ld.get("pipeline_id") else None,
                    "stage_id":    int(ld["status_id"]) if ld.get("status_id") else None,
                    "status":      nuevo_status,
                    "responsible_user_id": int(ld["responsible_user_id"]) if ld.get("responsible_user_id") else None,
                    "synced_at":   _dt.now(tz=_tz.utc).isoformat(),
                }
                row = {k: v for k, v in row.items() if v is not None}
                sb.table("kommo_leads").upsert(row, on_conflict="lead_id").execute()
                leads_up += 1

                # Si el lead se cerró (won/lost), buscar sus conversations y encolar audit
                if nuevo_status in ("won", "lost"):
                    try:
                        convs_lead = sb.table("conversations").select("conversation_id,audit_status").eq("lead_id", int(lead_id)).execute().data or []
                        for cv in convs_lead:
                            if cv.get("audit_status") != "completed":
                                conv_ids_para_auditar.append(cv["conversation_id"])
                    except Exception:
                        pass
            except Exception as e:
                _webhook_stats["errores_parser"] += 1
                _webhook_stats["ultimos_errores"] = ([f"lead: {str(e)[:200]}"] + _webhook_stats["ultimos_errores"])[:5]

    return {
        "messages": msgs_guardados,
        "conversations": convs_up,
        "leads": leads_up,
        "audit_queue": conv_ids_para_auditar,
    }


def _auditar_en_background(conv_ids: list[str]) -> None:
    """Wrapper para correr audit IA dentro de BackgroundTasks."""
    for cid in conv_ids:
        try:
            audit_ia.auditar_conversation(cid)
        except Exception as e:
            log.warning(f"audit auto {cid}: {e}")


@router.get("/debug/schema/{table}")
def debug_schema(table: str, _: CurrentUser = Depends(require_role("admin"))) -> dict:
    """Inspecciona columnas de una tabla via select limit 1."""
    sb = db._sb()
    if sb is None:
        raise HTTPException(503, "Supabase no configurado")
    try:
        r = sb.table(table).select("*").limit(1).execute()
        cols = list(r.data[0].keys()) if r.data else []
        return {"table": table, "columns": cols, "n_rows": len(r.data)}
    except Exception as e:
        return {"table": table, "error": str(e)[:300]}


@router.post("/kommo-webhook")
async def kommo_webhook(request: Request, background_tasks: BackgroundTasks) -> dict:
    """Receptor de eventos de Kommo. PÚBLICO. Parsea y persiste en Supabase.
    Si detecta cierre de lead (won/lost), dispara audit IA en background."""
    from datetime import datetime as _dt, timezone as _tz
    now_iso = _dt.now(tz=_tz.utc).isoformat()

    body_dict: dict = {}
    try:
        ct = (request.headers.get("content-type") or "").lower()
        if "json" in ct:
            body_dict = await request.json()
        else:
            form = await request.form()
            body_dict = dict(form)
    except Exception as e:
        body_dict = {"_parse_error": str(e)[:200]}

    _webhook_stats["total"] += 1
    if _webhook_stats["primero_en"] is None:
        _webhook_stats["primero_en"] = now_iso
    _webhook_stats["ultimo_en"] = now_iso

    keys = " ".join(body_dict.keys()) if isinstance(body_dict, dict) else ""
    es_msg = "message" in keys or "talk" in keys
    es_lead = "leads" in keys
    if es_msg:
        _webhook_stats["mensajes_evento"] += 1
    elif es_lead:
        _webhook_stats["leads_evento"] += 1
    else:
        _webhook_stats["otros"] += 1

    # Persistir en DB y disparar audit IA en background si aplica
    try:
        parsed = _kommo_form_to_nested(body_dict) if isinstance(body_dict, dict) else {}
        result = _procesar_webhook(parsed)
        _webhook_stats["mensajes_guardados"] += result.get("messages", 0)
        _webhook_stats["convs_upserteadas"] += result.get("conversations", 0)
        _webhook_stats["leads_actualizados"] += result.get("leads", 0)
        audit_queue = result.get("audit_queue") or []
        if audit_queue:
            background_tasks.add_task(_auditar_en_background, audit_queue)
            _webhook_stats["auto_audits_disparados"] = _webhook_stats.get("auto_audits_disparados", 0) + len(audit_queue)
    except Exception as e:
        _webhook_stats["errores_parser"] += 1
        _webhook_stats["ultimos_errores"] = ([f"top: {str(e)[:200]}"] + _webhook_stats["ultimos_errores"])[:5]

    preview = {k: (str(v)[:200] if not isinstance(v, (dict, list)) else "<obj>")
               for k, v in body_dict.items()}
    _webhook_stats["ultimos_payloads"].insert(0, {
        "ts": now_iso,
        "tipo": "message" if es_msg else "lead" if es_lead else "otro",
        "keys": list(body_dict.keys())[:20],
        "preview": preview,
    })
    _webhook_stats["ultimos_payloads"] = _webhook_stats["ultimos_payloads"][:10]

    return {"ok": True}


@router.get("/kommo-webhook/stats")
def kommo_webhook_stats(_: CurrentUser = Depends(require_role("admin"))) -> dict:
    """Estadísticas + últimos 10 payloads del receptor de webhooks Kommo."""
    return _webhook_stats


@router.get("/oauth/status")
def oauth_status(_: CurrentUser = Depends(require_role("admin"))) -> dict:
    """Estado actual del token OAuth (si hay) sin exponer el valor."""
    sb = db._sb()
    if sb is None:
        return {"ok": False, "error": "Supabase no configurado"}
    r = sb.table("kommo_oauth_tokens").select("account_id,scope,expires_at,updated_at").execute()
    if not r.data:
        return {"ok": False, "error": "Sin token OAuth — usar /api/revenue/oauth/start"}
    row = r.data[0]
    # Calcular si está vigente
    try:
        exp = datetime.fromisoformat((row["expires_at"] or "").replace("Z", "+00:00"))
        vigente = datetime.now(timezone.utc) < exp
        minutos_restantes = int((exp - datetime.now(timezone.utc)).total_seconds() / 60)
    except Exception:
        vigente = False
        minutos_restantes = 0
    return {
        "ok":               True,
        "account_id":       row["account_id"],
        "scope":            row.get("scope"),
        "expires_at":       row["expires_at"],
        "minutos_vigente":  minutos_restantes,
        "updated_at":       row.get("updated_at"),
    }


# ── Health ────────────────────────────────────────────────────────────────────
@router.get("/health")
def health(_: CurrentUser = Depends(require_role("admin", "operador"))) -> dict:
    """
    Valida la conexión con Kommo y devuelve info de la cuenta.
    Útil para confirmar que las env vars KOMMO_SUBDOMAIN/KOMMO_API_TOKEN
    están bien configuradas.
    """
    return kommo_svc.verificar_conexion()


@router.get("/stats")
def stats(_: CurrentUser = Depends(require_role("admin", "operador"))) -> dict:
    """KPIs del módulo: cuántos leads/conv/mensajes/audits."""
    return db.stats_revenue()


# ── Dashboard endpoints ───────────────────────────────────────────────────────
@router.get("/conversations")
def list_conversations(
    advisor_id: str | None = Query(None),
    status: str | None = Query(None, description="in_work|closed"),
    channel: str | None = Query(None),
    days_back: int = Query(30, ge=1, le=365),
    limit: int = Query(100, ge=1, le=500),
    _: CurrentUser = Depends(require_role("admin", "operador")),
) -> dict:
    """Lista de conversations con filtros, enriquecida con datos de lead y advisor."""
    sb = db._sb()
    if sb is None:
        raise HTTPException(503, "Supabase no configurado")
    desde = (datetime.now(tz=timezone.utc) - timedelta(days=days_back)).isoformat()
    q = sb.table("conversations").select(
        "conversation_id,lead_id,advisor_id,channel,started_at,last_message_at,status,message_count,audit_status"
    ).gte("last_message_at", desde).order("last_message_at", desc=True).limit(limit)
    if advisor_id:
        q = q.eq("advisor_id", advisor_id)
    if status:
        q = q.eq("status", status)
    if channel:
        q = q.eq("channel", channel)
    convs = q.execute().data or []

    advisor_ids = list({c["advisor_id"] for c in convs if c.get("advisor_id")})
    lead_ids = list({c["lead_id"] for c in convs if c.get("lead_id")})
    advisors_map: dict = {}
    leads_map: dict = {}
    if advisor_ids:
        for a in (sb.table("advisors").select("advisor_id,name,email").in_("advisor_id", advisor_ids).execute().data or []):
            advisors_map[a["advisor_id"]] = a
    if lead_ids:
        for l in (sb.table("kommo_leads").select("lead_id,status,lead_value,customer_name,customer_phone").in_("lead_id", lead_ids).execute().data or []):
            leads_map[l["lead_id"]] = l

    enriched = []
    for c in convs:
        adv = advisors_map.get(c.get("advisor_id"), {})
        lead = leads_map.get(c.get("lead_id"), {})
        enriched.append({
            **c,
            "advisor_name": adv.get("name"),
            "lead_status":  lead.get("status"),
            "lead_value":   lead.get("lead_value"),
            "customer_name": lead.get("customer_name"),
            "customer_phone": lead.get("customer_phone"),
        })
    return {"ok": True, "total": len(enriched), "conversations": enriched}


@router.get("/advisors/ranking")
def advisors_ranking(
    days_back: int = Query(30, ge=1, le=365),
    _: CurrentUser = Depends(require_role("admin", "operador")),
) -> dict:
    """Ranking de asesores: conversaciones, won/lost, tasa, último activo."""
    sb = db._sb()
    if sb is None:
        raise HTTPException(503, "Supabase no configurado")
    desde = (datetime.now(tz=timezone.utc) - timedelta(days=days_back)).isoformat()

    advisors = sb.table("advisors").select("advisor_id,name,email,active").execute().data or []
    convs = sb.table("conversations").select("conversation_id,advisor_id,lead_id,last_message_at,channel").gte("last_message_at", desde).execute().data or []
    lead_ids = list({c["lead_id"] for c in convs if c.get("lead_id")})
    leads_map: dict = {}
    if lead_ids:
        for l in (sb.table("kommo_leads").select("lead_id,status").in_("lead_id", lead_ids).execute().data or []):
            leads_map[l["lead_id"]] = l.get("status")

    by_advisor: dict = {}
    for c in convs:
        adv_id = c.get("advisor_id")
        if not adv_id:
            continue
        r = by_advisor.setdefault(adv_id, {
            "conversations": 0, "won": 0, "lost": 0, "in_progress": 0,
            "last_activity": None, "channels": {},
        })
        r["conversations"] += 1
        ch = c.get("channel") or "unknown"
        r["channels"][ch] = r["channels"].get(ch, 0) + 1
        st = leads_map.get(c.get("lead_id"))
        if st == "won":   r["won"] += 1
        elif st == "lost": r["lost"] += 1
        else:              r["in_progress"] += 1
        lm = c.get("last_message_at")
        if lm and (r["last_activity"] is None or lm > r["last_activity"]):
            r["last_activity"] = lm

    rows = []
    for adv in advisors:
        stats = by_advisor.get(adv["advisor_id"], {
            "conversations": 0, "won": 0, "lost": 0, "in_progress": 0,
            "last_activity": None, "channels": {},
        })
        cerradas = stats["won"] + stats["lost"]
        conv_rate = round(100 * stats["won"] / cerradas, 1) if cerradas else None
        rows.append({
            "advisor_id":     adv["advisor_id"],
            "name":           adv["name"],
            "email":          adv.get("email"),
            "active":         adv.get("active"),
            "conversations":  stats["conversations"],
            "won":            stats["won"],
            "lost":           stats["lost"],
            "in_progress":    stats["in_progress"],
            "conversion_rate": conv_rate,
            "last_activity":  stats["last_activity"],
            "channels":       stats["channels"],
        })
    rows.sort(key=lambda r: (r["conversations"], r["won"]), reverse=True)
    return {"ok": True, "total": len(rows), "rows": rows, "days_back": days_back}


# ── Backfill background de talks ──────────────────────────────────────────────
@router.post("/sync/talks/backfill")
def talks_backfill_start(
    background_tasks: BackgroundTasks,
    _: CurrentUser = Depends(require_role("admin")),
) -> dict:
    """Dispara un backfill completo de TODOS los talks históricos en background.
    Pagina sin timeout HTTP. Estado consultable en /sync/talks/backfill/status."""
    if kommo_svc.get_backfill_state().get("running"):
        return {"ok": False, "error": "ya_corriendo", "state": kommo_svc.get_backfill_state()}
    background_tasks.add_task(kommo_svc.sync_talks_backfill_completo)
    return {"ok": True, "started": True}


@router.get("/sync/talks/backfill/status")
def talks_backfill_status(
    _: CurrentUser = Depends(require_role("admin", "operador")),
) -> dict:
    return kommo_svc.get_backfill_state()


# ── Auditoría IA ──────────────────────────────────────────────────────────────
@router.post("/audit/run/{conversation_id}")
def audit_run_one(
    conversation_id: str,
    _: CurrentUser = Depends(require_role("admin")),
) -> dict:
    """Audita 1 conversation específica con Claude Haiku 4.5."""
    return audit_ia.auditar_conversation(conversation_id)


@router.post("/audit/run-pending")
def audit_run_pending(
    limit: int = Query(5, ge=1, le=30),
    solo_cerradas: bool = Query(True),
    _: CurrentUser = Depends(require_role("admin")),
) -> dict:
    """Audita hasta N conversations pendientes (cerradas por defecto)."""
    return audit_ia.auditar_pendientes(limit=limit, solo_cerradas=solo_cerradas)


@router.get("/conversations/{conversation_id}/detail")
def conversation_detail(
    conversation_id: str,
    _: CurrentUser = Depends(require_role("admin", "operador")),
) -> dict:
    """Detalle completo: conversation + lead + mensajes (ordenados) + última auditoría."""
    sb = db._sb()
    if sb is None:
        raise HTTPException(503, "Supabase no configurado")
    convs = sb.table("conversations").select("*").eq("conversation_id", conversation_id).limit(1).execute().data or []
    if not convs:
        raise HTTPException(404, "Conversación no encontrada")
    conv = convs[0]
    lead = {}
    if conv.get("lead_id"):
        ld = sb.table("kommo_leads").select("*").eq("lead_id", conv["lead_id"]).limit(1).execute().data
        if ld:
            lead = ld[0]
    advisor = None
    if conv.get("advisor_id"):
        adv = sb.table("advisors").select("name,email").eq("advisor_id", conv["advisor_id"]).limit(1).execute().data
        if adv:
            advisor = adv[0]
    msgs = (sb.table("messages")
              .select("message_id,sender_type,sender_name,message_text,sent_at")
              .eq("conversation_id", conversation_id)
              .order("sent_at")
              .limit(500)
              .execute().data) or []
    audits = (sb.table("chat_audits").select("*")
                .eq("conversation_id", conversation_id)
                .order("audit_date", desc=True)
                .limit(1).execute().data) or []
    return {
        "ok": True,
        "conversation": conv,
        "lead": lead,
        "advisor": advisor,
        "messages": msgs,
        "audit": audits[0] if audits else None,
    }


@router.post("/rankings/calcular")
def rankings_calcular(
    days_back: int = Query(30, ge=1, le=365),
    _: CurrentUser = Depends(require_role("admin")),
) -> dict:
    """Calcula advisor_rankings para el periodo y los persiste.
    Pensado para correr nocturno (cron). Idempotente: upserts por advisor_id + period."""
    sb = db._sb()
    if sb is None:
        raise HTTPException(503, "Supabase no configurado")
    desde_dt = datetime.now(tz=timezone.utc) - timedelta(days=days_back)
    desde = desde_dt.isoformat()
    period_key = f"{desde_dt.date().isoformat()}_to_{datetime.now(tz=timezone.utc).date().isoformat()}"

    advisors = sb.table("advisors").select("advisor_id,name,active").execute().data or []
    convs = sb.table("conversations").select("conversation_id,advisor_id,lead_id,last_message_at,started_at,channel").gte("last_message_at", desde).execute().data or []
    lead_ids = list({c["lead_id"] for c in convs if c.get("lead_id")})
    leads_map: dict = {}
    if lead_ids:
        for l in (sb.table("kommo_leads").select("lead_id,status,lead_value").in_("lead_id", lead_ids).execute().data or []):
            leads_map[l["lead_id"]] = l

    # Auditorías promedios por asesor
    audits_map: dict = {}
    audits = sb.table("chat_audits").select("advisor_id,overall_score,response_time_score,attention_score,follow_up_score,closing_score,economic_impact_estimate").gte("audit_date", desde).execute().data or []
    for a in audits:
        adv = a.get("advisor_id")
        if not adv:
            continue
        r = audits_map.setdefault(adv, {"count": 0, "overall": [], "response": [], "attention": [], "follow_up": [], "closing": [], "impact_perdido": 0})
        r["count"] += 1
        for k_src, k_dst in [("overall_score","overall"),("response_time_score","response"),("attention_score","attention"),("follow_up_score","follow_up"),("closing_score","closing")]:
            v = a.get(k_src)
            if v is not None:
                r[k_dst].append(float(v))
        r["impact_perdido"] += float(a.get("economic_impact_estimate") or 0)

    rows_persistir = []
    ahora_iso = datetime.now(tz=timezone.utc).isoformat()
    for adv in advisors:
        adv_id = adv["advisor_id"]
        convs_adv = [c for c in convs if c.get("advisor_id") == adv_id]
        won = sum(1 for c in convs_adv if leads_map.get(c.get("lead_id"), {}).get("status") == "won")
        lost = sum(1 for c in convs_adv if leads_map.get(c.get("lead_id"), {}).get("status") == "lost")
        revenue = sum(float(leads_map.get(c.get("lead_id"), {}).get("lead_value") or 0) for c in convs_adv if leads_map.get(c.get("lead_id"), {}).get("status") == "won")
        cerradas = won + lost
        conv_rate = round(100 * won / cerradas, 2) if cerradas else None
        a = audits_map.get(adv_id, {})
        def avg(lst): return round(sum(lst) / len(lst), 2) if lst else None
        rows_persistir.append({
            "advisor_id":       adv_id,
            "period_key":       period_key,
            "period_days":      days_back,
            "calculated_at":    ahora_iso,
            "conversations":    len(convs_adv),
            "won":              won,
            "lost":             lost,
            "conversion_rate":  conv_rate,
            "revenue_generated": revenue,
            "audits_count":     a.get("count", 0),
            "avg_overall_score": avg(a.get("overall", [])),
            "avg_response_score": avg(a.get("response", [])),
            "avg_attention_score": avg(a.get("attention", [])),
            "avg_follow_up_score": avg(a.get("follow_up", [])),
            "avg_closing_score": avg(a.get("closing", [])),
            "impact_perdido":   a.get("impact_perdido", 0),
        })

    persistidos = 0
    errores = []
    for row in rows_persistir:
        clean = {k: v for k, v in row.items() if v is not None}
        try:
            sb.table("advisor_rankings").upsert(clean, on_conflict="advisor_id,period_key").execute()
            persistidos += 1
        except Exception as e:
            if len(errores) < 3:
                errores.append(str(e)[:200])
    return {"ok": True, "persistidos": persistidos, "total_advisors": len(rows_persistir), "period_key": period_key, "errores": errores}


@router.get("/coaching/{advisor_id}")
def coaching_asesora(
    advisor_id: str,
    days_back: int = Query(60, ge=7, le=365),
    _: CurrentUser = Depends(require_role("admin")),
) -> dict:
    """Genera reporte de coaching IA para una asesora basado en sus auditorías."""
    return audit_ia.coaching_para_asesora(advisor_id, days_back=days_back)


@router.get("/rankings/historico")
def rankings_historico(
    advisor_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    _: CurrentUser = Depends(require_role("admin", "operador")),
) -> dict:
    """Histórico de rankings persistidos."""
    sb = db._sb()
    if sb is None:
        raise HTTPException(503, "Supabase no configurado")
    q = sb.table("advisor_rankings").select("*").order("calculated_at", desc=True).limit(limit)
    if advisor_id:
        q = q.eq("advisor_id", advisor_id)
    return {"ok": True, "rows": q.execute().data or []}


@router.get("/audit/list")
def audit_list(
    limit: int = Query(50, ge=1, le=200),
    classification: str | None = Query(None),
    _: CurrentUser = Depends(require_role("admin", "operador")),
) -> dict:
    """Lista de auditorías recientes."""
    sb = db._sb()
    if sb is None:
        raise HTTPException(503, "Supabase no configurado")
    q = sb.table("chat_audits").select("*").order("analyzed_at", desc=True).limit(limit)
    if classification:
        q = q.eq("result_classification", classification)
    rows = q.execute().data or []
    return {"ok": True, "total": len(rows), "audits": rows}


@router.get("/messages/recent")
def messages_recent(
    limit: int = Query(50, ge=1, le=300),
    _: CurrentUser = Depends(require_role("admin", "operador")),
) -> dict:
    """Feed cronológico de los últimos mensajes."""
    sb = db._sb()
    if sb is None:
        raise HTTPException(503, "Supabase no configurado")
    try:
        msgs = sb.table("messages").select(
            "message_id,conversation_id,lead_id,sender_type,sender_name,message_text,sent_at"
        ).order("sent_at", desc=True).limit(limit).execute().data or []
    except Exception as e:
        raise HTTPException(503, f"select messages: {str(e)[:300]}")
    lead_ids = list({m["lead_id"] for m in msgs if m.get("lead_id")})
    leads_map: dict = {}
    if lead_ids:
        for l in (sb.table("kommo_leads").select("lead_id,customer_name,customer_phone,status").in_("lead_id", lead_ids).execute().data or []):
            leads_map[l["lead_id"]] = l
    enriched = []
    for m in msgs:
        lead = leads_map.get(m.get("lead_id"), {})
        enriched.append({
            **m,
            "customer_name":  lead.get("customer_name"),
            "customer_phone": lead.get("customer_phone"),
            "lead_status":    lead.get("status"),
        })
    return {"ok": True, "total": len(enriched), "messages": enriched}


# ── Sync ──────────────────────────────────────────────────────────────────────
@router.post("/sync/advisors")
def sync_advisors_endpoint(
    _: CurrentUser = Depends(require_role("admin")),
) -> dict:
    """Trae asesoras de Kommo y las puebla en advisors. Idempotente."""
    return kommo_svc.sync_advisors()


@router.post("/sync/leads")
def sync_leads_endpoint(
    full: bool = Query(False, description="True = full sync (lento). False = solo cambios"),
    limit: int = Query(1000, ge=1, le=5000),
    _: CurrentUser = Depends(require_role("admin")),
) -> dict:
    """
    Sync de leads desde Kommo. Por defecto incremental (solo cambios
    desde el último sync). Con full=True trae todos.
    """
    return kommo_svc.sync_leads(full=full, limit_total=limit)


@router.post("/sync/talks")
def sync_talks_endpoint(
    full: bool = Query(False),
    limit: int = Query(1000, ge=1, le=5000),
    _: CurrentUser = Depends(require_role("admin")),
) -> dict:
    """
    Sync de talks (conversaciones) desde Kommo. Trae metadata: origin,
    rate, is_read, timestamps, lead asociado. NO trae texto de mensajes.
    """
    return kommo_svc.sync_talks(full=full, limit_total=limit)


@router.post("/sync/lead/{lead_id}/messages")
def sync_messages_endpoint(
    lead_id: int,
    _: CurrentUser = Depends(require_role("admin")),
) -> dict:
    """Trae mensajes de un lead específico (por si quieres re-procesar uno)."""
    return kommo_svc.sync_messages_de_lead(lead_id)


@router.post("/sync/completo")
def sync_completo_endpoint(
    full: bool = Query(False),
    lead_limit: int = Query(200, ge=1, le=5000),
    msg_limit: int = Query(50, ge=1, le=500),
    _: CurrentUser = Depends(require_role("admin")),
) -> dict:
    """
    Pasada completa: asesoras + leads + mensajes.
    El cron de revenue_scheduler llama esto cada 15 min.
    """
    return kommo_svc.sync_completo(full=full, lead_limit=lead_limit, msg_limit_por_lead=msg_limit)


# ── Debug / introspección de Kommo (admin only) ──────────────────────────────
@router.get("/debug/pipelines")
def debug_pipelines(_: CurrentUser = Depends(require_role("admin"))) -> dict:
    """Lista pipelines + stages de Kommo. Útil para mapear el catálogo."""
    import sys
    from pathlib import Path
    _SRC = Path(__file__).resolve().parent.parent.parent / "src"
    if str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))
    import kommo_client as kc
    try:
        return {"pipelines": kc.listar_pipelines()}
    except Exception as e:
        raise HTTPException(503, f"Error: {str(e)[:200]}")


@router.get("/debug/lead/{lead_id}")
def debug_lead(lead_id: int, _: CurrentUser = Depends(require_role("admin"))) -> dict:
    """Detalle crudo de un lead de Kommo. Para inspeccionar campos."""
    import sys
    from pathlib import Path
    _SRC = Path(__file__).resolve().parent.parent.parent / "src"
    if str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))
    import kommo_client as kc
    try:
        return {"lead": kc.obtener_lead(lead_id)}
    except Exception as e:
        raise HTTPException(503, f"Error: {str(e)[:200]}")


@router.get("/debug/lead/{lead_id}/notes")
def debug_lead_notes(
    lead_id: int,
    _: CurrentUser = Depends(require_role("admin")),
) -> dict:
    """
    Todas las notes de un lead, SIN filtro de note_type, para descubrir
    qué tipos usa esta cuenta de Kommo para los mensajes de WhatsApp.
    """
    import sys
    from pathlib import Path
    _SRC = Path(__file__).resolve().parent.parent.parent / "src"
    if str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))
    import kommo_client as kc
    try:
        notes = list(kc.listar_notes_de_lead(lead_id))
        # Cuenta por note_type para ver la distribución
        from collections import Counter
        types = Counter(str(n.get("note_type")) for n in notes)
        return {
            "lead_id":          lead_id,
            "total_notes":      len(notes),
            "tipos_distintos":  dict(types),
            "muestras":         notes[:5],   # primeros 5 con su payload completo
        }
    except Exception as e:
        raise HTTPException(503, f"Error: {str(e)[:200]}")


@router.get("/debug/explorar-chats")
def debug_explorar_chats(_: CurrentUser = Depends(require_role("admin"))) -> dict:
    """
    Explora varios endpoints de Kommo para encontrar dónde están los
    mensajes de WhatsApp en esta cuenta.
    """
    import os, requests, urllib.parse, sys
    from pathlib import Path
    _SRC = Path(__file__).resolve().parent.parent.parent / "src"
    if str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))
    import kommo_client as kc

    subdomain = os.environ.get("KOMMO_SUBDOMAIN", "")
    if not subdomain:
        return {"error": "KOMMO_SUBDOMAIN no configurado"}

    # Usar el helper _token() que prioriza el OAuth token sobre el long-lived
    try:
        token = kc._token()
    except RuntimeError as e:
        return {"error": str(e)}

    base = f"https://{subdomain}.kommo.com/api/v4"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    # Sacar primer lead_id que tengamos
    from backend.services import revenue_db as db
    sb = db._sb()
    lead_id = None
    if sb:
        r = sb.table("kommo_leads").select("lead_id").order("created_at", desc=True).limit(1).execute()
        if r.data:
            lead_id = r.data[0]["lead_id"]

    paths = [
        "_TALK_MESSAGES_",          # /talks/{id}/messages
        "_TALK_HISTORY_",           # /talks/{id}/history
        "_TALK_WITH_NOTES_",        # /talks/{id}?with=note_messages
        "_CHAT_DETAIL_",            # /chats/{chat_uuid}
        "_CHAT_HISTORY_",           # /chats/{chat_uuid}/messages
        # Customer chats embed
        "contacts?limit=1&with=chats,catalog_elements",
    ]

    # Primer talk_id y chat_id que aparezca
    primer_talk_id = None
    primer_chat_uuid = None
    try:
        r0 = requests.get(f"{base}/talks?limit=1", headers=headers, timeout=15)
        if r0.ok:
            talks = ((r0.json().get("_embedded") or {}).get("talks") or [])
            if talks:
                primer_talk_id = talks[0].get("talk_id")
                primer_chat_uuid = talks[0].get("chat_id")
    except Exception:
        pass

    resolved_paths = []
    for p in paths:
        if not p:
            continue
        if p == "_TALK_MESSAGES_" and primer_talk_id:
            resolved_paths.append(f"talks/{primer_talk_id}/messages")
        elif p == "_TALK_HISTORY_" and primer_talk_id:
            resolved_paths.append(f"talks/{primer_talk_id}/history")
        elif p == "_TALK_WITH_NOTES_" and primer_talk_id:
            resolved_paths.append(f"talks/{primer_talk_id}?with=note_messages")
        elif p == "_CHAT_DETAIL_" and primer_chat_uuid:
            resolved_paths.append(f"chats/{primer_chat_uuid}")
        elif p == "_CHAT_HISTORY_" and primer_chat_uuid:
            resolved_paths.append(f"chats/{primer_chat_uuid}/messages")
        elif p.startswith("_"):
            continue
        else:
            resolved_paths.append(p)

    resultados = []
    for p in resolved_paths:
        url = f"{base}/{p}"
        try:
            r = requests.get(url, headers=headers, timeout=15)
            body = r.text[:600] if r.status_code == 200 else r.text[:300]
            top_keys = []
            try:
                j = r.json()
                if isinstance(j, dict):
                    top_keys = list(j.keys())
                    if "_embedded" in j:
                        emb = j["_embedded"]
                        emb_keys = list(emb.keys()) if isinstance(emb, dict) else []
                        top_keys = top_keys + [f"_embedded.{k}" for k in emb_keys]
            except Exception:
                pass
            resultados.append({"path": p, "status": r.status_code, "top": top_keys, "body": body})
        except Exception as e:
            resultados.append({"path": p, "error": str(e)[:120]})

    return {
        "lead_id_usado":   lead_id,
        "primer_talk_id":  primer_talk_id,
        "primer_chat_uuid": primer_chat_uuid,
        "resultados":      resultados,
    }
def debug_lead_con_chat(_: CurrentUser = Depends(require_role("admin"))) -> dict:
    """
    Busca el primer lead con MUCHAS notes (probablemente chat largo de
    WhatsApp) entre los recién sincronizados. Devuelve su id y conteos
    por note_type para que sepamos qué filtrar.
    """
    from backend.services import revenue_db as db
    sb = db._sb()
    if sb is None:
        raise HTTPException(503, "Supabase no configurado")
    r = sb.table("kommo_leads").select("lead_id").order("synced_at", desc=True).limit(50).execute()
    lead_ids = [row["lead_id"] for row in (r.data or [])]

    import sys
    from pathlib import Path
    _SRC = Path(__file__).resolve().parent.parent.parent / "src"
    if str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))
    import kommo_client as kc
    from collections import Counter

    mejor = None
    for lid in lead_ids:
        notes = list(kc.listar_notes_de_lead(lid))
        if len(notes) > (mejor["total"] if mejor else 0):
            mejor = {
                "lead_id":  lid,
                "total":    len(notes),
                "tipos":    dict(Counter(str(n.get("note_type")) for n in notes)),
                "muestras": notes[:3],
            }
            if len(notes) >= 10:  # encontramos uno bueno, parar
                break
    return mejor or {"error": "ningún lead reciente tiene notes"}
