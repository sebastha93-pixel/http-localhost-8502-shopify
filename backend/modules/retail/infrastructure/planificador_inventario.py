"""El reloj que mantiene el inventario del POS igual al de Siigo.

Mismo molde que `planificador_outbox`: un hilo demonio en el proceso líder,
que publica su estado para que un hilo caído no pase por «todo normal».

CADA HORA. El inventario de una tienda cambia cuando llega mercancía o se hace
un traslado, que es un par de veces al día; con una hora, lo que entra por la
mañana se puede vender antes del almuerzo. Más seguido no gana nada y son 52
peticiones a Siigo cada vez.
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger("retail.inventario")

__all__ = ["start", "stop", "ultimo", "correr_ahora", "INTERVALO_SEGUNDOS"]

INTERVALO_SEGUNDOS = int(os.environ.get("RETAIL_INVENTARIO_SEC", 3600))
#  Tres minutos después de arrancar: el proceso primero atiende lo urgente.
RETRASO_INICIAL = 180

_hilo: Optional[threading.Thread] = None
_parar = threading.Event()
#  Una sola sincronización a la vez: la del reloj y la que pide una persona
#  no se pisan.
_candado = threading.Lock()

ultimo: dict = {"corrio_en": None, "ok": None, "tiendas": None, "error": None}


def correr_ahora() -> dict:
    """Una pasada. La usa el reloj y el botón del panel."""
    from backend.modules.retail.sincronizar_inventario import sincronizar

    url = os.environ.get("RETAIL_DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("Falta RETAIL_DATABASE_URL.")
    if not _candado.acquire(blocking=False):
        raise RuntimeError("Ya hay una sincronización en curso.")
    try:
        r = sincronizar(url, aplicar=True)
        ultimo.update({
            "corrio_en": datetime.now(timezone.utc).isoformat(), "ok": True,
            "error": None,
            "tiendas": {t: {k: v for k, v in d.items() if k != "problemas"}
                        for t, d in r["tiendas"].items()}})
        for tienda, d in r["tiendas"].items():
            if d["nuevos"] or d["saldos_cambiados"] or d["puestos_en_cero"]:
                log.info("[retail-inventario] %s: %d nuevas, %d saldos, %d en "
                         "cero", tienda, d["nuevos"], d["saldos_cambiados"],
                         d["puestos_en_cero"])
        return r
    except Exception as e:  # noqa: BLE001
        ultimo.update({
            "corrio_en": datetime.now(timezone.utc).isoformat(), "ok": False,
            "error": f"{type(e).__name__}: {e}"[:300]})
        raise
    finally:
        _candado.release()


def _bucle() -> None:
    if _parar.wait(RETRASO_INICIAL):
        return
    while not _parar.is_set():
        try:
            correr_ahora()
        except Exception as e:  # noqa: BLE001 — el hilo no muere por una pasada
            log.error("[retail-inventario] pasada fallida: %s", e)
        _parar.wait(INTERVALO_SEGUNDOS)


def start() -> bool:
    global _hilo
    from backend.modules.retail.interfaces.http import dependencias
    if not dependencias.configurado():
        return False
    if _hilo is not None and _hilo.is_alive():
        return True
    _parar.clear()
    _hilo = threading.Thread(target=_bucle, daemon=True,
                             name="retail-inventario")
    _hilo.start()
    return True


def stop() -> None:
    _parar.set()
