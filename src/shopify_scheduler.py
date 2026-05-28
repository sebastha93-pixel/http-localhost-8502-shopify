"""
Scheduler de sincronización automática Shopify — Male Denim OS

Estrategia dual (robusta en Streamlit Cloud):

  1. Sync-on-load: al abrir la página, compara la última sync guardada en la DB
     con el intervalo configurado. Si está desactualizada, sincroniza al instante.
     Funciona aunque la app haya estado dormida horas/días.

  2. Hilo de fondo (threading.Timer): mantiene los datos frescos mientras la app
     está activa y con usuarios. Se cancela solo si el proceso muere (sleep).

El método sincronizar_si_necesario() combina ambas estrategias y es el
único punto de entrada que debe llamar el dashboard.
"""

import threading
import os
from datetime import datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))

# ── Cargar .env localmente (Streamlit Cloud usa sus propias Secrets) ───────────
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

_hilo:           threading.Timer = None
_ultima_sync:    datetime        = None   # en memoria (se pierde con el sleep)
_sync_en_curso:  bool            = False
_sync_activo:    bool            = False
_lock:           threading.Lock  = threading.Lock()


# ── Credenciales ───────────────────────────────────────────────────────────────
def _credenciales_ok() -> bool:
    token = os.environ.get("SHOPIFY_ACCESS_TOKEN", "")
    store = os.environ.get("SHOPIFY_STORE", "")
    return bool(store and token
                and "xxxx" not in token.lower()
                and "tu-tienda" not in store.lower())


# ── Última sync desde la DB (persiste aunque el proceso se haya reiniciado) ───
def _ultima_sync_db() -> datetime | None:
    try:
        from db import get_conn
        with get_conn() as conn:
            row = conn.execute(
                "SELECT MAX(iniciada_en) FROM shopify_sync_log WHERE estado='ok'"
            ).fetchone()
            if row and row[0]:
                return datetime.fromisoformat(row[0])
    except Exception:
        pass
    return None


# ── Comprueba si los datos están desactualizados ───────────────────────────────
def datos_desactualizados() -> bool:
    """True si han pasado más de INTERVALO_HORAS desde la última sync exitosa."""
    ultima = _ultima_sync or _ultima_sync_db()
    if not ultima:
        return True
    horas = (datetime.now() - ultima).total_seconds() / 3600
    return horas >= INTERVALO_HORAS


# ── Sync inmediata (bloquea el hilo que la llame) ─────────────────────────────
def _ejecutar_sync_interna(dias_pedidos: int = 2) -> bool:
    global _ultima_sync, _sync_en_curso
    with _lock:
        if _sync_en_curso:
            return False
        _sync_en_curso = True

    try:
        from shopify_sync import sincronizar_todo
        sincronizar_todo(dias_pedidos=dias_pedidos)
        _ultima_sync = datetime.now()
        return True
    except Exception as e:
        print(f"[Shopify Scheduler] Error sync: {e}")
        return False
    finally:
        _sync_en_curso = False


# ── Sync-on-load: punto de entrada principal ──────────────────────────────────
def sincronizar_si_necesario(dias_pedidos: int = 2) -> bool:
    """
    Llama desde el dashboard al inicio de cada sesión.
    Sincroniza solo si los datos están desactualizados. Retorna True si sincronizó.
    """
    if not _credenciales_ok():
        return False
    if _sync_en_curso:
        return False
    if not datos_desactualizados():
        return False

    return _ejecutar_sync_interna(dias_pedidos=dias_pedidos)


# ── Hilo de fondo (se programa a sí mismo cada INTERVALO_SEG) ─────────────────
def _ciclo_hilo() -> None:
    global _hilo
    _ejecutar_sync_interna(dias_pedidos=2)
    # Reprogramar solo si el scheduler sigue activo
    if _sync_activo:
        _hilo = threading.Timer(INTERVALO_SEG, _ciclo_hilo)
        _hilo.daemon = True
        _hilo.start()


def iniciar(forzar: bool = False) -> bool:
    """
    Inicia el hilo de fondo si las credenciales están OK.
    El hilo espera INTERVALO_SEG antes de su primera ejecución
    (la sync inmediata del load ya habrá corrido).
    """
    global _hilo, _sync_activo

    if _sync_activo and not forzar:
        return True

    if not _credenciales_ok():
        return False

    _sync_activo = True
    _hilo = threading.Timer(INTERVALO_SEG, _ciclo_hilo)
    _hilo.daemon = True
    _hilo.start()
    print(f"[Shopify Scheduler] Hilo activo — sync cada {INTERVALO_HORAS:.0f}h")
    return True


def detener() -> None:
    global _hilo, _sync_activo
    _sync_activo = False
    if _hilo:
        _hilo.cancel()


# ── Estado para el dashboard ──────────────────────────────────────────────────
def estado() -> dict:
    ultima = _ultima_sync or _ultima_sync_db()
    credok = _credenciales_ok()
    horas_desde = None
    if ultima:
        horas_desde = round((datetime.now() - ultima).total_seconds() / 3600, 1)
    return {
        "activo":           _sync_activo,
        "en_curso":         _sync_en_curso,
        "ultima_sync":      ultima.strftime("%d/%m/%Y %H:%M") if ultima else None,
        "horas_desde_sync": horas_desde,
        "intervalo_horas":  INTERVALO_HORAS,
        "credenciales_ok":  credok,
        "store":            os.environ.get("SHOPIFY_STORE", "no configurado"),
        "desactualizado":   datos_desactualizados(),
    }
