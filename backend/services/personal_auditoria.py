"""
backend.services.personal_auditoria — Registro de auditoría del módulo Personal.

Alcance de módulo, no global
────────────────────────────
MALE DENIM OS no tiene hoy una tabla de auditoría global: /api/auditoria hace
merge en memoria de `acciones` + `notas`, y su único writer real vive en el
Streamlit legacy. Construir auditoría global es otro proyecto.

Aquí se resuelve con alcance de módulo, igual que postventa_timeline. El día
que exista una auditoría global, esta tabla migra con un INSERT ... SELECT.

Regla de oro: auditar NUNCA debe tumbar la operación
────────────────────────────────────────────────────
Si el registro de auditoría falla, se loguea y se sigue. Un empleado no puede
quedarse sin poder pedir un permiso porque la tabla de auditoría tuvo un
hipo. Lo que sí está prohibido es lo contrario: hacer un cambio sensible y
NO intentar auditarlo.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from backend.services.personal_base import _sb, es_error_tabla_faltante

log = logging.getLogger(__name__)


ORIGENES = ("api", "conector", "cron", "importacion", "sistema")

# Campos que jamás deben viajar a la auditoría, ni siquiera si el caller los
# incluye por descuido en valores_antes/valores_despues. Se filtran por nombre.
_CAMPOS_PROHIBIDOS = frozenset({
    "password", "password_hash", "token", "token_hash", "access_token",
    "refresh_token", "secret", "api_key", "authorization",
    "raw_payload_json",      # puede traer datos del dispositivo
    "referencia_snapshot",   # referencia a imagen facial
    "numero_documento",      # PII: no se replica en cada fila de auditoría
})


def _limpiar(d: Optional[dict]) -> Optional[dict]:
    """Quita campos sensibles antes de persistir.

    Defensa en profundidad: los callers ya deberían pasar solo lo relevante,
    pero un dict de Supabase completo trae de todo.
    """
    if not d:
        return d
    limpio = {}
    for k, v in d.items():
        if k.lower() in _CAMPOS_PROHIBIDOS:
            limpio[k] = "···"
        else:
            limpio[k] = v
    return limpio


def registrar(
    *,
    actor: str,
    accion: str,
    entidad: str,
    entidad_id: Optional[str] = None,
    valores_antes: Optional[dict] = None,
    valores_despues: Optional[dict] = None,
    motivo: Optional[str] = None,
    origen: str = "api",
    actor_id: Optional[str] = None,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> Optional[dict]:
    """Escribe un registro de auditoría. Best-effort: nunca lanza.

    Args:
        actor: email o identificador de quien hizo el cambio.
        accion: verbo en snake_case — 'crear_permiso', 'aprobar_th', 'cerrar_periodo'.
        entidad: nombre lógico — 'solicitud_permiso', 'jornada', 'dispositivo'.
        motivo: obligatorio por convención en acciones destructivas
                (reabrir periodo, ajuste manual). No se valida aquí: lo exige
                el endpoint, que es quien sabe si la acción lo requiere.

    Returns:
        El registro insertado, o None si no se pudo auditar.
    """
    if origen not in ORIGENES:
        origen = "api"

    fila = {
        "actor": (actor or "desconocido")[:200],
        "actor_id": actor_id,
        "accion": accion[:100],
        "entidad": entidad[:100],
        "entidad_id": entidad_id,
        "valores_antes": _limpiar(valores_antes),
        "valores_despues": _limpiar(valores_despues),
        "motivo": motivo,
        "origen": origen,
        "ip": ip,
        "user_agent": (user_agent or "")[:300] or None,
        "correlation_id": correlation_id,
    }

    sb = _sb()
    if sb is None:
        log.warning(f"[personal.auditoria] sin Supabase — se pierde: {accion} {entidad}")
        return None
    try:
        r = sb.table("personal_auditoria").insert(fila).execute()
        return (r.data or [fila])[0]
    except Exception as e:
        if es_error_tabla_faltante(e):
            log.warning(
                "[personal.auditoria] tabla ausente (¿migración sin aplicar?) — "
                f"se pierde: {accion} {entidad}"
            )
        else:
            log.error(f"[personal.auditoria] fallo al auditar {accion} {entidad}: {e}")
        return None


def diff(antes: Optional[dict], despues: Optional[dict]) -> tuple[dict, dict]:
    """Reduce dos snapshots a solo los campos que cambiaron.

    Evita auditorías de 40 columnas cuando solo cambió el estado, que es lo
    que hace ilegible un log de auditoría.

    >>> diff({"a": 1, "b": 2}, {"a": 1, "b": 3})
    ({'b': 2}, {'b': 3})
    """
    antes = antes or {}
    despues = despues or {}
    claves = set(antes) | set(despues)
    d_antes, d_despues = {}, {}
    for k in claves:
        va, vd = antes.get(k), despues.get(k)
        if va != vd:
            d_antes[k] = va
            d_despues[k] = vd
    return d_antes, d_despues


def registrar_cambio(
    *, actor: str, accion: str, entidad: str, entidad_id: str,
    antes: Optional[dict], despues: Optional[dict], **kw,
) -> Optional[dict]:
    """Como registrar(), pero guardando solo el delta. El caso común."""
    d_antes, d_despues = diff(antes, despues)
    return registrar(
        actor=actor, accion=accion, entidad=entidad, entidad_id=entidad_id,
        valores_antes=d_antes, valores_despues=d_despues, **kw,
    )


def listar(
    *, entidad: Optional[str] = None, entidad_id: Optional[str] = None,
    actor: Optional[str] = None, limit: int = 100,
) -> list[dict]:
    """Consulta el rastro de auditoría. Degrada a [] si no hay tabla."""
    sb = _sb()
    if sb is None:
        return []
    try:
        q = sb.table("personal_auditoria").select("*")
        if entidad:
            q = q.eq("entidad", entidad)
        if entidad_id:
            q = q.eq("entidad_id", entidad_id)
        if actor:
            q = q.eq("actor", actor)
        r = q.order("created_at", desc=True).limit(min(max(limit, 1), 500)).execute()
        return r.data or []
    except Exception as e:
        if es_error_tabla_faltante(e):
            return []
        log.error(f"[personal.auditoria] error listando: {e}")
        return []
