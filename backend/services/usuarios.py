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

import os
from typing import Optional

from supabase import create_client, Client


_client: Optional[Client] = None


def _sb() -> Optional[Client]:
    """Mismo patrón que src/memoria.py — lee env vars directo."""
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
        print(f"[usuarios] Error creando cliente Supabase: {e}")
        return None


# ── Roles principales ───────────────────────────────────────────────────────
# admin   = acceso total (owner)
# lector  = solo lectura en todos los módulos
# user    = permisos granulares por módulo+acción definidos en el campo `permisos`
ROLES = ("admin", "lector", "user")

# Aliases de retro-compat (usuarios viejos).
# operador → user (permisos amplios por default)
# lectura  → lector
ROLES_LEGACY = {"operador": "user", "lectura": "lector"}

# Grupos de permisos — agrupados por afinidad operativa para que el
# administrador no tenga que dar permiso uno por uno a cada módulo.
# El permiso se asigna al GRUPO, y el helper resuelve módulo→grupo.
MODULOS_GRUPOS = {
    "centro_control": ["centro_control"],
    "operaciones":    ["logistica", "envios", "devoluciones", "incidencias",
                       "historico", "b2b", "contraentrega", "inventario"],
    "finanzas":       ["finanzas"],
    "comercial":      ["comercial", "revenue", "inteligencia"],
    "configuracion":  ["configuracion", "usuarios", "auditoria"],
}

# Lista de grupos (lo que se expone en el formulario de permisos).
GRUPOS = tuple(MODULOS_GRUPOS.keys())

# Lista plana de todos los módulos individuales (retro-compat).
MODULOS = tuple(m for grupo in MODULOS_GRUPOS.values() for m in grupo)

# Mapping inverso: módulo → grupo, para resolver permisos al chequear.
_MODULO_A_GRUPO = {m: g for g, mods in MODULOS_GRUPOS.items() for m in mods}

ACCIONES = ("ver", "modificar", "borrar")

# Columnas que SELECT siempre debe pedir (incluye cargo + permisos nuevos).
_COLS = "id,email,nombre,cargo,rol,permisos,activo,creado_en,puede_autorizar_precosteo,puede_autorizar_corte"
_COLS_AUTH = "id,email,nombre,cargo,rol,permisos,activo,password_hash,puede_autorizar_precosteo,puede_autorizar_corte"


def _normalizar_rol(rol: str) -> str:
    """Convierte roles viejos a los nuevos."""
    return ROLES_LEGACY.get(rol, rol)


def listar() -> list[dict]:
    sb = _sb()
    if sb is None:
        return []
    try:
        res = (sb.table("usuarios")
               .select(_COLS)
               .order("creado_en", desc=False)
               .execute())
        return res.data or []
    except Exception as e:
        # Si cargo/permisos no existen aún en la DB (migración pendiente),
        # caer al SELECT antiguo para no romper la app.
        if "cargo" in str(e) or "permisos" in str(e):
            res = (sb.table("usuarios")
                   .select("id,email,nombre,rol,activo,creado_en")
                   .order("creado_en", desc=False)
                   .execute())
            return res.data or []
        raise


def obtener_por_email(email: str) -> Optional[dict]:
    sb = _sb()
    if sb is None:
        return None
    try:
        res = (sb.table("usuarios")
               .select(_COLS_AUTH)
               .eq("email", email.lower().strip())
               .limit(1)
               .execute())
        return (res.data or [None])[0]
    except Exception as e:
        if "cargo" in str(e) or "permisos" in str(e):
            res = (sb.table("usuarios")
                   .select("id,email,nombre,rol,activo,password_hash")
                   .eq("email", email.lower().strip())
                   .limit(1)
                   .execute())
            return (res.data or [None])[0]
        raise


def obtener_por_id(uid: str) -> Optional[dict]:
    sb = _sb()
    if sb is None:
        return None
    try:
        res = (sb.table("usuarios").select(_COLS).eq("id", uid).limit(1).execute())
        return (res.data or [None])[0]
    except Exception as e:
        if "cargo" in str(e) or "permisos" in str(e):
            res = (sb.table("usuarios")
                   .select("id,email,nombre,rol,activo,creado_en")
                   .eq("id", uid).limit(1).execute())
            return (res.data or [None])[0]
        raise


def crear(*, email: str, nombre: str, password_hash: str, rol: str = "user",
          cargo: str = "", permisos: Optional[dict] = None) -> dict:
    rol = _normalizar_rol(rol)
    if rol not in ROLES:
        raise ValueError(f"Rol inválido: {rol}. Permitidos: {ROLES}")
    if rol != "user" and permisos:
        # admin y lector ignoran permisos granulares
        permisos = None
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase no configurado")
    payload = {
        "email":         email.lower().strip(),
        "nombre":        nombre.strip(),
        "password_hash": password_hash,
        "rol":           rol,
        "activo":        True,
    }
    if cargo:
        payload["cargo"] = cargo.strip()
    if permisos is not None:
        payload["permisos"] = permisos
    try:
        res = sb.table("usuarios").insert(payload).execute()
        return res.data[0]
    except Exception as e:
        # Si la migración aún no corrió, intentar sin los campos nuevos.
        if "cargo" in str(e) or "permisos" in str(e):
            payload.pop("cargo", None)
            payload.pop("permisos", None)
            res = sb.table("usuarios").insert(payload).execute()
            return res.data[0]
        raise


def actualizar(uid: str, **campos) -> dict:
    permitidos = {"nombre", "cargo", "rol", "permisos", "activo", "password_hash"}
    update = {k: v for k, v in campos.items() if k in permitidos and v is not None}
    if "rol" in update:
        update["rol"] = _normalizar_rol(update["rol"])
        if update["rol"] not in ROLES:
            raise ValueError(f"Rol inválido: {update['rol']}. Permitidos: {ROLES}")
        if update["rol"] != "user":
            update["permisos"] = None  # limpiar granulares
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase no configurado")
    try:
        res = sb.table("usuarios").update(update).eq("id", uid).execute()
        if not res.data:
            raise ValueError(f"Usuario {uid} no encontrado")
        return res.data[0]
    except Exception as e:
        if "cargo" in str(e) or "permisos" in str(e):
            update.pop("cargo", None)
            update.pop("permisos", None)
            res = sb.table("usuarios").update(update).eq("id", uid).execute()
            if not res.data:
                raise ValueError(f"Usuario {uid} no encontrado")
            return res.data[0]
        raise


# ── Helper de chequeo de permisos ─────────────────────────────────────
def tiene_permiso(usuario: dict, modulo: str, accion: str) -> bool:
    """Verifica si un usuario tiene permiso para una acción en un módulo.

    - admin: siempre True
    - lector: solo accion='ver' es True
    - user: revisa el dict permisos[modulo] que es una lista de acciones
    - retro-compat: operador → todo excepto borrar; lectura → solo ver
    """
    if not usuario or not usuario.get("activo", True):
        return False
    rol = _normalizar_rol(usuario.get("rol") or "")
    if rol == "admin":
        return True
    if rol == "lector":
        return accion == "ver"
    if rol == "user":
        permisos = usuario.get("permisos") or {}
        if not isinstance(permisos, dict):
            return False
        # Buscar primero por grupo (modulo → grupo), luego por módulo
        # individual (para compat con permisos viejos por módulo).
        grupo = _MODULO_A_GRUPO.get(modulo)
        candidatos = [k for k in (grupo, modulo) if k]
        for k in candidatos:
            acciones = permisos.get(k)
            if acciones is None:
                continue
            if isinstance(acciones, list) and accion in acciones:
                return True
            if isinstance(acciones, dict) and acciones.get(accion):
                return True
        return False
    # Roles viejos retro-compat
    if usuario.get("rol") == "operador":
        return accion in ("ver", "modificar")
    if usuario.get("rol") == "lectura":
        return accion == "ver"
    return False


def contar() -> int:
    sb = _sb()
    if sb is None:
        return 0
    res = sb.table("usuarios").select("id", count="exact").execute()
    return res.count or 0
