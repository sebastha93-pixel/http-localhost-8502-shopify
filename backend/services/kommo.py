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
# touch: force railway redeploy con env vars nuevas


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


def sync_talks(full: bool = False, limit_total: int = 5000) -> dict:
    """
    Sync incremental de talks → tabla conversations.

    Cada talk se convierte en 1 conversation con:
      - conversation_id = "talk-{talk_id}"
      - lead_id        = talk.entity_id (si entity_type=="lead")
      - advisor_id     = uuid del responsible del lead asociado
      - channel        = talk.origin (waba, instagram_business, etc.)
      - started_at     = talk.created_at
      - last_message_at = talk.updated_at
      - status         = talk.status
      - audit_status   = 'pending'

    NO inserta mensajes individuales (la API no los expone). Esos se
    capturan vía webhook cuando se activa la Opción A.
    """
    import kommo_client as kc

    desde_ts: Optional[int] = None
    if not full:
        last = db.leer_sync_state("kommo_talks_last_sync")
        if last:
            try:
                desde_ts = int(last)
            except Exception:
                pass

    nuevo_corte_ts = int(datetime.now(tz=timezone.utc).timestamp())

    procesados = 0
    upserted = 0
    skip_not_lead = 0
    skip_no_entity_id = 0
    skip_lead_not_in_db = 0
    upsert_failed = 0
    entity_types_seen: dict[str, int] = {}
    sample_errors: list[str] = []
    sb = db._sb()
    if sb is None:
        return {"ok": False, "error": "Supabase no configurado"}

    # Cache leads → advisor_id para no consultar Supabase 1 por talk
    advisors_por_lead: dict[int, Optional[str]] = {}

    try:
        for talk in kc.listar_talks(updated_after_ts=desde_ts, limit_total=limit_total):
            procesados += 1
            entity_type = talk.get("entity_type") or "none"
            entity_types_seen[entity_type] = entity_types_seen.get(entity_type, 0) + 1
            if entity_type != "lead":
                skip_not_lead += 1
                continue
            lead_id = talk.get("entity_id")
            if not lead_id:
                skip_no_entity_id += 1
                continue

            # Buscar advisor_id del lead. Si no está en DB, lo traemos de Kommo on-the-fly.
            if lead_id not in advisors_por_lead:
                try:
                    r = sb.table("kommo_leads").select("advisor_id").eq("lead_id", lead_id).limit(1).execute()
                    if r.data:
                        advisors_por_lead[lead_id] = r.data[0]["advisor_id"]
                    else:
                        # Lead no está sincronizado: traerlo on-the-fly
                        try:
                            lead_data = kc.obtener_lead(lead_id)
                            if lead_data:
                                db.upsert_lead(lead_data)
                                r2 = sb.table("kommo_leads").select("advisor_id").eq("lead_id", lead_id).limit(1).execute()
                                advisors_por_lead[lead_id] = r2.data[0]["advisor_id"] if r2.data else None
                            else:
                                advisors_por_lead[lead_id] = "__NOT_FOUND__"
                        except Exception:
                            advisors_por_lead[lead_id] = "__NOT_FOUND__"
                except Exception:
                    advisors_por_lead[lead_id] = "__NOT_FOUND__"

            adv = advisors_por_lead.get(lead_id)
            if adv == "__NOT_FOUND__":
                skip_lead_not_in_db += 1
                continue

            started_ts = talk.get("created_at")
            updated_ts = talk.get("updated_at")
            conv = {
                "conversation_id":  f"talk-{talk['talk_id']}",
                "lead_id":          lead_id,
                "advisor_id":       adv,
                "channel":          talk.get("origin") or "unknown",
                "started_at":       datetime.fromtimestamp(int(started_ts), tz=timezone.utc).isoformat() if started_ts else None,
                "last_message_at":  datetime.fromtimestamp(int(updated_ts), tz=timezone.utc).isoformat() if updated_ts else None,
                "status":           talk.get("status"),
                "message_count":    0,
                "audit_status":     "pending",
                "synced_at":        datetime.now(tz=timezone.utc).isoformat(),
            }
            try:
                sb.table("conversations").upsert(conv, on_conflict="conversation_id").execute()
                upserted += 1
            except Exception as e:
                upsert_failed += 1
                if len(sample_errors) < 3:
                    sample_errors.append(f"talk={talk.get('talk_id')} lead={lead_id}: {str(e)[:200]}")
    except Exception as e:
        log.exception("sync_talks error")
        return {"ok": False, "error": str(e)[:300], "procesados": procesados}

    if procesados > 0 or desde_ts is None:
        db.guardar_sync_state("kommo_talks_last_sync", str(nuevo_corte_ts))

    return {
        "ok":          True,
        "procesados":  procesados,
        "upserted":    upserted,
        "modo":        "full" if full else "incremental",
        "desde_ts":    desde_ts,
        "hasta_ts":    nuevo_corte_ts,
        "breakdown": {
            "skip_not_lead":       skip_not_lead,
            "skip_no_entity_id":   skip_no_entity_id,
            "skip_lead_not_in_db": skip_lead_not_in_db,
            "upsert_failed":       upsert_failed,
            "entity_types":        entity_types_seen,
            "sample_errors":       sample_errors,
        },
    }


# Estado del backfill en memoria + persistente
_backfill_state: dict = {
    "running":      False,
    "started_at":   None,
    "finished_at":  None,
    "procesados":   0,
    "upserted":     0,
    "leads_traidos": 0,
    "skip_lead_not_found": 0,
    "last_updated_ts": None,
    "error":        None,
}


def get_backfill_state() -> dict:
    """Estado actual del job de backfill (read-only)."""
    return dict(_backfill_state)


def sync_talks_backfill_completo() -> None:
    """Backfill de TODOS los talks históricos. Para usar dentro de BackgroundTasks.

    Pagina sin límite usando filtro updated_at[from] avanzando con el max
    updated_at del último talk procesado. Trae leads on-the-fly.
    """
    import kommo_client as kc
    from datetime import datetime as _dt, timezone as _tz

    if _backfill_state["running"]:
        return
    _backfill_state.update({
        "running": True,
        "started_at": _dt.now(tz=_tz.utc).isoformat(),
        "finished_at": None,
        "procesados": 0,
        "upserted": 0,
        "leads_traidos": 0,
        "skip_lead_not_found": 0,
        "error": None,
    })
    sb = db._sb()
    if sb is None:
        _backfill_state["error"] = "supabase_no_configurado"
        _backfill_state["running"] = False
        return

    last_updated_ts: Optional[int] = None
    last_saved = db.leer_sync_state("kommo_talks_backfill_cursor")
    if last_saved:
        try:
            last_updated_ts = int(last_saved)
        except Exception:
            pass

    try:
        while True:
            procesados_lote = 0
            upserted_lote = 0
            max_ts_lote: Optional[int] = None
            for talk in kc.listar_talks(updated_after_ts=last_updated_ts, limit_total=500):
                procesados_lote += 1
                _backfill_state["procesados"] += 1
                ts = talk.get("updated_at")
                if ts is not None:
                    ts = int(ts)
                    if max_ts_lote is None or ts > max_ts_lote:
                        max_ts_lote = ts

                if talk.get("entity_type") != "lead":
                    continue
                lead_id = talk.get("entity_id")
                if not lead_id:
                    continue

                # Asegurar lead existe
                try:
                    r = sb.table("kommo_leads").select("lead_id,advisor_id").eq("lead_id", lead_id).limit(1).execute()
                    adv_id = None
                    if r.data:
                        adv_id = r.data[0].get("advisor_id")
                    else:
                        try:
                            lead_data = kc.obtener_lead(lead_id)
                            if lead_data:
                                db.upsert_lead(lead_data)
                                _backfill_state["leads_traidos"] += 1
                                r2 = sb.table("kommo_leads").select("advisor_id").eq("lead_id", lead_id).limit(1).execute()
                                adv_id = r2.data[0].get("advisor_id") if r2.data else None
                            else:
                                _backfill_state["skip_lead_not_found"] += 1
                                continue
                        except Exception:
                            _backfill_state["skip_lead_not_found"] += 1
                            continue
                except Exception:
                    continue

                created = talk.get("created_at")
                updated = talk.get("updated_at")
                row = {
                    "conversation_id":  f"talk-{talk['talk_id']}",
                    "lead_id":          int(lead_id),
                    "advisor_id":       adv_id,
                    "channel":          talk.get("origin") or "unknown",
                    "started_at":       _dt.fromtimestamp(int(created), tz=_tz.utc).isoformat() if created else None,
                    "last_message_at":  _dt.fromtimestamp(int(updated), tz=_tz.utc).isoformat() if updated else None,
                    "status":           talk.get("status"),
                    "message_count":    0,
                    "audit_status":     "pending",
                    "synced_at":        _dt.now(tz=_tz.utc).isoformat(),
                }
                try:
                    sb.table("conversations").upsert(row, on_conflict="conversation_id").execute()
                    upserted_lote += 1
                    _backfill_state["upserted"] += 1
                except Exception:
                    pass

            log.info(f"backfill lote: procesados={procesados_lote} upserted={upserted_lote} max_ts={max_ts_lote}")
            if procesados_lote == 0:
                break
            if max_ts_lote is None:
                break
            # Avanzar cursor: el siguiente lote debe partir desde max_ts + 1
            new_ts = max_ts_lote + 1
            if last_updated_ts is not None and new_ts <= last_updated_ts:
                break
            last_updated_ts = new_ts
            _backfill_state["last_updated_ts"] = new_ts
            db.guardar_sync_state("kommo_talks_backfill_cursor", str(new_ts))

    except Exception as e:
        log.exception("backfill error")
        _backfill_state["error"] = str(e)[:300]
    finally:
        _backfill_state["finished_at"] = _dt.now(tz=_tz.utc).isoformat()
        _backfill_state["running"] = False


def sync_messages_de_lead(lead_id: int, conversation_id_override: Optional[str] = None) -> dict:
    """
    Trae todas las notes (mensajes) del lead y las inserta en messages.
    Construye/actualiza la fila correspondiente en conversations.

    Si conversation_id_override se pasa, usa ese ID (p.ej "talk-XXX") en lugar
    del default "lead-XXX". Esto permite asociar mensajes históricos a la
    conversation ya existente creada via sync_talks.

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
            "conversation_id":       conversation_id_override or f"lead-{lead_id}",
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

    # 3. Talks (metadata de conversaciones — funciona hoy)
    res["steps"]["talks"] = sync_talks(full=full, limit_total=lead_limit)

    # 4. Mensajes — solo de leads que se actualizaron en este sync
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
