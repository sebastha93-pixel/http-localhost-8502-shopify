"""
Scheduler de sincronización automática Shopify — Male Denim OS
Corre en segundo plano mientras el dashboard está activo.

Usa threading.Timer para no requerir dependencias externas.
Se inicia automáticamente cuando Streamlit arranca shared.py.
"""

import threading
import time
import os
from datetime import datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))

# ── Cargar .env ───────────────────────────────────────────────────────────────
def _cargar_env() -> None:
    env_path = Path(__file__).parent.parent / ".env"
    if not env_path.exists():
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

_cargar_env()

INTERVALO_HORAS = float(os.environ.get("SHOPIFY_SYNC_INTERVALO_HORAS", "2"))
INTERVALO_SEG   = int(INTERVALO_HORAS * 3600)

_hilo: threading.Timer = None
_ultima_sync: datetime = None
_sync_en_curso: bool   = False
_sync_activo: bool     = False   # se activa solo si las credenciales están OK


def _ejecutar_sync() -> None:
    global _ultima_sync, _sync_en_curso, _hilo

    _sync_en_curso = True
    try:
        from shopify_sync import sincronizar_todo
        sincronizar_todo(dias_pedidos=2)     # sync incremental: últimas 48h
        _ultima_sync = datetime.now()
    except Exception as e:
        print(f"[Shopify Scheduler] Error en sync automático: {e}")
    finally:
        _sync_en_curso = False
        # Programar el siguiente ciclo
        _hilo = threading.Timer(INTERVALO_SEG, _ejecutar_sync)
        _hilo.daemon = True
        _hilo.start()


def iniciar(forzar: bool = False) -> bool:
    """
    Inicia el scheduler si las credenciales están configuradas.
    Retorna True si arrancó, False si faltan credenciales.
    """
    global _hilo, _sync_activo

    if _sync_activo and not forzar:
        return True

    store = os.environ.get("SHOPIFY_STORE", "")
    token = os.environ.get("SHOPIFY_ACCESS_TOKEN", "")

    if not store or not token or "tu-tienda" in store or "xxxx" in token:
        return False

    _sync_activo = True
    # Primera sync después de 10 segundos (no bloquear el arranque del dashboard)
    _hilo = threading.Timer(10, _ejecutar_sync)
    _hilo.daemon = True
    _hilo.start()

    print(f"[Shopify Scheduler] Iniciado — sync cada {INTERVALO_HORAS:.0f}h")
    return True


def detener() -> None:
    global _hilo, _sync_activo
    if _hilo:
        _hilo.cancel()
    _sync_activo = False


def estado() -> dict:
    """Retorna el estado actual del scheduler para mostrar en el dashboard."""
    credenciales_ok = bool(
        os.environ.get("SHOPIFY_ACCESS_TOKEN") and
        "xxxx" not in os.environ.get("SHOPIFY_ACCESS_TOKEN", "xxxx")
    )
    return {
        "activo":           _sync_activo,
        "en_curso":         _sync_en_curso,
        "ultima_sync":      _ultima_sync.strftime("%d/%m/%Y %H:%M") if _ultima_sync else None,
        "intervalo_horas":  INTERVALO_HORAS,
        "credenciales_ok":  credenciales_ok,
        "store":            os.environ.get("SHOPIFY_STORE", "no configurado"),
    }
