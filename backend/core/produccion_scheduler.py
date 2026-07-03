"""
backend.core.produccion_scheduler — Resumen diario de alertas de producción.

Cada mañana a las HORA_OBJETIVO_BOG (default 6:30 AM Bogotá, UTC-5) calcula
las alertas de producción (stock bajo + lotes estancados + cruce Siigo) y,
si hay alguna, envía el resumen por correo vía Resend.

ENV:
  PRODUCCION_DIGEST_EMAILS  — destinatarios separados por coma
                              (default sebastian.hurtado@maledenim.com)
  PRODUCCION_DIGEST_HORA    — hora Bogotá del envío (default 6, es decir 6:30)
  RESEND_API_KEY / RESEND_FROM — ya usados por el correo de orden de corte

Sigue el patrón threading + Event de los demás schedulers (sin apscheduler).
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)

_thread: threading.Thread | None = None
_stop_event = threading.Event()

HORA_OBJETIVO_BOG = int(os.environ.get("PRODUCCION_DIGEST_HORA", "6"))
MINUTO_OBJETIVO = 30
BOGOTA = timezone(timedelta(hours=-5))

_estado: dict = {"last_run_at": None, "last_result": None}


def _destinatarios() -> list[str]:
    raw = os.environ.get("PRODUCCION_DIGEST_EMAILS",
                         "sebastian.hurtado@maledenim.com")
    return [e.strip() for e in raw.split(",") if e.strip()]


def _armar_cuerpo(data: dict) -> str:
    lineas = [
        f"Resumen de producción MALE'DENIM · {datetime.now(BOGOTA).strftime('%Y-%m-%d %H:%M')} Bogotá",
        f"Alertas activas: {data['total']} ({data['altas']} de severidad alta)",
        "",
    ]
    EMOJI = {"alta": "🔴", "media": "🟡", "baja": "⚪"}
    for a in data["alertas"]:
        lineas.append(f"{EMOJI.get(a.get('severidad'), '⚪')} [{a.get('tipo')}] {a.get('mensaje')}")
    lineas += [
        "",
        "Detalle del cruce: https://app.maledenim.com/produccion/costeo",
        "Tablero: https://app.maledenim.com/produccion/tablero",
    ]
    return "\n".join(lineas)


def enviar_digest(force: bool = False) -> dict:
    """Calcula las alertas y envía el correo. `force=True` envía aunque no
    haya alertas (para probar el canal)."""
    from backend.services import produccion as svc

    data = svc.alertas_produccion(incluir_costeo=True)
    _estado["last_run_at"] = datetime.now(timezone.utc).isoformat()

    if data["total"] == 0 and not force:
        _estado["last_result"] = {"ok": True, "enviado": False, "motivo": "sin_alertas"}
        log.info("[digest-produccion] sin alertas — no se envía correo")
        return _estado["last_result"]

    resend_key = os.environ.get("RESEND_API_KEY", "").strip()
    if not resend_key:
        _estado["last_result"] = {"ok": False, "error": "sin_RESEND_API_KEY"}
        return _estado["last_result"]

    import httpx
    asunto = (f"⚠️ Producción: {data['total']} alerta(s)"
              if data["total"] else "Producción: sin alertas hoy ✅")
    cuerpo = _armar_cuerpo(data)
    dest = _destinatarios()
    try:
        r = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {resend_key}",
                     "Content-Type": "application/json"},
            json={
                "from": os.environ.get("RESEND_FROM", "orden-corte@maledenim.com").strip(),
                "to": dest,
                "subject": asunto,
                "text": cuerpo,
            },
            timeout=20.0,
        )
        ok = r.status_code < 400
        _estado["last_result"] = {
            "ok": ok, "enviado": ok, "destinatarios": dest,
            "alertas": data["total"],
            "error": None if ok else r.text[:200],
        }
        log.info(f"[digest-produccion] enviado={ok} alertas={data['total']} → {dest}")
    except Exception as e:
        _estado["last_result"] = {"ok": False, "error": str(e)[:300]}
        log.exception(f"[digest-produccion] fallo: {e}")
    return _estado["last_result"]


def _segundos_hasta_proximo() -> float:
    now = datetime.now(BOGOTA)
    objetivo = now.replace(hour=HORA_OBJETIVO_BOG, minute=MINUTO_OBJETIVO,
                           second=0, microsecond=0)
    if objetivo <= now:
        objetivo += timedelta(days=1)
    return (objetivo - now).total_seconds()


def _loop():
    log.info(f"[digest-produccion] cron activo · {HORA_OBJETIVO_BOG}:{MINUTO_OBJETIVO:02d} AM Bogotá")
    while not _stop_event.is_set():
        espera = _segundos_hasta_proximo()
        # Dormir en bloques de 60s para responder al stop
        while espera > 0 and not _stop_event.is_set():
            tick = min(60.0, espera)
            if _stop_event.wait(timeout=tick):
                return
            espera -= tick
        if _stop_event.is_set():
            return
        try:
            enviar_digest()
        except Exception as e:
            log.exception(f"[digest-produccion] error en tick: {e}")


def start() -> bool:
    global _thread
    if _thread is not None and _thread.is_alive():
        return False
    _stop_event.clear()
    _thread = threading.Thread(target=_loop, daemon=True, name="produccion-digest")
    _thread.start()
    return True


def stop():
    _stop_event.set()


def status() -> dict:
    return {
        "running": _thread is not None and _thread.is_alive(),
        "hora_objetivo_bogota": f"{HORA_OBJETIVO_BOG}:{MINUTO_OBJETIVO:02d}",
        "destinatarios": _destinatarios(),
        **_estado,
    }
