"""
backend.services.slack_notifier — Notificaciones a Slack via Incoming Webhook.

Mantiene un registro en memoria de qué conversation_id ya fue notificada y
cuándo, para evitar spam (re-notifica solo si pasaron > MIN_HORAS_REPETIR horas).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

log = logging.getLogger(__name__)

MIN_HORAS_REPETIR = float(os.environ.get("SLACK_RENOTIFY_HOURS", "4"))

# conversation_id → datetime UTC de última notificación
_notif_log: dict[str, datetime] = {}

_stats: dict = {
    "total_enviadas":      0,
    "skip_por_repeticion": 0,
    "errores":             0,
    "ultimo_error":        None,
}


def _webhook_url() -> Optional[str]:
    return (os.environ.get("SLACK_WEBHOOK_URL", "").strip() or None)


def get_stats() -> dict:
    return {**_stats, "webhook_configurado": bool(_webhook_url())}


def enviar_mensaje(text: str, blocks: Optional[list] = None) -> bool:
    """Envía un mensaje plano a Slack. Retorna True si fue OK."""
    url = _webhook_url()
    if not url:
        return False
    body: dict = {"text": text}
    if blocks:
        body["blocks"] = blocks
    try:
        r = requests.post(url, json=body, timeout=10)
        if r.status_code == 200:
            _stats["total_enviadas"] += 1
            return True
        _stats["errores"] += 1
        _stats["ultimo_error"] = f"{r.status_code}: {r.text[:200]}"
        return False
    except Exception as e:
        _stats["errores"] += 1
        _stats["ultimo_error"] = str(e)[:200]
        return False


def notificar_alerta_cliente_esperando(alerta: dict) -> bool:
    """Notifica una alerta individual al canal Slack. Antispam: no re-notifica
    el mismo conversation_id si fue notificado en últimas MIN_HORAS_REPETIR."""
    conv_id = alerta.get("conversation_id")
    if not conv_id:
        return False
    ahora = datetime.now(tz=timezone.utc)
    ultima = _notif_log.get(conv_id)
    if ultima and (ahora - ultima) < timedelta(hours=MIN_HORAS_REPETIR):
        _stats["skip_por_repeticion"] += 1
        return False

    cliente = alerta.get("customer_name") or alerta.get("customer_phone") or "Cliente sin nombre"
    asesora = alerta.get("advisor_name") or "Sin asesora asignada"
    canal = alerta.get("channel") or "—"
    mins = alerta.get("minutos_sin_respuesta")
    ultimo_msg = (alerta.get("ultimo_mensaje") or "").strip()

    text = f":warning: *{cliente}* lleva *{mins}m* sin respuesta de *{asesora}* ({canal})"
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":warning: *Cliente esperando*\n*{cliente}* lleva *{mins}m* sin respuesta de *{asesora}* ({canal})",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f">{ultimo_msg[:300]}",
            },
        },
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"Conversación: `{conv_id}`"}],
        },
    ]
    ok = enviar_mensaje(text, blocks)
    if ok:
        _notif_log[conv_id] = ahora
    return ok


def notificar_lote_alertas(alertas: list[dict]) -> dict:
    """Procesa una lista de alertas y notifica las que no fueron notificadas
    recientemente. Retorna contadores."""
    enviadas = 0
    omitidas = 0
    for a in alertas or []:
        if notificar_alerta_cliente_esperando(a):
            enviadas += 1
        else:
            omitidas += 1
    return {"enviadas": enviadas, "omitidas": omitidas}
