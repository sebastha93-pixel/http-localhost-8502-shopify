"""
backend.services.notificaciones — Avisos internos dentro de la app.

Distinto de lo que ya existía: postventa/whatsapp/revenue mandan mensajes
HACIA AFUERA (clientas, proveedores, Slack). Esto es para avisos ENTRE
usuarios del sistema — el cortador cierra un corte y el diseñador se entera.

REGLA DE ORO: crear una notificación NUNCA puede tumbar la acción que la
originó. Si el cortador cierra un corte y Supabase está caído, el corte se
cierra igual y el aviso se pierde. Por eso todo acá atrapa sus excepciones y
los llamadores usan `avisar_*` (que no levanta nada).

Schema (Supabase) — correr `migrations/notificaciones.sql`:
    create table notificaciones (
      id uuid primary key default gen_random_uuid(),
      destinatario_email text not null,
      tipo text not null,
      titulo text not null,
      mensaje text,
      enlace text,
      meta jsonb default '{}'::jsonb,
      leida boolean not null default false,
      creado_en timestamptz not null default now(),
      creado_por text
    );
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from supabase import create_client, Client


log = logging.getLogger(__name__)

_TABLA = "notificaciones"
_client: Optional[Client] = None

# Cuántas trae el campanita de una. Suficiente para el panel, corto para no
# arrastrar el histórico entero en cada poll (se consulta cada ~20s).
LIMITE_DEFAULT = 30


def _sb() -> Optional[Client]:
    global _client
    if _client is not None:
        return _client
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_KEY", "").strip()
    if not url or not key:
        return None
    try:
        _client = create_client(url, key)
        return _client
    except Exception as e:
        log.warning(f"[notificaciones] no se pudo crear cliente Supabase: {e}")
        return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Escritura ──────────────────────────────────────────────────────────────

def crear(*, destinatario_email: str, tipo: str, titulo: str,
          mensaje: str = "", enlace: str = "", meta: Optional[dict] = None,
          creado_por: str = "") -> Optional[dict]:
    """Crea UNA notificación. Devuelve la fila, o None si no se pudo."""
    dest = (destinatario_email or "").strip().lower()
    if not dest or not titulo:
        return None
    # No avisarle a alguien de su propia acción — sería ruido puro.
    if dest == (creado_por or "").strip().lower():
        return None
    sb = _sb()
    if sb is None:
        return None
    fila = {
        "destinatario_email": dest,
        "tipo": tipo,
        "titulo": titulo[:200],
        "mensaje": (mensaje or "")[:600],
        "enlace": (enlace or "")[:300],
        "meta": meta or {},
        "leida": False,
        "creado_en": _now(),
        "creado_por": (creado_por or "")[:200],
    }
    try:
        r = sb.table(_TABLA).insert(fila).execute()
        return (r.data or [fila])[0]
    except Exception as e:
        log.warning(f"[notificaciones] insert falló ({tipo} → {dest}): {str(e)[:160]}")
        return None


def emails_con_modulo(modulo: str, accion: str = "modificar") -> list[str]:
    """Emails de los usuarios ACTIVOS que pueden (modulo, accion).

    Replica la resolución de permisos de core.security.puede(): admin puede
    todo, `user` se resuelve por grupo o por módulo suelto. Se hace acá en vez
    de importar security para no crear un ciclo (security ya importa services).
    """
    try:
        from backend.services.usuarios import listar, MODULOS_GRUPOS
    except Exception as e:
        log.warning(f"[notificaciones] no pude importar usuarios: {e}")
        return []
    modulo_a_grupo = {m: g for g, mods in MODULOS_GRUPOS.items() for m in mods}
    claves = [k for k in (modulo_a_grupo.get(modulo), modulo) if k]
    out: list[str] = []
    try:
        usuarios = listar() or []
    except Exception as e:
        log.warning(f"[notificaciones] listar usuarios falló: {e}")
        return []
    for u in usuarios:
        if not u.get("activo"):
            continue
        email = (u.get("email") or "").strip().lower()
        if not email:
            continue
        rol = u.get("rol")
        if rol == "admin":
            out.append(email)
            continue
        if rol == "lector":
            if accion == "ver":
                out.append(email)
            continue
        if rol == "operador" and accion in ("ver", "modificar"):
            out.append(email)
            continue
        permisos = u.get("permisos") or {}
        for k in claves:
            acc = permisos.get(k)
            if (isinstance(acc, list) and accion in acc) or \
               (isinstance(acc, dict) and acc.get(accion)):
                out.append(email)
                break
    return sorted(set(out))


def crear_para_modulo(*, modulo: str, tipo: str, titulo: str,
                      mensaje: str = "", enlace: str = "",
                      meta: Optional[dict] = None,
                      creado_por: str = "") -> int:
    """Avisa a TODOS los que tienen un módulo. Devuelve cuántos recibieron."""
    n = 0
    for email in emails_con_modulo(modulo):
        if crear(destinatario_email=email, tipo=tipo, titulo=titulo,
                 mensaje=mensaje, enlace=enlace, meta=meta,
                 creado_por=creado_por):
            n += 1
    return n


# ── Lectura ────────────────────────────────────────────────────────────────

def listar(email: str, *, limite: int = LIMITE_DEFAULT,
           solo_no_leidas: bool = False) -> list[dict]:
    dest = (email or "").strip().lower()
    sb = _sb()
    if sb is None or not dest:
        return []
    try:
        q = (sb.table(_TABLA).select("*")
               .eq("destinatario_email", dest)
               .order("creado_en", desc=True)
               .limit(max(1, min(limite, 100))))
        if solo_no_leidas:
            q = q.eq("leida", False)
        return q.execute().data or []
    except Exception as e:
        log.warning(f"[notificaciones] listar falló: {str(e)[:160]}")
        return []


def contar_no_leidas(email: str) -> int:
    dest = (email or "").strip().lower()
    sb = _sb()
    if sb is None or not dest:
        return 0
    try:
        r = (sb.table(_TABLA).select("id", count="exact")
               .eq("destinatario_email", dest).eq("leida", False)
               .execute())
        return r.count or 0
    except Exception as e:
        log.warning(f"[notificaciones] contar falló: {str(e)[:160]}")
        return 0


def marcar_leida(notif_id: str, email: str) -> bool:
    """Marca una como leída. Filtra por email para que nadie marque las ajenas."""
    dest = (email or "").strip().lower()
    sb = _sb()
    if sb is None or not notif_id or not dest:
        return False
    try:
        sb.table(_TABLA).update({"leida": True}) \
          .eq("id", notif_id).eq("destinatario_email", dest).execute()
        return True
    except Exception as e:
        log.warning(f"[notificaciones] marcar_leida falló: {str(e)[:160]}")
        return False


def marcar_todas_leidas(email: str) -> int:
    dest = (email or "").strip().lower()
    sb = _sb()
    if sb is None or not dest:
        return 0
    try:
        r = (sb.table(_TABLA).update({"leida": True})
               .eq("destinatario_email", dest).eq("leida", False)
               .execute())
        return len(r.data or [])
    except Exception as e:
        log.warning(f"[notificaciones] marcar_todas falló: {str(e)[:160]}")
        return 0
