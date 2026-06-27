"""
backend.api.auth — Login, perfil actual, gestión de usuarios.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field

from backend.core.security import (
    CurrentUser, create_access_token, get_current_user, hash_password,
    require_role, verify_password,
)
from backend.services import usuarios as svc


router = APIRouter(prefix="/api/auth", tags=["auth"])


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
def login(body: LoginBody) -> LoginResponse:
    u = svc.obtener_por_email(body.email)
    if not u or not u.get("activo"):
        raise HTTPException(status_code=401, detail="Credenciales inválidas")
    if not verify_password(body.password, u["password_hash"]):
        raise HTTPException(status_code=401, detail="Credenciales inválidas")

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
        "modulos": list(svc.MODULOS),
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
    campos = body.model_dump(exclude_unset=True)
    if "password" in campos:
        campos["password_hash"] = hash_password(campos.pop("password"))
    try:
        u = svc.actualizar(uid, **campos)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _to_out(u)
