"""
backend.api.auth — Login, perfil actual, gestión de usuarios.
"""
from __future__ import annotations

import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from backend.core.security import (
    CurrentUser, create_access_token, get_current_user, hash_password,
    require_role, verify_password,
)
from backend.services import usuarios as svc


router = APIRouter(prefix="/api/auth", tags=["auth"])


# ── Rate limit anti brute-force en /login ──────────────────────────────
# Track intentos FALLIDOS por (IP, email). Si >5 fallos en 5 minutos,
# bloquea ese par por 15 minutos. In-memory por worker — suficiente para
# 25 usuarios concurrentes, no necesitamos Redis.
_LOGIN_ATTEMPTS: dict[tuple[str, str], list[float]] = {}
_LOGIN_BLOCKS: dict[tuple[str, str], float] = {}
_LOGIN_MAX_INTENTOS = 5
_LOGIN_VENTANA_SEC = 300       # 5 minutos
_LOGIN_BLOQUEO_SEC = 900       # 15 minutos


def _check_rate_limit(ip: str, email: str) -> None:
    """Levanta 429 si hay demasiados intentos fallidos recientes."""
    key = (ip or "?", (email or "").lower().strip())
    now = time.time()
    # Si está actualmente bloqueado, rechazar
    if key in _LOGIN_BLOCKS:
        if now < _LOGIN_BLOCKS[key]:
            restante = int(_LOGIN_BLOCKS[key] - now)
            raise HTTPException(
                status_code=429,
                detail=f"Demasiados intentos fallidos. Espera {restante}s.",
            )
        else:
            del _LOGIN_BLOCKS[key]
            _LOGIN_ATTEMPTS.pop(key, None)


def _registrar_intento_fallido(ip: str, email: str) -> None:
    """Registra un intento fallido. Si pasa el umbral, marca bloqueo."""
    key = (ip or "?", (email or "").lower().strip())
    now = time.time()
    intentos = _LOGIN_ATTEMPTS.setdefault(key, [])
    # Limpiar intentos viejos fuera de ventana
    intentos[:] = [t for t in intentos if (now - t) < _LOGIN_VENTANA_SEC]
    intentos.append(now)
    if len(intentos) >= _LOGIN_MAX_INTENTOS:
        _LOGIN_BLOCKS[key] = now + _LOGIN_BLOQUEO_SEC


def _resetear_intentos(ip: str, email: str) -> None:
    """Limpia los intentos al login exitoso."""
    key = (ip or "?", (email or "").lower().strip())
    _LOGIN_ATTEMPTS.pop(key, None)
    _LOGIN_BLOCKS.pop(key, None)


# ── Modelos ──────────────────────────────────────────────────────────

class LoginBody(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: CurrentUser


class UsuarioOut(BaseModel):
    id: str
    email: str
    nombre: str
    cargo: str = ""
    rol: str
    permisos: dict = {}
    activo: bool
    creado_en: Optional[str] = None


class CrearUsuarioBody(BaseModel):
    email: EmailStr
    nombre: str = Field(min_length=2)
    cargo: str = ""
    password: str = Field(min_length=8)
    rol: str = "user"
    permisos: dict = {}


class ActualizarUsuarioBody(BaseModel):
    nombre: Optional[str] = None
    cargo: Optional[str] = None
    rol: Optional[str] = None
    permisos: Optional[dict] = None
    activo: Optional[bool] = None
    password: Optional[str] = Field(default=None, min_length=8)


# ── Login ────────────────────────────────────────────────────────────

@router.post("/login", response_model=LoginResponse)
def login(body: LoginBody, request: Request) -> LoginResponse:
    # IP del cliente (considera proxy de Railway/Vercel)
    ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "?")
    # Anti brute-force: 5 intentos / 5 min, bloqueo 15 min
    _check_rate_limit(ip, body.email)

    u = svc.obtener_por_email(body.email)
    if not u or not u.get("activo"):
        _registrar_intento_fallido(ip, body.email)
        raise HTTPException(status_code=401, detail="Credenciales inválidas")
    if not verify_password(body.password, u["password_hash"]):
        _registrar_intento_fallido(ip, body.email)
        raise HTTPException(status_code=401, detail="Credenciales inválidas")

    # Login exitoso → reset contadores
    _resetear_intentos(ip, body.email)

    cu = CurrentUser(
        id=str(u["id"]),
        email=u["email"],
        nombre=u["nombre"],
        cargo=u.get("cargo") or "",
        rol=u["rol"],
        permisos=u.get("permisos") or {},
        activo=u["activo"],
    )
    return LoginResponse(access_token=create_access_token(cu), user=cu)


@router.get("/me", response_model=CurrentUser)
def me(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    return user


# ── Gestión de usuarios (solo admin) ─────────────────────────────────

def _to_out(u: dict) -> UsuarioOut:
    return UsuarioOut(
        id=str(u["id"]),
        email=u["email"],
        nombre=u["nombre"],
        cargo=u.get("cargo") or "",
        rol=u["rol"],
        permisos=u.get("permisos") or {},
        activo=u.get("activo", True),
        creado_en=u.get("creado_en"),
    )


@router.get("/usuarios/catalogo")
def catalogo_permisos(_: CurrentUser = Depends(require_role("admin"))) -> dict:
    """Catálogo de roles, módulos y acciones disponibles para el formulario."""
    return {
        "roles": list(svc.ROLES),
        "modulos": list(svc.MODULOS),       # plana, retro-compat
        "grupos": list(svc.GRUPOS),         # nuevos (lo que se muestra en UI)
        "grupos_detalle": svc.MODULOS_GRUPOS,  # mapping grupo → módulos
        "acciones": list(svc.ACCIONES),
    }


@router.get("/usuarios", response_model=list[UsuarioOut])
def listar_usuarios(_: CurrentUser = Depends(require_role("admin"))) -> list[UsuarioOut]:
    return [_to_out(u) for u in svc.listar()]


@router.post("/usuarios", response_model=UsuarioOut, status_code=201)
def crear_usuario(
    body: CrearUsuarioBody,
    _: CurrentUser = Depends(require_role("admin")),
) -> UsuarioOut:
    if body.rol not in svc.ROLES and body.rol not in svc.ROLES_LEGACY:
        raise HTTPException(status_code=400, detail=f"Rol inválido. Permitidos: {list(svc.ROLES)}")
    if svc.obtener_por_email(body.email):
        raise HTTPException(status_code=409, detail="El email ya está registrado")
    try:
        u = svc.crear(
            email=body.email,
            nombre=body.nombre,
            cargo=body.cargo or "",
            password_hash=hash_password(body.password),
            rol=body.rol,
            permisos=body.permisos or None,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return _to_out(u)


@router.patch("/usuarios/{uid}", response_model=UsuarioOut)
def actualizar_usuario(
    uid: str,
    body: ActualizarUsuarioBody,
    actor: CurrentUser = Depends(require_role("admin")),
) -> UsuarioOut:
    if actor.id == uid and body.activo is False:
        raise HTTPException(status_code=400, detail="No puedes desactivarte a ti mismo")
    # No permitir que el admin se quite el rol de admin a sí mismo —
    # evita lockout accidental del owner.
    if actor.id == uid and body.rol and body.rol != "admin":
        raise HTTPException(
            status_code=400,
            detail="No puedes quitarte el rol de admin a ti mismo. Pídele a otro admin que lo haga.",
        )
    campos = body.model_dump(exclude_unset=True)
    if "password" in campos:
        campos["password_hash"] = hash_password(campos.pop("password"))
    try:
        u = svc.actualizar(uid, **campos)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        # Loguear stack completo a stdout (Railway logs) pero NO exponer
        # tipo de excepción ni traceback al cliente (security: info disclosure).
        import traceback
        traceback.print_exc()
        # Mensaje genérico al cliente. Para diagnóstico real, ver Railway logs.
        raise HTTPException(
            status_code=500,
            detail="No se pudo guardar el usuario. Contacta al administrador.",
        )
    return _to_out(u)
