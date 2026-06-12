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

# Dos niveles de refresh:
#  LIGHT: solo fetch Melonn list (rápido, ~3-5 API calls)
#  FULL:  sync_completo (enrich Shopify + Melonn detail + verify states)
# Con webhooks de Melonn activos, el polling solo cubre el caso de webhooks
# perdidos. Pasamos de 15 min a 1 hora — reduce calls del list endpoint ~75%.
REFRESH_LIGHT_SECONDS = int(os.environ.get("SCHEDULER_LIGHT_SEC", 60 * 60))  # 1 hora
# FULL automático DESACTIVADO por defecto — preserva cuota Melonn.
# Si quieres FULL programado, setea SCHEDULER_FULL_SEC en Railway (ej 21600 = 6h).
# Sin esa env var, el FULL solo corre via botón "Sincronizar datos" (manual).
REFRESH_FULL_SECONDS = int(os.environ.get("SCHEDULER_FULL_SEC", 0))           # 0 = nunca

# Pausa de emergencia si Melonn responde 429 — preserva cuota
_cooldown_until: float = 0.0
COOLDOWN_AFTER_429_SEC = 30 * 60   # 30 min de pausa cuando detectamos rate limit

# Compat: variable antigua sigue funcionando para FULL
if os.environ.get("SCHEDULER_INTERVAL_SEC"):
    REFRESH_FULL_SECONDS = int(os.environ["SCHEDULER_INTERVAL_SEC"])

REFRESH_INTERVAL_SECONDS = REFRESH_LIGHT_SECONDS  # tick principal

INITIAL_DELAY_SECONDS = 30

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
    "type": None,           # "light" | "full"
}
_last_full_at: float = 0.0   # timestamp del último FULL sync


def _persistir_datos_cliente_en_overrides() -> None:
    """
    Recorre el caché y hace upsert en pedido_overrides para pedidos que
    tienen nombre/teléfono/ciudad pero NO están aún en overrides (o el
    override está vacío). Así los datos sobreviven cambios de estado.

    Sin saturar API — todo viene del caché en memoria.
    Solo procesa hasta 50 pedidos por tick para no saturar Supabase tampoco.
    """
    from backend.services import melonn as svc
    from backend.services import overrides as overrides_svc

    data = svc.obtener_pedidos(forzar_refresh=False)
    pedidos = data.get("pedidos", [])
    overrides = overrides_svc.cargar_map()

    persistidos = 0
    for p in pedidos:
        if persistidos >= 50:
            break
        nombre = (p.get("nombre_comprador") or "").strip()
        tel    = (p.get("telefono_comprador") or "").strip()
        ciu    = (p.get("ciudad_destino") or "").strip()
        if not (nombre or tel or ciu):
            continue
        orden = p.get("orden_tienda") or p.get("orden_melonn") or ""
        if not orden:
            continue
        # Skip si ya hay un override completo
        ov = overrides.get(orden) or overrides.get(p.get("orden_melonn", ""))
        if ov and ov.get("nombre_comprador") and ov.get("telefono_comprador"):
            continue
        try:
            overrides_svc.upsert(
                orden, nombre=nombre, telefono=tel, ciudad=ciu,
                autor="auto-enrich",
            )
            persistidos += 1
        except Exception:
            continue
    if persistidos:
        log.info(f"Scheduler: persistidos {persistidos} pedidos en overrides")


def _refresh_once(full: bool = False) -> dict:
    """
    Una pasada de refresh.
      full=False (default): solo Melonn list fetch (~5s, barato)
      full=True: sync_completo con enrich + verify states (~30-90s)
    """
    global _last_full_at, _cooldown_until

    # Circuit breaker: si estamos en cooldown por rate-limit, saltar
    now = time.time()
    if now < _cooldown_until:
        remaining = int(_cooldown_until - now)
        log.info(f"Scheduler en cooldown — quedan {remaining}s. Saltando este tick.")
        last_run["type"] = "skipped_cooldown"
        last_run["error"] = f"Cooldown {remaining}s restantes"
        return {"ok": False, "skipped": True, "cooldown_remaining": remaining}

    start = time.time()
    last_run["started_at"] = datetime.now(timezone.utc).isoformat()
    last_run["ok"] = None
    last_run["error"] = None
    last_run["type"] = "full" if full else "light"

    try:
        _SRC = Path(__file__).resolve().parent.parent.parent / "src"
        if str(_SRC) not in sys.path:
            sys.path.insert(0, str(_SRC))
        import melonn_client as mc

        # 1) Fresh fetch desde Melonn API (siempre — barato)
        log.info(f"Scheduler [{last_run['type']}]: refresh Melonn...")
        mc.obtener_pedidos_activos(forzar_refresh=True)

        if not full:
            # Persistir datos del cliente en overrides para que SOBREVIVAN
            # cambios de estado. Sin llamadas a Melonn API (usa el caché).
            try:
                _persistir_datos_cliente_en_overrides()
            except Exception as e:
                log.debug(f"Persist overrides: {e}")
            last_run["ok"] = True
            log.info("Scheduler light: ✓")
            return {"ok": True, "type": "light"}

        # 2) Solo en FULL: enrich + verify states
        log.info("Scheduler: sync_completo...")
        result = mc.sync_completo()
        _last_full_at = time.time()

        last_run["ok"] = bool(result.get("ok"))
        last_run["completados"] = result.get("completados", 0)
        last_run["total"] = result.get("total", 0)
        if not result.get("ok"):
            last_run["error"] = result.get("error") or "sync_completo retornó ok=False"
            log.warning(f"Scheduler full: {last_run['error']}")
        else:
            log.info(f"Scheduler full: ✓ {result.get('completados', 0)} de {result.get('total', 0)}")
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
    """Loop principal del scheduler: tick cada LIGHT, hace FULL cuando toca."""
    log.info(
        f"Scheduler iniciado · primer run en {INITIAL_DELAY_SECONDS}s · "
        f"light cada {REFRESH_LIGHT_SECONDS}s · full cada {REFRESH_FULL_SECONDS}s"
    )

    if _stop_event.wait(INITIAL_DELAY_SECONDS):
        return

    while not _stop_event.is_set():
        # Decide si toca FULL o LIGHT.
        # Si REFRESH_FULL_SECONDS == 0 → FULL nunca corre automáticamente.
        now = time.time()
        full = (
            REFRESH_FULL_SECONDS > 0
            and (now - _last_full_at) >= REFRESH_FULL_SECONDS
        )
        _refresh_once(full=full)

        if _stop_event.wait(REFRESH_LIGHT_SECONDS):
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


def trigger_cooldown(seconds: int = COOLDOWN_AFTER_429_SEC):
    """Pausa el scheduler por N segundos. Llamar cuando Melonn devuelve 429."""
    global _cooldown_until
    _cooldown_until = time.time() + seconds
    log.warning(f"Scheduler pausado {seconds}s por rate-limit Melonn")


def resume_now():
    """Cancela el cooldown — reanuda el scheduler ya."""
    global _cooldown_until
    _cooldown_until = 0.0
    log.info("Scheduler cooldown cancelado manualmente")


def status() -> dict:
    """Estado actual del scheduler — para /api/health/scheduler."""
    now = time.time()
    cooldown_remaining = max(0, int(_cooldown_until - now))
    return {
        "running": _thread is not None and _thread.is_alive(),
        "interval_seconds": REFRESH_LIGHT_SECONDS,
        "light_interval_seconds": REFRESH_LIGHT_SECONDS,
        "full_interval_seconds": REFRESH_FULL_SECONDS,
        "cooldown_remaining_seconds": cooldown_remaining,
        "last_run": last_run,
    }
