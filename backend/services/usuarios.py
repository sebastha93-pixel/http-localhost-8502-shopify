"""
backend.services.usuarios — CRUD de usuarios en Supabase.

Schema esperado:
    create table usuarios (
      id uuid primary key default gen_random_uuid(),
      email text unique not null,
      nombre text not null,
      password_hash text not null,
      rol text not null default 'operador',
      activo boolean not null default true,
      creado_en timestamptz default now()
    );
"""
from __future__ import annotations

from typing import Optional

from supabase import create_client, Client

from backend.core.config import settings


_client: Optional[Client] = None


def _sb() -> Optional[Client]:
    global _client
    if _client is not None:
        return _client
    if not settings.supabase_url or not settings.supabase_key:
        return None
    _client = create_client(settings.supabase_url, settings.supabase_key)
    return _client


ROLES = ("admin", "operador", "lectura")


def listar() -> list[dict]:
    sb = _sb()
    if sb is None:
        return []
    res = (sb.table("usuarios")
           .select("id,email,nombre,rol,activo,creado_en")
           .order("creado_en", desc=False)
           .execute())
    return res.data or []


def obtener_por_email(email: str) -> Optional[dict]:
    sb = _sb()
    if sb is None:
        return None
    res = (sb.table("usuarios")
           .select("id,email,nombre,rol,activo,password_hash")
           .eq("email", email.lower().strip())
           .limit(1)
           .execute())
    return (res.data or [None])[0]


def obtener_por_id(uid: str) -> Optional[dict]:
    sb = _sb()
    if sb is None:
        return None
    res = (sb.table("usuarios")
           .select("id,email,nombre,rol,activo,creado_en")
           .eq("id", uid)
           .limit(1)
           .execute())
    return (res.data or [None])[0]


def crear(*, email: str, nombre: str, password_hash: str, rol: str = "operador") -> dict:
    if rol not in ROLES:
        raise ValueError(f"Rol inválido: {rol}")
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase no configurado")
    res = sb.table("usuarios").insert({
        "email":         email.lower().strip(),
        "nombre":        nombre.strip(),
        "password_hash": password_hash,
        "rol":           rol,
        "activo":        True,
    }).execute()
    return res.data[0]


def actualizar(uid: str, **campos) -> dict:
    """Solo permite cambiar: nombre, rol, activo, password_hash."""
    permitidos = {"nombre", "rol", "activo", "password_hash"}
    update = {k: v for k, v in campos.items() if k in permitidos and v is not None}
    if "rol" in update and update["rol"] not in ROLES:
        raise ValueError(f"Rol inválido: {update['rol']}")
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase no configurado")
    res = sb.table("usuarios").update(update).eq("id", uid).execute()
    if not res.data:
        raise ValueError(f"Usuario {uid} no encontrado")
    return res.data[0]


def contar() -> int:
    sb = _sb()
    if sb is None:
        return 0
    res = sb.table("usuarios").select("id", count="exact").execute()
    return res.count or 0
