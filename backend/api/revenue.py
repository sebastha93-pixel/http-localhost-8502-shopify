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

# Columnas que PostgREST cache rechaza con PGRST204. Las descubrimos en runtime
# y las excluimos del row en mensajes subsecuentes hasta que se reinicie el proceso
# (o se corra NOTIFY pgrst, 'reload schema' en Supabase).
_columnas_problematicas_messages: set = set()


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

    # 1) message[add] de Kommo → en modo híbrido Meta:
    #    - WhatsApp lo manejamos via webhook Meta directo (Meta nos da texto completo).
    #    - Instagram, Messenger, TikTok y otros canales NO los recibimos por Meta,
    #      así que SÍ los procesamos desde el webhook de Kommo para no perderlos.
    HIBRIDO_META_ACTIVO = os.environ.get("HIBRIDO_META_ACTIVO", "true").lower() in ("true", "1", "yes")

    # Orígenes/canales que vienen por Meta directo → los saltamos en webhook Kommo
    # para evitar duplicados. El resto SÍ se procesa.
    WHATSAPP_ORIGINS = {"whatsapp", "whatsapp_business", "wa_business", "waba", "wa"}

    msg_block = (parsed.get("message") or {})
    adds = msg_block.get("add") or []
    if isinstance(adds, dict):
        adds = [adds]
    if HIBRIDO_META_ACTIVO:
        # Filtrar: dejar pasar IG, Messenger, TikTok y demás. Solo saltar WhatsApp.
        adds = [
            m for m in adds
            if isinstance(m, dict)
            and (m.get("origin") or "").lower() not in WHATSAPP_ORIGINS
        ]
    for m in adds:
        if not isinstance(m, dict):
            continue
        try:
            talk_id = m.get("talk_id")
            entity_id = m.get("entity_id") or m.get("element_id")
            entity_type = m.get("entity_type") or "lead"
            created = int(m.get("created_at") or 0) or None
            text = (m.get("text") or "").strip()
            # Placeholder visible para mensajes no-texto (audio, imagen, sticker, ubicación)
            if not text:
                mt = (m.get("message_type") or "").lower()
                placeholders = {
                    "audio":    "🎤 [audio]",
                    "voice":    "🎤 [audio]",
                    "picture":  "🖼️ [imagen]",
                    "image":    "🖼️ [imagen]",
                    "video":    "🎬 [video]",
                    "file":     "📎 [archivo]",
                    "document": "📄 [documento]",
                    "sticker":  "🟣 [sticker]",
                    "location": "📍 [ubicación]",
                    "contact":  "👤 [contacto]",
                }
                text = placeholders.get(mt, f"[{mt or 'sin texto'}]")
            conv_id = f"talk-{talk_id}" if talk_id else None

            # Asegurar conversation existe (FK)
            if conv_id and entity_type == "lead" and entity_id:
                _asegurar_lead_en_db(sb, int(entity_id))
                # Enriquecer customer_name del lead si está vacío + obtener advisor_id
                advisor_id_lead = None
                try:
                    r = sb.table("kommo_leads").select("customer_name,advisor_id").eq("lead_id", int(entity_id)).limit(1).execute()
                    if r.data:
                        advisor_id_lead = r.data[0].get("advisor_id")
                        cur = (r.data[0].get("customer_name") or "")
                        author = m.get("author") or {}
                        if author.get("type") == "external" and author.get("name") and not cur.strip():
                            sb.table("kommo_leads").update({"customer_name": author["name"]}).eq("lead_id", int(entity_id)).execute()
                except Exception:
                    pass
                try:
                    existe = sb.table("conversations").select("conversation_id,advisor_id").eq("conversation_id", conv_id).limit(1).execute()
                    if not existe.data:
                        sb.table("conversations").upsert({
                            "conversation_id":  conv_id,
                            "lead_id":          int(entity_id),
                            "advisor_id":       advisor_id_lead,
                            "channel":          m.get("origin") or "unknown",
                            "started_at":       _dt.fromtimestamp(created, tz=_tz.utc).isoformat() if created else None,
                            "last_message_at":  _dt.fromtimestamp(created, tz=_tz.utc).isoformat() if created else None,
                            "status":           "in_work",
                            "audit_status":     "pending",
                            "synced_at":        _dt.now(tz=_tz.utc).isoformat(),
                        }, on_conflict="conversation_id").execute()
                        convs_up += 1
                    elif advisor_id_lead and not existe.data[0].get("advisor_id"):
                        # Backfill: si la conv ya existe sin advisor_id, lo populamos
                        sb.table("conversations").update({"advisor_id": advisor_id_lead}).eq("conversation_id", conv_id).execute()
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
                # extension y event van en payload jsonb para evitar
                # romper el upsert cuando el cache de PostgREST está stale.
                "payload":         {
                    "extension":   m.get("origin") or "",
                    "event":       m.get("type") or "",
                    "author_id":   (m.get("author") or {}).get("id"),
                    "author_type": (m.get("author") or {}).get("type"),
                    "chat_id":     m.get("chat_id"),
                    "talk_id":     m.get("talk_id"),
                    "contact_id":  m.get("contact_id"),
                },
            }
            # Quitar columnas que ya sabemos que el cache de PostgREST rechaza
            for _col in _columnas_problematicas_messages:
                row.pop(_col, None)
            row = {k: v for k, v in row.items() if v is not None}

            # Intentar upsert con retry adaptativo: si falla con PGRST204,
            # detectamos qué columna y la agregamos al set global para futuros msgs.
            def _intentar_upsert(r: dict, intentos_max: int = 5) -> bool:
                import re as _re
                for _ in range(intentos_max):
                    try:
                        sb.table("messages").upsert(r, on_conflict="message_id").execute()
                        return True
                    except Exception as ex:
                        err = str(ex)
                        if "PGRST204" in err or "schema cache" in err:
                            m_col = _re.search(r"'(\w+)' column", err)
                            if m_col:
                                col_bad = m_col.group(1)
                                _columnas_problematicas_messages.add(col_bad)
                                r.pop(col_bad, None)
                                continue
                        # Cualquier otro error: salir y reportar
                        _webhook_stats["errores_parser"] += 1
                        _webhook_stats["ultimos_errores"] = ([f"msg: {err[:200]}"] + _webhook_stats["ultimos_errores"])[:5]
                        return False
                return False

            if _intentar_upsert(row):
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
                advisor_id_lead = None
                try:
                    rr = sb.table("kommo_leads").select("advisor_id").eq("lead_id", int(entity_id)).limit(1).execute()
                    if rr.data:
                        advisor_id_lead = rr.data[0].get("advisor_id")
                except Exception:
                    pass
                created = int(t.get("created_at") or 0) or None
                updated = int(t.get("updated_at") or 0) or None
                row = {
                    "conversation_id":  f"talk-{talk_id}",
                    "lead_id":          int(entity_id),
                    "advisor_id":       advisor_id_lead,
                    "channel":          t.get("origin") or "unknown",
                    "started_at":       _dt.fromtimestamp(created, tz=_tz.utc).isoformat() if created else None,
                    "last_message_at":  _dt.fromtimestamp(updated, tz=_tz.utc).isoformat() if updated else None,
                    "status":           "in_work" if (t.get("is_in_work") in ("1", 1, True)) else "closed",
                    "audit_status":     "pending",
                    "synced_at":        _dt.now(tz=_tz.utc).isoformat(),
                }
                row = {k: v for k, v in row.items() if v is not None}
                sb.table("conversations").upsert(row, on_conflict="conversation_id").execute()
                convs_up += 1
            except Exception as e:
                _webhook_stats["errores_parser"] += 1
                _webhook_stats["ultimos_errores"] = ([f"talk: {str(e)[:200]}"] + _webhook_stats["ultimos_errores"])[:5]

    # 2.5) note[add] → mensajes SALIENTES de asesoras (vía notas amochat_message)
    # Kommo no expone webhook "mensaje saliente" directo. Las respuestas de
    # asesoras vía Kommo se registran como notas con note_type=25/26.
    NOTE_TYPES_MSG = {"25", "26", "amochat_message", "amochat_attachment", 25, 26}
    note_block = (parsed.get("note") or {})
    for accion in ("add",):
        notes = note_block.get(accion) or []
        if isinstance(notes, dict):
            notes = [notes]
        for n in notes:
            if not isinstance(n, dict):
                continue
            try:
                nt = n.get("note_type")
                if nt not in NOTE_TYPES_MSG and str(nt) not in NOTE_TYPES_MSG:
                    continue  # No es mensaje de chat
                element_id = n.get("element_id") or n.get("entity_id")
                element_type = n.get("element_type")
                # element_type=2 = lead en Kommo
                if not element_id or str(element_type) not in ("2",):
                    continue
                lead_id = int(element_id)
                # Texto del mensaje: viene en params.text o text
                params = n.get("params") or {}
                if isinstance(params, str):
                    try:
                        import json as _json
                        params = _json.loads(params)
                    except Exception:
                        params = {}
                msg_text = (params.get("text") or n.get("text") or "").strip()
                if not msg_text:
                    mt_inner = (params.get("type") or "").lower()
                    placeholders = {
                        "audio":"🎤 [audio]", "voice":"🎤 [audio]", "picture":"🖼️ [imagen]",
                        "image":"🖼️ [imagen]", "video":"🎬 [video]", "file":"📎 [archivo]",
                        "document":"📄 [documento]", "sticker":"🟣 [sticker]",
                        "location":"📍 [ubicación]", "contact":"👤 [contacto]",
                    }
                    msg_text = placeholders.get(mt_inner, "[sin texto]")
                # Determinar talk_id si existe (para mapear a la conversation correcta)
                talk_id = params.get("talk_id") or n.get("talk_id")
                conv_id = f"talk-{talk_id}" if talk_id else f"lead-{lead_id}"
                # Asegurar lead y conversation existen
                _asegurar_lead_en_db(sb, lead_id)
                advisor_id_lead = None
                try:
                    r = sb.table("kommo_leads").select("advisor_id").eq("lead_id", lead_id).limit(1).execute()
                    if r.data:
                        advisor_id_lead = r.data[0].get("advisor_id")
                except Exception:
                    pass
                try:
                    existe = sb.table("conversations").select("conversation_id").eq("conversation_id", conv_id).limit(1).execute()
                    if not existe.data:
                        created_ts = int(n.get("created_at") or 0) or None
                        sb.table("conversations").upsert({
                            "conversation_id":  conv_id,
                            "lead_id":          lead_id,
                            "advisor_id":       advisor_id_lead,
                            "channel":          params.get("origin") or "unknown",
                            "started_at":       _dt.fromtimestamp(created_ts, tz=_tz.utc).isoformat() if created_ts else None,
                            "last_message_at":  _dt.fromtimestamp(created_ts, tz=_tz.utc).isoformat() if created_ts else None,
                            "status":           "in_work",
                            "audit_status":     "pending",
                            "synced_at":        _dt.now(tz=_tz.utc).isoformat(),
                        }, on_conflict="conversation_id").execute()
                        convs_up += 1
                except Exception:
                    pass

                created_ts = int(n.get("created_at") or 0) or None
                # Sender: si type=outgoing en params es asesora; si incoming es cliente
                params_type = (params.get("type") or "").lower()
                if params_type == "outgoing":
                    sender_type = "advisor"
                elif params_type == "incoming":
                    sender_type = "customer"
                else:
                    # En las notas de asesoras, generalmente created_by != 0 = asesora
                    sender_type = "advisor" if n.get("created_by") else "system"

                # Sender name desde author o params
                sender_name = (params.get("name") or params.get("author_name") or "").strip()
                # Si no, lookup del advisor por created_by (kommo_user_id)
                if not sender_name and n.get("created_by"):
                    try:
                        adv_lookup = sb.table("advisors").select("name").eq("kommo_user_id", int(n.get("created_by"))).limit(1).execute()
                        if adv_lookup.data:
                            sender_name = adv_lookup.data[0].get("name") or ""
                    except Exception:
                        pass

                msg_row = {
                    "message_id":      f"note-{n.get('id')}",
                    "conversation_id": conv_id,
                    "lead_id":         lead_id,
                    "sender_type":     sender_type,
                    "sender_name":     sender_name[:80] if sender_name else "",
                    "message_text":    msg_text[:5000],
                    "sent_at":         _dt.fromtimestamp(created_ts, tz=_tz.utc).isoformat() if created_ts else _dt.now(tz=_tz.utc).isoformat(),
                    "topic":           "text",
                    "payload":         {
                        "via":           "note",
                        "note_type":     nt,
                        "kommo_user_id": n.get("created_by"),
                        "params":        params,
                    },
                }
                # Quitar columnas problemáticas conocidas
                for _col in _columnas_problematicas_messages:
                    msg_row.pop(_col, None)
                msg_row = {k: v for k, v in msg_row.items() if v is not None}
                try:
                    sb.table("messages").upsert(msg_row, on_conflict="message_id").execute()
                    msgs_guardados += 1
                except Exception as e:
                    # Reutilizar la lógica de retry simple: si PGRST204, marcar columna
                    err = str(e)
                    if "PGRST204" in err:
                        import re as _re
                        m_col = _re.search(r"'(\w+)' column", err)
                        if m_col:
                            _columnas_problematicas_messages.add(m_col.group(1))
                            msg_row.pop(m_col.group(1), None)
                            try:
                                sb.table("messages").upsert(msg_row, on_conflict="message_id").execute()
                                msgs_guardados += 1
                            except Exception:
                                pass
                    else:
                        _webhook_stats["errores_parser"] += 1
                        _webhook_stats["ultimos_errores"] = ([f"note: {err[:200]}"] + _webhook_stats["ultimos_errores"])[:5]
            except Exception as e:
                _webhook_stats["errores_parser"] += 1
                _webhook_stats["ultimos_errores"] = ([f"note: {str(e)[:200]}"] + _webhook_stats["ultimos_errores"])[:5]

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

    # Procesamiento en background para responder rápido a Kommo (evita timeouts
    # que desactivan el webhook). Las llamadas a Kommo API en fases C1/C2 pueden
    # tomar varios segundos, no podemos bloquear la respuesta del webhook.
    def _procesar_en_background(body: dict) -> None:
        try:
            parsed = _kommo_form_to_nested(body) if isinstance(body, dict) else {}
            result = _procesar_webhook(parsed)
            _webhook_stats["mensajes_guardados"] += result.get("messages", 0)
            _webhook_stats["convs_upserteadas"] += result.get("conversations", 0)
            _webhook_stats["leads_actualizados"] += result.get("leads", 0)
            audit_queue = result.get("audit_queue") or []
            if audit_queue:
                _auditar_en_background(audit_queue)
                _webhook_stats["auto_audits_disparados"] = _webhook_stats.get("auto_audits_disparados", 0) + len(audit_queue)
        except Exception as e:
            _webhook_stats["errores_parser"] += 1
            _webhook_stats["ultimos_errores"] = ([f"bg: {str(e)[:200]}"] + _webhook_stats["ultimos_errores"])[:5]

    if isinstance(body_dict, dict) and not body_dict.get("_parse_error"):
        background_tasks.add_task(_procesar_en_background, body_dict)

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
    search: str | None = Query(None, description="Búsqueda por nombre/teléfono/lead_id"),
    reply_filter: str | None = Query(
        None,
        description="'pending' = sin respuesta de asesora · 'attended' = con respuesta · None = todas"
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    _: CurrentUser = Depends(require_role("admin", "operador")),
) -> dict:
    """Lista de conversations con filtros + paginación + búsqueda + filtro respondidas.
    'Hoy' (days_back=1) = desde 00:00 Bogotá hasta ahora."""
    sb = db._sb()
    if sb is None:
        raise HTTPException(503, "Supabase no configurado")
    from zoneinfo import ZoneInfo
    TZ_BOG = ZoneInfo("America/Bogota")
    now_bog = datetime.now(tz=TZ_BOG)
    start_bog = now_bog.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_back - 1)
    desde = start_bog.astimezone(timezone.utc).isoformat()

    # 1. Si hay search, primero matchear leads por nombre/teléfono.
    lead_ids_filter: list[int] | None = None
    if search and search.strip():
        s = search.strip()
        # ¿Es lead_id numérico?
        if s.isdigit():
            lead_ids_filter = [int(s)]
        else:
            # Buscar leads cuyo nombre o teléfono contenga el query (case-insensitive).
            try:
                lq = (
                    sb.table("kommo_leads")
                      .select("lead_id")
                      .or_(f"customer_name.ilike.%{s}%,customer_phone.ilike.%{s}%")
                      .limit(500)
                      .execute()
                )
                lead_ids_filter = [r["lead_id"] for r in (lq.data or []) if r.get("lead_id")]
                if not lead_ids_filter:
                    # No hay matches → respuesta vacía rápida.
                    return {
                        "ok": True, "total": 0, "page": page, "page_size": page_size,
                        "pages": 0, "conversations": []
                    }
            except Exception:
                lead_ids_filter = []

    # 2. Construir query base sobre conversations.
    q = sb.table("conversations").select(
        "conversation_id,lead_id,advisor_id,channel,started_at,last_message_at,status,message_count,audit_status",
        count="exact",
    ).gte("last_message_at", desde).order("last_message_at", desc=True)
    if advisor_id:
        q = q.eq("advisor_id", advisor_id)
    if status:
        q = q.eq("status", status)
    if channel:
        q = q.eq("channel", channel)
    if lead_ids_filter is not None:
        if not lead_ids_filter:
            return {"ok": True, "total": 0, "page": page, "page_size": page_size, "pages": 0, "conversations": []}
        q = q.in_("lead_id", lead_ids_filter)

    # 3. Traemos un set amplio para hacer dedup por lead_id + filtros en Python.
    # Cada lead puede tener varias conversations en nuestra DB (meta-wa-*, talk-*,
    # lead-*) — pero el negocio piensa por LEAD, no por canal. Unificamos.
    fetch_limit = 2000
    q = q.limit(fetch_limit)

    res = q.execute()
    convs_all = res.data or []

    # 4. Dedup por lead_id: nos quedamos con la conversation más reciente por lead.
    # Si no hay lead_id (raro), conservamos por conversation_id como fallback.
    convs_all.sort(key=lambda c: c.get("last_message_at") or "", reverse=True)
    convs_dedup: list[dict] = []
    seen_leads: set = set()
    seen_no_lead: set = set()
    for c in convs_all:
        lid = c.get("lead_id")
        if lid:
            if lid in seen_leads:
                continue
            seen_leads.add(lid)
        else:
            cid = c.get("conversation_id")
            if cid in seen_no_lead:
                continue
            seen_no_lead.add(cid)
        convs_dedup.append(c)

    # 5. Filtro pending/attended sobre la lista deduped.
    apply_reply_filter = reply_filter in ("pending", "attended")
    if apply_reply_filter and convs_dedup:
        # Buscar advisor reply por lead_id (no por conversation_id) porque los
        # mensajes pueden estar en cualquiera de las conv del mismo lead.
        lead_ids_check = [c["lead_id"] for c in convs_dedup if c.get("lead_id")]
        leads_with_reply: set = set()
        for i in range(0, len(lead_ids_check), 200):
            batch = lead_ids_check[i:i+200]
            try:
                ms = (sb.table("messages")
                        .select("lead_id,sender_type")
                        .in_("lead_id", batch)
                        .eq("sender_type", "advisor")
                        .limit(5000)
                        .execute().data) or []
                for m in ms:
                    if m.get("lead_id"):
                        leads_with_reply.add(m["lead_id"])
            except Exception:
                pass
        if reply_filter == "pending":
            convs_filtered = [c for c in convs_dedup if c.get("lead_id") not in leads_with_reply]
        else:  # attended
            convs_filtered = [c for c in convs_dedup if c.get("lead_id") in leads_with_reply]
    else:
        convs_filtered = convs_dedup

    total_filtered = len(convs_filtered)

    # 6. Paginar el resultado final.
    convs = convs_filtered[(page - 1) * page_size : page * page_size]

    # 6. Enriquecer.
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

    # Contador de mensajes (cliente / asesora) + tiempo respuesta promedio por lead.
    msg_counts: dict = {}  # lead_id → {customer, advisor, avg_response_min}
    if lead_ids:
        for batch_start in range(0, len(lead_ids), 100):
            batch = lead_ids[batch_start:batch_start + 100]
            try:
                ms = (sb.table("messages")
                        .select("lead_id,sender_type,sent_at")
                        .in_("lead_id", batch)
                        .order("sent_at")
                        .limit(5000)
                        .execute().data) or []
            except Exception:
                ms = []
            # Agrupar por lead
            by_lead: dict = {}
            for m in ms:
                lid = m.get("lead_id")
                if lid is None:
                    continue
                by_lead.setdefault(lid, []).append(m)
            for lid, msgs_lead in by_lead.items():
                cust = sum(1 for m in msgs_lead if m.get("sender_type") == "customer")
                adv  = sum(1 for m in msgs_lead if m.get("sender_type") == "advisor")
                # Tiempo de respuesta: del último customer al siguiente advisor
                rts: list = []
                last_cust_ts = None
                for m in msgs_lead:
                    sa = m.get("sent_at")
                    if not sa:
                        continue
                    try:
                        ts = datetime.fromisoformat(sa.replace("Z", "+00:00"))
                    except Exception:
                        continue
                    st = m.get("sender_type")
                    if st == "customer":
                        last_cust_ts = ts
                    elif st == "advisor" and last_cust_ts:
                        delta = (ts - last_cust_ts).total_seconds()
                        if 0 <= delta <= 86400:
                            rts.append(delta)
                        last_cust_ts = None
                avg_min = round(sum(rts) / len(rts) / 60, 1) if rts else None
                msg_counts[lid] = {"customer": cust, "advisor": adv, "avg_response_min": avg_min}

    # Clientes VIP: aquellos con ≥3 órdenes ganadas (proxy de cliente recurrente).
    # Si la columna existe en kommo_leads la usamos; sino derivamos de count(leads).
    vip_lead_ids: set = set()
    if lead_ids:
        try:
            # Contar leads ganados por customer_phone para identificar recurrentes
            r = (sb.table("kommo_leads")
                   .select("customer_phone")
                   .in_("lead_id", lead_ids)
                   .execute().data) or []
            phones_in_page = list({x["customer_phone"] for x in r if x.get("customer_phone")})
            if phones_in_page:
                # Para cada phone, contar leads históricos won
                for batch_start in range(0, len(phones_in_page), 50):
                    batch = phones_in_page[batch_start:batch_start + 50]
                    rr = (sb.table("kommo_leads")
                            .select("customer_phone,lead_id,status")
                            .in_("customer_phone", batch)
                            .eq("status", "won")
                            .execute().data) or []
                    cnt: dict = {}
                    for x in rr:
                        ph = x.get("customer_phone")
                        if ph:
                            cnt[ph] = cnt.get(ph, 0) + 1
                    phones_vip = {ph for ph, n in cnt.items() if n >= 3}
                    # Marcar como VIP los leads cuyo phone está en phones_vip
                    for lid, lead in leads_map.items():
                        if lead.get("customer_phone") in phones_vip:
                            vip_lead_ids.add(lid)
        except Exception:
            pass

    enriched = []
    for c in convs:
        adv = advisors_map.get(c.get("advisor_id"), {})
        lead = leads_map.get(c.get("lead_id"), {})
        counts = msg_counts.get(c.get("lead_id"), {})
        enriched.append({
            **c,
            "advisor_name":    adv.get("name"),
            "lead_status":     lead.get("status"),
            "lead_value":      lead.get("lead_value"),
            "customer_name":   lead.get("customer_name"),
            "customer_phone":  lead.get("customer_phone"),
            "msgs_customer":   counts.get("customer", 0),
            "msgs_advisor":    counts.get("advisor", 0),
            "avg_response_min": counts.get("avg_response_min"),
            "is_vip":          c.get("lead_id") in vip_lead_ids,
        })

    pages = max(1, (total_filtered + page_size - 1) // page_size) if total_filtered else 0
    return {
        "ok": True,
        "total": total_filtered,
        "page": page,
        "page_size": page_size,
        "pages": pages,
        "conversations": enriched,
    }


@router.get("/advisors/ranking")
def advisors_ranking(
    days_back: int = Query(30, ge=1, le=365),
    incluir_inactivos: bool = Query(False),
    _: CurrentUser = Depends(require_role("admin", "operador")),
) -> dict:
    """Ranking de asesores: conversaciones, won/lost, tasa, último activo.
    Por defecto solo asesoras activas. Use incluir_inactivos=true para ver todas."""
    sb = db._sb()
    if sb is None:
        raise HTTPException(503, "Supabase no configurado")
    desde = (datetime.now(tz=timezone.utc) - timedelta(days=days_back)).isoformat()

    adv_q = sb.table("advisors").select("advisor_id,name,email,active")
    if not incluir_inactivos:
        adv_q = adv_q.eq("active", True)
    advisors = adv_q.execute().data or []
    convs = sb.table("conversations").select("conversation_id,advisor_id,lead_id,last_message_at,channel").gte("last_message_at", desde).execute().data or []
    conv_ids = [c["conversation_id"] for c in convs]
    lead_ids = list({c["lead_id"] for c in convs if c.get("lead_id")})
    leads_map: dict = {}
    if lead_ids:
        for batch_start in range(0, len(lead_ids), 200):
            batch = lead_ids[batch_start:batch_start + 200]
            for l in (sb.table("kommo_leads").select("lead_id,status,lead_value").in_("lead_id", batch).execute().data or []):
                leads_map[l["lead_id"]] = l

    # Mensajes para calcular: atendidas (≥1 msg de advisor) y tiempo de respuesta promedio
    msgs_por_conv: dict = {}  # conv_id → lista de mensajes ordenados
    if conv_ids:
        for batch_start in range(0, len(conv_ids), 100):
            batch = conv_ids[batch_start:batch_start + 100]
            ms = (sb.table("messages")
                    .select("conversation_id,sender_type,sent_at")
                    .in_("conversation_id", batch)
                    .order("sent_at")
                    .limit(5000).execute().data) or []
            for m in ms:
                msgs_por_conv.setdefault(m["conversation_id"], []).append(m)

    by_advisor: dict = {}
    for c in convs:
        adv_id = c.get("advisor_id")
        if not adv_id:
            continue
        r = by_advisor.setdefault(adv_id, {
            "asignadas": 0, "atendidas": 0, "won": 0, "lost": 0, "in_progress": 0,
            "revenue_ganado": 0.0, "last_activity": None, "channels": {},
            "response_times_seg": [],
        })
        r["asignadas"] += 1
        ch = c.get("channel") or "unknown"
        r["channels"][ch] = r["channels"].get(ch, 0) + 1
        lead = leads_map.get(c.get("lead_id")) or {}
        st = lead.get("status")
        if st == "won":
            r["won"] += 1
            r["revenue_ganado"] += float(lead.get("lead_value") or 0)
        elif st == "lost":
            r["lost"] += 1
        else:
            r["in_progress"] += 1
        lm = c.get("last_message_at")
        if lm and (r["last_activity"] is None or lm > r["last_activity"]):
            r["last_activity"] = lm

        # Mensajes de esta conv: ¿hubo respuesta de la asesora? + tiempos
        ms = msgs_por_conv.get(c["conversation_id"], [])
        tiene_advisor_msg = any(m.get("sender_type") == "advisor" for m in ms)
        if tiene_advisor_msg:
            r["atendidas"] += 1
        # Tiempo de respuesta: ms del primer mensaje advisor después de un customer
        last_customer_ts = None
        for m in ms:
            sa = m.get("sent_at")
            if not sa:
                continue
            try:
                ts = datetime.fromisoformat(sa.replace("Z", "+00:00"))
            except Exception:
                continue
            if m.get("sender_type") == "customer":
                last_customer_ts = ts
            elif m.get("sender_type") == "advisor" and last_customer_ts:
                delta = (ts - last_customer_ts).total_seconds()
                if 0 <= delta <= 86400:  # max 24h, descarta outliers
                    r["response_times_seg"].append(delta)
                last_customer_ts = None  # reset hasta próximo customer

    rows = []
    for adv in advisors:
        s = by_advisor.get(adv["advisor_id"], {
            "asignadas": 0, "atendidas": 0, "won": 0, "lost": 0, "in_progress": 0,
            "revenue_ganado": 0.0, "last_activity": None, "channels": {},
            "response_times_seg": [],
        })
        cerradas = s["won"] + s["lost"]
        conv_rate = round(100 * s["won"] / cerradas, 1) if cerradas else None
        # Tasa de respuesta: cuántas conversaciones recibió y efectivamente atendió
        response_rate = round(100 * s["atendidas"] / s["asignadas"], 1) if s["asignadas"] else None
        # Ticket promedio de las ganadas
        ticket_promedio = round(s["revenue_ganado"] / s["won"], 0) if s["won"] else None
        # Tiempo de respuesta promedio (minutos)
        rts = s["response_times_seg"]
        avg_response_min = round(sum(rts) / len(rts) / 60, 1) if rts else None
        rows.append({
            "advisor_id":         adv["advisor_id"],
            "name":               adv["name"],
            "email":              adv.get("email"),
            "active":             adv.get("active"),
            "asignadas":          s["asignadas"],
            "atendidas":          s["atendidas"],
            "won":                s["won"],
            "lost":               s["lost"],
            "in_progress":        s["in_progress"],
            "response_rate":      response_rate,
            "conversion_rate":    conv_rate,
            "revenue_ganado":     s["revenue_ganado"],
            "ticket_promedio":    ticket_promedio,
            "avg_response_min":   avg_response_min,
            "last_activity":      s["last_activity"],
            "channels":           s["channels"],
            # Compat: alias para no romper frontend que ya consume "conversations"
            "conversations":      s["asignadas"],
        })
    rows.sort(key=lambda r: (r["won"], r["asignadas"]), reverse=True)
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
    # Traer TODOS los mensajes del lead — no solo los del conversation_id exacto.
    # Razón: incoming WhatsApp llega como meta-wa-*, pero las respuestas de la
    # asesora desde Kommo entran como talk-* o lead-*. Unificando por lead_id
    # se ven cliente + asesora en orden cronológico, sin importar el canal.
    lead_id_conv = conv.get("lead_id")
    if lead_id_conv:
        msgs = (sb.table("messages")
                  .select("message_id,conversation_id,sender_type,sender_name,message_text,sent_at")
                  .eq("lead_id", lead_id_conv)
                  .order("sent_at")
                  .limit(500)
                  .execute().data) or []
    else:
        # Fallback: si no hay lead_id (raro), usar conversation_id directo.
        msgs = (sb.table("messages")
                  .select("message_id,conversation_id,sender_type,sender_name,message_text,sent_at")
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


@router.post("/sync/notas-recientes")
def sync_notas_recientes(
    horas: int = Query(48, ge=1, le=720, description="Ventana hacia atrás en horas"),
    limit: int = Query(500, ge=10, le=2000, description="Máx conversations a procesar"),
    _: CurrentUser = Depends(require_role("admin")),
) -> dict:
    """Pulla notas de Kommo para conversations activas en últimas N horas.
    Sirve para recuperar mensajes outgoing de asesoras que Kommo no manda
    por webhook (talk[update] llega sin texto). Mucho más amplio que el
    poller cron (que solo mira últimos 10 min)."""
    sb = db._sb()
    if sb is None:
        raise HTTPException(503, "Supabase no configurado")

    cutoff = (datetime.now(tz=timezone.utc) - timedelta(hours=horas)).isoformat()
    try:
        convs = (sb.table("conversations")
                   .select("conversation_id,lead_id,last_message_at")
                   .gte("last_message_at", cutoff)
                   .not_.is_("lead_id", "null")
                   .order("last_message_at", desc=True)
                   .limit(limit).execute().data) or []
    except Exception as e:
        raise HTTPException(503, f"query: {str(e)[:200]}")

    if not convs:
        return {"ok": True, "candidatos": 0, "procesadas": 0, "msgs_total": 0}

    procesadas = 0
    msgs_total = 0
    errores = []
    for c in convs:
        lead_id = c.get("lead_id")
        cid = c.get("conversation_id")
        if not lead_id or not cid:
            continue
        try:
            res = kommo_svc.sync_messages_de_lead(int(lead_id), conversation_id_override=cid)
            procesadas += 1
            msgs_total += int(res.get("mensajes", 0) or 0)
        except Exception as e:
            if len(errores) < 5:
                errores.append(f"lead={lead_id}: {str(e)[:150]}")
    return {
        "ok": True,
        "candidatos": len(convs),
        "procesadas": procesadas,
        "msgs_total": msgs_total,
        "horas": horas,
        "errores": errores,
    }


@router.post("/sync/messages-historicos")
def sync_messages_historicos(
    limit: int = Query(50, ge=1, le=300, description="Cuántas conversaciones procesar"),
    _: CurrentUser = Depends(require_role("admin")),
) -> dict:
    """Toma conversations sin mensajes, llama /leads/{lead_id}/notes para cada una
    y persiste los mensajes históricos (note_type amochat_message/attachment)."""
    sb = db._sb()
    if sb is None:
        raise HTTPException(503, "Supabase no configurado")
    # Conversations con message_count=0 o null, donde sabemos lead_id
    convs = (sb.table("conversations").select("conversation_id,lead_id,message_count")
               .or_("message_count.is.null,message_count.eq.0")
               .not_.is_("lead_id", "null")
               .limit(limit).execute().data) or []
    if not convs:
        return {"ok": True, "candidatos": 0, "procesadas": 0}

    procesadas = 0
    con_mensajes = 0
    total_mensajes = 0
    errores = []
    for c in convs:
        lead_id = c.get("lead_id")
        if not lead_id:
            continue
        try:
            res = kommo_svc.sync_messages_de_lead(lead_id, conversation_id_override=c["conversation_id"])
            procesadas += 1
            if res.get("ok") and res.get("mensajes", 0) > 0:
                con_mensajes += 1
                total_mensajes += res["mensajes"]
        except Exception as e:
            if len(errores) < 3:
                errores.append(f"lead={lead_id}: {str(e)[:200]}")
    return {
        "ok": True,
        "candidatos": len(convs),
        "procesadas": procesadas,
        "con_mensajes": con_mensajes,
        "total_mensajes_nuevos": total_mensajes,
        "errores": errores,
    }


@router.post("/enrich/conversations-advisors")
def enrich_conversations_advisors(
    limit: int = Query(2000, ge=10, le=10000),
    _: CurrentUser = Depends(require_role("admin")),
) -> dict:
    """Llena advisor_id en conversations donde está null, leyendo de kommo_leads.advisor_id"""
    sb = db._sb()
    if sb is None:
        raise HTTPException(503, "Supabase no configurado")
    convs = (sb.table("conversations").select("conversation_id,lead_id,advisor_id")
               .is_("advisor_id", "null").limit(limit).execute().data) or []
    lead_ids = list({c["lead_id"] for c in convs if c.get("lead_id")})
    leads_map: dict = {}
    if lead_ids:
        for batch_start in range(0, len(lead_ids), 200):
            batch = lead_ids[batch_start:batch_start + 200]
            r = sb.table("kommo_leads").select("lead_id,advisor_id").in_("lead_id", batch).execute().data or []
            for ld in r:
                if ld.get("advisor_id"):
                    leads_map[ld["lead_id"]] = ld["advisor_id"]
    actualizados = 0
    for c in convs:
        adv = leads_map.get(c.get("lead_id"))
        if adv:
            try:
                sb.table("conversations").update({"advisor_id": adv}).eq("conversation_id", c["conversation_id"]).execute()
                actualizados += 1
            except Exception:
                pass
    return {"ok": True, "candidatos": len(convs), "actualizados": actualizados, "leads_con_advisor": len(leads_map)}


@router.post("/enrich/leads-customers")
def enrich_leads_customers(
    limit: int = Query(500, ge=10, le=2000, description="Cuántos leads sin nombre procesar"),
    _: CurrentUser = Depends(require_role("admin")),
) -> dict:
    """Toma leads con customer_name vacío, lee contact_id desde campo raw,
    bulk fetch a /contacts y actualiza customer_name + customer_phone."""
    sb = db._sb()
    if sb is None:
        raise HTTPException(503, "Supabase no configurado")
    import sys
    from pathlib import Path
    _SRC = Path(__file__).resolve().parent.parent.parent / "src"
    if str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))
    import kommo_client as kc

    # Leads sin nombre
    leads = (sb.table("kommo_leads").select("lead_id,customer_name,customer_phone,raw")
               .or_("customer_name.is.null,customer_name.eq.")
               .limit(limit).execute().data) or []
    contact_to_lead: dict = {}
    for ld in leads:
        raw = ld.get("raw") or {}
        contacts = ((raw.get("_embedded") or {}).get("contacts") or [])
        if contacts:
            cid = contacts[0].get("id")
            if cid:
                contact_to_lead[int(cid)] = ld["lead_id"]
    if not contact_to_lead:
        return {"ok": True, "candidatos": len(leads), "enriquecidos": 0, "msg": "ningún lead tiene contact_id en raw"}

    contact_ids = list(contact_to_lead.keys())
    contactos = kc.listar_contactos_por_ids(contact_ids)

    enriquecidos = 0
    errores = []
    for c in contactos:
        try:
            cid = int(c.get("id"))
            lead_id = contact_to_lead.get(cid)
            if not lead_id:
                continue
            name = c.get("name") or ""
            # Teléfono está en custom_fields_values con field_code=PHONE
            phone = None
            for cf in (c.get("custom_fields_values") or []):
                if cf.get("field_code") == "PHONE":
                    vals = cf.get("values") or []
                    if vals:
                        phone = vals[0].get("value")
                    break
            updates = {}
            if name: updates["customer_name"] = name
            if phone: updates["customer_phone"] = str(phone)
            if updates:
                sb.table("kommo_leads").update(updates).eq("lead_id", lead_id).execute()
                enriquecidos += 1
        except Exception as e:
            if len(errores) < 3:
                errores.append(str(e)[:200])
    return {
        "ok": True,
        "candidatos": len(leads),
        "contact_ids_consultados": len(contact_ids),
        "contactos_devueltos": len(contactos),
        "enriquecidos": enriquecidos,
        "errores": errores,
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

    advisors = sb.table("advisors").select("advisor_id,name,active").eq("active", True).execute().data or []
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


@router.get("/alertas")
def alertas_activas(
    sin_respuesta_min: int = Query(30, ge=5, le=720, description="Minutos sin respuesta asesora"),
    _: CurrentUser = Depends(require_role("admin", "operador")),
) -> dict:
    """Conversations activas donde:
    1. El último mensaje fue del cliente
    2. Pasaron > N minutos sin respuesta de la asesora
    Útil para detectar clientes esperando.
    """
    sb = db._sb()
    if sb is None:
        raise HTTPException(503, "Supabase no configurado")
    cutoff = datetime.now(tz=timezone.utc) - timedelta(minutes=sin_respuesta_min)
    # Conversations activas (last_message_at en últimas 7 días pero hace > N min)
    desde_amplio = (datetime.now(tz=timezone.utc) - timedelta(days=7)).isoformat()
    convs = (sb.table("conversations")
               .select("conversation_id,lead_id,advisor_id,channel,last_message_at,status")
               .eq("status", "in_work")
               .gte("last_message_at", desde_amplio)
               .lte("last_message_at", cutoff.isoformat())
               .order("last_message_at", desc=True)
               .limit(200).execute().data) or []
    if not convs:
        return {"ok": True, "alertas": [], "total": 0}

    conv_ids = [c["conversation_id"] for c in convs]
    # Para cada conv, último mensaje
    ultimos: dict = {}
    for cid in conv_ids:
        m = (sb.table("messages").select("sender_type,sender_name,message_text,sent_at")
               .eq("conversation_id", cid)
               .order("sent_at", desc=True)
               .limit(1).execute().data) or []
        if m:
            ultimos[cid] = m[0]

    # Filtrar: último mensaje debe ser del cliente
    alertas = []
    lead_ids = list({c["lead_id"] for c in convs if c.get("lead_id")})
    advisor_ids = list({c["advisor_id"] for c in convs if c.get("advisor_id")})
    leads_map = {}
    advisors_map = {}
    if lead_ids:
        for l in (sb.table("kommo_leads").select("lead_id,customer_name,customer_phone").in_("lead_id", lead_ids).execute().data or []):
            leads_map[l["lead_id"]] = l
    if advisor_ids:
        for a in (sb.table("advisors").select("advisor_id,name").in_("advisor_id", advisor_ids).execute().data or []):
            advisors_map[a["advisor_id"]] = a

    ahora = datetime.now(tz=timezone.utc)
    for c in convs:
        cid = c["conversation_id"]
        last = ultimos.get(cid)
        if not last or last.get("sender_type") != "customer":
            continue
        try:
            last_dt = datetime.fromisoformat(last["sent_at"].replace("Z", "+00:00"))
            mins = int((ahora - last_dt).total_seconds() / 60)
        except Exception:
            mins = None
        lead = leads_map.get(c.get("lead_id"), {})
        advisor = advisors_map.get(c.get("advisor_id"), {})
        alertas.append({
            "conversation_id": cid,
            "advisor_id":      c.get("advisor_id"),
            "advisor_name":    advisor.get("name"),
            "customer_name":   lead.get("customer_name"),
            "customer_phone": lead.get("customer_phone"),
            "channel":         c.get("channel"),
            "ultimo_mensaje":  (last.get("message_text") or "")[:200],
            "minutos_sin_respuesta": mins,
            "ultima_actividad": last.get("sent_at"),
        })
    alertas.sort(key=lambda a: a.get("minutos_sin_respuesta") or 0, reverse=True)
    return {"ok": True, "total": len(alertas), "alertas": alertas, "umbral_min": sin_respuesta_min}


@router.get("/tendencias")
def tendencias(
    days_back: int = Query(30, ge=1, le=365),
    _: CurrentUser = Depends(require_role("admin", "operador")),
) -> dict:
    """Agrega conversations por canal, hora del día y día de semana.
    Incluye breakdown won/lost para cada grupo."""
    sb = db._sb()
    if sb is None:
        raise HTTPException(503, "Supabase no configurado")
    desde = (datetime.now(tz=timezone.utc) - timedelta(days=days_back)).isoformat()
    convs = sb.table("conversations").select("conversation_id,lead_id,channel,started_at,last_message_at").gte("last_message_at", desde).execute().data or []
    lead_ids = list({c["lead_id"] for c in convs if c.get("lead_id")})
    leads_map: dict = {}
    if lead_ids:
        for l in (sb.table("kommo_leads").select("lead_id,status").in_("lead_id", lead_ids).execute().data or []):
            leads_map[l["lead_id"]] = l.get("status")

    por_canal: dict = {}
    por_hora: dict = {h: {"total": 0, "won": 0, "lost": 0} for h in range(24)}
    por_dia_semana: dict = {d: {"total": 0, "won": 0, "lost": 0} for d in range(7)}
    DIAS_LABEL = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]

    for c in convs:
        canal = c.get("channel") or "unknown"
        status = leads_map.get(c.get("lead_id"))
        rc = por_canal.setdefault(canal, {"total": 0, "won": 0, "lost": 0, "en_proceso": 0})
        rc["total"] += 1
        if status == "won":
            rc["won"] += 1
        elif status == "lost":
            rc["lost"] += 1
        else:
            rc["en_proceso"] += 1
        started = c.get("started_at") or c.get("last_message_at")
        if started:
            try:
                d = datetime.fromisoformat(started.replace("Z", "+00:00"))
                # Hora local Bogotá UTC-5
                d_local = d.astimezone(timezone(timedelta(hours=-5)))
                h = d_local.hour
                dow = d_local.weekday()
                por_hora[h]["total"] += 1
                por_dia_semana[dow]["total"] += 1
                if status == "won":
                    por_hora[h]["won"] += 1
                    por_dia_semana[dow]["won"] += 1
                elif status == "lost":
                    por_hora[h]["lost"] += 1
                    por_dia_semana[dow]["lost"] += 1
            except Exception:
                pass

    # Calcular tasa de conversión por bucket
    def add_rate(d):
        cerradas = d["won"] + d["lost"]
        d["conv_rate"] = round(100 * d["won"] / cerradas, 1) if cerradas else None
        return d
    for d in por_canal.values(): add_rate(d)
    for d in por_hora.values(): add_rate(d)
    for d in por_dia_semana.values(): add_rate(d)

    return {
        "ok": True,
        "days_back": days_back,
        "total_conversations": len(convs),
        "por_canal": [{"canal": k, **v} for k, v in por_canal.items()],
        "por_hora":  [{"hora": h, **por_hora[h]} for h in range(24)],
        "por_dia_semana": [{"dia": d, "dia_label": DIAS_LABEL[d], **por_dia_semana[d]} for d in range(7)],
    }


@router.get("/coaching/{advisor_id}")
def coaching_asesora(
    advisor_id: str,
    days_back: int = Query(60, ge=7, le=365),
    _: CurrentUser = Depends(require_role("admin")),
) -> dict:
    """Genera reporte de coaching IA para una asesora basado en sus auditorías."""
    return audit_ia.coaching_para_asesora(advisor_id, days_back=days_back)


@router.get("/cron/status")
def cron_status(_: CurrentUser = Depends(require_role("admin"))) -> dict:
    """Estado del cron nocturno de rankings."""
    from backend.core import revenue_scheduler as rsch
    return rsch.get_state()


@router.get("/notifications/slack/status")
def slack_status(_: CurrentUser = Depends(require_role("admin"))) -> dict:
    """Estado del notificador Slack."""
    from backend.services import slack_notifier as sn
    return sn.get_stats()


@router.post("/notifications/slack/test")
def slack_test(_: CurrentUser = Depends(require_role("admin"))) -> dict:
    """Manda un mensaje de prueba a Slack."""
    from backend.services import slack_notifier as sn
    ok = sn.enviar_mensaje(":wave: Test de notificación desde MALE'DENIM OS")
    return {"ok": ok, "stats": sn.get_stats()}


@router.post("/notifications/slack/check-alertas")
def slack_check_alertas(_: CurrentUser = Depends(require_role("admin"))) -> dict:
    """Ejecuta manualmente el detector de alertas + envío a Slack."""
    from backend.core import revenue_scheduler as rsch
    return rsch._detectar_alertas_y_notificar()


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


@router.get("/messages/stats")
def messages_stats(
    desde: str | None = Query(None, description="ISO YYYY-MM-DD (UTC)"),
    hasta: str | None = Query(None, description="ISO YYYY-MM-DD (UTC, inclusive)"),
    days_back: int = Query(7, ge=1, le=180, description="Si no se pasa desde/hasta, ventana de N días desde hoy"),
    _: CurrentUser = Depends(require_role("admin", "operador")),
) -> dict:
    """Contadores de mensajes por día en un rango. Si no se pasa desde/hasta usa
    ventana de los últimos days_back días. Devuelve totales y serie diaria con
    breakdown customer/advisor. 'Hoy' = 00:00 a 23:59 hora Bogotá (UTC-5)."""
    sb = db._sb()
    if sb is None:
        raise HTTPException(503, "Supabase no configurado")
    from datetime import date as _date
    from zoneinfo import ZoneInfo
    TZ_BOG = ZoneInfo("America/Bogota")
    if desde and hasta:
        try:
            # Interpretar desde/hasta como fecha Bogotá (no UTC).
            d_des = datetime.fromisoformat(desde).replace(tzinfo=TZ_BOG)
            d_has = datetime.fromisoformat(hasta).replace(hour=23, minute=59, second=59, tzinfo=TZ_BOG)
            dt_desde = d_des.astimezone(timezone.utc)
            dt_hasta = d_has.astimezone(timezone.utc)
        except Exception:
            raise HTTPException(400, "desde/hasta deben ser YYYY-MM-DD")
    else:
        # 'Hoy' = desde 00:00 Bogotá hasta ahora.
        now_bog = datetime.now(tz=TZ_BOG)
        start_bog = now_bog.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_back - 1)
        dt_desde = start_bog.astimezone(timezone.utc)
        dt_hasta = now_bog.astimezone(timezone.utc)

    # Bajamos rows con sent_at en el rango
    msgs = (sb.table("messages")
              .select("message_id,sender_type,sent_at,conversation_id")
              .gte("sent_at", dt_desde.isoformat())
              .lte("sent_at", dt_hasta.isoformat())
              .limit(50000).execute().data) or []

    por_dia: dict = {}
    total_customer = 0
    total_advisor = 0
    total_otros = 0
    convs_unicas = set()
    for m in msgs:
        sa = m.get("sent_at") or ""
        day = sa[:10]
        if not day:
            continue
        r = por_dia.setdefault(day, {"total": 0, "customer": 0, "advisor": 0, "otros": 0, "conversations": set()})
        r["total"] += 1
        st = m.get("sender_type") or "otros"
        if st == "customer":
            r["customer"] += 1; total_customer += 1
        elif st == "advisor":
            r["advisor"] += 1; total_advisor += 1
        else:
            r["otros"] += 1; total_otros += 1
        cid = m.get("conversation_id")
        if cid:
            r["conversations"].add(cid)
            convs_unicas.add(cid)

    # Serializar: convertir set a count
    serie = []
    cur = dt_desde
    while cur.date() <= dt_hasta.date():
        key = cur.date().isoformat()
        r = por_dia.get(key, {"total": 0, "customer": 0, "advisor": 0, "otros": 0, "conversations": set()})
        serie.append({
            "fecha": key,
            "total": r["total"],
            "customer": r["customer"],
            "advisor": r["advisor"],
            "otros": r["otros"],
            "conversations": len(r["conversations"]) if isinstance(r["conversations"], set) else 0,
        })
        cur = cur + timedelta(days=1)

    return {
        "ok": True,
        "desde": dt_desde.date().isoformat(),
        "hasta": dt_hasta.date().isoformat(),
        "total_mensajes": len(msgs),
        "total_customer": total_customer,
        "total_advisor": total_advisor,
        "total_otros":   total_otros,
        "conversaciones_unicas": len(convs_unicas),
        "serie": serie,
    }


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


# ═══════════════════════════════════════════════════════════════════════════
# Informe Consultor — análisis A-I automatizado
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/informe-consultor")
def get_informe_consultor(
    days_back: int = Query(7, ge=1, le=90),
    advisor_id: str | None = Query(None),
    guardar: bool = Query(False),
    _: CurrentUser = Depends(require_role("admin", "operador")),
) -> dict:
    """Genera informe director comercial sobre conversaciones del periodo."""
    informe = informe_svc.generar_informe(
        days_back=days_back,
        advisor_id=advisor_id,
    )

    if "error" in informe:
        raise HTTPException(status_code=400, detail=informe)

    if guardar:
        informe_id = informe_svc.guardar_informe(informe)
        informe["_metadata"]["informe_id"] = informe_id

    return informe


@router.post("/informe-consultor/run-weekly")
def run_informe_semanal(
    _: CurrentUser = Depends(require_role("admin")),
) -> dict:
    """Endpoint disparado por el cron de lunes 7am Bogotá."""
    informe = informe_svc.generar_informe(days_back=7)

    if "error" in informe:
        raise HTTPException(status_code=400, detail=informe)

    informe_id = informe_svc.guardar_informe(informe)
    informe["_metadata"]["informe_id"] = informe_id

    try:
        slack_url = os.environ.get("SLACK_WEBHOOK_URL")
        if slack_url:
            resumen = informe.get("resumen", {})
            msg = (
                f"📊 *Informe Consultor Semanal MALE Denim*\n"
                f"• Conv analizadas: {resumen.get('total_conversaciones', 0)}\n"
                f"• Ganadas/Perdidas: {resumen.get('ganadas', 0)}/{resumen.get('perdidas', 0)}\n"
                f"• Conv rate: {resumen.get('conv_rate_pct', 0):.1f}%\n"
                f"• Valor recuperable: ${resumen.get('valor_recuperable_estimado_cop', 0):,} COP\n\n"
                f"{resumen.get('diagnostico_general', '')[:500]}\n\n"
                f"Ver informe: /revenue/informes/{informe_id}"
            )
            requests.post(slack_url, json={"text": msg}, timeout=5)
    except Exception as e:
        log.warning(f"Slack notify falló: {e}")

    return {"informe_id": informe_id, "metadata": informe["_metadata"]}


@router.get("/informe-consultor/historico")
def listar_informes(
    limit: int = Query(20, ge=1, le=100),
    _: CurrentUser = Depends(require_role("admin", "operador")),
) -> dict:
    """Lista los últimos N informes generados."""
    sb = db._sb()
    if sb is None:
        raise HTTPException(503, "Supabase no configurado")
    res = (
        sb.table("revenue_informes")
        .select("id, generado_at, days_back, advisor_id, conversaciones_analizadas, "
                "tokens_input, tokens_output")
        .order("generado_at", desc=True)
        .limit(limit)
        .execute()
    )
    return {"ok": True, "informes": res.data or []}


@router.get("/informe-consultor/{informe_id}")
def obtener_informe(
    informe_id: str,
    _: CurrentUser = Depends(require_role("admin", "operador")),
) -> dict:
    """Recupera un informe específico por ID."""
    sb = db._sb()
    if sb is None:
        raise HTTPException(503, "Supabase no configurado")
    res = (
        sb.table("revenue_informes")
        .select("*")
        .eq("id", informe_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Informe no encontrado")
    return res.data[0]
