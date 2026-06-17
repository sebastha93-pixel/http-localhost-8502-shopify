"""
backend.services.audit_ia — Motor de auditoría comercial con Claude Haiku 4.5.

Lee el thread de una conversation (mensajes + metadata del lead),
construye un prompt estructurado, llama Anthropic API y parsea la
respuesta JSON. Persiste el resultado en chat_audits.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import requests

from backend.services import revenue_db as db


log = logging.getLogger(__name__)

ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
ANTHROPIC_API   = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VER   = "2023-06-01"

MAX_INPUT_MESSAGES = 80
MAX_OUTPUT_TOKENS  = 1500


SYSTEM_PROMPT = """Eres un auditor comercial experto en ventas conversacionales por WhatsApp e Instagram para una marca de jeans premium (MALE DENIM).

Recibirás una conversación entre una asesora de ventas y un cliente potencial. Tu tarea es analizarla objetivamente y devolver SOLO un JSON válido con esta estructura exacta:

{
  "result_classification": "venta_lograda" | "venta_perdida" | "inconclusa",
  "calidad_servicio": <entero 1-10>,
  "tiempo_respuesta_score": <entero 1-10>,
  "tono_score": <entero 1-10>,
  "resumen": "<2-3 frases describiendo la conversación>",
  "motivos_perdida": ["precio", "talla_no_disponible", "no_responde_cliente", "asesora_lenta", "competencia", "otro"],
  "loss_reason_principal": "<uno de los anteriores o null>",
  "oportunidades_perdidas": ["<frase específica de algo que la asesora pudo haber hecho>"],
  "frases_positivas": ["<frase textual donde la asesora hizo algo bien>"],
  "frases_negativas": ["<frase textual donde la asesora pudo haber hecho mejor>"],
  "recomendaciones": ["<consejo accionable para la asesora>"],
  "señales_compra": ["<frase del cliente mostrando interés>"]
}

Reglas:
- Si la conversación tiene menos de 4 mensajes Y el lead no está cerrado, usa "inconclusa".
- Sé directo. No inventes frases que no estén en la conversación.
- Si un campo no aplica, devuelve [] o null.
- NO uses markdown ni texto fuera del JSON."""


def _api_key() -> Optional[str]:
    return os.environ.get("ANTHROPIC_API_KEY", "").strip() or None


def _construir_mensajes(conv_id: str) -> Optional[dict]:
    """Lee la conversation + sus mensajes + metadata del lead. Retorna dict o None."""
    sb = db._sb()
    if sb is None:
        return None
    convs = sb.table("conversations").select("*").eq("conversation_id", conv_id).limit(1).execute().data or []
    if not convs:
        return None
    conv = convs[0]

    msgs = (sb.table("messages")
              .select("message_id,sender_type,sender_name,message_text,sent_at")
              .eq("conversation_id", conv_id)
              .order("sent_at")
              .limit(MAX_INPUT_MESSAGES)
              .execute().data) or []

    lead = {}
    if conv.get("lead_id"):
        ld = sb.table("kommo_leads").select("lead_id,status,lead_value,customer_name,customer_phone,closed_at").eq("lead_id", conv["lead_id"]).limit(1).execute().data
        if ld:
            lead = ld[0]

    advisor_name = None
    if conv.get("advisor_id"):
        adv = sb.table("advisors").select("name").eq("advisor_id", conv["advisor_id"]).limit(1).execute().data
        if adv:
            advisor_name = adv[0].get("name")

    return {"conv": conv, "messages": msgs, "lead": lead, "advisor_name": advisor_name}


def _formato_thread(data: dict) -> str:
    """Convierte el thread en texto plano para enviar al modelo."""
    lines = []
    lead = data.get("lead") or {}
    conv = data.get("conv") or {}
    lines.append(f"# Conversación {conv.get('conversation_id')}")
    lines.append(f"Canal: {conv.get('channel') or '—'}")
    lines.append(f"Asesora: {data.get('advisor_name') or '—'}")
    lines.append(f"Cliente: {lead.get('customer_name') or '—'} ({lead.get('customer_phone') or '—'})")
    lines.append(f"Estado del lead: {lead.get('status') or '—'}")
    if lead.get("lead_value"):
        lines.append(f"Valor del lead (COP): {lead['lead_value']}")
    lines.append("")
    lines.append("# Thread de mensajes:")
    for m in data.get("messages", []) or []:
        who = m.get("sender_type") or "?"
        nom = m.get("sender_name") or ""
        ts  = m.get("sent_at") or ""
        txt = (m.get("message_text") or "").replace("\n", " ").strip()
        if not txt:
            continue
        lines.append(f"[{who} | {nom} | {ts}] {txt}")
    return "\n".join(lines)


def _llamar_haiku(thread_text: str) -> Optional[dict]:
    """Llama Claude Haiku 4.5 y retorna el JSON parseado. None si falla."""
    key = _api_key()
    if not key:
        log.warning("ANTHROPIC_API_KEY no configurado")
        return None
    headers = {
        "x-api-key":         key,
        "anthropic-version": ANTHROPIC_VER,
        "content-type":      "application/json",
    }
    body = {
        "model":      ANTHROPIC_MODEL,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "system":     SYSTEM_PROMPT,
        "messages": [
            {"role": "user", "content": thread_text}
        ],
    }
    try:
        r = requests.post(ANTHROPIC_API, headers=headers, json=body, timeout=60)
        if r.status_code != 200:
            log.warning(f"Haiku {r.status_code}: {r.text[:300]}")
            return None
        resp = r.json()
        # Anthropic devuelve content[].text
        text = ""
        for c in resp.get("content", []):
            if c.get("type") == "text":
                text += c.get("text", "")
        text = text.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:].strip()
        return json.loads(text)
    except Exception as e:
        log.exception("Haiku call failed")
        return None


def auditar_conversation(conv_id: str) -> dict:
    """Audita una conversation completa. Retorna dict con resultado y/o error."""
    data = _construir_mensajes(conv_id)
    if not data:
        return {"ok": False, "error": "conversation_no_encontrada"}
    if not data["messages"]:
        return {"ok": False, "error": "sin_mensajes"}

    thread = _formato_thread(data)
    parsed = _llamar_haiku(thread)
    if not parsed:
        return {"ok": False, "error": "haiku_fallo_o_no_json"}

    audit_row = {
        "conversation_id":       conv_id,
        "lead_id":               data["conv"].get("lead_id"),
        "advisor_id":            data["conv"].get("advisor_id"),
        "result_classification": parsed.get("result_classification"),
        "calidad_servicio":      parsed.get("calidad_servicio"),
        "tiempo_respuesta_score": parsed.get("tiempo_respuesta_score"),
        "tono_score":            parsed.get("tono_score"),
        "resumen":               parsed.get("resumen"),
        "loss_reason_code":      parsed.get("loss_reason_principal"),
        "motivos_perdida":       parsed.get("motivos_perdida") or [],
        "oportunidades_perdidas": parsed.get("oportunidades_perdidas") or [],
        "frases_positivas":      parsed.get("frases_positivas") or [],
        "frases_negativas":      parsed.get("frases_negativas") or [],
        "recomendaciones":       parsed.get("recomendaciones") or [],
        "señales_compra":        parsed.get("señales_compra") or [],
        "model":                 ANTHROPIC_MODEL,
        "analyzed_at":           datetime.now(tz=timezone.utc).isoformat(),
        "raw_response":          parsed,
    }
    audit_id = db.insertar_audit(audit_row)
    if not audit_id:
        return {"ok": False, "error": "insert_fallo", "audit_data": audit_row}

    # Marcar la conversation como auditada
    try:
        sb = db._sb()
        if sb is not None:
            sb.table("conversations").update({"audit_status": "completed"}).eq("conversation_id", conv_id).execute()
    except Exception:
        pass

    return {"ok": True, "audit_id": audit_id, "result": parsed}


def auditar_pendientes(limit: int = 10, solo_cerradas: bool = True) -> dict:
    """Procesa hasta N conversations con audit_status=pending."""
    sb = db._sb()
    if sb is None:
        return {"ok": False, "error": "supabase_no_configurado"}

    q = sb.table("conversations").select("conversation_id,status,lead_id,message_count").eq("audit_status", "pending").order("last_message_at", desc=True).limit(limit * 3)
    pendientes = q.execute().data or []
    procesadas = []
    ok = 0
    err = 0
    for c in pendientes:
        if len(procesadas) >= limit:
            break
        if solo_cerradas and c.get("status") != "closed":
            continue
        res = auditar_conversation(c["conversation_id"])
        procesadas.append({"conversation_id": c["conversation_id"], "ok": res.get("ok"), "error": res.get("error")})
        if res.get("ok"):
            ok += 1
        else:
            err += 1
    return {"ok": True, "procesadas": len(procesadas), "exitosas": ok, "fallidas": err, "detalle": procesadas}
