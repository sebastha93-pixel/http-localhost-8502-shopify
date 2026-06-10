"""
backend.core.scheduler — Refresca caché Melonn + enriquecimiento cada N min.

Daemon thread que corre dentro del mismo proceso FastAPI. Sin dependencias
externas (Redis, Celery, etc.). Se detiene automáticamente al apagar el
servidor.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


log = logging.getLogger(__name__)

# Intervalo configurable vía env var (segundos). Default: 15 min.
REFRESH_INTERVAL_SECONDS = int(os.environ.get("SCHEDULER_INTERVAL_SEC", 15 * 60))

# Delay inicial antes del primer run (evita pelearse con bootstrap del proceso)
INITIAL_DELAY_SECONDS = 60

_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()

# Estado expuesto para health-check
last_run: dict = {
    "started_at": None,
    "finished_at": None,
    "ok": None,
    "duration_seconds": None,
    "completados": 0,
    "total": 0,
    "error": None,
}


def _refresh_once() -> dict:
    """Una pasada completa: refresh Melonn + lazy enrich + sync exhaustivo."""
    start = time.time()
    last_run["started_at"] = datetime.now(timezone.utc).isoformat()
    last_run["ok"] = None
    last_run["error"] = None

    try:
        # Asegurar que src/ está en path
        _SRC = Path(__file__).resolve().parent.parent.parent / "src"
        if str(_SRC) not in sys.path:
            sys.path.insert(0, str(_SRC))
        import melonn_client as mc

        # 1) Fresh fetch desde Melonn API (actualiza estado + nuevos pedidos)
        log.info("Scheduler: refresh Melonn...")
        mc.obtener_pedidos_activos(forzar_refresh=True)

        # 2) Pasada exhaustiva de enriquecimiento (Shopify + Melonn detail)
        log.info("Scheduler: sync_completo...")
        result = mc.sync_completo()

        last_run["ok"] = True
        last_run["completados"] = result.get("completados", 0)
        last_run["total"] = result.get("total", 0)
        log.info(f"Scheduler: ✓ {result.get('completados', 0)} pedidos completados de {result.get('total', 0)}")
        return result
    except Exception as e:
        last_run["ok"] = False
        last_run["error"] = str(e)
        log.exception(f"Scheduler error: {e}")
        return {"ok": False, "error": str(e)}
    finally:
        last_run["finished_at"] = datetime.now(timezone.utc).isoformat()
        last_run["duration_seconds"] = round(time.time() - start, 1)


def _loop():
    """Loop principal del scheduler."""
    log.info(f"Scheduler iniciado · primer run en {INITIAL_DELAY_SECONDS}s · luego cada {REFRESH_INTERVAL_SECONDS}s")

    # Delay inicial (no bloquear startup)
    if _stop_event.wait(INITIAL_DELAY_SECONDS):
        return

    while not _stop_event.is_set():
        _refresh_once()
        # Espera con poll para poder detenerse rápido
        if _stop_event.wait(REFRESH_INTERVAL_SECONDS):
            break

    log.info("Scheduler detenido.")


def start() -> threading.Thread:
    """Arranca el scheduler en un daemon thread. Idempotente."""
    global _thread
    if _thread is not None and _thread.is_alive():
        return _thread
    _stop_event.clear()
    _thread = threading.Thread(target=_loop, daemon=True, name="scheduler")
    _thread.start()
    return _thread


def stop():
    """Detiene el scheduler (al apagar el servidor)."""
    _stop_event.set()


def status() -> dict:
    """Estado actual del scheduler — para /api/health/scheduler."""
    return {
        "running": _thread is not None and _thread.is_alive(),
        "interval_seconds": REFRESH_INTERVAL_SECONDS,
        "last_run": last_run,
    }
