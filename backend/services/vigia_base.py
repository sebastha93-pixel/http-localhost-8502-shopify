"""
backend.services.vigia_base — Alarma cuando la base de datos deja de responder.

POR QUÉ (17-nov-2026): la base de Supabase dejó de aceptar conexiones a las
8:57 y nadie se enteró hasta que Sebastián no pudo entrar, pasadas las 10:30.
El backend seguía "online" para Railway; lo que estaba muerto era la base, y
la página de estado de Supabase decía "todo operativo".

CÓMO: el worker líder hace una consulta mínima a la base cada 2 minutos. Tras 3
fallos seguidos (~6 min, para no despertar a nadie por un parpadeo) manda un
correo con qué hacer; mientras siga caída, recuerda cada 30 minutos; cuando
vuelve, avisa que volvió y cuánto duró.

EL AVISO NO PUEDE DEPENDER DE LA BASE: nada de campanita (vive en la base).
Va por correo (Resend, sin base) y, si se configura una plantilla aprobada de
WhatsApp (ALERTA_BASE_WHATSAPP + ALERTA_BASE_PLANTILLA), también por WhatsApp:
Meta no deja escribir texto libre a quien no escribió en las últimas 24 h.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import httpx


log = logging.getLogger(__name__)

INTERVALO_SEG = int(os.environ.get("VIGIA_BASE_SEC", 120))
FALLOS_PARA_ALERTA = int(os.environ.get("VIGIA_BASE_FALLOS", 3))
RECORDAR_CADA_SEG = int(os.environ.get("VIGIA_BASE_RECORDAR_SEC", 30 * 60))
TIMEOUT_SEG = 10
_BOGOTA = ZoneInfo("America/Bogota")

_estado: dict = {
    "fallos_seguidos": 0,
    "caida_desde": None,      # datetime UTC del primer fallo de la racha
    "alertado_at": None,      # datetime UTC del último aviso de caída
    "ultimo_ok": None,
    "ultimo_error": "",
    "ultima_latencia_ms": None,
}
_thread: Optional[threading.Thread] = None
_stop = threading.Event()


def _destinatarios() -> list[str]:
    raw = (os.environ.get("ALERTA_BASE_EMAILS")
           or os.environ.get("LAVANDERIA_ESCALA_EMAILS")
           or "sebastian.hurtado@maledenim.com")
    return [e.strip().lower() for e in raw.split(",") if e.strip()]


def probar(timeout: float = TIMEOUT_SEG) -> tuple:
    """(ok, detalle, latencia_ms) de una consulta mínima a la base por PostgREST.

    Lee la fila 2 de melonn_cache (45 bytes): toca Postgres de verdad pero no
    le cuesta nada. Un 522/timeout aquí es exactamente lo que pasó el 17-nov."""
    url = (os.environ.get("SUPABASE_URL") or "").strip().rstrip("/")
    key = (os.environ.get("SUPABASE_KEY") or "").strip()
    if not url or not key:
        return True, "sin_credenciales", None   # sin base configurada no hay a quién vigilar
    t0 = time.monotonic()
    try:
        r = httpx.get(f"{url}/rest/v1/melonn_cache",
                      params={"select": "id", "id": "eq.2"},
                      headers={"apikey": key, "Authorization": f"Bearer {key}"},
                      timeout=timeout)
        ms = round((time.monotonic() - t0) * 1000)
        if r.status_code == 200:
            return True, "ok", ms
        return False, f"HTTP {r.status_code}", ms
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:120]}", None


def _hora(dt: datetime) -> str:
    return dt.astimezone(_BOGOTA).strftime("%-I:%M %p").lower().replace("am", "a. m.").replace("pm", "p. m.")


def _duracion(seg: float) -> str:
    m = int(seg // 60)
    if m < 60:
        return f"{m} min"
    return f"{m // 60} h {m % 60:02d} min"


def _avisar(asunto: str, cuerpo_html: str, texto_corto: str) -> int:
    enviados = 0
    try:
        from backend.services import correo
        if correo.disponible():
            for email in _destinatarios():
                r = correo.enviar(para=email, asunto=asunto, html=cuerpo_html, texto=texto_corto)
                enviados += 1 if r.get("ok") else 0
        else:
            log.error(f"[vigia-base] sin RESEND_API_KEY: no pude avisar «{asunto}»")
    except Exception as e:
        log.error(f"[vigia-base] el correo falló: {str(e)[:160]}")
    tel = (os.environ.get("ALERTA_BASE_WHATSAPP") or "").strip()
    plantilla = (os.environ.get("ALERTA_BASE_PLANTILLA") or "").strip()
    if tel and plantilla:
        try:
            from backend.services import whatsapp_cloud as wa
            for t in [x.strip() for x in tel.split(",") if x.strip()]:
                r = wa.enviar_plantilla(t, plantilla, variables=[texto_corto[:900]])
                enviados += 1 if r.get("enviado") else 0
        except Exception as e:
            log.error(f"[vigia-base] el WhatsApp falló: {str(e)[:160]}")
    return enviados


def revisar_una_vez(ahora: Optional[datetime] = None) -> dict:
    """Una vuelta del vigía. Devuelve qué hizo (para pruebas y el health)."""
    ahora = ahora or datetime.now(timezone.utc)
    ok, detalle, ms = probar()
    e = _estado
    if ok:
        accion = "ok"
        if e["alertado_at"] is not None and e["caida_desde"] is not None:
            dur = (ahora - e["caida_desde"]).total_seconds()
            _avisar(
                "🟢 La base de datos del OS volvió",
                f"<p>La base de datos volvió a responder a las <b>{_hora(ahora)}</b>.</p>"
                f"<p>Estuvo caída <b>{_duracion(dur)}</b> (desde las {_hora(e['caida_desde'])}). "
                f"El OS y el POS ya deberían funcionar; si alguien sigue sin poder entrar, "
                f"que recargue la página.</p>",
                f"La base del OS volvió a las {_hora(ahora)}; estuvo caída {_duracion(dur)}.")
            accion = "aviso_volvio"
        e.update({"fallos_seguidos": 0, "caida_desde": None, "alertado_at": None,
                  "ultimo_ok": ahora, "ultimo_error": "", "ultima_latencia_ms": ms})
        return {"accion": accion, "detalle": detalle}

    e["fallos_seguidos"] += 1
    e["ultimo_error"] = detalle
    if e["caida_desde"] is None:
        e["caida_desde"] = ahora
    log.warning(f"[vigia-base] la base no respondió ({e['fallos_seguidos']} seguidos): {detalle}")
    if e["fallos_seguidos"] < FALLOS_PARA_ALERTA:
        return {"accion": "fallo", "detalle": detalle}
    ya = e["alertado_at"]
    if ya is not None and (ahora - ya).total_seconds() < RECORDAR_CADA_SEG:
        return {"accion": "fallo_ya_avisado", "detalle": detalle}
    dur = (ahora - e["caida_desde"]).total_seconds()
    recordatorio = ya is not None
    _avisar(
        ("🔴 SIGUE CAÍDA la base de datos del OS" if recordatorio
         else "🔴 La base de datos del OS no responde"),
        f"<p>La base de datos no responde desde las <b>{_hora(e['caida_desde'])}</b> "
        f"(hace {_duracion(dur)}). Mientras tanto <b>nadie puede entrar al OS y el POS de "
        f"las tiendas no cobra</b>.</p>"
        f"<p><b>Qué hacer:</b> entra a Supabase → proyecto «sebastha93-pixel's Project» → "
        f"Project Settings → General → <b>Restart project</b>, o escríbele a Claude "
        f"«la base está caída».</p>"
        f"<p style='color:#888'>Detalle técnico: {detalle}</p>",
        f"La base del OS no responde desde las {_hora(e['caida_desde'])} "
        f"({_duracion(dur)}). OS y POS caídos. Reiniciar en Supabase → Settings → General → "
        f"Restart project.")
    e["alertado_at"] = ahora
    return {"accion": "recordatorio" if recordatorio else "aviso_caida", "detalle": detalle}


def _loop():
    log.info(f"[vigia-base] vigilando la base cada {INTERVALO_SEG}s "
             f"(aviso tras {FALLOS_PARA_ALERTA} fallos)")
    if _stop.wait(20):
        return
    while not _stop.is_set():
        try:
            revisar_una_vez()
        except Exception as e:
            log.warning(f"[vigia-base] la vuelta falló: {str(e)[:160]}")
        if _stop.wait(INTERVALO_SEG):
            break


def arrancar() -> threading.Thread:
    """Arranca el vigía en un hilo (solo el worker líder). Idempotente."""
    global _thread
    if _thread is not None and _thread.is_alive():
        return _thread
    _stop.clear()
    _thread = threading.Thread(target=_loop, daemon=True, name="vigia-base")
    _thread.start()
    return _thread


def estado() -> dict:
    e = _estado
    return {
        "vivo": _thread is not None and _thread.is_alive(),
        "fallos_seguidos": e["fallos_seguidos"],
        "caida_desde": e["caida_desde"].isoformat() if e["caida_desde"] else None,
        "alertado_at": e["alertado_at"].isoformat() if e["alertado_at"] else None,
        "ultimo_ok": e["ultimo_ok"].isoformat() if e["ultimo_ok"] else None,
        "ultimo_error": e["ultimo_error"],
        "ultima_latencia_ms": e["ultima_latencia_ms"],
    }
