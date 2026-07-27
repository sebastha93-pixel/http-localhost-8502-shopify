"""
backend.services.personal_organizacion — Sedes y áreas.

Catálogos pequeños y estables (2 sedes, 3-5 áreas). Se cachean 60 s porque los
lee casi todo el módulo para filtros y reportes, y cambian una vez al año.

La sede importa más de lo que parece: de ella sale la zona horaria con la que
se interpreta cada marcación. Hoy todo es America/Bogota (UTC-5 fijo, sin
horario de verano), pero el campo existe desde el principio para que abrir
sede en otro huso no obligue a rediseñar el motor.
"""
from __future__ import annotations

import logging
from typing import Optional

from backend.services import personal_auditoria as aud
from backend.services.personal_base import (
    _now_iso, _sb, cache_get, cache_invalidar, cache_set,
    es_error_tabla_faltante, sb_requerido, TZ_DEFECTO,
)

log = logging.getLogger(__name__)

_CACHE_PREFIJO = "personal:org:"
_CACHE_TTL = 60


# ── Sedes ────────────────────────────────────────────────────────────────────

def listar_sedes(*, solo_activas: bool = False) -> list[dict]:
    key = f"{_CACHE_PREFIJO}sedes:{solo_activas}"
    cacheado = cache_get(key)
    if cacheado is not None:
        return cacheado
    sb = _sb()
    if sb is None:
        return []
    try:
        q = sb.table("personal_sedes").select("*")
        if solo_activas:
            q = q.eq("activa", True)
        filas = (q.order("nombre").execute().data) or []
    except Exception as e:
        if not es_error_tabla_faltante(e):
            log.error(f"[personal.org] error listando sedes: {e}")
        return []
    return cache_set(key, filas, _CACHE_TTL)


def obtener_sede(sede_id: str) -> Optional[dict]:
    return next((s for s in listar_sedes() if s.get("id") == sede_id), None)


def timezone_de_sede(sede_id: Optional[str]) -> str:
    """Zona horaria con la que interpretar las marcaciones de esa sede."""
    if not sede_id:
        return TZ_DEFECTO
    sede = obtener_sede(sede_id)
    return (sede or {}).get("timezone") or TZ_DEFECTO


def crear_sede(*, nombre: str, direccion: str = "", timezone: str = TZ_DEFECTO,
               actor: str = "sistema") -> dict:
    if not (nombre or "").strip():
        raise ValueError("campo_requerido:nombre")
    sb = sb_requerido()
    fila = {"nombre": nombre.strip(), "direccion": direccion or None,
            "timezone": timezone or TZ_DEFECTO, "updated_at": _now_iso()}
    try:
        r = sb.table("personal_sedes").insert(fila).execute()
    except Exception as e:
        if "duplicate" in str(e).lower() or "unique" in str(e).lower():
            raise ValueError("sede_ya_existe")
        raise
    cache_invalidar(_CACHE_PREFIJO)
    creada = (r.data or [fila])[0]
    aud.registrar(actor=actor, accion="crear_sede", entidad="sede",
                  entidad_id=creada.get("id"), valores_despues={"nombre": nombre})
    return creada


def actualizar_sede(sede_id: str, *, actor: str = "sistema", **campos) -> dict:
    permitidos = {"nombre", "direccion", "timezone", "activa"}
    update = {k: v for k, v in campos.items() if k in permitidos and v is not None}
    if not update:
        raise ValueError("nada_que_actualizar")
    antes = obtener_sede(sede_id)
    update["updated_at"] = _now_iso()
    sb = sb_requerido()
    r = sb.table("personal_sedes").update(update).eq("id", sede_id).execute()
    if not r.data:
        raise ValueError("sede_no_existe")
    cache_invalidar(_CACHE_PREFIJO)
    aud.registrar_cambio(actor=actor, accion="actualizar_sede", entidad="sede",
                         entidad_id=sede_id, antes=antes, despues=r.data[0])
    return r.data[0]


# ── Áreas ────────────────────────────────────────────────────────────────────

def listar_areas(*, sede_id: Optional[str] = None,
                 solo_activas: bool = False) -> list[dict]:
    key = f"{_CACHE_PREFIJO}areas:{sede_id}:{solo_activas}"
    cacheado = cache_get(key)
    if cacheado is not None:
        return cacheado
    sb = _sb()
    if sb is None:
        return []
    try:
        q = sb.table("personal_areas").select("*")
        if sede_id:
            q = q.eq("sede_id", sede_id)
        if solo_activas:
            q = q.eq("activa", True)
        filas = (q.order("nombre").execute().data) or []
    except Exception as e:
        if not es_error_tabla_faltante(e):
            log.error(f"[personal.org] error listando áreas: {e}")
        return []
    return cache_set(key, filas, _CACHE_TTL)


def obtener_area(area_id: str) -> Optional[dict]:
    return next((a for a in listar_areas() if a.get("id") == area_id), None)


def crear_area(*, nombre: str, sede_id: Optional[str] = None,
               actor: str = "sistema") -> dict:
    if not (nombre or "").strip():
        raise ValueError("campo_requerido:nombre")
    sb = sb_requerido()
    fila = {"nombre": nombre.strip(), "sede_id": sede_id, "updated_at": _now_iso()}
    try:
        r = sb.table("personal_areas").insert(fila).execute()
    except Exception as e:
        if "duplicate" in str(e).lower() or "unique" in str(e).lower():
            raise ValueError("area_ya_existe")
        raise
    cache_invalidar(_CACHE_PREFIJO)
    creada = (r.data or [fila])[0]
    aud.registrar(actor=actor, accion="crear_area", entidad="area",
                  entidad_id=creada.get("id"), valores_despues={"nombre": nombre})
    return creada


def actualizar_area(area_id: str, *, actor: str = "sistema", **campos) -> dict:
    permitidos = {"nombre", "sede_id", "activa"}
    update = {k: v for k, v in campos.items() if k in permitidos and v is not None}
    if not update:
        raise ValueError("nada_que_actualizar")
    antes = obtener_area(area_id)
    update["updated_at"] = _now_iso()
    sb = sb_requerido()
    r = sb.table("personal_areas").update(update).eq("id", area_id).execute()
    if not r.data:
        raise ValueError("area_no_existe")
    cache_invalidar(_CACHE_PREFIJO)
    aud.registrar_cambio(actor=actor, accion="actualizar_area", entidad="area",
                         entidad_id=area_id, antes=antes, despues=r.data[0])
    return r.data[0]


def invalidar_cache() -> int:
    return cache_invalidar(_CACHE_PREFIJO)
