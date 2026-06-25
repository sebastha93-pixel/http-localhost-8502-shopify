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
def _extract_custom_fields(lead: dict) -> dict:
    """Extrae custom_fields_values del lead a un dict plano.

    Mapea los campos relevantes que Kommo trae pero no estábamos
    procesando: UTMs, gclid/fbclid/ttad_id (atribución de ads), Ciudad,
    Talla, Referencia, Cantidad de Unidades, Motivo de Perdida/Ganado
    estructurados, Num Total Compras (LTV), Shopify status, etc.

    Retorna dict con keys del schema kommo_leads (utm_source, utm_campaign,
    motivo_perdida, talla, etc). Solo incluye keys cuyo valor NO es null.
    """
    out: dict = {}
    cfv = lead.get("custom_fields_values") or []
    if not isinstance(cfv, list):
        return out

    # Mapeo: field_code O field_name → columna nuestra
    # Usamos field_code primero (más estable), fallback a field_name
    code_map = {
        # Atribución marketing
        "UTM_SOURCE":   "utm_source",
        "UTM_MEDIUM":   "utm_medium",
        "UTM_CAMPAIGN": "utm_campaign",
        "UTM_CONTENT":  "utm_content",
        "UTM_TERM":     "utm_term",
        "UTM_REFERRER": "utm_referrer",
        "REFERRER":     "referrer",
        "GCLID":        "gclid",
        "GCLIENTID":    "gclientid",
        "FBCLID":       "fbclid",
        "TIKTOK_AD_ID_TD":   "ttad_id",
        "TIKTOK_AD_NAME_TD": "ttad_name",
        # Shopify cross-reference
        "SHOPIFY_LEAD_EXTERNAL_ID":      "shopify_lead_id",
        "SHOPIFY_LEAD_FULFILLMENT_STATUS": "shopify_fulfillment",
        "SHOPIFY_LEAD_CURRENCY":         "shopify_currency",
        "SHOPIFY_ORDER_STATUS":          "shopify_order_status",
        "SHOPIFY_ORDER_PAYMENT_STATUS":  "shopify_payment_status",
        "SHOPIFY_ORDER_LINK":            "shopify_order_link",
        # Próxima cita
        "CF_SCHEDULER_UPCOMING_APPOINTMENT": "proxima_cita",
    }
    # Campos sin field_code estable, los mapeamos por field_name (español)
    name_map = {
        "Ciudad":               "ciudad",
        "Referencia":           "referencia",
        "Talla":                "talla",
        "Cantidad de Unidades": "cantidad_unidades",
        "Motivo de Perdida":    "motivo_perdida",
        "Motivo de Ganado":     "motivo_ganado",
        "Numero de Compras":    "numero_compras",
        "Num Total Compras":    "num_total_compras",
        "Incremento":           "incremento",
        "Telefono contacto":    "telefono_secundario",
        "correo contacto":      "email_lead",
    }

    for f in cfv:
        if not isinstance(f, dict):
            continue
        field_code = f.get("field_code") or ""
        field_name = f.get("field_name") or ""
        vals = f.get("values") or []
        if not vals:
            continue
        first = vals[0] if isinstance(vals[0], dict) else {"value": vals[0]}
        raw_val = first.get("value")
        if raw_val is None or raw_val == "":
            continue

        # Decidir columna destino
        col = code_map.get(field_code) or name_map.get(field_name)
        if not col:
            continue

        # Casting según el tipo de campo
        if col in ("numero_compras", "num_total_compras", "incremento", "cantidad_unidades", "shopify_lead_id"):
            try:
                out[col] = int(float(str(raw_val).replace(",", "")))
            except Exception:
                pass
        else:
            out[col] = str(raw_val)[:500]
    return out


def upsert_lead(lead: dict) -> bool:
    """
    `lead` es el dict que entrega kommo_client.listar_leads (estructura Kommo
    cruda). Lo mapeamos al schema de la tabla.

    Extrae custom_fields_values a columnas dedicadas (UTMs, talla, ciudad,
    motivo perdida/ganado, LTV, Shopify status). El fallback en raw JSONB
    se mantiene para campos no mapeados.
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

        # loss_reason (de _embedded — texto libre)
        lr_list = ((lead.get("_embedded") or {}).get("loss_reason") or [])
        loss_reason = lr_list[0].get("name") if lr_list else None

        # tags
        tags = ((lead.get("_embedded") or {}).get("tags") or [])
        tag_names = [t.get("name") for t in tags if t.get("name")]

        # closed_at: cuando el lead fue cerrado (status 142 = ganado, 143 = perdido)
        closed_at_ts = lead.get("closed_at")

        # updated_at de Kommo (no nuestro synced_at)
        kommo_updated_ts = lead.get("updated_at")

        # closest_task_at: próxima tarea del lead
        closest_task_ts = lead.get("closest_task_at")

        # Custom fields → columnas dedicadas
        cf_data = _extract_custom_fields(lead)

        data = {
            "lead_id":              int(lead["id"]),
            "pipeline_id":          lead.get("pipeline_id"),
            "stage_id":             lead.get("status_id"),
            "status":               _map_status(lead.get("status_id")),
            "responsible_user_id":  responsible_id,
            "advisor_id":           advisor_id,
            "created_at":           _epoch_to_iso(lead.get("created_at")),
            "closed_at":            _epoch_to_iso(closed_at_ts) if closed_at_ts else None,
            "kommo_updated_at":     _epoch_to_iso(kommo_updated_ts) if kommo_updated_ts else None,
            "closest_task_at":      _epoch_to_iso(closest_task_ts) if closest_task_ts else None,
            "lead_value":           float(lead.get("price") or 0),
            "loss_reason":          loss_reason,
            "tags":                 tag_names,
            "customer_phone":       _phone_from_contact(contact),
            "customer_name":        cust_name,
            "raw":                  lead,
            "synced_at":            datetime.now(timezone.utc).isoformat(),
            **cf_data,  # spread de custom fields extraídos
        }
        sb.table("kommo_leads").upsert(data, on_conflict="lead_id").execute()
        return True
    except Exception as e:
        log.warning(f"upsert_lead {lead.get('id')}: {e}")
        return False


def backfill_custom_fields(limit: int = 500, start_lead_id: int = 0) -> dict:
    """Backfill: extrae custom_fields_values del raw JSONB de leads ya
    sincronizados a las columnas nuevas. Idempotente: se puede correr
    múltiples veces sin duplicar nada.

    start_lead_id: permite paginar entre llamadas externas (cada call
    procesa hasta `limit` leads desde lead_id > start_lead_id, retorna
    last_lead_id para la próxima call).
    """
    sb = _sb()
    if sb is None:
        return {"ok": False, "error": "supabase_no_configurado"}
    procesados = 0
    enriquecidos = 0
    errores = 0
    last_id = int(start_lead_id or 0)
    while procesados < limit:
        batch_size = min(100, limit - procesados)
        try:
            r = (sb.table("kommo_leads")
                   .select("lead_id,raw")
                   .gt("lead_id", last_id)
                   .order("lead_id")
                   .limit(batch_size)
                   .execute())
            rows = r.data or []
        except Exception as e:
            log.warning(f"backfill_custom_fields fetch: {e}")
            errores += 1
            break
        if not rows:
            break
        for row in rows:
            lead_id = row["lead_id"]
            last_id = lead_id
            procesados += 1
            raw = row.get("raw") or {}
            cf_data = _extract_custom_fields(raw)
            if not cf_data:
                continue
            try:
                sb.table("kommo_leads").update(cf_data).eq("lead_id", lead_id).execute()
                enriquecidos += 1
            except Exception as e:
                errores += 1
                log.warning(f"backfill {lead_id}: {str(e)[:100]}")
                if errores > 10:
                    break
        if errores > 10:
            break
    return {
        "ok": True,
        "procesados": procesados,
        "enriquecidos": enriquecidos,
        "errores": errores,
        "last_lead_id": last_id,
    }


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
    """Inserta un análisis IA. Si ya existe un audit para esa conversation_id,
    lo borra primero (permite re-auditar). Retorna audit_id si OK."""
    sb = _sb()
    if sb is None:
        return None
    conv_id = audit.get("conversation_id")
    try:
        # Borrar audits anteriores de la misma conversation (re-audit reemplaza)
        if conv_id:
            try:
                sb.table("chat_audits").delete().eq("conversation_id", conv_id).execute()
            except Exception as e:
                log.debug(f"insertar_audit: delete previo falló (ok si no existía): {e}")
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
from backend.core.cache import cached_ttl


@cached_ttl(ttl_seconds=60, max_size=4)
def stats_revenue() -> dict:
    """KPIs del módulo. Cache 60s para reducir COUNT queries a Supabase."""
    sb = _sb()
    if sb is None:
        return {"ok": False, "error": "Supabase no configurado"}
    try:
        return {
            "ok":             True,
            # Solo asesoras activas (operativas). Las inactivas no aportan al ranking.
            "advisors":       _count(sb, "advisors", {"active": True}),
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
