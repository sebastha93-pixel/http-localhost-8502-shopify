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
from datetime import datetime, timezone, timedelta
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

Recibirás una conversación entre una asesora de ventas y un cliente potencial. Devuelve SOLO un JSON válido con esta estructura exacta:

{
  "result_classification": "venta_lograda" | "venta_perdida" | "inconclusa",
  "sale_status": "ganada" | "perdida" | "en_proceso" | "abandonada_cliente" | "abandonada_asesora",
  "main_loss_reason": "precio" | "talla_no_disponible" | "no_responde_cliente" | "asesora_lenta" | "competencia" | "envio_lento" | "metodo_pago" | "otro" | null,
  "response_time_score": <1-10>,
  "attention_score": <1-10>,
  "follow_up_score": <1-10>,
  "closing_score": <1-10>,
  "overall_score": <1-10>,
  "lost_moment": "<frase textual exacta del momento donde se perdió la venta, o null>",
  "recommended_response": "<lo que la asesora debió responder en el momento crítico, o null>",
  "economic_impact_estimate": <COP estimado de la venta perdida o 0>,
  "confidence_score": <0-1, qué tan seguro estás del análisis>,
  "ai_summary_internal": "<2-4 frases describiendo qué pasó>",
  "oportunidades_perdidas": ["<frases accionables>"],
  "frases_positivas": ["<lo que la asesora hizo bien, textual>"],
  "frases_negativas": ["<lo que pudo hacer mejor, textual>"],
  "señales_compra": ["<frase del cliente mostrando interés>"],
  "recomendaciones": ["<consejos para la asesora>"]
}

Reglas:
- Si conversación tiene <4 mensajes y lead no está cerrado → "inconclusa" + "en_proceso".
- NO inventes frases. Cita textual.
- Si campo no aplica → [] o null.
- NO uses markdown. Solo JSON puro."""


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


def _llamar_haiku(thread_text: str) -> Optional[tuple[dict, float]]:
    """Llama Claude Haiku 4.5 y retorna (JSON parseado, costo_usd). None si falla."""
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
        text = ""
        for c in resp.get("content", []):
            if c.get("type") == "text":
                text += c.get("text", "")
        text = text.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:].strip()
        parsed = json.loads(text)
        usage = resp.get("usage") or {}
        # Haiku 4.5: $1/MTok input, $5/MTok output
        cost = (usage.get("input_tokens", 0) / 1_000_000) * 1.0 + (usage.get("output_tokens", 0) / 1_000_000) * 5.0
        return parsed, round(cost, 6)
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
    res = _llamar_haiku(thread)
    if not res:
        return {"ok": False, "error": "haiku_fallo_o_no_json"}
    parsed, cost_usd = res

    audit_row = {
        "conversation_id":         conv_id,
        "lead_id":                 data["conv"].get("lead_id"),
        "advisor_id":              data["conv"].get("advisor_id"),
        "audit_date":              datetime.now(tz=timezone.utc).isoformat(),
        "result_classification":   parsed.get("result_classification"),
        "sale_status":             parsed.get("sale_status"),
        "main_loss_reason":        parsed.get("main_loss_reason"),
        "response_time_score":     parsed.get("response_time_score"),
        "attention_score":         parsed.get("attention_score"),
        "follow_up_score":         parsed.get("follow_up_score"),
        "closing_score":           parsed.get("closing_score"),
        "overall_score":           parsed.get("overall_score"),
        "lost_moment":             parsed.get("lost_moment"),
        "recommended_response":    parsed.get("recommended_response"),
        "economic_impact_estimate": parsed.get("economic_impact_estimate") or 0,
        "confidence_score":        parsed.get("confidence_score"),
        "ai_summary_internal":     parsed.get("ai_summary_internal"),
        "raw_analysis":            parsed,
        "modelo_ia":               ANTHROPIC_MODEL,
        "costo_analisis_usd":      cost_usd,
    }
    audit_row = {k: v for k, v in audit_row.items() if v is not None}
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


COACHING_SYSTEM_PROMPT = """Eres un coach de ventas experto. Tu rol es analizar el desempeño de UNA asesora de MALE DENIM basándote en múltiples auditorías de conversaciones (ya pre-analizadas por IA) y generar un reporte de coaching ACCIONABLE.

Recibirás un resumen estadístico + extractos textuales (frases positivas, negativas, recomendaciones) de varias auditorías de la misma asesora.

Devuelve SOLO JSON válido con esta estructura:

{
  "diagnostico_general": "<3-4 frases del estado general>",
  "fortalezas": ["<patrón positivo recurrente>"],
  "areas_de_mejora": ["<patrón problemático recurrente>"],
  "momento_critico_recurrente": "<si hay un patrón de dónde se pierden las ventas, descríbelo>",
  "plan_accion_30_dias": [
    {"semana": 1, "objetivo": "<>", "ejercicio": "<>"},
    {"semana": 2, "objetivo": "<>", "ejercicio": "<>"},
    {"semana": 3, "objetivo": "<>", "ejercicio": "<>"},
    {"semana": 4, "objetivo": "<>", "ejercicio": "<>"}
  ],
  "frases_modelo": ["<3-5 frases ejemplo que debería usar más>"],
  "frases_a_evitar": ["<3-5 frases o patrones que debe dejar de usar>"],
  "kpi_objetivo": {"conv_rate_target": <0-100>, "overall_score_target": <1-10>},
  "prioridad_urgente": "<la UNA cosa más importante a corregir esta semana>"
}

Sé directo, específico y accionable. Cita frases textuales cuando sea posible. NO uses markdown."""


def coaching_para_asesora(advisor_id: str, days_back: int = 60) -> dict:
    """Genera reporte de coaching IA basado en todas las auditorías de una asesora.
    Toma el dataset, lo resume estadísticamente y pasa a Haiku para sintetizar."""
    sb = db._sb()
    if sb is None:
        return {"ok": False, "error": "supabase_no_configurado"}

    adv = sb.table("advisors").select("name,email").eq("advisor_id", advisor_id).limit(1).execute().data
    if not adv:
        return {"ok": False, "error": "asesora_no_encontrada"}
    advisor_name = adv[0]["name"]

    desde = (datetime.now(tz=timezone.utc) - timedelta(days=days_back)).isoformat()
    audits = (sb.table("chat_audits").select("*")
                .eq("advisor_id", advisor_id)
                .gte("audit_date", desde)
                .order("audit_date", desc=True)
                .limit(50).execute().data) or []
    if not audits:
        return {"ok": False, "error": "sin_auditorias"}

    # Agregados estadísticos
    n = len(audits)
    won = sum(1 for a in audits if a.get("result_classification") == "venta_lograda")
    lost = sum(1 for a in audits if a.get("result_classification") == "venta_perdida")
    inconclusas = n - won - lost
    impact_perdido = sum(float(a.get("economic_impact_estimate") or 0) for a in audits if a.get("result_classification") == "venta_perdida")

    def avg(field):
        vals = [float(a[field]) for a in audits if a.get(field) is not None]
        return round(sum(vals) / len(vals), 2) if vals else None

    # Recopilar frases / motivos
    motivos = {}
    frases_pos = []
    frases_neg = []
    recomendaciones = []
    momentos = []
    for a in audits:
        m = a.get("main_loss_reason")
        if m:
            motivos[m] = motivos.get(m, 0) + 1
        if a.get("lost_moment"):
            momentos.append(a["lost_moment"])
        raw = a.get("raw_analysis") or {}
        for f in (raw.get("frases_positivas") or [])[:2]:
            frases_pos.append(f)
        for f in (raw.get("frases_negativas") or [])[:2]:
            frases_neg.append(f)
        for r in (raw.get("recomendaciones") or [])[:1]:
            recomendaciones.append(r)

    resumen_para_ia = f"""Asesora: {advisor_name}
Periodo: últimos {days_back} días, {n} conversaciones auditadas.

Resultados:
- Ventas ganadas: {won}
- Ventas perdidas: {lost}
- Inconclusas: {inconclusas}
- Tasa de conversión: {round(100 * won / (won + lost), 1) if (won + lost) else 0}%
- Impacto económico de ventas perdidas: COP ${int(impact_perdido):,}

Scores promedio (1-10):
- Overall: {avg('overall_score')}
- Tiempo de respuesta: {avg('response_time_score')}
- Atención al cliente: {avg('attention_score')}
- Follow-up: {avg('follow_up_score')}
- Cierre: {avg('closing_score')}

Motivos de pérdida más frecuentes: {motivos}

Frases POSITIVAS detectadas (cosas que hace bien): {frases_pos[:15]}

Frases NEGATIVAS detectadas (cosas que hace mal): {frases_neg[:15]}

Momentos donde perdió ventas: {momentos[:10]}

Recomendaciones previas de las auditorías: {recomendaciones[:15]}
"""

    # Llamada a Haiku con system prompt coaching
    key = _api_key()
    if not key:
        return {"ok": False, "error": "no_api_key"}
    headers = {"x-api-key": key, "anthropic-version": ANTHROPIC_VER, "content-type": "application/json"}
    body = {
        "model":      ANTHROPIC_MODEL,
        "max_tokens": 2000,
        "system":     COACHING_SYSTEM_PROMPT,
        "messages":   [{"role": "user", "content": resumen_para_ia}],
    }
    try:
        r = requests.post(ANTHROPIC_API, headers=headers, json=body, timeout=60)
        if r.status_code != 200:
            return {"ok": False, "error": f"haiku_{r.status_code}", "body": r.text[:300]}
        resp = r.json()
        text = ""
        for c in resp.get("content", []):
            if c.get("type") == "text":
                text += c.get("text", "")
        text = text.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:].strip()
        parsed = json.loads(text)
        usage = resp.get("usage") or {}
        cost = (usage.get("input_tokens", 0) / 1_000_000) * 1.0 + (usage.get("output_tokens", 0) / 1_000_000) * 5.0
        return {
            "ok": True,
            "advisor_id": advisor_id,
            "advisor_name": advisor_name,
            "n_auditorias": n,
            "stats": {
                "won": won, "lost": lost, "inconclusas": inconclusas,
                "conversion_rate": round(100 * won / (won + lost), 1) if (won + lost) else 0,
                "impact_perdido_cop": int(impact_perdido),
                "avg_overall": avg('overall_score'),
            },
            "coaching": parsed,
            "modelo": ANTHROPIC_MODEL,
            "costo_usd": round(cost, 6),
        }
    except Exception as e:
        log.exception("coaching failed")
        return {"ok": False, "error": str(e)[:300]}


def auditar_pendientes(limit: int = 10, solo_cerradas: bool = True) -> dict:
    """Procesa hasta N conversations con audit_status=pending que TENGAN
    mensajes capturados. Las que no tienen mensajes se omiten silenciosamente
    (esperan a que el webhook acumule data)."""
    sb = db._sb()
    if sb is None:
        return {"ok": False, "error": "supabase_no_configurado"}

    # Buscar conversation_ids únicos con al menos 1 mensaje en la tabla messages
    msgs = sb.table("messages").select("conversation_id").limit(1000).execute().data or []
    conv_ids_con_mensajes = list({m["conversation_id"] for m in msgs if m.get("conversation_id")})
    if not conv_ids_con_mensajes:
        return {"ok": True, "procesadas": 0, "exitosas": 0, "fallidas": 0,
                "razon": "sin_mensajes_en_db", "detalle": []}

    # Filtrar pendientes que estén en esa lista
    q = (sb.table("conversations")
           .select("conversation_id,status,lead_id,message_count")
           .eq("audit_status", "pending")
           .in_("conversation_id", conv_ids_con_mensajes)
           .order("last_message_at", desc=True)
           .limit(limit * 3))
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
    return {
        "ok": True,
        "candidatos_con_mensajes": len(conv_ids_con_mensajes),
        "procesadas": len(procesadas),
        "exitosas": ok,
        "fallidas": err,
        "detalle": procesadas,
    }
