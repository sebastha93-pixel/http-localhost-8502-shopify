"""
backend.core.bot_scheduler — Cron del bot scraper de guías Melonn.

Cada BOT_INTERVAL_SEC procesa un lote de BOT_LOTE pedidos activos sin guía.
Como el bot guarda incremental y salta los que ya tienen guía, va cubriendo
todos los pendientes progresivamente sin reprocesar.

Activación: setear BOT_AUTO_ENABLED=true en Railway. Desactivado por defecto.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Optional


log = logging.getLogger(__name__)

# Config (env vars) — tracking PÚBLICO: sin bloqueo, podemos ir más rápido
BOT_AUTO_ENABLED = os.environ.get("BOT_AUTO_ENABLED", "false").lower() == "true"
BOT_INTERVAL_SEC = int(os.environ.get("BOT_INTERVAL_SEC", 20 * 60))   # cada 20 min
BOT_LOTE         = int(os.environ.get("BOT_LOTE", 25))                # 25 por lote
BOT_INITIAL_DELAY = 120                                               # 2 min tras boot

# Tope diario de seguridad
BOT_MAX_DIARIO = int(os.environ.get("BOT_MAX_DIARIO", 400))

_thread: Optional[threading.Thread] = None
_stop = threading.Event()

estado: dict = {
    "enabled": BOT_AUTO_ENABLED,
    "interval_seconds": BOT_INTERVAL_SEC,
    "lote": BOT_LOTE,
    "ultimo_run": None,
    "procesados_hoy": 0,
    "fecha_contador": None,
    "ultimo_resultado": None,
}


def _hoy() -> str:
    return (datetime.now(timezone.utc)).date().isoformat()


def _loop():
    log.info(
        f"Bot scheduler iniciado · lote={BOT_LOTE} cada {BOT_INTERVAL_SEC}s · "
        f"tope diario {BOT_MAX_DIARIO}"
    )
    if _stop.wait(BOT_INITIAL_DELAY):
        return

    while not _stop.is_set():
        try:
            # Reset contador diario
            if estado["fecha_contador"] != _hoy():
                estado["fecha_contador"] = _hoy()
                estado["procesados_hoy"] = 0

            # Respetar tope diario
            if estado["procesados_hoy"] >= BOT_MAX_DIARIO:
                log.info(f"Bot scheduler: tope diario {BOT_MAX_DIARIO} alcanzado")
            else:
                from backend.api.bot import iniciar_run, _bot_state
                # No arrancar si ya hay un run manual en curso
                if not _bot_state.get("running"):
                    r = iniciar_run(BOT_LOTE, autor="Cron", solo_sin_guia=True)
                    estado["ultimo_run"] = datetime.now(timezone.utc).isoformat()
                    estado["ultimo_resultado"] = r
                    if r.get("ok"):
                        # Esperar a que termine este lote antes del próximo tick
                        log.info(f"Bot scheduler: lote de {r.get('total')} iniciado")
                        # Poll hasta que termine (máx 15 min)
                        wait_until = time.time() + 15 * 60
                        while time.time() < wait_until and not _stop.is_set():
                            if not _bot_state.get("running"):
                                break
                            time.sleep(10)
                        estado["procesados_hoy"] += _bot_state.get("processed", 0)
                    else:
                        log.info(f"Bot scheduler: sin trabajo ({r.get('error')})")
        except Exception as e:
            log.exception(f"Bot scheduler error: {e}")

        if _stop.wait(BOT_INTERVAL_SEC):
            break

    log.info("Bot scheduler detenido.")


def start():
    global _thread
    if not BOT_AUTO_ENABLED:
        log.info("Bot scheduler DESACTIVADO (BOT_AUTO_ENABLED no es true)")
        return None
    if _thread is not None and _thread.is_alive():
        return _thread
    _stop.clear()
    _thread = threading.Thread(target=_loop, daemon=True, name="bot_scheduler")
    _thread.start()
    return _thread


def stop():
    _stop.set()


def status() -> dict:
    return {**estado, "running": _thread is not None and _thread.is_alive()}
