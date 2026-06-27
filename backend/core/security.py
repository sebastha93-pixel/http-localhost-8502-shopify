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
    return CurrentUser(
        id=payload["sub"],
        email=payload["email"],
        nombre=payload["nombre"],
        rol=payload["rol"],
        cargo=payload.get("cargo", ""),
        permisos=payload.get("permisos", {}) or {},
    )


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
    """Dependency factory: requiere que el usuario tenga uno de los roles dados.

    Acepta los roles nuevos (admin/lector/user) y los viejos (operador/lectura)
    para retro-compat con código existente.
    """
    # Mapping de roles viejos para que callers viejos sigan funcionando.
    ALIASES = {
        "operador": ("operador", "user", "admin"),
        "lectura":  ("lectura", "lector", "user", "admin"),
    }
    permitidos = set()
    for r in roles:
        permitidos.add(r)
        if r in ALIASES:
            permitidos.update(ALIASES[r])
    # Admin SIEMPRE pasa (acceso total al owner).
    permitidos.add("admin")

    def _check(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.rol not in permitidos:
            raise HTTPException(status_code=403, detail=f"Requiere rol: {', '.join(roles)}")
        return user
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
        permisos = user.permisos or {}
        acciones = permisos.get(modulo) or []
        if isinstance(acciones, list):
            return accion in acciones
        if isinstance(acciones, dict):
            return bool(acciones.get(accion))
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
