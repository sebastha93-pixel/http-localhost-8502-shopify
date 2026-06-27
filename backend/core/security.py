"""
backend.core.security — JWT + bcrypt + dependency de usuario actual.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from backend.core.config import settings


# ── Modelo del usuario autenticado ───────────────────────────────────

class CurrentUser(BaseModel):
    id: str
    email: str
    nombre: str
    rol: str             # admin | lector | user (legacy: operador, lectura)
    cargo: str = ""      # cargo en la empresa (ej. "Asesora de ventas", "Logística")
    permisos: dict = {}  # dict modulo -> lista de acciones (solo aplica si rol='user')
    activo: bool = True


# ── Hashing ─────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# ── JWT ─────────────────────────────────────────────────────────────

def create_access_token(user: CurrentUser) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.auth_jwt_expiry_min)
    payload = {
        "sub":      user.id,
        "email":    user.email,
        "nombre":   user.nombre,
        "rol":      user.rol,
        "cargo":    user.cargo or "",
        "permisos": user.permisos or {},
        "exp":      int(expire.timestamp()),
        "iat":      int(datetime.now(timezone.utc).timestamp()),
    }
    return jwt.encode(payload, settings.auth_jwt_secret, algorithm="HS256")


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.auth_jwt_secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expirado")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token inválido")


# ── Dependency para extraer el usuario actual ────────────────────────

_bearer = HTTPBearer(auto_error=False)


def get_current_user(creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer)) -> CurrentUser:
    if creds is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autenticado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_token(creds.credentials)

    # Verificar contra DB que el usuario sigue ACTIVO y con el mismo rol.
    # Esto cierra el gap de JWT cacheado por 2h después de desactivar/cambiar
    # rol al usuario en Supabase. Caché TTL 30s para no martillar la DB.
    uid = payload["sub"]
    cached = _USER_CACHE.get(uid)
    import time as _t
    now = _t.time()
    if cached and (now - cached["ts"]) < 30:
        fresh = cached["data"]
    else:
        from backend.services import usuarios as _svc
        try:
            db_user = _svc.obtener_por_id(uid)
        except Exception:
            db_user = None
        if not db_user or not db_user.get("activo", True):
            # Limpiar cache para forzar re-check si el usuario se reactiva
            _USER_CACHE.pop(uid, None)
            raise HTTPException(status_code=401, detail="Usuario inactivo o no existe")
        fresh = {
            "rol": db_user.get("rol") or payload["rol"],
            "permisos": db_user.get("permisos") or {},
            "activo": True,
        }
        _USER_CACHE[uid] = {"ts": now, "data": fresh}

    return CurrentUser(
        id=uid,
        email=payload["email"],
        nombre=payload["nombre"],
        rol=fresh["rol"],
        cargo=payload.get("cargo", ""),
        permisos=fresh["permisos"],
        activo=fresh["activo"],
    )


# Cache simple en memoria por worker. Refresh cada 30s. Aplica chequeo de DB
# para evitar martillar Supabase en cada request mientras se mantiene
# revocación rápida (un usuario desactivado pierde acceso en ≤30s).
_USER_CACHE: dict = {}


def get_current_user_optional(creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer)) -> Optional[CurrentUser]:
    if creds is None:
        return None
    try:
        payload = decode_token(creds.credentials)
        return CurrentUser(
            id=payload["sub"],
            email=payload["email"],
            nombre=payload["nombre"],
            rol=payload["rol"],
        )
    except HTTPException:
        return None


def require_role(*roles: str):
    """Dependency factory: gate por rol.

    Semántica de los roles aceptados:
      - "admin"     → solo admin pasa
      - "operador"  → acción de ESCRITURA (modificar). Pasan:
                      admin, operador (legacy), user con permiso 'modificar' en algún grupo
      - "lectura"   → acción de LECTURA. Pasan:
                      admin, operador, lector, lectura (legacy), user con cualquier permiso
    """
    requiere_escritura = "operador" in roles
    requiere_lectura   = "lectura" in roles or requiere_escritura
    # Roles literales que siempre pasan si están en la lista
    literales = set(roles) | {"admin"}
    if "operador" in roles:
        literales.add("operador")  # legacy escritura
    if "lectura" in roles:
        literales |= {"lectura", "lector"}  # legacy + nuevo lectura

    def _check(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not user.activo:
            raise HTTPException(403, "Usuario inactivo")
        # admin SIEMPRE pasa
        if user.rol == "admin":
            return user
        # Roles literales legacy (operador, lectura) y lector nuevo
        if user.rol in literales:
            return user
        # Rol "user" granular: pasa solo si tiene la acción correcta en ALGÚN grupo.
        # Esto es un check liviano "global"; los endpoints críticos deben usar
        # require_permission(grupo, accion) para chequeo fino.
        if user.rol == "user":
            permisos = user.permisos or {}
            necesaria = "modificar" if requiere_escritura else ("ver" if requiere_lectura else None)
            if necesaria is None:
                # Endpoint admin-only — user no pasa
                raise HTTPException(403, "Acceso restringido a administrador")
            for acciones in permisos.values():
                if isinstance(acciones, list) and necesaria in acciones:
                    return user
                if isinstance(acciones, dict) and acciones.get(necesaria):
                    return user
            raise HTTPException(403, f"Sin permiso de '{necesaria}' en ningún módulo")
        raise HTTPException(403, f"Requiere rol: {', '.join(roles)}")
    return _check


def _check_permiso(user: CurrentUser, modulo: str, accion: str) -> bool:
    """Lógica central de permisos. Espejo de services.usuarios.tiene_permiso
    pero opera sobre CurrentUser (que viene del JWT, no de Supabase)."""
    if not user or not user.activo:
        return False
    rol = user.rol
    if rol == "admin":
        return True
    if rol == "lector":
        return accion == "ver"
    if rol == "user":
        # Importación local para evitar ciclo con services.
        from backend.services.usuarios import MODULOS_GRUPOS
        permisos = user.permisos or {}
        # Resolver modulo → grupo, chequear ambos.
        modulo_a_grupo = {m: g for g, mods in MODULOS_GRUPOS.items() for m in mods}
        candidatos = [modulo_a_grupo.get(modulo), modulo]
        for k in candidatos:
            if not k:
                continue
            acciones = permisos.get(k)
            if isinstance(acciones, list) and accion in acciones:
                return True
            if isinstance(acciones, dict) and acciones.get(accion):
                return True
        return False
    # Roles legacy
    if rol == "operador":
        return accion in ("ver", "modificar")
    if rol == "lectura":
        return accion == "ver"
    return False


def require_permission(modulo: str, accion: str):
    """Dependency factory granular: requiere permiso para (modulo, accion).

    Ejemplo:
        @router.post("/algo", ...)
        def hacer_algo(_: CurrentUser = Depends(require_permission("contraentrega", "modificar"))):
            ...
    """
    def _check(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not _check_permiso(user, modulo, accion):
            raise HTTPException(
                status_code=403,
                detail=f"Sin permiso para '{accion}' en módulo '{modulo}'",
            )
        return user
    return _check
