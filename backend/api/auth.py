"""
backend.api.auth — Login, perfil actual, gestión de usuarios.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from backend.core.config import settings
from backend.core.security import (
    CurrentUser, create_access_token, get_current_user, hash_password,
    require_role, verify_password,
)
from backend.services import correo, usuarios as svc


log = logging.getLogger(__name__)


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
    puede_autorizar_precosteo: bool = False
    # Puede borrar ingresos de tela y cambiar metros. Ver la migración
    # 20260805020000_permiso_metraje.sql.
    puede_ajustar_metraje: bool = False
    puede_autorizar_corte: bool = False
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
    puede_autorizar_precosteo: Optional[bool] = None
    puede_ajustar_metraje: Optional[bool] = None
    puede_autorizar_corte:     Optional[bool] = None


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


# ── Recuperar contraseña ─────────────────────────────────────────────────
#
# POR QUÉ EXISTE (2026-08-18): la única forma de cambiar una clave era que un
# admin YA ADENTRO la cambiara desde /usuarios. Cuando el que no puede entrar es
# el admin, no había salida. Pasó, y con 10 usuarios volverá a pasar.
#
# LAS TRES REGLAS QUE DEFINEN ESTE FLUJO:
#
# 1. La contraseña la escribe LA PERSONA, en su navegador. Nadie más —ni un
#    admin, ni soporte, ni quien mantiene el sistema— la ve ni la digita. Es la
#    razón de ser de todo esto.
# 2. El enlace va SOLO al correo registrado en `usuarios`. Nunca a una
#    dirección que venga en la petición: eso sería regalar cuentas a quien
#    conozca un correo.
# 3. `/recuperar` responde LO MISMO exista o no el correo. Si dijera "ese
#    usuario no existe", cualquiera podría averiguar qué correos son reales.

_RESET_MAX_POR_HORA = 5      # por usuario; freno anti-inundación de correos


def _hash_token(token: str) -> str:
    """SHA-256 hex. En la base se guarda esto, jamás el token del enlace."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _parse_ts(valor: str) -> Optional[datetime]:
    """Timestamp de Postgres → datetime, tolerando la fracción de segundo.

    Railway corre Python 3.10, y el `fromisoformat` de esa versión SOLO acepta
    fracciones de 3 o 6 dígitos. Postgres devuelve las que sean —recorta los
    ceros de la derecha—, así que un `2026-08-18T15:04:05.12345+00:00` (cinco
    dígitos) levanta ValueError. Acá eso significaría decirle "el enlace no es
    válido" a alguien cuyo enlace estaba perfecto, así que la fracción se
    normaliza a seis dígitos antes de parsear.
    """
    s = (valor or "").strip().replace("Z", "+00:00")
    if not s:
        return None
    if "." in s:
        cabeza, resto = s.split(".", 1)
        digitos = ""
        for ch in resto:
            if ch.isdigit():
                digitos += ch
            else:
                break
        s = f"{cabeza}.{digitos.ljust(6, '0')[:6]}{resto[len(digitos):]}"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class RecuperarBody(BaseModel):
    email: EmailStr


class RestablecerBody(BaseModel):
    token: str = Field(min_length=20)
    password: str = Field(min_length=8)


def _cuerpo_correo(nombre: str, enlace: str, minutos: int) -> tuple[str, str]:
    """(html, texto). Sin imágenes ni rastreadores: es un correo de seguridad."""
    html = f"""\
<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;max-width:520px">
  <p style="font-size:11px;letter-spacing:3px;color:#6b7280;margin:0 0 18px">
    MALE&#39;DENIM · OPERATING SYSTEM
  </p>
  <p style="font-size:15px;color:#111827">Hola {nombre},</p>
  <p style="font-size:15px;color:#111827">
    Alguien pidió restablecer la contraseña de tu cuenta. Si fuiste tú, abre
    este enlace y escribe tu contraseña nueva:
  </p>
  <p style="margin:22px 0">
    <a href="{enlace}"
       style="background:#111827;color:#fff;text-decoration:none;padding:12px 20px;
              border-radius:6px;font-size:14px;font-weight:600;display:inline-block">
      Cambiar mi contraseña
    </a>
  </p>
  <p style="font-size:13px;color:#6b7280">
    El enlace sirve <strong>una sola vez</strong> y vence en {minutos} minutos.
  </p>
  <p style="font-size:13px;color:#6b7280">
    Si no lo pediste, no tienes que hacer nada: tu contraseña actual sigue
    funcionando y este enlace vence solo.
  </p>
</div>"""
    texto = (
        f"Hola {nombre},\n\n"
        "Alguien pidió restablecer la contraseña de tu cuenta. Si fuiste tú, "
        f"abre este enlace y escribe tu contraseña nueva:\n\n{enlace}\n\n"
        f"Sirve una sola vez y vence en {minutos} minutos.\n"
        "Si no lo pediste, no tienes que hacer nada.\n"
    )
    return html, texto


@router.post("/recuperar")
def recuperar(body: RecuperarBody, request: Request) -> dict:
    """Manda un enlace de un solo uso al correo registrado del usuario.

    Responde `{"ok": true}` SIEMPRE —exista el correo o no, salga el envío o
    no—. Lo que pasó de verdad queda en los logs del servidor, no en la
    respuesta, porque la respuesta la puede leer cualquiera.
    """
    ip = (request.headers.get("x-forwarded-for", "").split(",")[0].strip()
          or (request.client.host if request.client else "?"))
    email = body.email.lower().strip()
    respuesta = {"ok": True}

    u = svc.obtener_por_email(email)
    if not u or not u.get("activo"):
        log.info("reset: pedido para email inexistente o inactivo (ip=%s)", ip)
        return respuesta

    ahora = datetime.now(timezone.utc)
    try:
        recientes = svc.contar_tokens_recientes(
            str(u["id"]), desde=(ahora - timedelta(hours=1)).isoformat())
        if recientes >= _RESET_MAX_POR_HORA:
            log.warning("reset: %s pidió %d enlaces en una hora — frenado",
                        email, recientes)
            return respuesta

        token = secrets.token_urlsafe(32)
        svc.crear_token_reset(
            usuario_id=str(u["id"]),
            token_hash=_hash_token(token),
            expira_en=(ahora + timedelta(minutes=settings.auth_reset_ttl_min)).isoformat(),
            ip=ip,
        )
        enlace = f"{settings.app_public_url.rstrip('/')}/restablecer?token={token}"
        html, texto = _cuerpo_correo(
            (u.get("nombre") or "").split(" ")[0] or "hola",
            enlace, settings.auth_reset_ttl_min)
        env = correo.enviar(
            para=u["email"],
            asunto="Restablecer tu contraseña · MALE'DENIM OS",
            html=html, texto=texto,
        )
        if not env.get("ok"):
            log.error("reset: no se pudo enviar el correo a %s — %s",
                      email, env.get("error"))
        else:
            log.info("reset: enlace enviado a %s (resend=%s)", email, env.get("id"))
    except Exception as e:
        # Ni siquiera un fallo interno cambia la respuesta: distinguirlo diría
        # que ese correo sí existe.
        log.exception("reset: fallo generando el enlace para %s: %s", email, e)

    return respuesta


@router.post("/restablecer")
def restablecer(body: RestablecerBody) -> dict:
    """Cambia la contraseña usando un token de un solo uso.

    Los errores van en 400 y NO en 401 a propósito: el cliente redirige al
    login ante cualquier 401 (ver `irAlLogin` en lib/api.ts), así que un 401
    acá sacaría a la persona de la pantalla justo cuando le íbamos a explicar
    que el enlace venció.
    """
    fila = svc.obtener_token_reset(_hash_token(body.token))
    if not fila:
        raise HTTPException(400, "El enlace no es válido. Pide uno nuevo.")
    if fila.get("usado_en"):
        raise HTTPException(400, "Ese enlace ya se usó. Pide uno nuevo.")

    ahora = datetime.now(timezone.utc)
    expira = _parse_ts(str(fila.get("expira_en") or ""))
    if expira is None:
        raise HTTPException(400, "El enlace no es válido. Pide uno nuevo.")
    if ahora > expira:
        raise HTTPException(400, "El enlace venció. Pide uno nuevo.")

    uid = str(fila["usuario_id"])
    u = svc.obtener_por_id(uid)
    if not u or not u.get("activo"):
        raise HTTPException(400, "La cuenta no está activa.")

    svc.actualizar(uid, password_hash=hash_password(body.password))
    # Primero la clave, después apagar los enlaces: si se cae en medio, la
    # persona ya puede entrar y los enlaces sobrantes vencen solos. Al revés
    # se quedaría afuera con todos los enlaces gastados.
    svc.gastar_tokens_de(uid, ahora=ahora.isoformat())
    # El bloqueo por intentos fallidos se limpia: si llegó acá fue porque no
    # podía entrar, y dejarlo bloqueado 15 minutos después de cambiar la clave
    # es cerrarle la puerta justo cuando por fin tiene la llave.
    #
    # OJO CON EL ALCANCE: el contador vive en memoria de CADA worker (son 4), y
    # esta petición la atendió uno solo, así que solo se limpia el de ese. No
    # es inútil —quita el bloqueo de un cuarto de los intentos— pero tampoco es
    # una garantía. Mover el contador a la base lo arreglaría de verdad; no se
    # hace acá porque los bloqueos duran 15 minutos y vencen solos.
    email = (u.get("email") or "").lower().strip()
    for tabla in (_LOGIN_ATTEMPTS, _LOGIN_BLOCKS):
        for key in [k for k in tabla if k[1] == email]:
            tabla.pop(key, None)

    log.info("reset: contraseña cambiada para %s", email)
    return {"ok": True, "email": u.get("email")}


@router.get("/me", response_model=CurrentUser)
def me(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """El usuario de la sesión, con los flags FRESCOS de la base.

    No se devuelve `user` tal cual: viene del token, y el token se firmó cuando la
    persona entró. Un permiso que se prende (o se revoca) ahora tiene que verse
    ahora, no cuando expire la sesión — que con la sesión deslizante puede ser
    nunca. Es la misma regla que usa el backend al verificar el permiso.
    """
    try:
        u = svc.obtener_por_id(user.id)
        if u:
            user = user.model_copy(update={
                "puede_ajustar_metraje": bool(u.get("puede_ajustar_metraje")),
                # El rol y activo también pueden haber cambiado desde el login.
                "rol": u.get("rol") or user.rol,
                "activo": bool(u.get("activo", True)),
                "permisos": u.get("permisos") or user.permisos,
            })
    except Exception:
        # Si la base no responde se devuelve lo del token: peor es no responder.
        pass
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
        puede_autorizar_precosteo=bool(u.get("puede_autorizar_precosteo")),
        puede_ajustar_metraje=bool(u.get("puede_ajustar_metraje")),
        puede_autorizar_corte=bool(u.get("puede_autorizar_corte")),
        creado_en=u.get("creado_en"),
    )


@router.get("/usuarios/diagnosticar")
def diagnosticar_usuario(
    email: str,
    _: CurrentUser = Depends(require_role("admin")),
) -> dict:
    """Diagnóstico de un usuario: existe, activo, rol, último login.
    Útil cuando alguien reporta que no puede entrar.
    """
    u = svc.obtener_por_email(email)
    if not u:
        return {"existe": False, "mensaje": f"No hay usuario con email {email}"}
    return {
        "existe": True,
        "email": u.get("email"),
        "nombre": u.get("nombre"),
        "rol": u.get("rol"),
        "activo": u.get("activo"),
        "cargo": u.get("cargo"),
        "tiene_permisos": bool(u.get("permisos")),
        "puede_loguearse": bool(u.get("activo")),
    }


@router.post("/usuarios/{uid}/resetear-bloqueo")
def resetear_bloqueo(
    uid: str,
    _: CurrentUser = Depends(require_role("admin")),
) -> dict:
    """Limpia el rate-limit de login para un usuario.
    Llamar cuando un usuario quedó bloqueado por intentos fallidos.
    """
    u = svc.obtener_por_id(uid)
    if not u:
        raise HTTPException(404, "Usuario no encontrado")
    email = (u.get("email") or "").lower().strip()
    # Limpiar todas las entradas del rate-limit para ese email (cualquier IP)
    claves_borradas = 0
    for key in list(_LOGIN_ATTEMPTS.keys()):
        if key[1] == email:
            _LOGIN_ATTEMPTS.pop(key, None)
            claves_borradas += 1
    for key in list(_LOGIN_BLOCKS.keys()):
        if key[1] == email:
            _LOGIN_BLOCKS.pop(key, None)
            claves_borradas += 1
    return {"ok": True, "email": email, "bloqueos_eliminados": claves_borradas}


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


@router.delete("/usuarios/{uid}", status_code=204)
def eliminar_usuario(
    uid: str,
    actor: CurrentUser = Depends(require_role("admin")),
) -> None:
    """Elimina un usuario definitivamente. Guardas:
    - no puedes eliminarte a ti mismo (usa desactivar si hace falta);
    - no se puede eliminar al último admin activo (evita lockout)."""
    if actor.id == uid:
        raise HTTPException(status_code=400, detail="No puedes eliminarte a ti mismo")
    u = svc.obtener_por_id(uid)
    if not u:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if u.get("rol") == "admin":
        admins_activos = [x for x in svc.listar() if x.get("rol") == "admin" and x.get("activo")]
        if len(admins_activos) <= 1:
            raise HTTPException(status_code=400, detail="No se puede eliminar al último admin activo")
    try:
        svc.eliminar(uid)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="No se pudo eliminar el usuario. Contacta al administrador.")
