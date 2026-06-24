"""
backend.services.transcription — Transcribe audios WhatsApp con OpenAI Whisper.

Flujo:
  1. Meta webhook guarda mensajes con type='audio'. Marca topic='audio' y deja
     un placeholder '🎤 [audio]' como message_text.
  2. process_pending(limit) busca esos mensajes, descarga el binario desde
     Graph API usando META_SYSTEM_USER_TOKEN, lo manda a Whisper, y actualiza
     message_text con la transcripción: '🎤 [audio] hola, sí me interesa...'.
  3. La columna payload conserva el media_id original para idempotencia.

Costo: Whisper API = $0.006/min ≈ ~$0.30 por 1000 audios cortos.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import requests

from backend.services import revenue_db as db

log = logging.getLogger(__name__)

WHISPER_API = "https://api.openai.com/v1/audio/transcriptions"
WHISPER_MODEL = "whisper-1"  # único disponible vía API
META_GRAPH_BASE = "https://graph.facebook.com/v23.0"


def _openai_key() -> Optional[str]:
    return os.environ.get("OPENAI_API_KEY", "").strip() or None


def _meta_token() -> Optional[str]:
    return os.environ.get("META_SYSTEM_USER_TOKEN", "").strip() or None


def _descargar_audio_meta(media_id: str) -> Optional[tuple[bytes, str]]:
    """Descarga binario de audio desde Meta Graph API.
    Devuelve (bytes, mime_type) o None.
    """
    token = _meta_token()
    if not token or not media_id:
        return None
    # 1. Obtener URL temporal del media
    try:
        r = requests.get(
            f"{META_GRAPH_BASE}/{media_id}",
            params={"access_token": token},
            timeout=15,
        )
        if r.status_code != 200:
            log.warning(f"meta media meta {media_id}: {r.status_code} {r.text[:200]}")
            return None
        meta_info = r.json()
        url = meta_info.get("url")
        mime = meta_info.get("mime_type") or "audio/ogg"
        if not url:
            return None
    except Exception as e:
        log.warning(f"meta media fetch {media_id}: {e}")
        return None
    # 2. Descargar binario (esta URL también requiere el token).
    # Cap a 25MB: Whisper API tope, además protege memoria del worker
    # contra un audio anómalo que reviente Railway.
    try:
        r2 = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
            stream=True,
        )
        if r2.status_code != 200:
            log.warning(f"meta media binary {media_id}: {r2.status_code}")
            return None
        chunks: list = []
        total = 0
        MAX_BYTES = 25 * 1024 * 1024
        for chunk in r2.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_BYTES:
                log.warning(f"meta media {media_id} excede 25MB, skip")
                return None
            chunks.append(chunk)
        return (b"".join(chunks), mime)
    except Exception as e:
        log.warning(f"meta media download {media_id}: {e}")
        return None


def _whisper_transcribe(audio_bytes: bytes, mime: str) -> Optional[str]:
    """Llama OpenAI Whisper. Retorna texto o None."""
    key = _openai_key()
    if not key:
        return None
    # Whisper acepta ogg, mp3, mp4, m4a, wav, webm. WhatsApp típicamente manda ogg.
    ext = "ogg"
    if "mp3" in mime:    ext = "mp3"
    elif "mp4" in mime:  ext = "mp4"
    elif "m4a" in mime:  ext = "m4a"
    elif "wav" in mime:  ext = "wav"
    elif "webm" in mime: ext = "webm"

    try:
        files = {"file": (f"audio.{ext}", audio_bytes, mime)}
        data = {
            "model": WHISPER_MODEL,
            "language": "es",  # español, mejor accuracy que auto-detect
            "response_format": "text",
        }
        r = requests.post(
            WHISPER_API,
            headers={"Authorization": f"Bearer {key}"},
            files=files,
            data=data,
            timeout=60,
        )
        if r.status_code != 200:
            log.warning(f"whisper {r.status_code}: {r.text[:200]}")
            return None
        return (r.text or "").strip()
    except Exception as e:
        log.warning(f"whisper error: {e}")
        return None


def process_pending(limit: int = 20) -> dict:
    """Procesa hasta `limit` mensajes de audio sin transcripción.

    Busca messages con topic='audio' Y message_text que aún sea el placeholder
    '🎤 [audio]' (sin transcripción). Idempotente: una vez transcrito no
    vuelve a procesarlo.
    """
    sb = db._sb()
    if sb is None:
        return {"ok": False, "error": "supabase_no_configurado"}
    if not _openai_key():
        return {"ok": False, "error": "no_openai_key", "hint": "Setea OPENAI_API_KEY en Railway"}
    if not _meta_token():
        return {"ok": False, "error": "no_meta_token"}

    # Buscar mensajes pendientes: topic=audio, message_text empieza con
    # placeholder. Intenta full select (con payload); si la columna no existe
    # en el schema, hace fallback informativo (no podemos transcribir sin
    # payload porque ahí viene el media_id de Meta).
    rows: list = []
    try:
        r = (sb.table("messages")
               .select("message_id,payload,sent_at")
               .eq("topic", "audio")
               .like("message_text", "🎤 [audio]%")
               .order("sent_at", desc=True)
               .limit(limit)
               .execute())
        rows = r.data or []
    except Exception as e:
        err = str(e)
        if "payload" in err and ("does not exist" in err or "42703" in err):
            return {
                "ok": False,
                "error": "schema_missing_payload_column",
                "hint": (
                    "La columna 'payload' (jsonb) no existe en la tabla messages "
                    "de Supabase. Agrégala desde Supabase Table Editor: "
                    "messages → + New column → name=payload, type=jsonb, allow NULL. "
                    "Una vez creada, los audios NUEVOS guardarán el media_id y este "
                    "endpoint los podrá transcribir."
                ),
            }
        return {"ok": False, "error": f"query: {err[:200]}"}

    n_transcritos = 0
    n_sin_audio_id = 0
    n_descarga_fallo = 0
    n_whisper_fallo = 0
    samples: list = []

    for row in rows:
        msg_id = row["message_id"]
        payload = row.get("payload") or {}
        # WhatsApp Meta payload: payload.raw.audio.id (incoming) o
        # payload.raw.attachments[0].id (outgoing legacy).
        raw = payload.get("raw") or {}
        audio = raw.get("audio") or raw.get("voice") or {}
        media_id = audio.get("id")
        if not media_id:
            # Fallback: buscar en attachments
            atts = raw.get("attachments") or []
            for a in atts:
                if a.get("type") in ("audio", "voice"):
                    media_id = a.get("id") or (a.get("payload") or {}).get("url")
                    break
        if not media_id:
            n_sin_audio_id += 1
            continue

        downloaded = _descargar_audio_meta(media_id)
        if not downloaded:
            n_descarga_fallo += 1
            continue
        audio_bytes, mime = downloaded

        texto = _whisper_transcribe(audio_bytes, mime)
        if not texto:
            n_whisper_fallo += 1
            continue

        # Actualizar mensaje con la transcripción
        nuevo_texto = f"🎤 [audio] {texto[:4500]}"
        try:
            sb.table("messages").update({"message_text": nuevo_texto}).eq("message_id", msg_id).execute()
            n_transcritos += 1
            if len(samples) < 3:
                samples.append({"message_id": msg_id, "preview": texto[:120]})
        except Exception as e:
            log.warning(f"update msg {msg_id}: {e}")

    return {
        "ok": True,
        "procesados": len(rows),
        "transcritos": n_transcritos,
        "sin_audio_id": n_sin_audio_id,
        "descarga_fallo": n_descarga_fallo,
        "whisper_fallo": n_whisper_fallo,
        "samples": samples,
    }
