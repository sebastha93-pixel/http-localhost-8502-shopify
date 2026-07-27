"""
backend.services.personal_base — Cimientos compartidos del módulo Personal.

Patrón: espeja backend/services/produccion.py y revenue_db.py (cliente lazy
singleton leyendo os.environ directo, caché en memoria con TTL por worker).

Diferencia deliberada con el resto del repo
───────────────────────────────────────────
El proyecto repite el bloque `_sb()` en ~14 módulos. Para un módulo con 10
servicios eso serían 10 copias del mismo código. Aquí se centraliza UNA vez y
los servicios de Personal importan de aquí. Sigue siendo "cada módulo dueño de
su cliente" —que es el espíritu del patrón— sin la copia absurda.

Zona horaria
────────────
Colombia es UTC-5 fijo, sin horario de verano. Se usa offset fijo igual que
produccion_scheduler.py. Si algún día hay sede en otro huso, la zona se lee de
personal_sedes.timezone y este default deja de aplicar.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from supabase import Client, create_client

log = logging.getLogger(__name__)


# ── Zona horaria ─────────────────────────────────────────────────────────────

BOGOTA = timezone(timedelta(hours=-5))
TZ_DEFECTO = "America/Bogota"


def ahora_utc() -> datetime:
    return datetime.now(timezone.utc)


def ahora_bogota() -> datetime:
    return datetime.now(BOGOTA)


def hoy_bogota() -> date:
    """La fecha 'de hoy' según Bogotá, no según el reloj UTC del servidor.

    A las 20:00 de Bogotá ya son las 01:00 UTC del día siguiente. Usar
    date.today() en Railway adelantaría un día la jornada de la noche.
    """
    return ahora_bogota().date()


def _now_iso() -> str:
    return ahora_utc().isoformat()


# ── Cliente Supabase ─────────────────────────────────────────────────────────

_client: Optional[Client] = None


def _sb() -> Optional[Client]:
    global _client
    if _client is not None:
        return _client
    url = (os.environ.get("SUPABASE_URL") or "").strip()
    key = (os.environ.get("SUPABASE_KEY") or "").strip()
    if not url or not key:
        return None
    try:
        _client = create_client(url, key)
        return _client
    except Exception as e:
        log.warning(f"[personal] Supabase client failed: {e}")
        return None


def sb_requerido() -> Client:
    """Para escrituras: falla ruidosamente si no hay Supabase.

    Las lecturas usan _sb() y degradan a lista vacía; las escrituras NO deben
    fingir que funcionaron.
    """
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase no configurado")
    return sb


class TablaNoExiste(RuntimeError):
    """La migración del módulo no se ha aplicado todavía.

    Se distingue de un error genérico para que el API responda 503 con una
    instrucción accionable en vez de un 500 opaco.
    """


def es_error_tabla_faltante(e: Exception) -> bool:
    """¿El error viene de que la migración no está aplicada?

    Postgres devuelve 42P01 (undefined_table); PostgREST lo envuelve con
    'does not exist' o 'schema cache'. Se chequean las tres formas porque
    la librería no expone el código de forma estable.
    """
    msg = str(e).lower()
    return (
        "42p01" in msg
        or "does not exist" in msg
        or ("relation" in msg and "not" in msg and "exist" in msg)
        or ("could not find the table" in msg)
        or ("schema cache" in msg and "personal_" in msg)
    )


# ── Caché en memoria por worker ──────────────────────────────────────────────
# Igual que produccion.py, pero SIN el bug de aquel: allí _cache_get recibe
# ttl_seg y no lo usa, así que el TTL real es el que se pasó en _cache_set.
# Aquí el TTL se fija una sola vez, al escribir, y no se pide al leer.

_CACHE: dict[str, tuple[float, Any]] = {}


def cache_get(key: str) -> Any:
    """Devuelve el valor cacheado, o None si no existe o expiró."""
    hit = _CACHE.get(key)
    if not hit:
        return None
    expira_en, valor = hit
    if time.time() > expira_en:
        _CACHE.pop(key, None)
        return None
    return valor


def cache_set(key: str, valor: Any, ttl_seg: int) -> Any:
    _CACHE[key] = (time.time() + ttl_seg, valor)
    return valor


def cache_invalidar(prefijo: str = "") -> int:
    """Invalida las claves que empiezan por `prefijo`. Sin prefijo, todo.

    Devuelve cuántas claves se limpiaron — útil para log y para test.
    """
    claves = [k for k in _CACHE if k.startswith(prefijo)]
    for k in claves:
        _CACHE.pop(k, None)
    return len(claves)


# ── Enmascaramiento de datos técnicos ────────────────────────────────────────
# Serial e IP identifican equipos físicos. Un usuario de RRHH no necesita
# verlos, y exponerlos amplía la superficie de ataque sin beneficio.


def enmascarar_ip(ip: Optional[str]) -> Optional[str]:
    """192.168.1.50 → 192.168.x.x · deja ver la red, oculta el host."""
    if not ip:
        return ip
    partes = str(ip).split(".")
    if len(partes) == 4:
        return f"{partes[0]}.{partes[1]}.x.x"
    return "···"


def enmascarar_serie(serie: Optional[str]) -> Optional[str]:
    """ABC123456789 → ABC…789 · suficiente para distinguir equipos."""
    if not serie:
        return serie
    s = str(serie)
    if len(s) <= 6:
        return "···"
    return f"{s[:3]}…{s[-3:]}"


def enmascarar_documento(doc: Optional[str]) -> Optional[str]:
    """1234567890 → ···7890 · para listados donde no hace falta el número."""
    if not doc:
        return doc
    s = str(doc)
    return f"···{s[-4:]}" if len(s) > 4 else "···"


# ── Utilidades de tiempo laboral ─────────────────────────────────────────────


def minutos_entre(inicio: datetime, fin: datetime) -> int:
    """Minutos completos entre dos instantes. Nunca negativo.

    Se trunca (no redondea) a propósito: reconocer 7 minutos cuando se
    trabajaron 7.9 es conservador y defendible; reconocer 8 no lo es.
    """
    if inicio is None or fin is None:
        return 0
    delta = (fin - inicio).total_seconds()
    return max(0, int(delta // 60))


def minutos_a_hhmm(minutos: int) -> str:
    """450 → '7h 30m'. Para mostrar, nunca para calcular."""
    m = int(minutos or 0)
    signo = "-" if m < 0 else ""
    m = abs(m)
    h, resto = divmod(m, 60)
    if h and resto:
        return f"{signo}{h}h {resto}m"
    if h:
        return f"{signo}{h}h"
    return f"{signo}{resto}m"


def quincena_de(f: date) -> tuple[date, date]:
    """Periodo quincenal que contiene la fecha dada.

    MALE DENIM cierra nómina el 15 y el último día del mes.
    Devuelve (inicio, fin) inclusive.
    """
    if f.day <= 15:
        return date(f.year, f.month, 1), date(f.year, f.month, 15)
    if f.month == 12:
        ultimo = date(f.year, 12, 31)
    else:
        ultimo = date(f.year, f.month + 1, 1) - timedelta(days=1)
    return date(f.year, f.month, 16), ultimo
