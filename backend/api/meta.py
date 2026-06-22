"""
backend.api.meta — Webhook unificado de Meta (WhatsApp + Messenger + Instagram).

Una sola App de Meta cubre los 3 canales. Meta envía todos los eventos al
mismo endpoint, distinguiendo por el campo `object`:
  - "whatsapp_business_account" → WhatsApp Cloud API
  - "page"                      → Facebook Messenger
  - "instagram"                 → Instagram DMs

A diferencia del webhook de Kommo (que solo nos entrega INCOMING), Meta nos
da INCOMING y OUTGOING — exactamente lo que nos faltaba para auditar
respuestas de las asesoras.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from backend.core.security import CurrentUser, require_role
from backend.services import revenue_db as db


log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/meta", tags=["meta"])

_stats: dict = {
    "total":             0,
    "whatsapp_events":   0,
    "messenger_events":  0,
    "instagram_events":  0,
    "otros":             0,
    "mensajes_guardados": 0,
    "errores":           0,
    "ultimo_error":      None,
    "primero_en":        None,
    "ultimo_en":         None,
    "ultimos_payloads":  [],
}


def _verify_token() -> str:
    return os.environ.get("META_WEBHOOK_VERIFY_TOKEN", "").strip()


def _app_secret() -> str:
    return os.environ.get("META_APP_SECRET", "").strip()


def _system_token() -> str:
    return os.environ.get("META_SYSTEM_USER_TOKEN", "").strip()


def _verify_signature(body: bytes, header_signature: str) -> bool:
    """Verifica que el webhook venga firmado por Meta usando META_APP_SECRET.
    Header: X-Hub-Signature-256: sha256=HEX"""
    secret = _app_secret()
    if not secret or not header_signature:
        return False
    if not header_signature.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    received = header_signature[7:]
    return hmac.compare_digest(expected, received)


# ─────────────────────────────────────────────────────────────────────────────
# Webhook: GET (verificación) + POST (eventos)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/webhook")
def webhook_verify(
    hub_mode: str = Query(default="", alias="hub.mode"),
    hub_verify_token: str = Query(default="", alias="hub.verify_token"),
    hub_challenge: str = Query(default="", alias="hub.challenge"),
):
    """Verificación inicial del webhook por Meta.
    Meta hace GET con hub.mode=subscribe&hub.verify_token=X&hub.challenge=Y
    Si verify_token coincide, devolvemos el challenge en plaintext."""
    if hub_mode != "subscribe":
        raise HTTPException(400, "hub.mode debe ser 'subscribe'")
    if hub_verify_token != _verify_token() or not _verify_token():
        raise HTTPException(403, "verify_token incorrecto")
    # Devolver el challenge EXACTO como int o string (Meta espera plain text)
    return int(hub_challenge) if hub_challenge.isdigit() else hub_challenge


@router.post("/webhook")
async def webhook_receive(request: Request) -> dict:
    """Receptor de eventos de Meta. PÚBLICO (Meta no autentica con Bearer).
    Valida firma X-Hub-Signature-256 con META_APP_SECRET."""
    body = await request.body()
    sig = request.headers.get("x-hub-signature-256") or ""
    now_iso = datetime.now(tz=timezone.utc).isoformat()

    _stats["total"] += 1
    if _stats["primero_en"] is None:
        _stats["primero_en"] = now_iso
    _stats["ultimo_en"] = now_iso

    # Validar firma (solo si tenemos APP_SECRET configurado)
    if _app_secret() and not _verify_signature(body, sig):
        _stats["errores"] += 1
        _stats["ultimo_error"] = "firma_invalida"
        # Responder 200 igual para que Meta no desactive el webhook,
        # pero log el evento como sospechoso
        log.warning("Meta webhook: firma inválida")
        return {"ok": True, "warning": "signature_invalid"}

    try:
        payload = await request.json()
    except Exception as e:
        _stats["errores"] += 1
        _stats["ultimo_error"] = f"json_parse: {str(e)[:200]}"
        return {"ok": True}

    obj = payload.get("object") or ""
    if obj == "whatsapp_business_account":
        _stats["whatsapp_events"] += 1
        result = _procesar_whatsapp(payload)
    elif obj == "page":
        _stats["messenger_events"] += 1
        result = _procesar_messenger(payload)
    elif obj == "instagram":
        _stats["instagram_events"] += 1
        result = _procesar_instagram(payload)
    else:
        _stats["otros"] += 1
        result = {"skip": "objeto_desconocido", "obj": obj}

    _stats["mensajes_guardados"] += int(result.get("messages_saved", 0) or 0)

    # Guardar preview del último payload (debug)
    keys = list(payload.keys())[:5]
    preview = {"object": obj, "entry_count": len(payload.get("entry", []) or [])}
    _stats["ultimos_payloads"].insert(0, {"ts": now_iso, "obj": obj, "result": result, "preview": preview})
    _stats["ultimos_payloads"] = _stats["ultimos_payloads"][:10]

    return {"ok": True, **result}


# ─────────────────────────────────────────────────────────────────────────────
# Parsers por canal
# ─────────────────────────────────────────────────────────────────────────────

def _procesar_whatsapp(payload: dict) -> dict:
    """Parsea evento de WhatsApp Cloud API.
    Estructura: payload.entry[].changes[].value.messages[] (incoming)
                                       .value.statuses[] (delivery/read)
    """
    sb = db._sb()
    if sb is None:
        return {"error": "supabase_no_configurado"}
    msgs_saved = 0
    for entry in (payload.get("entry") or []):
        for change in (entry.get("changes") or []):
            value = change.get("value") or {}
            messaging_product = value.get("messaging_product")
            if messaging_product != "whatsapp":
                continue
            phone_number_id = (value.get("metadata") or {}).get("phone_number_id")
            display_phone = (value.get("metadata") or {}).get("display_phone_number")
            # Contactos para enriquecer nombre
            contacts_map: dict = {}
            for c in (value.get("contacts") or []):
                wa_id = c.get("wa_id")
                if wa_id:
                    contacts_map[wa_id] = (c.get("profile") or {}).get("name") or ""

            # Mensajes (incoming SIEMPRE; outgoing solo si configuramos echo en la App)
            for m in (value.get("messages") or []):
                wa_id_from = m.get("from")  # número del cliente
                msg_id = m.get("id")
                msg_type = m.get("type") or "text"
                ts = m.get("timestamp")
                sent_at = _epoch_to_iso(ts)
                text = (m.get("text") or {}).get("body") or ""
                if not text:
                    text = _placeholder_for_type(msg_type)
                sender_name = contacts_map.get(wa_id_from) or wa_id_from or ""
                row = _build_message_row(
                    message_id=f"meta-wa-{msg_id}",
                    conversation_id=_conv_id_for_whatsapp(wa_id_from, phone_number_id),
                    sender_type="customer",
                    sender_name=sender_name,
                    message_text=text,
                    sent_at=sent_at,
                    payload={
                        "channel": "whatsapp",
                        "wa_id": wa_id_from,
                        "phone_number_id": phone_number_id,
                        "display_phone_number": display_phone,
                        "type": msg_type,
                        "raw": m,
                    },
                )
                if _upsert_message(sb, row):
                    msgs_saved += 1

            # Statuses (sent/delivered/read) — son los eventos para OUTGOING
            # Meta los envía con el id del mensaje saliente. Si NO lo teníamos
            # registrado lo creamos como outgoing-stub.
            for s in (value.get("statuses") or []):
                wa_id_to = s.get("recipient_id")
                msg_id = s.get("id")
                status_type = s.get("status")  # sent | delivered | read | failed
                ts = s.get("timestamp")
                sent_at = _epoch_to_iso(ts)
                # Solo creamos el mensaje cuando llega status=sent (el primero).
                # Status posteriores (delivered/read) son updates de estado.
                if status_type != "sent":
                    continue
                row = _build_message_row(
                    message_id=f"meta-wa-{msg_id}",
                    conversation_id=_conv_id_for_whatsapp(wa_id_to, phone_number_id),
                    sender_type="advisor",
                    sender_name="",  # Meta no nos dice qué asesora envió; se resuelve después por advisor del lead
                    message_text="",  # Meta solo nos da el ID. Texto no viene en statuses.
                    sent_at=sent_at,
                    payload={
                        "channel": "whatsapp",
                        "wa_id": wa_id_to,
                        "phone_number_id": phone_number_id,
                        "display_phone_number": display_phone,
                        "status": status_type,
                        "raw": s,
                    },
                )
                if _upsert_message(sb, row):
                    msgs_saved += 1

    return {"messages_saved": msgs_saved}


def _procesar_messenger(payload: dict) -> dict:
    """Facebook Messenger: payload.entry[].messaging[]"""
    sb = db._sb()
    if sb is None:
        return {"error": "supabase_no_configurado"}
    msgs_saved = 0
    for entry in (payload.get("entry") or []):
        page_id = entry.get("id")
        for ev in (entry.get("messaging") or []):
            sender_id = (ev.get("sender") or {}).get("id")
            recipient_id = (ev.get("recipient") or {}).get("id")
            ts = ev.get("timestamp")
            sent_at = _epoch_to_iso(int(ts / 1000) if ts and ts > 9_999_999_999 else ts)
            msg = ev.get("message") or {}
            if not msg:
                continue
            msg_id = msg.get("mid")
            text = msg.get("text") or ""
            is_echo = bool(msg.get("is_echo"))
            attachments = msg.get("attachments") or []
            if not text:
                if attachments:
                    att_type = (attachments[0] or {}).get("type", "")
                    text = _placeholder_for_type(att_type)
                else:
                    text = "[sin contenido]"
            # is_echo=True significa que fue enviado por la Page → asesora
            sender_type = "advisor" if is_echo else "customer"
            # El "otro lado" (cliente) es el recipient si es echo, sender si no
            user_id = recipient_id if is_echo else sender_id
            row = _build_message_row(
                message_id=f"meta-fb-{msg_id}",
                conversation_id=_conv_id_for_messenger(user_id, page_id),
                sender_type=sender_type,
                sender_name=user_id or "",
                message_text=text,
                sent_at=sent_at,
                payload={
                    "channel": "facebook",
                    "page_id": page_id,
                    "user_id": user_id,
                    "is_echo": is_echo,
                    "raw": ev,
                },
            )
            if _upsert_message(sb, row):
                msgs_saved += 1
    return {"messages_saved": msgs_saved}


def _procesar_instagram(payload: dict) -> dict:
    """Instagram DMs: estructura igual a Messenger (payload.entry[].messaging[])
    pero con object='instagram'."""
    sb = db._sb()
    if sb is None:
        return {"error": "supabase_no_configurado"}
    msgs_saved = 0
    for entry in (payload.get("entry") or []):
        ig_account_id = entry.get("id")
        for ev in (entry.get("messaging") or []):
            sender_id = (ev.get("sender") or {}).get("id")
            recipient_id = (ev.get("recipient") or {}).get("id")
            ts = ev.get("timestamp")
            sent_at = _epoch_to_iso(int(ts / 1000) if ts and ts > 9_999_999_999 else ts)
            msg = ev.get("message") or {}
            if not msg:
                continue
            msg_id = msg.get("mid")
            text = msg.get("text") or ""
            is_echo = bool(msg.get("is_echo"))
            attachments = msg.get("attachments") or []
            if not text:
                if attachments:
                    att_type = (attachments[0] or {}).get("type", "")
                    text = _placeholder_for_type(att_type)
                else:
                    text = "[sin contenido]"
            sender_type = "advisor" if is_echo else "customer"
            user_id = recipient_id if is_echo else sender_id
            row = _build_message_row(
                message_id=f"meta-ig-{msg_id}",
                conversation_id=_conv_id_for_instagram(user_id, ig_account_id),
                sender_type=sender_type,
                sender_name=user_id or "",
                message_text=text,
                sent_at=sent_at,
                payload={
                    "channel": "instagram",
                    "ig_account_id": ig_account_id,
                    "user_id": user_id,
                    "is_echo": is_echo,
                    "raw": ev,
                },
            )
            if _upsert_message(sb, row):
                msgs_saved += 1
    return {"messages_saved": msgs_saved}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _epoch_to_iso(ts) -> str:
    if not ts:
        return datetime.now(tz=timezone.utc).isoformat()
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
    except Exception:
        return datetime.now(tz=timezone.utc).isoformat()


def _placeholder_for_type(t: str) -> str:
    t = (t or "").lower()
    return {
        "audio":    "🎤 [audio]",
        "voice":    "🎤 [audio]",
        "image":    "🖼️ [imagen]",
        "picture":  "🖼️ [imagen]",
        "video":    "🎬 [video]",
        "file":     "📎 [archivo]",
        "document": "📄 [documento]",
        "sticker":  "🟣 [sticker]",
        "location": "📍 [ubicación]",
        "contacts": "👤 [contacto]",
        "template": "📋 [plantilla]",
        "interactive": "🔘 [interactivo]",
    }.get(t, f"[{t or 'sin texto'}]")


def _normalizar_phone(phone: str) -> str:
    """Normaliza un número: solo dígitos, sin + ni espacios."""
    return "".join(c for c in (phone or "") if c.isdigit())


_cross_ref_cache: dict = {}  # wa_id → (ts, resultado o None)
_CROSS_REF_TTL = 300  # 5 min


def _buscar_lead_kommo_por_phone(wa_id: str) -> Optional[dict]:
    """Busca un lead de Kommo que tenga customer_phone matching el wa_id.
    wa_id de Meta viene tipo '573103021444' (sin + ni espacios).
    Cachea resultado 5 min para no consultar Supabase por cada mensaje.
    Retorna {lead_id, advisor_id, customer_name, conversation_id_existente}
    o None si no hay match."""
    import time as _t
    sb = db._sb()
    if sb is None or not wa_id:
        return None
    wa_norm = _normalizar_phone(wa_id)
    if not wa_norm:
        return None
    # Cache check
    hit = _cross_ref_cache.get(wa_norm)
    if hit and (_t.time() - hit[0]) < _CROSS_REF_TTL:
        return hit[1]
    # Estrategias: probar varias variantes del número
    variants = {wa_norm}
    if wa_norm.startswith("57"):
        variants.add(wa_norm[2:])  # sin código país
    variants.add(f"+{wa_norm}")
    variants.add(f"+57{wa_norm[2:]}" if wa_norm.startswith("57") else f"+{wa_norm}")
    import time as _t
    result: Optional[dict] = None
    try:
        # 1. Match exacto por variantes comunes
        for v in variants:
            r = sb.table("kommo_leads").select("lead_id,advisor_id,customer_name,customer_phone").eq("customer_phone", v).limit(1).execute()
            if r.data:
                lead = r.data[0]
                cr = sb.table("conversations").select("conversation_id").eq("lead_id", lead["lead_id"]).like("conversation_id", "talk-%").order("last_message_at", desc=True).limit(1).execute()
                result = {
                    "lead_id":                 lead["lead_id"],
                    "advisor_id":              lead.get("advisor_id"),
                    "customer_name":           lead.get("customer_name"),
                    "conversation_id_existente": cr.data[0]["conversation_id"] if cr.data else None,
                }
                break

        # 2. Match por dígitos finales si el exacto no funcionó (los últimos 10
        # dígitos cubren el número sin código país). Necesario porque Kommo
        # guarda phones con espacios/guiones/formatos inconsistentes.
        if not result and len(wa_norm) >= 7:
            ultimos = wa_norm[-10:] if len(wa_norm) >= 10 else wa_norm
            # Buscar leads cuyo customer_phone CONTENGA esos dígitos
            r = sb.table("kommo_leads").select("lead_id,advisor_id,customer_name,customer_phone").like("customer_phone", f"%{ultimos}%").limit(5).execute()
            for lead in (r.data or []):
                # Verificar normalizando: que coincidan los últimos N dígitos
                lead_phone_norm = _normalizar_phone(lead.get("customer_phone") or "")
                if lead_phone_norm and lead_phone_norm[-10:] == ultimos:
                    cr = sb.table("conversations").select("conversation_id").eq("lead_id", lead["lead_id"]).like("conversation_id", "talk-%").order("last_message_at", desc=True).limit(1).execute()
                    result = {
                        "lead_id":                 lead["lead_id"],
                        "advisor_id":              lead.get("advisor_id"),
                        "customer_name":           lead.get("customer_name"),
                        "conversation_id_existente": cr.data[0]["conversation_id"] if cr.data else None,
     except Exception:
        result = None
    
    # FASE C1: Si NO encontramos en DB local, preguntar a Kommo API en vivo.
    # Esto resuelve el caso típico: lead recién creado en Kommo (vía sales bot o
    # contacto WhatsApp Business) que aún no se ha sincronizado a nuestra DB.
    if not result:
        try:
            import sys
            from pathlib import Path
            _SRC = Path(__file__).resolve().parent.parent.parent / "src"
            if str(_SRC) not in sys.path:
                sys.path.insert(0, str(_SRC))
            import kommo_client as kc
            # Probar variantes en Kommo (con y sin código país)
            for q in (wa_norm, wa_norm[2:] if wa_norm.startswith("57") else wa_norm):
                leads_kommo = kc.buscar_leads_por_phone(q, limit=3)
                if not leads_kommo:
                    continue
                # Tomar el lead más reciente (Kommo los devuelve ordenados desc)
                lead_kommo = leads_kommo[0]
                lead_id_int = lead_kommo.get("id")
                if not lead_id_int:
                    continue
                # Upsert el lead a nuestra DB para futuras búsquedas
                try:
                    db.upsert_lead(lead_kommo)
                except Exception:
                    pass
                # Releer del DB para obtener advisor_id resuelto
                try:
                    r = sb.table("kommo_leads").select(
                        "lead_id,advisor_id,customer_name,customer_phone"
                    ).eq("lead_id", int(lead_id_int)).limit(1).execute()
                    if r.data:
                        lead = r.data[0]
                        result = {
                            "lead_id":                  lead["lead_id"],
                            "advisor_id":               lead.get("advisor_id"),
                            "customer_name":            lead.get("customer_name"),
                            "conversation_id_existente": None,
                        }
                        break
                except Exception:
                    pass
        except Exception:
            pass
    
    # Cache (incluso si es None, para no re-consultar leads que no matchean)
    _cross_ref_cache[wa_norm] = (_t.time(), result)


def _conv_id_for_whatsapp(wa_id: str, phone_number_id: str) -> str:
    """ID de conversation para WhatsApp. Si el wa_id matchea un lead en Kommo
    con conversation existente (talk-*), USA ESE — así Meta y Kommo unifican
    en la misma conversación. Sino crea uno nuevo meta-wa-*."""
    match = _buscar_lead_kommo_por_phone(wa_id)
    if match and match.get("conversation_id_existente"):
        return match["conversation_id_existente"]
    return f"meta-wa-{wa_id or 'unknown'}-{phone_number_id or 'na'}"


def _conv_id_for_messenger(user_id: str, page_id: str) -> str:
    return f"meta-fb-{user_id or 'unknown'}-{page_id or 'na'}"


def _conv_id_for_instagram(user_id: str, ig_account_id: str) -> str:
    return f"meta-ig-{user_id or 'unknown'}-{ig_account_id or 'na'}"


_columnas_problematicas: set = set()


def _build_message_row(*, message_id, conversation_id, sender_type, sender_name,
                       message_text, sent_at, payload) -> dict:
    row = {
        "message_id":      message_id,
        "conversation_id": conversation_id,
        "sender_type":     sender_type,
        "sender_name":     (sender_name or "")[:80],
        "message_text":    (message_text or "")[:5000],
        "sent_at":         sent_at,
        "topic":           "text",
        "payload":         payload,
    }
    return {k: v for k, v in row.items() if v is not None}


def _asegurar_conversation(sb, conversation_id: str, payload: dict) -> None:
    """Asegura que conversation_id exista en conversations (FK requirement).
    Si no existe, la crea con metadata. Si es WhatsApp con wa_id, busca lead
    en Kommo y enriquece con lead_id/advisor_id."""
    if not conversation_id:
        return
    try:
        r = sb.table("conversations").select("conversation_id").eq("conversation_id", conversation_id).limit(1).execute()
        if r.data:
            return  # Ya existe (no la sobrescribimos para no perder metadata Kommo)
    except Exception:
        return

    channel = (payload or {}).get("channel") or "unknown"
    row: dict = {
        "conversation_id":  conversation_id,
        "channel":          channel,
        "started_at":       datetime.now(tz=timezone.utc).isoformat(),
        "last_message_at":  datetime.now(tz=timezone.utc).isoformat(),
        "status":           "in_work",
        "audit_status":     "pending",
        "synced_at":        datetime.now(tz=timezone.utc).isoformat(),
    }
    # Cross-reference con Kommo: si el conv_id es meta-wa-* extraer wa_id y buscar lead
    if channel == "whatsapp" and conversation_id.startswith("meta-wa-"):
        wa_id = (payload or {}).get("wa_id") or ""
        if wa_id:
            match = _buscar_lead_kommo_por_phone(wa_id)
            if match:
                row["lead_id"] = match.get("lead_id")
                row["advisor_id"] = match.get("advisor_id")
    try:
        sb.table("conversations").upsert(row, on_conflict="conversation_id").execute()
    except Exception as e:
        _stats["errores"] += 1
        _stats["ultimo_error"] = f"conv: {str(e)[:200]}"


def _upsert_message(sb, row: dict) -> bool:
    """Upsert con auto-recuperación de PGRST204 (cache PostgREST stale) +
    asegura conversation existe para no romper FK."""
    # Asegurar conversation antes del insert
    _asegurar_conversation(sb, row.get("conversation_id") or "", row.get("payload") or {})
    # Quitar columnas conocidas como problemáticas
    for col in _columnas_problematicas:
        row.pop(col, None)
    for _ in range(5):
        try:
            sb.table("messages").upsert(row, on_conflict="message_id").execute()
            return True
        except Exception as e:
            err = str(e)
            if "PGRST204" in err or "schema cache" in err:
                import re as _re
                m = _re.search(r"'(\w+)' column", err)
                if m:
                    col = m.group(1)
                    _columnas_problematicas.add(col)
                    row.pop(col, None)
                    continue
            _stats["errores"] += 1
            _stats["ultimo_error"] = err[:200]
            return False
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints de debug y stats
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/webhook/stats")
def webhook_stats(_: CurrentUser = Depends(require_role("admin"))) -> dict:
    """Estadísticas del receiver Meta."""
    return {**_stats, "verify_token_configurado": bool(_verify_token()),
            "app_secret_configurado": bool(_app_secret()),
            "system_token_configurado": bool(_system_token())}


@router.get("/config/check")
def config_check(_: CurrentUser = Depends(require_role("admin"))) -> dict:
    """Verifica qué env vars de Meta están configuradas (sin exponer valores)."""
    return {
        "META_APP_ID":               bool(os.environ.get("META_APP_ID", "").strip()),
        "META_APP_SECRET":           bool(_app_secret()),
        "META_WEBHOOK_VERIFY_TOKEN": bool(_verify_token()),
        "META_SYSTEM_USER_TOKEN":    bool(_system_token()),
    }


@router.get("/discover")
def discover_assets(_: CurrentUser = Depends(require_role("admin"))) -> dict:
    """Descubre Pages e IG accounts via /me/accounts (funciona con System User Token).
    WABAs/phone_numbers requieren conocer el WABA_ID por env var (META_WABA_ID)."""
    import requests
    token = _system_token()
    if not token:
        raise HTTPException(503, "META_SYSTEM_USER_TOKEN no configurado")
    out: dict = {"pages": [], "instagram_accounts": [], "phone_numbers": [], "errors": []}

    # 1. Pages via /me/accounts (esto SÍ funciona con System User Token)
    try:
        r = requests.get("https://graph.facebook.com/v23.0/me/accounts",
                         params={"access_token": token, "fields": "id,name,access_token,instagram_business_account"},
                         timeout=20)
        if r.status_code == 200:
            for p in (r.json().get("data") or []):
                out["pages"].append({
                    "page_id":          p["id"],
                    "page_name":        p.get("name"),
                    "page_access_token": p.get("access_token"),
                })
                # 2. Instagram Business vinculado a la Page
                ig = p.get("instagram_business_account") or {}
                if ig.get("id"):
                    out["instagram_accounts"].append({
                        "ig_id":      ig["id"],
                        "page_id":    p["id"],
                        "page_name":  p.get("name"),
                    })
        else:
            out["errors"].append({"step": "/me/accounts", "status": r.status_code, "body": r.text[:300]})
    except Exception as e:
        out["errors"].append({"step": "/me/accounts", "error": str(e)[:200]})

    # 3. WABA: si está en env, descubrir phone_numbers
    waba_id = os.environ.get("META_WABA_ID", "").strip()
    if waba_id:
        try:
            r = requests.get(f"https://graph.facebook.com/v23.0/{waba_id}/phone_numbers",
                             params={"access_token": token}, timeout=20)
            if r.status_code == 200:
                for n in (r.json().get("data") or []):
                    out["phone_numbers"].append({
                        "waba_id":          waba_id,
                        "phone_number_id":  n["id"],
                        "display":          n.get("display_phone_number"),
                        "verified_name":    n.get("verified_name"),
                    })
            else:
                out["errors"].append({"step": f"/{waba_id}/phone_numbers", "status": r.status_code, "body": r.text[:300]})
        except Exception as e:
            out["errors"].append({"step": "phone_numbers", "error": str(e)[:200]})
    else:
        out["errors"].append({"step": "waba", "info": "META_WABA_ID no configurado en env vars"})

    return out


@router.post("/subscribe-numbers")
def subscribe_numbers(_: CurrentUser = Depends(require_role("admin"))) -> dict:
    """Suscribe la WABA completa al webhook (la API moderna lo hace a nivel
    WABA, no por phone_number)."""
    import requests
    token = _system_token()
    if not token:
        raise HTTPException(503, "META_SYSTEM_USER_TOKEN no configurado")
    waba_id = os.environ.get("META_WABA_ID", "").strip()
    if not waba_id:
        raise HTTPException(503, "META_WABA_ID no configurado")
    try:
        r = requests.post(f"https://graph.facebook.com/v23.0/{waba_id}/subscribed_apps",
                          params={"access_token": token}, timeout=20)
        ok = (r.status_code == 200) and (r.json().get("success") is True)
        return {"ok": True, "results": [{"level": "waba", "waba_id": waba_id, "status_code": r.status_code, "ok": ok, "response": r.text[:500]}]}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


@router.get("/debug/token")
def debug_token(_: CurrentUser = Depends(require_role("admin"))) -> dict:
    """Diagnostica qué puede ver el System User Token actual."""
    import requests
    token = _system_token()
    if not token:
        return {"error": "no_token"}
    out: dict = {}
    paths = [
        ("/me",                     "?fields=id,name"),
        ("/me/accounts",            "?fields=id,name,access_token"),
        ("/debug_token",            f"?input_token={token}"),
    ]
    for path, qs in paths:
        try:
            r = requests.get(f"https://graph.facebook.com/v23.0{path}{qs}",
                             params={"access_token": token}, timeout=15)
            out[path] = {"status": r.status_code, "body": r.text[:600]}
        except Exception as e:
            out[path] = {"error": str(e)[:200]}
    return out


@router.post("/purge-conversations-and-messages")
def purge_conversations_and_messages(
    confirm: str = Query(..., description="Debe ser 'YES_PURGE_ALL' para ejecutar"),
    _: CurrentUser = Depends(require_role("admin"))
) -> dict:
    """⚠️ PURGA messages + chat_audits + conversations.
    Mantiene: advisors, kommo_leads, kommo_oauth_tokens, revenue_sync_state."""
    if confirm != "YES_PURGE_ALL":
        raise HTTPException(400, "Confirm con ?confirm=YES_PURGE_ALL")
    sb = db._sb()
    if sb is None:
        raise HTTPException(503, "no_sb")
    results: dict = {}
    # Orden importa por FK: messages → audits → conversations
    deletes = [
        ("messages",       "message_id",      "__nunca__"),
        ("chat_audits",    "conversation_id", "__nunca__"),  # uuid no es la PK, usa otro filtro
        ("conversations",  "conversation_id", "__nunca__"),
    ]
    for table, col, val in deletes:
        try:
            r = sb.table(table).delete().neq(col, val).execute()
            results[table] = {"borrados": len(r.data) if r.data else "ok"}
        except Exception as e:
            results[table] = {"error": str(e)[:200]}
    _cross_ref_cache.clear()
    try:
        sb.table("revenue_sync_state").delete().eq("key", "kommo_talks_last_sync").execute()
        sb.table("revenue_sync_state").delete().eq("key", "kommo_talks_backfill_cursor").execute()
        results["sync_state_reset"] = "ok"
    except Exception:
        pass
    return {"ok": True, "results": results}


@router.post("/purge-kommo-data")
def purge_kommo_data(
    confirm: str = Query(..., description="Debe ser 'YES_PURGE_KOMMO' para ejecutar"),
    _: CurrentUser = Depends(require_role("admin"))
) -> dict:
    """⚠️ PURGA TOTAL: kommo_leads + clientes_clasificacion + advisor_rankings + sync_state.
    Después de esto, todo arranca cuando llega el primer mensaje Meta. Las
    asesoras (advisors) se mantienen para el ranking. OAuth tokens se mantienen
    para que la API siga funcionando."""
    if confirm != "YES_PURGE_KOMMO":
        raise HTTPException(400, "Confirm con ?confirm=YES_PURGE_KOMMO")
    sb = db._sb()
    if sb is None:
        raise HTTPException(503, "no_sb")
    results: dict = {}
    tables = [
        ("kommo_leads",            "lead_id"),
        ("clientes_clasificacion", "email"),
        ("advisor_rankings",       "advisor_id"),
    ]
    for table, col in tables:
        try:
            r = sb.table(table).delete().neq(col, "__nunca_existe__").execute()
            results[table] = {"borrados": len(r.data) if r.data else "ok"}
        except Exception as e:
            results[table] = {"error": str(e)[:200]}
    # Resetear TODOS los sync_state (no solo talks)
    try:
        sb.table("revenue_sync_state").delete().neq("key", "__nunca__").execute()
        results["sync_state"] = "fully_reset"
    except Exception as e:
        results["sync_state"] = {"error": str(e)[:200]}
    _cross_ref_cache.clear()
    return {
        "ok": True,
        "results": results,
        "next": "Todo arranca desde el primer mensaje Meta. Las asesoras se conservan. El cross-reference irá llenando kommo_leads on-demand cuando llegue tráfico Kommo (talk[update], leads[status])."
    }


@router.post("/cycle-enrichment")
def cycle_enrichment(
    max_iterations: int = Query(5, ge=1, le=20, description="Max ciclos antes de parar"),
    _: CurrentUser = Depends(require_role("admin"))
) -> dict:
    """Corre el ciclo completo de enrichment: sync leads → bulk customers → normalize → re-cross-ref.
    Repite hasta que no haya más cambios o llegue al límite. Útil para recuperar
    todos los clientes que aún están sin asociar."""
    import requests
    from backend.services import kommo as _kommo_svc
    sb = db._sb()
    if sb is None:
        raise HTTPException(503, "no_sb")

    log_steps: list = []
    convs_total_enriched = 0

    for iteration in range(max_iterations):
        step: dict = {"iteration": iteration + 1}

        # 1. Sync incremental leads
        try:
            res_sync = _kommo_svc.sync_leads(full=False, limit_total=2000)
            step["sync_leads"] = {"upserted": res_sync.get("upserted", 0)}
        except Exception as e:
            step["sync_leads"] = {"error": str(e)[:200]}

        # 2. Bulk enrich customers (lotes hasta 0 candidatos)
        try:
            import sys
            from pathlib import Path
            _SRC = Path(__file__).resolve().parent.parent.parent / "src"
            if str(_SRC) not in sys.path:
                sys.path.insert(0, str(_SRC))
            import kommo_client as kc
            total_enriquecidos = 0
            for _ in range(8):  # max 8 lotes de 500 = 4000 leads por iteración
                leads = (sb.table("kommo_leads").select("lead_id,customer_phone,raw")
                           .or_("customer_name.is.null,customer_name.eq.")
                           .limit(500).execute().data) or []
                contact_to_lead: dict = {}
                for ld in leads:
                    raw = ld.get("raw") or {}
                    contacts = ((raw.get("_embedded") or {}).get("contacts") or [])
                    if contacts:
                        cid = contacts[0].get("id")
                        if cid:
                            contact_to_lead[int(cid)] = ld["lead_id"]
                if not contact_to_lead:
                    break
                contactos = kc.listar_contactos_por_ids(list(contact_to_lead.keys()))
                for c in contactos:
                    try:
                        cid = int(c.get("id"))
                        lead_id = contact_to_lead.get(cid)
                        if not lead_id:
                            continue
                        name = c.get("name") or ""
                        phone = None
                        for cf in (c.get("custom_fields_values") or []):
                            if cf.get("field_code") == "PHONE":
                                vals = cf.get("values") or []
                                if vals:
                                    phone = vals[0].get("value")
                                break
                        updates = {}
                        if name: updates["customer_name"] = name
                        if phone: updates["customer_phone"] = _normalizar_phone(str(phone)) or str(phone)
                        if updates:
                            sb.table("kommo_leads").update(updates).eq("lead_id", lead_id).execute()
                            total_enriquecidos += 1
                    except Exception:
                        pass
            step["bulk_enrich_customers"] = total_enriquecidos
        except Exception as e:
            step["bulk_enrich_customers"] = {"error": str(e)[:200]}

        # 3. Normalizar phones que no estén normalizados
        total_normalizados = 0
        for _ in range(8):
            leads = (sb.table("kommo_leads").select("lead_id,customer_phone")
                       .not_.is_("customer_phone", "null")
                       .neq("customer_phone", "")
                       .limit(1000).execute().data) or []
            cnt = 0
            for ld in leads:
                orig = ld.get("customer_phone") or ""
                norm = _normalizar_phone(orig)
                if norm and norm != orig:
                    try:
                        sb.table("kommo_leads").update({"customer_phone": norm}).eq("lead_id", ld["lead_id"]).execute()
                        cnt += 1
                    except Exception:
                        pass
            total_normalizados += cnt
            if cnt == 0:
                break
        step["normalizados"] = total_normalizados

        # 4. Re-enrich conversations Meta (limpiar cache primero)
        _cross_ref_cache.clear()
        try:
            convs = (sb.table("conversations").select("conversation_id,lead_id,advisor_id")
                       .like("conversation_id", "meta-wa-%")
                       .is_("lead_id", "null")
                       .limit(2000).execute().data) or []
            enriquecidos = 0
            for c in convs:
                cid = c["conversation_id"]
                partes = cid.split("-")
                if len(partes) < 4:
                    continue
                wa_id = partes[2]
                match = _buscar_lead_kommo_por_phone(wa_id)
                if match and match.get("lead_id"):
                    update = {"lead_id": match["lead_id"]}
                    if match.get("advisor_id"):
                        update["advisor_id"] = match["advisor_id"]
                    try:
                        sb.table("conversations").update(update).eq("conversation_id", cid).execute()
                        enriquecidos += 1
                    except Exception:
                        pass
            step["meta_convs_candidatos"] = len(convs)
            step["meta_convs_enriquecidos"] = enriquecidos
            convs_total_enriched += enriquecidos
        except Exception as e:
            step["meta_re_enrich"] = {"error": str(e)[:200]}
            enriquecidos = 0

        log_steps.append(step)
        # Convergencia: si esta iteración no enriqueció nada nuevo, paramos
        if step.get("meta_convs_enriquecidos", 0) == 0 and step.get("bulk_enrich_customers", 0) == 0:
            break

    return {"ok": True, "convs_total_enriched": convs_total_enriched, "iteraciones": log_steps}


@router.post("/normalizar-phones-kommo")
def normalizar_phones_kommo(
    limit: int = Query(10000, ge=10, le=50000),
    _: CurrentUser = Depends(require_role("admin"))
) -> dict:
    """Normaliza el customer_phone de kommo_leads (quita espacios, guiones, +).
    Ej: '+57 300 4789094' → '573004789094'. Necesario para que el cross-reference
    con Meta wa_id funcione (Meta envía solo dígitos)."""
    sb = db._sb()
    if sb is None:
        raise HTTPException(503, "no_sb")
    leads = (sb.table("kommo_leads").select("lead_id,customer_phone")
               .not_.is_("customer_phone", "null")
               .neq("customer_phone", "")
               .limit(limit).execute().data) or []
    normalizados = 0
    sin_cambio = 0
    for ld in leads:
        original = ld.get("customer_phone") or ""
        normalizado = _normalizar_phone(original)
        if not normalizado:
            continue
        if normalizado == original:
            sin_cambio += 1
            continue
        try:
            sb.table("kommo_leads").update({"customer_phone": normalizado}).eq("lead_id", ld["lead_id"]).execute()
            normalizados += 1
        except Exception:
            pass
    return {"ok": True, "total": len(leads), "normalizados": normalizados, "sin_cambio": sin_cambio}


@router.get("/debug/cross-ref")
def debug_cross_ref(_: CurrentUser = Depends(require_role("admin"))) -> dict:
    """Diagnostica por qué el cross-reference no matchea."""
    sb = db._sb()
    if sb is None:
        raise HTTPException(503, "no_sb")
    out: dict = {"conversations_meta_sin_lead": [], "muestra_kommo_phones": []}

    # Tomar algunas conversations meta-wa-* sin lead
    convs = (sb.table("conversations").select("conversation_id,lead_id")
               .like("conversation_id", "meta-wa-%")
               .is_("lead_id", "null")
               .limit(5).execute().data) or []
    for c in convs:
        cid = c["conversation_id"]
        partes = cid.split("-")
        wa_id = partes[2] if len(partes) >= 3 else "?"
        wa_norm = _normalizar_phone(wa_id)
        ultimos = wa_norm[-10:] if len(wa_norm) >= 10 else wa_norm
        # Buscar matches potenciales
        r = sb.table("kommo_leads").select("lead_id,customer_phone,customer_name").like("customer_phone", f"%{ultimos}%").limit(3).execute()
        out["conversations_meta_sin_lead"].append({
            "conversation_id": cid,
            "wa_id_extraido": wa_id,
            "wa_norm": wa_norm,
            "ultimos_10": ultimos,
            "kommo_matches_por_like": [{"lead_id": l["lead_id"], "customer_phone": l.get("customer_phone"), "customer_name": l.get("customer_name")} for l in (r.data or [])]
        })

    # Muestra de phones que sí están en kommo_leads
    sample = (sb.table("kommo_leads").select("customer_phone,customer_name")
                .not_.is_("customer_phone", "null")
                .neq("customer_phone", "")
                .limit(10).execute().data) or []
    out["muestra_kommo_phones"] = [{"phone": l.get("customer_phone"), "name": l.get("customer_name")} for l in sample]

    return out


@router.post("/enrich-conversations")
def enrich_conversations(
    limit: int = Query(500, ge=10, le=5000),
    _: CurrentUser = Depends(require_role("admin"))
) -> dict:
    """Toma conversations meta-wa-* sin lead_id y las cruza con kommo_leads
    para asignar lead_id, advisor_id. Útil para re-enriquecer las conversations
    que ya se crearon antes de que el matching fuera robusto."""
    sb = db._sb()
    if sb is None:
        raise HTTPException(503, "Supabase no configurado")
    # Buscar conversations meta-wa-* sin lead_id
    convs = (sb.table("conversations").select("conversation_id,lead_id,advisor_id")
               .like("conversation_id", "meta-wa-%")
               .is_("lead_id", "null")
               .limit(limit).execute().data) or []
    if not convs:
        return {"ok": True, "candidatos": 0, "enriquecidos": 0}
    enriquecidos = 0
    sin_match = 0
    for c in convs:
        cid = c["conversation_id"]
        # Extraer wa_id del conversation_id: meta-wa-{wa_id}-{phone_id}
        partes = cid.split("-")
        if len(partes) < 4:
            continue
        wa_id = partes[2]
        match = _buscar_lead_kommo_por_phone(wa_id)
        if match and match.get("lead_id"):
            try:
                update = {"lead_id": match["lead_id"]}
                if match.get("advisor_id"):
                    update["advisor_id"] = match["advisor_id"]
                sb.table("conversations").update(update).eq("conversation_id", cid).execute()
                enriquecidos += 1
            except Exception:
                pass
        else:
            sin_match += 1
    return {"ok": True, "candidatos": len(convs), "enriquecidos": enriquecidos, "sin_match": sin_match}


@router.post("/subscribe-waba")
def subscribe_waba(
    waba_id: str = Query(..., description="WABA ID a suscribir al webhook"),
    _: CurrentUser = Depends(require_role("admin"))
) -> dict:
    """Suscribe una WABA específica al webhook de la App.
    Útil cuando tienes múltiples WABAs (los 3 números de MALE DENIM viven en 2 WABAs distintas)."""
    import requests
    token = _system_token()
    if not token:
        raise HTTPException(503, "META_SYSTEM_USER_TOKEN no configurado")
    try:
        r = requests.post(f"https://graph.facebook.com/v23.0/{waba_id}/subscribed_apps",
                          params={"access_token": token}, timeout=20)
        ok = (r.status_code == 200) and (r.json().get("success") is True)
        return {"waba_id": waba_id, "status_code": r.status_code, "ok": ok, "body": r.text[:500]}
    except Exception as e:
        return {"waba_id": waba_id, "ok": False, "error": str(e)[:300]}


@router.post("/subscribe-by-id")
def subscribe_by_id(
    phone_number_id: str = Query(..., description="Phone number ID de Meta (no el número telefónico)"),
    _: CurrentUser = Depends(require_role("admin"))
) -> dict:
    """Suscribe un phone_number_id específico al webhook de la App.
    Útil si discover automático no funciona — pasa el ID manualmente."""
    import requests
    token = _system_token()
    if not token:
        raise HTTPException(503, "META_SYSTEM_USER_TOKEN no configurado")
    try:
        r = requests.post(f"https://graph.facebook.com/v23.0/{phone_number_id}/subscribed_apps",
                          params={"access_token": token}, timeout=20)
        return {"phone_number_id": phone_number_id, "status_code": r.status_code, "body": r.text[:500]}
    except Exception as e:
        return {"error": str(e)[:300]}


@router.post("/subscribe-pages")
def subscribe_pages(_: CurrentUser = Depends(require_role("admin"))) -> dict:
    """Suscribe la App a webhooks de cada Page usando page_access_token específico
    (Meta requiere ese token para suscribir Pages, no el System User Token)."""
    import requests
    discovery = discover_assets()
    results: list = []
    for p in discovery.get("pages", []):
        pid = p["page_id"]
        page_token = p.get("page_access_token")
        if not page_token:
            results.append({"page_id": pid, "name": p.get("page_name"), "ok": False, "error": "sin page_access_token"})
            continue
        try:
            r = requests.post(f"https://graph.facebook.com/v23.0/{pid}/subscribed_apps",
                              params={"access_token": page_token,
                                      "subscribed_fields": "messages,messaging_postbacks,message_deliveries,message_reads"},
                              timeout=20)
            ok = (r.status_code == 200) and (r.json().get("success") is True)
            results.append({"page_id": pid, "name": p.get("page_name"), "status_code": r.status_code, "ok": ok, "response": r.text[:300]})
        except Exception as e:
            results.append({"page_id": pid, "ok": False, "error": str(e)[:200]})
    return {"ok": True, "results": results}
