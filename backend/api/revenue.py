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


def _safe_exec(q, retries: int = 2, default=None):
    """
    Ejecuta una query Supabase con retry + backoff cuando httpx desconecta
    el pool mid-stream (RemoteProtocolError: Server disconnected).
    Retorna la data o `default` (típicamente []) tras agotar retries.
    """
    import time
    last_exc = None
    for i in range(retries + 1):
        try:
            return q.execute().data or (default if default is not None else [])
        except Exception as e:
            last_exc = e
            msg = str(e).lower()
            if "remoteprotocol" in msg or "disconnected" in msg or "server disconnected" in msg:
                if i < retries:
                    time.sleep(0.4 * (2 ** i))  # 0.4s, 0.8s
                    continue
            raise
    if last_exc is not None:
        log.warning(f"_safe_exec agotó retries: {last_exc}")
    return default if default is not None else []


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
                conv_id_talk = f"talk-{talk_id}"
                new_lma = _dt.fromtimestamp(updated, tz=_tz.utc).isoformat() if updated else None

                # Monotonic write: si la conv ya existe, no retrocedas el reloj
                # de last_message_at. Esto evita que un webhook con timestamp
                # viejo de Kommo pise un timestamp más reciente del Meta webhook.
                existing_lma = None
                try:
                    exq = sb.table("conversations").select("last_message_at").eq("conversation_id", conv_id_talk).limit(1).execute()
                    if exq.data:
                        existing_lma = exq.data[0].get("last_message_at")
                except Exception:
                    pass
                if existing_lma and new_lma and existing_lma >= new_lma:
                    # Skip last_message_at en este upsert
                    new_lma = existing_lma

                row = {
                    "conversation_id":  conv_id_talk,
                    "lead_id":          int(entity_id),
                    "advisor_id":       advisor_id_lead,
                    "channel":          t.get("origin") or "unknown",
                    "started_at":       _dt.fromtimestamp(created, tz=_tz.utc).isoformat() if created else None,
                    "last_message_at":  new_lma,
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
    """Receptor de eventos de Kommo. PÚBLICO.

    CRITICAL: Kommo desactiva el webhook si tarda >2s en responder. Por eso:
    1. Leemos bytes crudos (rápido, no parsea form/json).
    2. Encolamos TODO el parseo y persistencia en background.
    3. Respondemos 200 inmediatamente.
    """
    from datetime import datetime as _dt, timezone as _tz
    now_iso = _dt.now(tz=_tz.utc).isoformat()

    # Lectura mínima: bytes crudos + content-type. Sin await form()/json() acá.
    try:
        raw = await request.body()
        ct = (request.headers.get("content-type") or "").lower()
    except Exception:
        raw = b""
        ct = ""

    _webhook_stats["total"] += 1
    if _webhook_stats["primero_en"] is None:
        _webhook_stats["primero_en"] = now_iso
    _webhook_stats["ultimo_en"] = now_iso

    def _procesar_en_background(raw_bytes: bytes, ctype: str) -> None:
        """Parsea body + persiste. Corre DESPUÉS de responder a Kommo."""
        try:
            body_dict: dict = {}
            if "json" in ctype:
                import json as _json
                try:
                    body_dict = _json.loads(raw_bytes.decode("utf-8", errors="replace") or "{}")
                except Exception:
                    body_dict = {}
            else:
                # form-urlencoded: parsear manualmente sin instanciar Starlette.FormData
                from urllib.parse import parse_qsl
                try:
                    body_dict = dict(parse_qsl(
                        raw_bytes.decode("utf-8", errors="replace"),
                        keep_blank_values=True,
                    ))
                except Exception:
                    body_dict = {}
            if not isinstance(body_dict, dict):
                body_dict = {}

            keys = " ".join(body_dict.keys())
            es_msg = "message" in keys or "talk" in keys
            es_lead = "leads" in keys
            if es_msg:
                _webhook_stats["mensajes_evento"] += 1
            elif es_lead:
                _webhook_stats["leads_evento"] += 1
            else:
                _webhook_stats["otros"] += 1

            preview = {k: (str(v)[:200] if not isinstance(v, (dict, list)) else "<obj>")
                       for k, v in list(body_dict.items())[:20]}
            _webhook_stats["ultimos_payloads"].insert(0, {
                "ts": now_iso,
                "tipo": "message" if es_msg else "lead" if es_lead else "otro",
                "keys": list(body_dict.keys())[:20],
                "preview": preview,
            })
            _webhook_stats["ultimos_payloads"] = _webhook_stats["ultimos_payloads"][:10]

            parsed = _kommo_form_to_nested(body_dict)
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

    background_tasks.add_task(_procesar_en_background, raw, ct)
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
@router.get("/diag")
def diag() -> dict:
    """Diagnostic público sin auth — útil para debug remoto sin ver logs Railway.

    Reporta:
    - uptime del proceso (cuánto lleva vivo)
    - memoria + CPU
    - timestamp del último cron run
    - últimos errores capturados
    """
    import os
    import time
    info: dict = {
        "ok": True,
        "ts": datetime.now(tz=timezone.utc).isoformat(),
        "pid": os.getpid(),
    }
    # Uptime proceso
    try:
        with open("/proc/self/stat") as f:
            stat = f.read().split()
        start_jiffies = int(stat[21])
        clock_ticks = os.sysconf("SC_CLK_TCK")
        with open("/proc/uptime") as f:
            boot_uptime = float(f.read().split()[0])
        proc_uptime = boot_uptime - (start_jiffies / clock_ticks)
        info["uptime_sec"] = round(proc_uptime, 1)
    except Exception as e:
        info["uptime_err"] = str(e)[:100]
    # Memory
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    info["mem_kb"] = int(line.split()[1])
                elif line.startswith("VmPeak:"):
                    info["mem_peak_kb"] = int(line.split()[1])
    except Exception:
        pass
    # Scheduler state
    try:
        from backend.core import revenue_scheduler as rsch
        st = rsch.get_state()
        info["scheduler"] = {
            "last_run_at":  st.get("last_run_at"),
            "last_result":  (str(st.get("last_result") or "")[:300]) or None,
        }
    except Exception as e:
        info["scheduler_err"] = str(e)[:200]
    # Stats webhook Kommo
    try:
        info["kommo_webhook_stats"] = {
            "total":             _webhook_stats.get("total", 0),
            "ultimo_en":         _webhook_stats.get("ultimo_en"),
            "mensajes_evento":   _webhook_stats.get("mensajes_evento", 0),
            "leads_evento":      _webhook_stats.get("leads_evento", 0),
            "errores_parser":    _webhook_stats.get("errores_parser", 0),
            "ultimos_errores":   _webhook_stats.get("ultimos_errores", [])[:3],
        }
    except Exception:
        pass
    return info


@router.get("/kommo/describe")
def kommo_describe(_: CurrentUser = Depends(require_role("admin"))) -> dict:
    """Extrae TODO lo estructural de Kommo en un solo response.

    Útil para entender el ecosistema completo de un vistazo:
    - Account info (subdomain, currency, country, plan)
    - Pipelines con sus stages
    - Custom fields del lead (con field_id, code, type)
    - Sample lead con TODOS los campos populados
    - Lista de usuarios (asesoras) con roles
    """
    import sys
    from pathlib import Path
    _SRC = Path(__file__).resolve().parent.parent.parent / "src"
    if str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))
    import kommo_client as kc

    out: dict = {"ok": True}
    # Account
    try:
        out["account"] = kc.verificar_conexion()
    except Exception as e:
        out["account_err"] = str(e)[:200]
    # Pipelines
    try:
        out["pipelines"] = kc.listar_pipelines()
    except Exception as e:
        out["pipelines_err"] = str(e)[:200]
    # Users / advisors
    try:
        users = kc.listar_usuarios()
        out["users"] = [
            {"id": u.get("id"), "name": u.get("name"), "email": u.get("email"),
             "rights": u.get("rights") or {}, "lang": u.get("lang")}
            for u in users
        ]
    except Exception as e:
        out["users_err"] = str(e)[:200]
    # Custom fields lead (via raw API)
    try:
        from urllib.parse import urlencode as _ue
        url = f"{kc._base_url()}/leads/custom_fields"
        resp = kc._get(url.replace(kc._base_url(), ""), {"limit": 250})
        out["lead_custom_fields"] = ((resp or {}).get("_embedded") or {}).get("custom_fields", [])
    except Exception as e:
        out["lead_custom_fields_err"] = str(e)[:200]
    # Custom fields contact
    try:
        url = f"{kc._base_url()}/contacts/custom_fields"
        resp = kc._get(url.replace(kc._base_url(), ""), {"limit": 250})
        out["contact_custom_fields"] = ((resp or {}).get("_embedded") or {}).get("custom_fields", [])
    except Exception as e:
        out["contact_custom_fields_err"] = str(e)[:200]
    # Sample lead con TODOS los campos
    try:
        leads_sample = list(kc.listar_leads(limit_total=1))
        out["sample_lead"] = leads_sample[0] if leads_sample else None
    except Exception as e:
        out["sample_lead_err"] = str(e)[:200]
    return out


@router.post("/backfill/conversations-vacias")
def backfill_conversations_vacias(
    background_tasks: BackgroundTasks,
    limit: int = Query(100, ge=1, le=1000, description="Cuántas conversaciones vacías procesar"),
    days_back: int = Query(30, ge=1, le=365, description="Solo conversaciones activas en últimos N días"),
    _: CurrentUser = Depends(require_role("admin")),
) -> dict:
    """Encuentra conversaciones SIN mensajes y trata de jalar las notas
    históricas desde Kommo. Útil para rellenar conversaciones 0/0 que
    quedaron así porque se crearon antes del webhook Meta o durante
    apagones del webhook Kommo.

    Corre en background para no bloquear la respuesta. Cada lead toma
    ~2-5s (rate-limit Kommo). Con limit=100 son ~5-10 minutos.
    """
    sb = db._sb()
    if sb is None:
        raise HTTPException(503, "Supabase no configurado")

    desde = (datetime.now(tz=timezone.utc) - timedelta(days=days_back)).isoformat()

    # Encontrar conversaciones recientes con lead_id pero SIN mensajes en messages
    convs_q = (sb.table("conversations")
                 .select("conversation_id,lead_id")
                 .not_.is_("lead_id", "null")
                 .gte("last_message_at", desde)
                 .order("last_message_at", desc=True)
                 .limit(2000))
    convs = _safe_exec(convs_q, retries=2, default=[])

    # Cuáles tienen mensajes en messages
    conv_ids = [c["conversation_id"] for c in convs]
    con_mensajes: set = set()
    for i in range(0, len(conv_ids), 200):
        batch = conv_ids[i:i+200]
        try:
            mq = (sb.table("messages").select("conversation_id")
                    .in_("conversation_id", batch).limit(2000).execute().data) or []
            for m in mq:
                con_mensajes.add(m["conversation_id"])
        except Exception:
            pass

    # Las que faltan
    vacias = [c for c in convs if c["conversation_id"] not in con_mensajes][:limit]
    leads_pendientes = list({c["lead_id"] for c in vacias if c.get("lead_id")})

    # Disparar en background
    def _backfill_worker(lead_ids: list[int]):
        rescatados = 0
        fallidos = 0
        for lid in lead_ids:
            try:
                res = kommo_svc.sync_messages_de_lead(int(lid))
                if res.get("messages_guardados", 0) > 0:
                    rescatados += 1
                else:
                    fallidos += 1
            except Exception:
                fallidos += 1
        log.info(f"backfill_conversations_vacias terminó: rescatados={rescatados} fallidos={fallidos}")

    background_tasks.add_task(_backfill_worker, leads_pendientes)
    return {
        "ok": True,
        "encolados": len(leads_pendientes),
        "convs_vacias_detectadas": len(vacias),
        "convs_revisadas": len(convs),
        "hint": "Corriendo en background. Re-consulta /diagnostico en 5-10 min para ver progreso.",
    }


@router.get("/media/{message_id}")
def media_proxy(message_id: str):
    """Sirve media (imagen/video/audio) de un mensaje WhatsApp, proxy a Meta.

    El media_id de Meta expira en ~5 min, por eso no podemos cachearlo en
    DB. Cada vez que el frontend pide la imagen, hacemos lookup del media_id
    desde messages.payload y llamamos a Meta Graph API en vivo.

    Útil para mostrar inline en /revenue las fotos que clientes envían
    (capturas de pantalla, fotos de productos, comprobantes de pago).

    PÚBLICO sin auth para que el browser pueda mostrar <img src=...>.
    El message_id sigue siendo opaco (no enumerable), no es un riesgo real.
    """
    from fastapi.responses import Response
    sb = db._sb()
    if sb is None:
        raise HTTPException(503, "Supabase no configurado")
    try:
        r = sb.table("messages").select("payload").eq("message_id", message_id).limit(1).execute()
        if not r.data:
            raise HTTPException(404, "mensaje no encontrado")
        payload = r.data[0].get("payload") or {}
        raw = payload.get("raw") or {}
        media_id = None
        # WhatsApp: payload.raw tiene image/audio/video/document/sticker
        for kind in ("image", "audio", "video", "document", "sticker", "voice"):
            obj = raw.get(kind) or {}
            if obj.get("id"):
                media_id = obj["id"]
                break
        if not media_id:
            raise HTTPException(404, "media_id no encontrado en payload")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"lookup: {str(e)[:120]}")

    from backend.services import transcription as _tx
    downloaded = _tx.descargar_media_meta(media_id)
    if not downloaded:
        raise HTTPException(502, "Meta media descarga falló")
    audio_bytes, mime = downloaded
    return Response(content=audio_bytes, media_type=mime, headers={
        "Cache-Control": "private, max-age=300",  # 5 min cache cliente
    })


@router.api_route("/ping", methods=["GET", "HEAD"])
def ping() -> dict:
    """Health-check PÚBLICO sin auth — pega esto a UptimeRobot cada 5 min
    para que Railway no duerma y el webhook Kommo responda en <2s siempre.
    Acepta GET y HEAD (UptimeRobot usa HEAD por default).
    """
    from datetime import datetime as _dt, timezone as _tz
    return {"ok": True, "ts": _dt.now(tz=_tz.utc).isoformat()}


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
    hours_back: float | None = Query(None, gt=0, le=8760, description="Si se pasa, override days_back: ventana rolling de N horas desde ahora (ej. 1, 4, 12)."),
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
    'Hoy' (days_back=1) = desde 00:00 Bogotá hasta ahora.
    Si se pasa hours_back, usa ventana rolling de N horas en vez de anchor a medianoche."""
    sb = db._sb()
    if sb is None:
        raise HTTPException(503, "Supabase no configurado")
    from zoneinfo import ZoneInfo
    TZ_BOG = ZoneInfo("America/Bogota")
    now_bog = datetime.now(tz=TZ_BOG)
    if hours_back is not None:
        desde = (datetime.now(tz=timezone.utc) - timedelta(hours=hours_back)).isoformat()
    else:
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

    # 3. Traemos un set acotado para dedup por lead_id + filtros en Python.
    # Cada lead puede tener varias conversations (meta-wa-*, talk-*, lead-*),
    # pero el negocio piensa por LEAD, no por canal.
    # 800 es suficiente para 30 días reales y evita timeouts de Supabase.
    fetch_limit = 800
    q = q.limit(fetch_limit)

    convs_all = _safe_exec(q, retries=2, default=[])

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
        # Solo necesitamos saber si CADA lead tiene ≥1 mensaje de asesora.
        # Batch grande (200 lead_ids) con select mínimo (solo lead_id) +
        # filter sender_type=advisor + limit 3000 = una query cubre 200
        # leads. Para 800 convs → 4 queries (vs 8 antes). Sin N+1 real.
        # NOTA: limit 3000 funciona porque ya filtramos sender_type=advisor;
        # si un lead muy verbose tiene >15 advisor msgs simplemente lo
        # detectamos en el primero.
        lead_ids_check = [c["lead_id"] for c in convs_dedup if c.get("lead_id")]
        leads_with_reply: set = set()
        for i in range(0, len(lead_ids_check), 200):
            batch = lead_ids_check[i:i+200]
            try:
                q_msg = (sb.table("messages")
                           .select("lead_id")
                           .in_("lead_id", batch)
                           .eq("sender_type", "advisor")
                           .limit(3000))
                ms = _safe_exec(q_msg, retries=1, default=[])
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
        adv_q = sb.table("advisors").select("advisor_id,name,email").in_("advisor_id", advisor_ids)
        for a in _safe_exec(adv_q, retries=2, default=[]):
            advisors_map[a["advisor_id"]] = a
    if lead_ids:
        leads_q = sb.table("kommo_leads").select("lead_id,status,lead_value,customer_name,customer_phone").in_("lead_id", lead_ids)
        for l in _safe_exec(leads_q, retries=2, default=[]):
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
    hours_back: float | None = Query(None, gt=0, le=8760, description="Override days_back: ventana rolling de N horas."),
    incluir_inactivos: bool = Query(False),
    _: CurrentUser = Depends(require_role("admin", "operador")),
) -> dict:
    """Ranking de asesores: conversaciones, won/lost, tasa, último activo."""
    sb = db._sb()
    if sb is None:
        raise HTTPException(503, "Supabase no configurado")
    if hours_back is not None:
        desde = (datetime.now(tz=timezone.utc) - timedelta(hours=hours_back)).isoformat()
    else:
        desde = (datetime.now(tz=timezone.utc) - timedelta(days=days_back)).isoformat()

    adv_q = sb.table("advisors").select("advisor_id,name,email,active")
    if not incluir_inactivos:
        adv_q = adv_q.eq("active", True)
    advisors = _safe_exec(adv_q, retries=2, default=[])
    # Limit explícito: el ranking opera sobre conv recientes, 3000 cubre periodos
    # razonables sin reventar el pool de Supabase.
    convs_q = (sb.table("conversations")
                 .select("conversation_id,advisor_id,lead_id,last_message_at,channel")
                 .gte("last_message_at", desde)
                 .order("last_message_at", desc=True)
                 .limit(3000))
    convs = _safe_exec(convs_q, retries=2, default=[])
    conv_ids = [c["conversation_id"] for c in convs]
    lead_ids = list({c["lead_id"] for c in convs if c.get("lead_id")})
    leads_map: dict = {}
    if lead_ids:
        # Batches de 100 (era 200) — postgrest IN(...) clauses grandes hacen
        # URLs que el load balancer corta.
        for batch_start in range(0, len(lead_ids), 100):
            batch = lead_ids[batch_start:batch_start + 100]
            leads_q = (sb.table("kommo_leads")
                         .select("lead_id,status,lead_value")
                         .in_("lead_id", batch)
                         .limit(200))
            for l in _safe_exec(leads_q, retries=1, default=[]):
                leads_map[l["lead_id"]] = l

    # Mensajes para calcular: atendidas + tiempo de respuesta promedio.
    # Batches 50 (era 100) + limit 2000 (era 5000) para evitar
    # RemoteProtocolError mid-stream.
    msgs_por_conv: dict = {}  # conv_id → lista de mensajes ordenados
    if conv_ids:
        for batch_start in range(0, len(conv_ids), 50):
            batch = conv_ids[batch_start:batch_start + 50]
            msgs_q = (sb.table("messages")
                        .select("conversation_id,sender_type,sent_at")
                        .in_("conversation_id", batch)
                        .order("sent_at")
                        .limit(2000))
            for m in _safe_exec(msgs_q, retries=1, default=[]):
                msgs_por_conv.setdefault(m["conversation_id"], []).append(m)

    # Ampliar campos traídos del lead para métricas adicionales.
    if lead_ids:
        leads_map = {}
        for batch_start in range(0, len(lead_ids), 100):
            batch = lead_ids[batch_start:batch_start + 100]
            leads_q = (sb.table("kommo_leads")
                         .select("lead_id,status,lead_value,created_at,closed_at")
                         .in_("lead_id", batch)
                         .limit(200))
            for l in _safe_exec(leads_q, retries=1, default=[]):
                leads_map[l["lead_id"]] = l

    now_utc = datetime.now(tz=timezone.utc)
    cutoff_24h = (now_utc - timedelta(hours=24)).isoformat()
    cutoff_48h = (now_utc - timedelta(hours=48)).isoformat()

    by_advisor: dict = {}
    for c in convs:
        adv_id = c.get("advisor_id")
        if not adv_id:
            continue
        r = by_advisor.setdefault(adv_id, {
            "asignadas": 0, "atendidas": 0, "won": 0, "lost": 0, "in_progress": 0,
            "revenue_ganado": 0.0, "last_activity": None, "channels": {},
            "response_times_seg": [],
            # Nuevas métricas
            "atendidas_24h": 0,
            "dormidos_48h":  0,
            "edades_cierre_dias": [],
            "cierre_por_canal": {},  # canal → {won, lost}
        })
        r["asignadas"] += 1
        ch_raw = (c.get("channel") or "unknown").lower()
        if "waba" in ch_raw or "whatsapp" in ch_raw or ch_raw == "wa": ch_norm = "WhatsApp"
        elif "instagram" in ch_raw or ch_raw == "ig" or ch_raw == "dm": ch_norm = "Instagram"
        elif "messenger" in ch_raw or "facebook" in ch_raw: ch_norm = "Messenger"
        elif "tiktok" in ch_raw: ch_norm = "TikTok"
        else: ch_norm = ch_raw.capitalize() or "Otro"
        r["channels"][ch_norm] = r["channels"].get(ch_norm, 0) + 1

        lead = leads_map.get(c.get("lead_id")) or {}
        st = lead.get("status")
        cierre_canal = r["cierre_por_canal"].setdefault(ch_norm, {"won": 0, "lost": 0})
        if st == "won":
            r["won"] += 1
            r["revenue_ganado"] += float(lead.get("lead_value") or 0)
            cierre_canal["won"] += 1
            # Antigüedad lead al cerrar (días)
            try:
                if lead.get("created_at") and lead.get("closed_at"):
                    c_dt = datetime.fromisoformat(lead["created_at"].replace("Z", "+00:00"))
                    f_dt = datetime.fromisoformat(lead["closed_at"].replace("Z", "+00:00"))
                    edad_dias = (f_dt - c_dt).total_seconds() / 86400
                    if 0 < edad_dias < 365:
                        r["edades_cierre_dias"].append(edad_dias)
            except Exception:
                pass
        elif st == "lost":
            r["lost"] += 1
            cierre_canal["lost"] += 1
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
            # Atendidas en últimas 24h
            ultimo_advisor = max((m.get("sent_at", "") for m in ms if m.get("sender_type") == "advisor"), default="")
            if ultimo_advisor and ultimo_advisor >= cutoff_24h:
                r["atendidas_24h"] += 1

        # Lead "dormido": último mensaje > 48h y sin cerrar (in_progress)
        if st not in ("won", "lost") and lm and lm < cutoff_48h:
            r["dormidos_48h"] += 1

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
            "response_times_seg": [], "atendidas_24h": 0, "dormidos_48h": 0,
            "edades_cierre_dias": [], "cierre_por_canal": {},
        })
        cerradas = s["won"] + s["lost"]
        conv_rate = round(100 * s["won"] / cerradas, 1) if cerradas else None
        response_rate = round(100 * s["atendidas"] / s["asignadas"], 1) if s["asignadas"] else None
        ticket_promedio = round(s["revenue_ganado"] / s["won"], 0) if s["won"] else None
        rts = s["response_times_seg"]
        avg_response_min = round(sum(rts) / len(rts) / 60, 1) if rts else None
        # Antigüedad promedio del lead al cerrar (días)
        edades = s["edades_cierre_dias"]
        avg_edad_cierre_dias = round(sum(edades) / len(edades), 1) if edades else None
        # Tasa de cierre por canal: %win en cada uno
        cierre_canal_rate = {
            ch: round(100 * v["won"] / (v["won"] + v["lost"]), 1) if (v["won"] + v["lost"]) else None
            for ch, v in s["cierre_por_canal"].items()
        }
        rows.append({
            "advisor_id":          adv["advisor_id"],
            "name":                adv["name"],
            "email":               adv.get("email"),
            "active":              adv.get("active"),
            "asignadas":           s["asignadas"],
            "atendidas":           s["atendidas"],
            "won":                 s["won"],
            "lost":                s["lost"],
            "in_progress":         s["in_progress"],
            "response_rate":       response_rate,
            "conversion_rate":     conv_rate,
            "revenue_ganado":      s["revenue_ganado"],
            "ticket_promedio":     ticket_promedio,
            "avg_response_min":    avg_response_min,
            "last_activity":       s["last_activity"],
            "channels":            s["channels"],
            # Nuevas métricas
            "atendidas_24h":       s["atendidas_24h"],
            "dormidos_48h":        s["dormidos_48h"],
            "avg_edad_cierre_dias": avg_edad_cierre_dias,
            "cierre_por_canal":    cierre_canal_rate,
            # Compat
            "conversations":       s["asignadas"],
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


@router.get("/lead-fields-stats")
def lead_fields_stats(
    days_back: int = Query(30, ge=1, le=365),
    _: CurrentUser = Depends(require_role("admin", "operador")),
) -> dict:
    """Agrega valores de custom_fields_values de los leads en el período.

    Lee la columna `raw` JSONB de kommo_leads (donde guardamos el lead crudo)
    y extrae cada campo personalizado: fuente, campaña, talla, color, etc.
    Útil para que el director comercial vea atribución y mix de producto.
    """
    sb = db._sb()
    if sb is None:
        raise HTTPException(503, "Supabase no configurado")
    desde = (datetime.now(tz=timezone.utc) - timedelta(days=days_back)).isoformat()

    leads_q = (sb.table("kommo_leads")
                 .select("lead_id,status,lead_value,raw,created_at")
                 .gte("created_at", desde)
                 .order("created_at", desc=True)
                 .limit(3000))
    leads = _safe_exec(leads_q, retries=2, default=[])

    # Estructura: { field_name: { value: { count, won, revenue } } }
    by_field: dict = {}
    n_con_custom_fields = 0
    for l in leads:
        raw = l.get("raw") or {}
        cfv = raw.get("custom_fields_values") or []
        if cfv:
            n_con_custom_fields += 1
        is_won = l.get("status") == "won"
        revenue = float(l.get("lead_value") or 0) if is_won else 0
        for f in cfv:
            fname = f.get("field_name") or f.get("field_code") or "—"
            vals = f.get("values") or []
            for v in vals:
                vraw = v.get("value")
                if vraw is None:
                    continue
                vstr = str(vraw)[:100]
                bucket = by_field.setdefault(fname, {})
                row = bucket.setdefault(vstr, {"count": 0, "won": 0, "revenue": 0.0})
                row["count"] += 1
                if is_won:
                    row["won"] += 1
                    row["revenue"] += revenue

    # Top 10 valores por field, calcular conv_rate
    resumen: dict = {}
    for fname, valores in by_field.items():
        rows = []
        for vstr, stats in valores.items():
            rows.append({
                "value": vstr,
                "count": stats["count"],
                "won":   stats["won"],
                "revenue": int(stats["revenue"]),
                "conv_rate": round(100 * stats["won"] / stats["count"], 1) if stats["count"] else 0,
            })
        rows.sort(key=lambda r: r["count"], reverse=True)
        resumen[fname] = rows[:10]

    return {
        "ok": True,
        "periodo_dias":             days_back,
        "leads_analizados":         len(leads),
        "leads_con_custom_fields":  n_con_custom_fields,
        "campos":                   resumen,
    }


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
    days_back: int = Query(8, ge=1, le=90),
    _: CurrentUser = Depends(require_role("admin")),
) -> dict:
    """Coaching IA basado en auditorías recientes (default 8 días).
    Usa kommo_leads.status como ground truth para won/lost, no Haiku."""
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
    hours_back: float | None = Query(None, gt=0, le=8760, description="Override days_back: ventana rolling de N horas."),
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
            d_des = datetime.fromisoformat(desde).replace(tzinfo=TZ_BOG)
            d_has = datetime.fromisoformat(hasta).replace(hour=23, minute=59, second=59, tzinfo=TZ_BOG)
            dt_desde = d_des.astimezone(timezone.utc)
            dt_hasta = d_has.astimezone(timezone.utc)
        except Exception:
            raise HTTPException(400, "desde/hasta deben ser YYYY-MM-DD")
    elif hours_back is not None:
        # Ventana rolling de N horas desde ahora.
        dt_hasta = datetime.now(tz=timezone.utc)
        dt_desde = dt_hasta - timedelta(hours=hours_back)
    else:
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


@router.get("/loss-reasons-stats")
def loss_reasons_stats(
    days_back: int = Query(30, ge=1, le=365),
    _: CurrentUser = Depends(require_role("admin", "operador")),
) -> dict:
    """Top motivos de pérdida estructurados (custom field 'Motivo de Perdida').
    Mucho más accionable que loss_reason texto libre.
    """
    sb = db._sb()
    if sb is None:
        raise HTTPException(503, "Supabase no configurado")
    desde = (datetime.now(tz=timezone.utc) - timedelta(days=days_back)).isoformat()
    leads_q = (sb.table("kommo_leads")
                 .select("lead_id,status,lead_value,raw,closed_at,advisor_id")
                 .eq("status", "lost")
                 .gte("closed_at", desde)
                 .order("closed_at", desc=True)
                 .limit(3000))
    leads = _safe_exec(leads_q, retries=2, default=[])

    # Agregar por motivo + por asesora
    por_motivo: dict = {}
    por_asesora_motivo: dict = {}
    for l in leads:
        raw = l.get("raw") or {}
        cfv = raw.get("custom_fields_values") or []
        motivo = None
        for f in cfv:
            if f.get("field_name") == "Motivo de Perdida":
                vals = f.get("values") or []
                if vals:
                    motivo = vals[0].get("value") or "Sin motivo"
                break
        motivo = motivo or "Sin motivo"
        val = float(l.get("lead_value") or 0)
        m = por_motivo.setdefault(motivo, {"count": 0, "valor_perdido": 0})
        m["count"] += 1
        m["valor_perdido"] += val
        aid = l.get("advisor_id")
        if aid:
            ka = por_asesora_motivo.setdefault(aid, {})
            ka[motivo] = ka.get(motivo, 0) + 1

    top_motivos = sorted(
        [{"motivo": k, **v, "valor_perdido": int(v["valor_perdido"])}
         for k, v in por_motivo.items()],
        key=lambda r: r["count"], reverse=True,
    )
    return {
        "ok": True,
        "periodo_dias": days_back,
        "total_leads_perdidos": len(leads),
        "top_motivos": top_motivos,
        "por_asesora_motivo": por_asesora_motivo,
    }


@router.get("/pipelines")
def pipelines_list(_: CurrentUser = Depends(require_role("admin", "operador"))) -> dict:
    """Lista los pipelines de Kommo (no cacheado — siempre fresh).
    Útil para el selector en /revenue.
    """
    import sys
    from pathlib import Path
    _SRC = Path(__file__).resolve().parent.parent.parent / "src"
    if str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))
    import kommo_client as kc
    try:
        pips = kc.listar_pipelines()
        return {
            "ok": True,
            "pipelines": [
                {
                    "id": p.get("id"),
                    "name": p.get("name"),
                    "is_main": p.get("is_main", False),
                    "sort": p.get("sort"),
                }
                for p in pips
            ],
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:200], "pipelines": []}


@router.get("/briefing-hoy")
def briefing_hoy(_: CurrentUser = Depends(require_role("admin", "operador"))) -> dict:
    """Briefing matutino — el reporte que el equipo revisa cada mañana.

    Usa el MISMO patrón de /messages/stats (limit 50000, funciona) en vez del
    patrón de /diagnostico (limit 3000, fallaba). Garantiza datos reales.

    Ventana: 00:00 Bogotá hasta ahora.
    Retorna: total convs del día · atendidas/pendientes/sin asesora ·
             por canal · por asesora ordenada por pendientes desc ·
             tiempo promedio primera respuesta.
    """
    sb = db._sb()
    if sb is None:
        raise HTTPException(503, "Supabase no configurado")
    from zoneinfo import ZoneInfo
    TZ_BOG = ZoneInfo("America/Bogota")
    now_bog = datetime.now(tz=TZ_BOG)
    start_bog = now_bog.replace(hour=0, minute=0, second=0, microsecond=0)
    dt_desde = start_bog.astimezone(timezone.utc)

    # 1. Todos los mensajes desde midnight Bogotá hasta ahora.
    msgs = (sb.table("messages")
              .select("conversation_id,sender_type,sent_at")
              .gte("sent_at", dt_desde.isoformat())
              .limit(50000).execute().data) or []

    # Conteo bruto de mensajes ENTRANTES vs SALIENTES hoy
    # (no dedup por conv — son TODOS los msgs, para espejar Kommo).
    mensajes_entrantes = sum(1 for m in msgs if (m.get("sender_type") or "").lower() == "customer")
    mensajes_salientes = sum(1 for m in msgs if (m.get("sender_type") or "").lower() in ("advisor", "agent"))

    if not msgs:
        return {
            "ok": True,
            "fecha_bogota": now_bog.strftime("%Y-%m-%d"),
            "total": 0, "atendidas": 0, "pendientes": 0, "sin_asesora": 0,
            "avg_response_min": None, "max_response_min": None,
            "por_canal": {}, "por_canal_entrantes": {}, "por_canal_salientes": {},
            "por_asesora": [],
            "mensajes_entrantes_hoy": 0,
            "mensajes_salientes_hoy": 0,
            "total_mensajes_hoy": 0,
            "leads_hoy": {"ganados": 0, "perdidos": 0, "activos_nuevos": 0, "valor_ganado": 0, "valor_perdido": 0},
        }

    # 2. Agrupar mensajes por conversation_id.
    por_conv: dict = {}
    for m in msgs:
        cid = m.get("conversation_id")
        if not cid:
            continue
        row = por_conv.setdefault(cid, {"customer": 0, "advisor": 0, "first_customer_at": None, "first_advisor_at": None})
        st = (m.get("sender_type") or "").lower()
        sa = m.get("sent_at")
        if st == "customer":
            row["customer"] += 1
            if not row["first_customer_at"] or (sa and sa < row["first_customer_at"]):
                row["first_customer_at"] = sa
        elif st in ("advisor", "agent"):
            row["advisor"] += 1
            if not row["first_advisor_at"] or (sa and sa < row["first_advisor_at"]):
                row["first_advisor_at"] = sa

    # 3. Hidratar conversaciones únicas con metadata.
    conv_ids = list(por_conv.keys())
    convs_meta: dict = {}
    for i in range(0, len(conv_ids), 100):
        batch = conv_ids[i:i+100]
        try:
            cs = (sb.table("conversations")
                    .select("conversation_id,lead_id,advisor_id,channel")
                    .in_("conversation_id", batch)
                    .execute().data) or []
            for c in cs:
                convs_meta[c["conversation_id"]] = c
        except Exception:
            continue

    # 4. Lookup de nombres de asesoras.
    advisor_ids = list({c.get("advisor_id") for c in convs_meta.values() if c.get("advisor_id")})
    advisor_names: dict = {}
    if advisor_ids:
        try:
            ad = (sb.table("advisors").select("advisor_id,name")
                    .in_("advisor_id", advisor_ids).limit(50).execute().data) or []
            advisor_names = {a["advisor_id"]: a.get("name") for a in ad}
        except Exception:
            pass

    # 5. Dedup por lead_id (un lead puede tener varios convs hoy = 1 cliente real).
    por_lead: dict = {}
    for cid, counts in por_conv.items():
        meta = convs_meta.get(cid, {})
        lead_id = meta.get("lead_id") or cid
        existing = por_lead.get(lead_id)
        if existing:
            existing["customer"] += counts["customer"]
            existing["advisor"]  += counts["advisor"]
            if counts["first_customer_at"] and (not existing["first_customer_at"] or counts["first_customer_at"] < existing["first_customer_at"]):
                existing["first_customer_at"] = counts["first_customer_at"]
            if counts["first_advisor_at"] and (not existing["first_advisor_at"] or counts["first_advisor_at"] < existing["first_advisor_at"]):
                existing["first_advisor_at"] = counts["first_advisor_at"]
        else:
            por_lead[lead_id] = {
                "customer": counts["customer"],
                "advisor":  counts["advisor"],
                "first_customer_at": counts["first_customer_at"],
                "first_advisor_at":  counts["first_advisor_at"],
                "channel":  (meta.get("channel") or "unknown").lower(),
                "advisor_id": meta.get("advisor_id"),
            }

    # 6. Métricas finales.
    total = len(por_lead)
    atendidas = sum(1 for r in por_lead.values() if r["advisor"] > 0)
    pendientes = total - atendidas
    sin_asesora = sum(1 for r in por_lead.values() if not r.get("advisor_id"))

    por_canal: dict = {}
    for r in por_lead.values():
        ch = r["channel"]
        if "waba" in ch or "whatsapp" in ch or ch == "wa":
            cn = "WhatsApp"
        elif "instagram" in ch or ch == "ig" or ch == "dm":
            cn = "Instagram"
        elif "messenger" in ch or "facebook" in ch or ch == "fb":
            cn = "Messenger"
        elif "tiktok" in ch or ch == "tt":
            cn = "TikTok"
        else:
            cn = ch.capitalize() or "Otro"
        por_canal[cn] = por_canal.get(cn, 0) + 1

    # Tiempo primera respuesta = first_advisor_at - first_customer_at (si ambos existen).
    response_times: list = []
    for r in por_lead.values():
        fc = r.get("first_customer_at")
        fa = r.get("first_advisor_at")
        if fc and fa and fa > fc:
            try:
                tc = datetime.fromisoformat(fc.replace("Z", "+00:00"))
                ta = datetime.fromisoformat(fa.replace("Z", "+00:00"))
                response_times.append((ta - tc).total_seconds() / 60.0)
            except Exception:
                pass
    avg_response_min = round(sum(response_times) / len(response_times), 1) if response_times else None
    max_response_min = round(max(response_times), 1) if response_times else None

    # Mensajes por canal — separado en entrantes vs salientes (espejo Kommo).
    por_canal_entrantes: dict = {}
    por_canal_salientes: dict = {}
    for m in msgs:
        cid = m.get("conversation_id")
        meta = convs_meta.get(cid, {})
        ch = (meta.get("channel") or "unknown").lower()
        if "waba" in ch or "whatsapp" in ch or ch == "wa":
            cn = "WhatsApp"
        elif "instagram" in ch or ch == "ig" or ch == "dm":
            cn = "Instagram"
        elif "messenger" in ch or "facebook" in ch or ch == "fb":
            cn = "Messenger"
        elif "tiktok" in ch or ch == "tt":
            cn = "TikTok"
        else:
            cn = ch.capitalize() or "Otro"
        st = (m.get("sender_type") or "").lower()
        if st == "customer":
            por_canal_entrantes[cn] = por_canal_entrantes.get(cn, 0) + 1
        elif st in ("advisor", "agent"):
            por_canal_salientes[cn] = por_canal_salientes.get(cn, 0) + 1

    # Leads sin tareas pendientes (estado abierto y no hay task pendiente).
    # APROXIMACIÓN EFICIENTE: en vez de cargar 48k+ lead_ids en RAM (que
    # causaba OOM de 3.2GB en Railway), usamos COUNTs separados:
    #   leads_sin_tareas ≈ count(leads open) - count(distinct task.entity_id)
    # Es aproximación porque algunas tasks pueden ser de leads ya cerrados,
    # pero para el KPI del briefing es 99% exacto y NO carga listas en RAM.
    leads_sin_tareas: int | None = None
    try:
        open_q = sb.table("kommo_leads").select("lead_id", count="exact", head=True).eq("status", "open").execute()
        total_open = open_q.count or 0
        tasks_q = sb.table("kommo_tasks").select("entity_id", count="exact", head=True).eq("is_completed", False).execute()
        with_task_count = tasks_q.count or 0
        # Algunas tasks pueden estar duplicadas por lead, así que esto da
        # un upper bound del "con tarea". El resultado es conservador (≥ real).
        leads_sin_tareas = max(0, total_open - with_task_count)
    except Exception:
        leads_sin_tareas = None

    # Leads del día (cerrados hoy o creados hoy en Kommo).
    leads_hoy = {"ganados": 0, "perdidos": 0, "activos_nuevos": 0, "valor_ganado": 0, "valor_perdido": 0}
    try:
        lq = (sb.table("kommo_leads")
                .select("lead_id,status,lead_value,closed_at,created_at")
                .or_(f"closed_at.gte.{dt_desde.isoformat()},created_at.gte.{dt_desde.isoformat()}")
                .limit(2000)
                .execute().data) or []
        vg = 0.0
        vp = 0.0
        for l in lq:
            st_lead = (l.get("status") or "").lower()
            val = float(l.get("lead_value") or 0)
            closed = l.get("closed_at") or ""
            created = l.get("created_at") or ""
            cerrado_hoy = closed and closed >= dt_desde.isoformat()
            creado_hoy = created and created >= dt_desde.isoformat()
            if cerrado_hoy:
                if st_lead == "won":
                    leads_hoy["ganados"] += 1
                    vg += val
                elif st_lead == "lost":
                    leads_hoy["perdidos"] += 1
                    vp += val
            if creado_hoy and st_lead not in ("won", "lost"):
                leads_hoy["activos_nuevos"] += 1
        leads_hoy["valor_ganado"]  = int(vg)
        leads_hoy["valor_perdido"] = int(vp)
    except Exception:
        pass

    # Por asesora.
    por_asesora_dict: dict = {}
    for r in por_lead.values():
        aid = r.get("advisor_id")
        if not aid:
            continue
        row = por_asesora_dict.setdefault(aid, {
            "advisor_id": aid,
            "name": advisor_names.get(aid) or "—",
            "asignadas": 0, "atendidas": 0, "pendientes": 0,
        })
        row["asignadas"] += 1
        if r["advisor"] > 0:
            row["atendidas"] += 1
        else:
            row["pendientes"] += 1
    por_asesora = sorted(por_asesora_dict.values(), key=lambda r: r["pendientes"], reverse=True)

    return {
        "ok": True,
        "fecha_bogota": now_bog.strftime("%Y-%m-%d"),
        # Conversaciones únicas (leads únicos con actividad hoy)
        "total": total,
        "atendidas": atendidas,
        "pendientes": pendientes,
        "sin_asesora": sin_asesora,
        "avg_response_min": avg_response_min,
        "max_response_min": max_response_min,
        # Canales — Kommo distingue in/out, replicamos eso
        "por_canal": por_canal,                         # dedup por lead (legacy)
        "por_canal_entrantes": por_canal_entrantes,     # NEW: mensajes recibidos
        "por_canal_salientes": por_canal_salientes,     # NEW: mensajes enviados
        # Mensajes totales del día (no dedup, espejo de Kommo)
        "mensajes_entrantes_hoy": mensajes_entrantes,
        "mensajes_salientes_hoy": mensajes_salientes,
        "total_mensajes_hoy": len(msgs),
        # Leads del día (cerrados hoy en Kommo)
        "leads_hoy": leads_hoy,
        "leads_sin_tareas": leads_sin_tareas,
        # Equipo
        "por_asesora": por_asesora,
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


@router.post("/transcribe-audios")
def transcribe_audios(
    limit: int = Query(20, ge=1, le=200),
    _: CurrentUser = Depends(require_role("admin")),
) -> dict:
    """Transcribe audios WhatsApp pendientes con OpenAI Whisper.
    Necesita OPENAI_API_KEY + META_SYSTEM_USER_TOKEN en Railway env.
    """
    from backend.services import transcription as _tx
    return _tx.process_pending(limit=limit)


@router.post("/dedupe-conversations")
def dedupe_conversations(
    dry_run: bool = Query(True, description="True = solo reporta. False = ejecuta merge."),
    _: CurrentUser = Depends(require_role("admin")),
) -> dict:
    """Consolida conversations duplicadas para un mismo lead_id.

    Regla de merge: para cada lead_id con >1 conversation, se queda con UNA
    (preferencia: talk-* más reciente > meta-* más reciente). Los mensajes
    de las otras se reasignan a la canónica y luego se borran las duplicadas.

    Por default es dry_run=True (solo reporta). Pasa dry_run=false para ejecutar.
    """
    sb = db._sb()
    if sb is None:
        raise HTTPException(503, "Supabase no configurado")

    # 1. Conversations agrupadas por lead_id (sólo las que tienen lead_id).
    page = 0
    per_page = 1000
    todas: list[dict] = []
    while True:
        q = (sb.table("conversations")
               .select("conversation_id,lead_id,last_message_at")
               .not_.is_("lead_id", "null")
               .order("last_message_at", desc=True)
               .range(page * per_page, page * per_page + per_page - 1))
        rows = _safe_exec(q, retries=2, default=[])
        if not rows:
            break
        todas.extend(rows)
        if len(rows) < per_page:
            break
        page += 1
        if page > 50:  # safety cap 50k convs
            break

    por_lead: dict = {}
    for c in todas:
        por_lead.setdefault(c["lead_id"], []).append(c)

    grupos_duplicados = {lid: convs for lid, convs in por_lead.items() if len(convs) > 1}

    def _prio(conv: dict) -> tuple:
        """Mayor = mejor. Prefiere talk-* > meta-* > otros y más reciente."""
        cid = conv["conversation_id"] or ""
        kind = 2 if cid.startswith("talk-") else (1 if cid.startswith("meta-") else 0)
        return (kind, conv.get("last_message_at") or "")

    n_leads_afectados = len(grupos_duplicados)
    n_convs_a_borrar = sum(len(g) - 1 for g in grupos_duplicados.values())
    samples = []
    for lid, convs in list(grupos_duplicados.items())[:5]:
        ordenadas = sorted(convs, key=_prio, reverse=True)
        samples.append({
            "lead_id": lid,
            "canónica": ordenadas[0]["conversation_id"],
            "duplicadas": [c["conversation_id"] for c in ordenadas[1:]],
        })

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "leads_con_duplicados": n_leads_afectados,
            "conversations_a_borrar": n_convs_a_borrar,
            "ejemplos": samples,
            "siguiente": "Re-ejecuta con dry_run=false para aplicar.",
        }

    # 2. Ejecutar merge.
    n_msgs_reasignados = 0
    n_convs_borradas = 0
    errores: list[str] = []
    for lid, convs in grupos_duplicados.items():
        ordenadas = sorted(convs, key=_prio, reverse=True)
        canon = ordenadas[0]["conversation_id"]
        dupes = [c["conversation_id"] for c in ordenadas[1:]]
        try:
            # Reasignar mensajes de las dupes a la canónica.
            for dupe in dupes:
                try:
                    upd = (sb.table("messages")
                             .update({"conversation_id": canon})
                             .eq("conversation_id", dupe)
                             .execute())
                    n_msgs_reasignados += len(upd.data or [])
                except Exception as e:
                    errores.append(f"msgs {dupe}: {str(e)[:120]}")
            # Borrar las conversations duplicadas.
            for dupe in dupes:
                try:
                    sb.table("conversations").delete().eq("conversation_id", dupe).execute()
                    n_convs_borradas += 1
                except Exception as e:
                    errores.append(f"del {dupe}: {str(e)[:120]}")
        except Exception as e:
            errores.append(f"lead {lid}: {str(e)[:120]}")

    return {
        "ok": True,
        "dry_run": False,
        "leads_consolidados":       n_leads_afectados,
        "conversations_borradas":   n_convs_borradas,
        "mensajes_reasignados":     n_msgs_reasignados,
        "errores":                  errores[:10],
    }


@router.post("/sync/tasks")
def sync_tasks_endpoint(
    full: bool = Query(False),
    limit: int = Query(10000, ge=1, le=50000),
    _: CurrentUser = Depends(require_role("admin")),
) -> dict:
    """Sync de tasks Kommo → tabla kommo_tasks.
    Habilita el KPI 'Leads sin tareas' del briefing.
    """
    return kommo_svc.sync_tasks(full=full, limit_total=limit)


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


# ── Diagnóstico de calidad de datos ───────────────────────────────────────────
@router.get("/diagnostico/data-quality")
def diagnostico_data_quality(
    days_back: int = Query(8, ge=1, le=90),
    _: CurrentUser = Depends(require_role("admin")),
) -> dict:
    """
    Auditoría rápida de la calidad de los datos que estamos sirviendo en /revenue.

    Reporta:
      - Audits últimos N días: total, distribución según Haiku vs según Kommo
      - Mismatches Haiku/Kommo (qué tanto se equivoca el modelo)
      - Conversaciones vigentes vs huérfanas (sin lead_id)
      - Distribución de leads por status en el período
      - Ejemplos concretos para inspección manual
    """
    sb = db._sb()
    if sb is None:
        raise HTTPException(503, "Supabase no configurado")

    from zoneinfo import ZoneInfo
    TZ_BOG = ZoneInfo("America/Bogota")
    now_bog = datetime.now(tz=TZ_BOG)
    start_bog = now_bog.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_back - 1)
    desde_iso = start_bog.astimezone(timezone.utc).isoformat()

    # ── 1. Audits del período (limit acotado + retry seguro) ─────────────
    try:
        audits_q = (sb.table("chat_audits")
                      .select("conversation_id,lead_id,advisor_id,result_classification,economic_impact_estimate,audit_date")
                      .gte("audit_date", desde_iso)
                      .order("audit_date", desc=True)
                      .limit(300))
        audits = _safe_exec(audits_q, retries=2, default=[])
    except Exception as e:
        log.warning(f"diagnostico audits fail: {e}")
        audits = []

    lead_ids_audits = list({a.get("lead_id") for a in audits if a.get("lead_id")})
    leads_map: dict = {}
    if lead_ids_audits:
        for i in range(0, len(lead_ids_audits), 80):
            batch = lead_ids_audits[i:i+80]
            try:
                ld_q = (sb.table("kommo_leads")
                          .select("lead_id,status,customer_name,customer_phone,lead_value")
                          .in_("lead_id", batch)
                          .limit(120))
                for l in _safe_exec(ld_q, retries=1, default=[]):
                    leads_map[l["lead_id"]] = l
            except Exception:
                pass

    def _kommo_class(a: dict) -> str:
        lead = leads_map.get(a.get("lead_id")) or {}
        kst = (lead.get("status") or "").lower()
        if kst == "won":
            return "venta_lograda"
        if kst == "lost":
            return "venta_perdida"
        return "en_proceso"

    haiku_counts = {"venta_lograda": 0, "venta_perdida": 0, "inconclusa": 0, "otro": 0}
    kommo_counts = {"venta_lograda": 0, "venta_perdida": 0, "en_proceso": 0}
    mismatches: dict = {
        "haiku_perdida_kommo_ganada": [],
        "haiku_ganada_kommo_perdida": [],
        "haiku_terminal_kommo_abierto": [],
        "sin_lead_id_en_audit": [],
    }
    for a in audits:
        haiku = a.get("result_classification") or "otro"
        haiku_counts[haiku] = haiku_counts.get(haiku, 0) + 1
        if not a.get("lead_id"):
            mismatches["sin_lead_id_en_audit"].append({
                "conversation_id": a.get("conversation_id"),
                "haiku": haiku,
                "audit_date": a.get("audit_date"),
            })
            continue
        kommo = _kommo_class(a)
        kommo_counts[kommo] = kommo_counts.get(kommo, 0) + 1
        lead = leads_map.get(a["lead_id"]) or {}
        ejemplo = {
            "conversation_id": a.get("conversation_id"),
            "lead_id":         a.get("lead_id"),
            "cliente":         lead.get("customer_name") or lead.get("customer_phone"),
            "lead_value":      lead.get("lead_value"),
            "haiku":           haiku,
            "kommo_status":    lead.get("status"),
            "audit_date":      a.get("audit_date"),
        }
        if haiku == "venta_perdida" and kommo == "venta_lograda":
            mismatches["haiku_perdida_kommo_ganada"].append(ejemplo)
        elif haiku == "venta_lograda" and kommo == "venta_perdida":
            mismatches["haiku_ganada_kommo_perdida"].append(ejemplo)
        elif haiku in ("venta_lograda", "venta_perdida") and kommo == "en_proceso":
            mismatches["haiku_terminal_kommo_abierto"].append(ejemplo)

    # ── 2. Conversaciones del período ─────────────────────────────────────
    try:
        convs_q = (sb.table("conversations")
                     .select("conversation_id,lead_id,advisor_id,last_message_at,status")
                     .gte("last_message_at", desde_iso)
                     .order("last_message_at", desc=True)
                     .limit(800))
        convs = _safe_exec(convs_q, retries=2, default=[])
    except Exception as e:
        log.warning(f"diagnostico convs fail: {e}")
        convs = []
    n_convs = len(convs)
    n_con_lead = sum(1 for c in convs if c.get("lead_id"))
    n_sin_lead = n_convs - n_con_lead
    n_sin_advisor = sum(1 for c in convs if not c.get("advisor_id"))
    ejemplos_huerfanas = [
        {
            "conversation_id": c["conversation_id"],
            "last_message_at": c.get("last_message_at"),
            "channel_inferido": (c["conversation_id"].split("-")[0] if c.get("conversation_id") else None),
        }
        for c in convs if not c.get("lead_id")
    ][:10]

    # ── 3. Leads del período por status (con desglose de valor) ──────────
    # Pedimos también pipeline_id + status_id para detectar si el sync está
    # mapeando bien los estados.
    try:
        leads_q = (sb.table("kommo_leads")
                     .select("lead_id,status,status_id,pipeline_id,lead_value,closed_at,updated_at")
                     .gte("updated_at", desde_iso)
                     .order("updated_at", desc=True)
                     .limit(800))
        leads_periodo = _safe_exec(leads_q, retries=2, default=[])
    except Exception as e:
        log.warning(f"diagnostico leads fail: {e}")
        leads_periodo = []

    status_dist: dict = {}
    pipeline_dist: dict = {}
    valor_won = 0.0
    valor_lost = 0.0
    n_won_con_valor = 0
    n_won_sin_valor = 0
    n_lost_con_valor = 0
    n_lost_sin_valor = 0
    for l in leads_periodo:
        st = (l.get("status") or "unknown").lower()
        status_dist[st] = status_dist.get(st, 0) + 1
        pid = l.get("pipeline_id")
        if pid:
            pipeline_dist[pid] = pipeline_dist.get(pid, 0) + 1
        val = float(l.get("lead_value") or 0)
        has_val = val > 0
        if st == "won":
            valor_won += val
            if has_val: n_won_con_valor += 1
            else:       n_won_sin_valor += 1
        elif st == "lost":
            valor_lost += val
            if has_val: n_lost_con_valor += 1
            else:       n_lost_sin_valor += 1

    # ── 3.5. Valor según economic_impact_estimate del audit (más confiable
    # que lead_value, que muchas veces no se llena en Kommo) ──────────────
    val_audit_won = 0.0
    val_audit_lost = 0.0
    val_audit_inconclusas = 0.0
    for a in audits:
        impact = float(a.get("economic_impact_estimate") or 0)
        if impact <= 0:
            continue
        lead = leads_map.get(a.get("lead_id")) or {}
        kst = (lead.get("status") or "").lower()
        if kst == "won":
            val_audit_won += impact
        elif kst == "lost":
            val_audit_lost += impact
        else:
            val_audit_inconclusas += impact

    # ── 3.6. Cobertura de auditoría ───────────────────────────────────────
    # Cuántas conversaciones del período tienen audit_status pendiente
    try:
        n_pending_q = (sb.table("conversations")
                         .select("conversation_id", count="exact")
                         .gte("last_message_at", desde_iso)
                         .eq("audit_status", "pending")
                         .limit(1))
        n_pending_res = n_pending_q.execute()
        n_audit_pending = n_pending_res.count or 0
    except Exception:
        n_audit_pending = -1  # no se pudo calcular

    # ── 3.7. Valor según leads asociados a audits del período ────────────
    # Esto resuelve la incoherencia: los counters de "según leads_periodo"
    # filtran por updated_at (puede dar 0 si los cierres no actualizaron
    # updated_at), pero los audits SÍ tienen 24 leads asociados. Mostramos
    # ambos universos para que se vea la diferencia.
    val_audits_won = 0.0
    val_audits_lost = 0.0
    n_audits_won_con_val = 0
    n_audits_won_sin_val = 0
    n_audits_lost_con_val = 0
    n_audits_lost_sin_val = 0
    seen_leads = set()
    for a in audits:
        lid = a.get("lead_id")
        if not lid or lid in seen_leads:
            continue
        seen_leads.add(lid)
        lead = leads_map.get(lid) or {}
        kst = (lead.get("status") or "").lower()
        val = float(lead.get("lead_value") or 0)
        has_val = val > 0
        if kst == "won":
            val_audits_won += val
            if has_val: n_audits_won_con_val += 1
            else:       n_audits_won_sin_val += 1
        elif kst == "lost":
            val_audits_lost += val
            if has_val: n_audits_lost_con_val += 1
            else:       n_audits_lost_sin_val += 1

    # ── 4.5. CONVERSACIONES DEL DÍA — briefing matutino en TZ Bogotá ─────
    # Definimos "conversación del día" como: lead único que tuvo al menos
    # un mensaje (de cliente o asesora) entre 00:00 y ahora en Bogotá.
    hoy_bog_start = now_bog.replace(hour=0, minute=0, second=0, microsecond=0)
    hoy_iso = hoy_bog_start.astimezone(timezone.utc).isoformat()

    # Estrategia: consultar messages.sent_at >= midnight_bog (más confiable que
    # conversations.last_message_at que solo se actualiza vía webhook Meta).
    # Después hidratamos las conversaciones únicas con metadata.
    convs_hoy: list[dict] = []
    msgs_hoy_por_conv: dict = {}  # conv_id -> {customer:n, advisor:n}
    try:
        msgs_hoy_q = (sb.table("messages")
                        .select("conversation_id,sender_type,sent_at")
                        .gte("sent_at", hoy_iso)
                        .order("sent_at", desc=True)
                        .limit(3000))
        msgs_hoy = _safe_exec(msgs_hoy_q, retries=2, default=[])
        for m in msgs_hoy:
            cid = m.get("conversation_id")
            if not cid:
                continue
            row = msgs_hoy_por_conv.setdefault(cid, {"customer": 0, "advisor": 0, "first_at": None})
            stype = (m.get("sender_type") or "").lower()
            if stype == "customer":
                row["customer"] += 1
            elif stype in ("advisor", "agent"):
                row["advisor"] += 1
            row["first_at"] = m.get("sent_at")  # last in order=desc → más viejo

        # Hidratar conversaciones únicas
        conv_ids_hoy = list(msgs_hoy_por_conv.keys())
        if conv_ids_hoy:
            for i in range(0, len(conv_ids_hoy), 80):
                batch = conv_ids_hoy[i:i+80]
                cs_q = (sb.table("conversations")
                          .select("conversation_id,lead_id,advisor_id,channel,last_message_at,status,avg_response_min")
                          .in_("conversation_id", batch))
                cs = _safe_exec(cs_q, retries=2, default=[])
                for c in cs:
                    cid = c["conversation_id"]
                    mc = msgs_hoy_por_conv.get(cid, {})
                    c["msgs_customer"] = mc.get("customer", 0)
                    c["msgs_advisor"]  = mc.get("advisor", 0)
                    convs_hoy.append(c)
    except Exception as e:
        log.warning(f"conversaciones_del_dia query fail: {e}")

    # Dedup por lead_id (un lead puede tener varios canales = 1 conversación
    # operativa). Si no hay lead_id, dedup por conversation_id.
    convs_hoy_dedup: dict = {}
    for c in convs_hoy:
        key = c.get("lead_id") or c.get("conversation_id")
        if key and key not in convs_hoy_dedup:
            convs_hoy_dedup[key] = c
    convs_hoy_list = list(convs_hoy_dedup.values())

    # Métricas del día
    total_hoy = len(convs_hoy_list)
    canal_hoy: dict = {}
    atendidas_hoy = 0
    pendientes_hoy = 0
    sin_asesora_hoy = 0
    response_times: list = []
    por_asesora_hoy: dict = {}
    advisor_ids_hoy = list({c.get("advisor_id") for c in convs_hoy_list if c.get("advisor_id")})
    advisor_names: dict = {}
    if advisor_ids_hoy:
        try:
            adv_data = (sb.table("advisors").select("advisor_id,name")
                          .in_("advisor_id", advisor_ids_hoy).limit(50).execute().data) or []
            advisor_names = {a["advisor_id"]: a.get("name") for a in adv_data}
        except Exception:
            pass

    for c in convs_hoy_list:
        ch = (c.get("channel") or "unknown").lower()
        # Normalizar canal
        if "waba" in ch or "whatsapp" in ch or ch == "wa":
            ch_norm = "WhatsApp"
        elif "instagram" in ch or ch == "ig" or ch == "dm":
            ch_norm = "Instagram"
        elif "messenger" in ch or "facebook" in ch or ch == "fb":
            ch_norm = "Messenger"
        elif "tiktok" in ch or ch == "tt":
            ch_norm = "TikTok"
        else:
            ch_norm = ch.capitalize() or "Otro"
        canal_hoy[ch_norm] = canal_hoy.get(ch_norm, 0) + 1

        adv_id = c.get("advisor_id")
        msgs_a = int(c.get("msgs_advisor") or 0)
        if not adv_id:
            sin_asesora_hoy += 1
        if msgs_a > 0:
            atendidas_hoy += 1
        else:
            pendientes_hoy += 1
        rt = c.get("avg_response_min")
        if rt is not None and float(rt) > 0:
            response_times.append(float(rt))

        if adv_id:
            row = por_asesora_hoy.setdefault(adv_id, {
                "name": advisor_names.get(adv_id) or "—",
                "asignadas": 0,
                "atendidas": 0,
                "pendientes": 0,
            })
            row["asignadas"] += 1
            if msgs_a > 0:
                row["atendidas"] += 1
            else:
                row["pendientes"] += 1

    avg_response_min = round(sum(response_times) / len(response_times), 1) if response_times else None
    por_asesora_lista = sorted(
        por_asesora_hoy.values(), key=lambda r: r["pendientes"], reverse=True,
    )

    # ── 4. Conversaciones por edad (vigencia) ─────────────────────────────
    now_utc = datetime.now(tz=timezone.utc)
    rangos = {"0-24h": 0, "24-48h": 0, "48-72h": 0, "3-7d": 0, "mas_de_7d": 0}
    for c in convs:
        lm = c.get("last_message_at")
        if not lm:
            continue
        try:
            t = datetime.fromisoformat(lm.replace("Z", "+00:00"))
            hours = (now_utc - t).total_seconds() / 3600
            if hours < 24:
                rangos["0-24h"] += 1
            elif hours < 48:
                rangos["24-48h"] += 1
            elif hours < 72:
                rangos["48-72h"] += 1
            elif hours < 168:
                rangos["3-7d"] += 1
            else:
                rangos["mas_de_7d"] += 1
        except Exception:
            pass

    return {
        "ok": True,
        "ventana_dias": days_back,
        "desde": desde_iso,
        "hasta": now_utc.isoformat(),
        "audits": {
            "total": len(audits),
            "haiku_dice": haiku_counts,
            "kommo_dice": kommo_counts,
            "mismatches_count": {k: len(v) for k, v in mismatches.items()},
            "mismatches_ejemplos": {k: v[:5] for k, v in mismatches.items()},
        },
        "conversations": {
            "total": n_convs,
            "con_lead_id": n_con_lead,
            "sin_lead_id_huerfanas": n_sin_lead,
            "sin_advisor_asignada": n_sin_advisor,
            "ejemplos_huerfanas": ejemplos_huerfanas,
            "edad_distribucion": rangos,
        },
        "leads_periodo": {
            "total": len(leads_periodo),
            "distribucion_status": status_dist,
            "distribucion_pipeline": pipeline_dist,
            "valor_total_ganadas_cop": int(valor_won),
            "valor_total_perdidas_cop": int(valor_lost),
            "won_con_valor": n_won_con_valor,
            "won_sin_valor": n_won_sin_valor,
            "lost_con_valor": n_lost_con_valor,
            "lost_sin_valor": n_lost_sin_valor,
        },
        "valor_segun_audit": {
            "ganadas_cop": int(val_audit_won),
            "perdidas_cop": int(val_audit_lost),
            "inconclusas_cop": int(val_audit_inconclusas),
            "nota": "Suma de economic_impact_estimate de Haiku, agrupado por status real de Kommo. Más confiable que lead_value cuando los operadores no llenan el valor en Kommo.",
        },
        "leads_de_audits": {
            "total_leads_unicos": len(seen_leads),
            "valor_won_cop": int(val_audits_won),
            "valor_lost_cop": int(val_audits_lost),
            "won_con_valor": n_audits_won_con_val,
            "won_sin_valor": n_audits_won_sin_val,
            "lost_con_valor": n_audits_lost_con_val,
            "lost_sin_valor": n_audits_lost_sin_val,
            "nota": "Leads ASOCIADOS A AUDITS del período (sin filtrar updated_at). Resuelve el caso donde Kommo no actualizó updated_at en el cierre.",
        },
        "cobertura_audit": {
            "conversaciones_periodo": n_convs,
            "audits_periodo": len(audits),
            "audits_pendientes": n_audit_pending,
            "pct_cobertura": round(100 * len(audits) / n_convs, 1) if n_convs > 0 else 0,
        },
        "conversaciones_del_dia": {
            "fecha_bogota": now_bog.strftime("%Y-%m-%d"),
            "total": total_hoy,
            "por_canal": canal_hoy,
            "atendidas": atendidas_hoy,
            "pendientes": pendientes_hoy,
            "sin_asesora": sin_asesora_hoy,
            "avg_response_min": avg_response_min,
            "por_asesora": por_asesora_lista,
        },
    }
