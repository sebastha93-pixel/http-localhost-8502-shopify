"""
backend.services.revenue_db — CRUD para las 7 tablas de Revenue Intelligence.

Capa fina sobre Supabase para que los servicios de sync/auditoría no
hablen SQL directamente.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

from supabase import create_client, Client


log = logging.getLogger(__name__)

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
    except Exception as e:
        log.warning(f"revenue_db: no conectó Supabase: {e}")
        return None


# ── advisors ──────────────────────────────────────────────────────────────────
def upsert_advisor(kommo_user_id: int, name: str, email: str = "",
                    active: bool = True) -> Optional[dict]:
    sb = _sb()
    if sb is None:
        return None
    try:
        r = sb.table("advisors").upsert({
            "kommo_user_id": kommo_user_id,
            "name":          name,
            "email":         (email or "").strip() or None,
            "active":        active,
        }, on_conflict="kommo_user_id").execute()
        return r.data[0] if r.data else None
    except Exception as e:
        log.warning(f"upsert_advisor {kommo_user_id}: {e}")
        return None


def advisor_uuid_por_kommo(kommo_user_id: int) -> Optional[str]:
    """Devuelve advisor_id (uuid) dado un kommo_user_id."""
    sb = _sb()
    if sb is None or not kommo_user_id:
        return None
    try:
        r = sb.table("advisors").select("advisor_id").eq("kommo_user_id", kommo_user_id).limit(1).execute()
        return r.data[0]["advisor_id"] if r.data else None
    except Exception:
        return None


# ── kommo_leads ───────────────────────────────────────────────────────────────
def upsert_lead(lead: dict) -> bool:
    """
    `lead` es el dict que entrega kommo_client.listar_leads (estructura Kommo
    cruda). Lo mapeamos al schema de la tabla.
    """
    sb = _sb()
    if sb is None:
        return False
    try:
        responsible_id = lead.get("responsible_user_id")
        advisor_id = advisor_uuid_por_kommo(responsible_id) if responsible_id else None

        # Customer info viene en _embedded.contacts si pediste with=contacts
        contact = ((lead.get("_embedded") or {}).get("contacts") or [{}])[0] if lead.get("_embedded") else {}
        cust_name = contact.get("name") or ""

        # loss_reason
        lr_list = ((lead.get("_embedded") or {}).get("loss_reason") or [])
        loss_reason = lr_list[0].get("name") if lr_list else None

        # tags
        tags = ((lead.get("_embedded") or {}).get("tags") or [])
        tag_names = [t.get("name") for t in tags if t.get("name")]

        # closed_at: cuando el lead fue cerrado (status 142 = ganado, 143 = perdido)
        closed_at_ts = lead.get("closed_at")

        data = {
            "lead_id":              int(lead["id"]),
            "pipeline_id":          lead.get("pipeline_id"),
            "stage_id":             lead.get("status_id"),
            "status":               _map_status(lead.get("status_id")),
            "responsible_user_id":  responsible_id,
            "advisor_id":           advisor_id,
            "created_at":           _epoch_to_iso(lead.get("created_at")),
            "closed_at":            _epoch_to_iso(closed_at_ts) if closed_at_ts else None,
            "lead_value":           float(lead.get("price") or 0),
            "loss_reason":          loss_reason,
            "tags":                 tag_names,
            "customer_phone":       _phone_from_contact(contact),
            "customer_name":        cust_name,
            "raw":                  lead,
            "synced_at":            datetime.now(timezone.utc).isoformat(),
        }
        sb.table("kommo_leads").upsert(data, on_conflict="lead_id").execute()
        return True
    except Exception as e:
        log.warning(f"upsert_lead {lead.get('id')}: {e}")
        return False


def _map_status(status_id: Any) -> str:
    """Stages especiales de Kommo: 142=ganado, 143=perdido. Resto=open."""
    try:
        sid = int(status_id or 0)
    except Exception:
        return "open"
    if sid == 142:  return "won"
    if sid == 143:  return "lost"
    return "open"


def _epoch_to_iso(ts: Any) -> Optional[str]:
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
    except Exception:
        return None


def _phone_from_contact(contact: dict) -> Optional[str]:
    """Extrae el teléfono del contacto desde sus custom_fields_values."""
    cfv = contact.get("custom_fields_values") or []
    for f in cfv:
        if str(f.get("field_code") or "").upper() == "PHONE":
            vals = f.get("values") or []
            if vals:
                return str(vals[0].get("value") or "").strip() or None
    return None


# ── conversations ─────────────────────────────────────────────────────────────
def upsert_conversation(conv: dict) -> bool:
    sb = _sb()
    if sb is None:
        return False
    try:
        sb.table("conversations").upsert(conv, on_conflict="conversation_id").execute()
        return True
    except Exception as e:
        log.warning(f"upsert_conversation {conv.get('conversation_id')}: {e}")
        return False


# ── messages ──────────────────────────────────────────────────────────────────
def upsert_messages_batch(messages: list[dict]) -> int:
    """Inserta mensajes en batch. Retorna cuántos quedaron upserted."""
    sb = _sb()
    if sb is None or not messages:
        return 0
    try:
        r = sb.table("messages").upsert(messages, on_conflict="message_id").execute()
        return len(r.data) if r.data else len(messages)
    except Exception as e:
        log.warning(f"upsert_messages_batch ({len(messages)}): {e}")
        return 0


# ── chat_audits ───────────────────────────────────────────────────────────────
def insertar_audit(audit: dict) -> Optional[str]:
    """Inserta un análisis IA. Retorna audit_id si OK."""
    sb = _sb()
    if sb is None:
        return None
    try:
        r = sb.table("chat_audits").insert(audit).execute()
        return r.data[0]["audit_id"] if r.data else None
    except Exception as e:
        log.warning(f"insertar_audit: {e}")
        return None


# ── revenue_sync_state ────────────────────────────────────────────────────────
def leer_sync_state(key: str) -> Optional[str]:
    sb = _sb()
    if sb is None:
        return None
    try:
        r = sb.table("revenue_sync_state").select("value").eq("key", key).limit(1).execute()
        return r.data[0]["value"] if r.data else None
    except Exception:
        return None


def guardar_sync_state(key: str, value: str) -> None:
    sb = _sb()
    if sb is None:
        return
    try:
        sb.table("revenue_sync_state").upsert({
            "key":         key,
            "value":       value,
            "updated_at":  datetime.now(timezone.utc).isoformat(),
        }, on_conflict="key").execute()
    except Exception as e:
        log.warning(f"guardar_sync_state {key}: {e}")


# ── Stats / queries para el dashboard ─────────────────────────────────────────
def stats_revenue() -> dict:
    """KPIs del módulo: cuántos leads, conversations, audits, etc."""
    sb = _sb()
    if sb is None:
        return {"ok": False, "error": "Supabase no configurado"}
    try:
        return {
            "ok":             True,
            "advisors":       _count(sb, "advisors"),
            "leads":          _count(sb, "kommo_leads"),
            "conversations":  _count(sb, "conversations"),
            "messages":       _count(sb, "messages"),
            "audits":         _count(sb, "chat_audits"),
            "pending_audits": _count(sb, "conversations", {"audit_status": "pending"}),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def _count(sb: Client, tabla: str, filtros: Optional[dict] = None) -> int:
    q = sb.table(tabla).select("*", count="exact", head=True)
    if filtros:
        for k, v in filtros.items():
            q = q.eq(k, v)
    r = q.execute()
    return r.count or 0
