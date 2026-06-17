"""
backend.services.kommo — Sincronización Kommo CRM → DB Supabase.

Orquesta:
  1. Sync usuarios (asesoras) — corre al inicio, refresca diario
  2. Sync leads (incremental, por updated_at)
  3. Sync notes (mensajes) por cada lead actualizado
  4. Construcción de conversations a partir de las notes

NO analiza con IA — eso es trabajo de ia_auditor.py (próxima fase).
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# Importar el cliente low-level desde src/
_SRC = Path(__file__).resolve().parent.parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from backend.services import revenue_db as db


log = logging.getLogger(__name__)


# ── Health check ─────────────────────────────────────────────────────────────
def verificar_conexion() -> dict:
    """Wrapper sobre kommo_client.verificar_conexion para el endpoint /health."""
    import kommo_client as kc
    try:
        return kc.verificar_conexion()
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


# ── Sync de asesoras ──────────────────────────────────────────────────────────
def sync_advisors() -> dict:
    """
    Trae todos los usuarios de Kommo y los upserta como advisors.
    Idempotente.
    """
    import kommo_client as kc
    try:
        users = kc.listar_usuarios()
    except RuntimeError as e:
        return {"ok": False, "error": str(e), "total": 0}

    procesados = 0
    activos = 0
    for u in users:
        rights = u.get("rights") or {}
        activo = not rights.get("is_free") and rights.get("is_active") is not False
        name = u.get("name") or "—"
        email = u.get("email") or ""
        db.upsert_advisor(int(u["id"]), name, email, active=activo)
        procesados += 1
        if activo:
            activos += 1
    return {"ok": True, "total": procesados, "activos": activos}


# ── Sync de leads ─────────────────────────────────────────────────────────────
def sync_leads(full: bool = False, limit_total: int = 5000) -> dict:
    """
    Sync incremental de leads. Por defecto solo trae los modificados
    desde el último sync. Con full=True trae todos (max limit_total).

    Almacena en kommo_leads. NO sincroniza mensajes — eso lo hace
    sync_messages_de_lead en un paso aparte.
    """
    import kommo_client as kc

    # Calcular desde cuándo traer
    desde_ts: Optional[int] = None
    if not full:
        last = db.leer_sync_state("kommo_leads_last_sync")
        if last:
            try:
                desde_ts = int(last)
            except Exception:
                pass

    nuevo_corte_ts = int(datetime.now(tz=timezone.utc).timestamp())

    procesados = 0
    nuevos = 0
    try:
        for lead in kc.listar_leads(updated_after_ts=desde_ts, limit_total=limit_total):
            ok = db.upsert_lead(lead)
            procesados += 1
            if ok:
                nuevos += 1
    except RuntimeError as e:
        return {"ok": False, "error": str(e), "procesados": 0}
    except Exception as e:
        log.exception("sync_leads error")
        return {"ok": False, "error": str(e)[:300], "procesados": procesados}

    # Solo avanzar el cursor si todo OK
    if procesados > 0 or desde_ts is None:
        db.guardar_sync_state("kommo_leads_last_sync", str(nuevo_corte_ts))

    return {
        "ok":          True,
        "procesados":  procesados,
        "upserted":    nuevos,
        "desde_ts":    desde_ts,
        "hasta_ts":    nuevo_corte_ts,
        "modo":        "full" if full else "incremental",
    }


# ── Sync de mensajes de un lead específico ────────────────────────────────────
# Kommo expone los mensajes de WhatsApp como notes con note_type específicos.
# Tipos conocidos:
#   25 = amochat_message (mensaje incoming/outgoing)
#   26 = amochat_attachment
#   4  = message_cashier (no nos sirve)
# Y otros sistémicos. Filtramos solo los relevantes.

_NOTE_TYPES_MENSAJE = {25, 26, "amochat_message", "amochat_attachment"}


def sync_messages_de_lead(lead_id: int) -> dict:
    """
    Trae todas las notes (mensajes) del lead y las inserta en messages.
    Construye/actualiza la fila correspondiente en conversations.

    Idempotente: se basa en el message_id de Kommo (note.id).
    """
    import kommo_client as kc

    notes = list(kc.listar_notes_de_lead(lead_id))
    if not notes:
        return {"ok": True, "lead_id": lead_id, "mensajes": 0, "razon": "sin notes"}

    # Filtrar solo notes que son mensajes de chat
    msgs_raw = []
    for n in notes:
        nt = n.get("note_type")
        if nt in _NOTE_TYPES_MENSAJE or str(nt) in _NOTE_TYPES_MENSAJE:
            msgs_raw.append(n)

    if not msgs_raw:
        return {"ok": True, "lead_id": lead_id, "mensajes": 0, "razon": "ninguna note es mensaje"}

    # Ordenar por created_at ascendente
    msgs_raw.sort(key=lambda n: int(n.get("created_at") or 0))

    # Mapear cada note → fila messages, calculando response_time_seconds
    last_other_side_ts: Optional[int] = None
    last_sender_type: Optional[str] = None
    messages_dicts = []
    advisor_kommo_id: Optional[int] = None
    customer_phone: Optional[str] = None

    for idx, n in enumerate(msgs_raw):
        params = n.get("params") or {}
        # Kommo "incoming" = del cliente; "outgoing" = del asesor
        kind = params.get("type") or params.get("incoming")
        if kind == "incoming" or kind is True:
            sender_type = "customer"
        elif kind == "outgoing" or kind is False:
            sender_type = "advisor"
            advisor_kommo_id = n.get("created_by") or advisor_kommo_id
        else:
            sender_type = "system"

        # Texto del mensaje
        text = params.get("text") or n.get("text") or ""

        # Sender name
        sender_name = params.get("name") or ""

        sent_ts = int(n.get("created_at") or 0)
        sent_iso = datetime.fromtimestamp(sent_ts, tz=timezone.utc).isoformat() if sent_ts else None

        # response_time: tiempo desde el último mensaje del OTRO lado
        response_seconds = None
        if sender_type in ("customer", "advisor"):
            if last_sender_type and last_sender_type != sender_type and last_other_side_ts:
                response_seconds = max(0, sent_ts - last_other_side_ts)
            last_other_side_ts = sent_ts
            last_sender_type = sender_type

        # customer_phone: tomarlo del primer mensaje incoming si tiene en params
        if not customer_phone and params.get("phone"):
            customer_phone = str(params.get("phone"))

        messages_dicts.append({
            "message_id":            f"kommo-{n.get('id')}",
            "conversation_id":       f"lead-{lead_id}",
            "lead_id":               lead_id,
            "sender_type":           sender_type,
            "sender_name":           sender_name[:80] if sender_name else None,
            "message_text":          (text or "")[:5000],
            "sent_at":               sent_iso,
            "response_time_seconds": response_seconds,
            "message_order":         idx + 1,
        })

    # Construir conversation (una por lead)
    started_at = messages_dicts[0]["sent_at"] if messages_dicts else None
    last_msg_at = messages_dicts[-1]["sent_at"] if messages_dicts else None
    advisor_uuid = db.advisor_uuid_por_kommo(advisor_kommo_id) if advisor_kommo_id else None

    db.upsert_conversation({
        "conversation_id":  f"lead-{lead_id}",
        "lead_id":          lead_id,
        "customer_phone":   customer_phone,
        "advisor_id":       advisor_uuid,
        "channel":          "whatsapp",
        "started_at":       started_at,
        "last_message_at":  last_msg_at,
        "status":           "open",
        "message_count":    len(messages_dicts),
        "audit_status":     "pending",
        "synced_at":        datetime.now(tz=timezone.utc).isoformat(),
    })

    upserted = db.upsert_messages_batch(messages_dicts)
    return {
        "ok":                True,
        "lead_id":           lead_id,
        "conversation_id":   f"lead-{lead_id}",
        "mensajes_total":    len(messages_dicts),
        "mensajes_upserted": upserted,
    }


# ── Sync orquestado (uso por scheduler) ───────────────────────────────────────
def sync_completo(full: bool = False, lead_limit: int = 1000,
                   msg_limit_por_lead: int = 200) -> dict:
    """
    Pasada completa:
      1. Asesoras
      2. Leads incremental (o full)
      3. Mensajes de cada lead que se haya tocado

    Para >3000 conv/mes con scheduler cada 15 min, basta lead_limit=200
    por tick. Con full=True hacer la primera carga (puede tardar 30+ min).
    """
    res = {"steps": {}}

    # 1. Asesoras
    res["steps"]["advisors"] = sync_advisors()

    # 2. Leads
    res["steps"]["leads"] = sync_leads(full=full, limit_total=lead_limit)

    # 3. Mensajes — solo de leads que se actualizaron en este sync
    # Por ahora hacemos un fetch simple de leads recientes y sus mensajes.
    # En producción esto debería ser una cola, pero para v1 sirve.
    sb = db._sb()
    if sb is not None:
        try:
            r = sb.table("kommo_leads").select("lead_id").order(
                "synced_at", desc=True
            ).limit(msg_limit_por_lead).execute()
            lead_ids = [row["lead_id"] for row in (r.data or [])]
        except Exception as e:
            log.warning(f"fetch lead_ids: {e}")
            lead_ids = []

        msgs_total = 0
        for lid in lead_ids:
            try:
                rsync = sync_messages_de_lead(lid)
                msgs_total += rsync.get("mensajes_upserted", 0)
            except Exception as e:
                log.warning(f"sync_messages_de_lead {lid}: {e}")
        res["steps"]["messages"] = {"leads_procesados": len(lead_ids), "mensajes": msgs_total}

    return res
