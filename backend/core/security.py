"""
backend.core.security — JWT + bcrypt + dependency de usuario actual.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
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
    # Puede borrar ingresos de tela, cambiar los metros de un rollo y hacer
    # ajustes de stock. Se llena SIEMPRE desde la base en /auth/me, nunca desde el
    # token: así revocarlo tiene efecto inmediato.
    #
    # ESTUVO ROTO (2026-08-05): el campo se agregó a UsuarioOut —la lista de
    # /usuarios— pero no acá, y /auth/me devuelve CurrentUser. Resultado: el flag
    # nunca llegaba al navegador, el frontend lo leía como false y Sebastián se
    # quedó sin poder editar el metraje justo después de que le dieran el permiso.
    # Poner un control detrás de un dato que no viaja es peor que no ponerlo.
    puede_ajustar_metraje: bool = False


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


# ── Sesión deslizante ────────────────────────────────────────────────
# El token vive unas horas. Antes, cuando vencía, el frontend te echaba al
# /login en medio de lo que estuvieras haciendo — aunque llevaras todo el día
# trabajando en la app. Ahora: si al usuario le queda menos de la MITAD de la
# vida del token, se le entrega uno nuevo en la cabecera de la respuesta y el
# navegador lo guarda. Mientras uses la app, la sesión no se cae nunca.
#
# Se renueva a media vida y no en cada llamada para no reemitir un token en
# cada una de las decenas de peticiones que hace una pantalla.
#
# Por qué NO es un token eterno: `get_current_user` revalida contra la base
# cada 30 s que el usuario siga ACTIVO y con el mismo rol, así que desactivar
# a alguien en Supabase lo saca en medio minuto, dure lo que dure su token.

def renovar_token_si_conviene(token: str) -> Optional[str]:
    """Token nuevo si al actual le queda menos de media vida; None si no toca.

    Nunca lanza: esto corre en un middleware para TODAS las peticiones, y un
    token inválido o vencido no es asunto suyo — de eso se encarga el endpoint.
    """
    try:
        payload = jwt.decode(token, settings.auth_jwt_secret, algorithms=["HS256"])
    except Exception:
        return None

    exp = payload.get("exp")
    if not exp:
        return None
    restante_s = int(exp) - int(datetime.now(timezone.utc).timestamp())
    if restante_s <= 0:
        return None
    if restante_s > (settings.auth_jwt_expiry_min * 60) // 2:
        return None      # todavía le queda cuerda

    try:
        return create_access_token(CurrentUser(
            id=str(payload.get("sub") or ""),
            email=str(payload.get("email") or ""),
            nombre=str(payload.get("nombre") or ""),
            rol=str(payload.get("rol") or ""),
            cargo=str(payload.get("cargo") or ""),
            permisos=payload.get("permisos") or {},
        ))
    except Exception:
        return None


# ── Token de servicio de la Oficina Virtual ──────────────────────────
# Auditoría de seguridad 2026-11-08 (Oficina #26a). Antes el motor de la Oficina
# tenía AUTH_JWT_SECRET (allá MDS_JWT_SECRET) y se firmaba su propio token con
# «rol: admin». Con ese secreto se acuña la sesión de CUALQUIER persona del OS:
# comprometer el motor (una dependencia, un prompt injection con herramientas,
# una fuga de variables de Railway) era ser admin de producción, inventario y
# facturación. Ahora el motor firma con OFICINA_SERVICIO_SECRET, un secreto
# distinto, y ese token solo abre los endpoints que el motor de verdad usa, con
# permisos explícitos. Cualquier otra ruta: 403.

SERVICIO_SUB = "oficina-motor"
SERVICIO_AUD = "male-os-servicio"
SERVICIO_RUTAS: tuple[tuple[str, str], ...] = (
    ("GET",  r"/api/produccion/costeo-real"),         # Jefe de Producción
    ("POST", r"/api/produccion/rutas/[^/]+/notas"),   # nota_lote aprobada en el Despacho
    ("GET",  r"/api/finanzas/resumen"),               # Director Financiero
    ("GET",  r"/api/dashboard/overview"),             # Director Financiero
    ("GET",  r"/api/melonn/pedidos"),                 # Jefe de Logística
)
SERVICIO_PERMISOS = {
    "produccion_costos": ["ver"],
    "produccion_remisiones": ["ver", "modificar"],
}


def usuario_de_servicio(token: str, metodo: str, ruta: str) -> Optional[CurrentUser]:
    """El principal de servicio si el token es de la Oficina; None si no lo es.

    403 si es un token de servicio válido pero pide una ruta fuera de la lista.
    """
    secreto = settings.oficina_servicio_secret
    if not secreto:
        return None
    try:
        payload = jwt.decode(token, secreto, algorithms=["HS256"], audience=SERVICIO_AUD,
                             options={"require": ["exp", "sub", "aud"]})
    except jwt.InvalidTokenError:
        return None
    if payload.get("sub") != SERVICIO_SUB:
        return None
    if not any(m == metodo and re.fullmatch(p, ruta) for m, p in SERVICIO_RUTAS):
        raise HTTPException(status_code=403, detail="El token de servicio no abre esta ruta")
    return CurrentUser(
        id=SERVICIO_SUB, email="oficina@maledenim.com", nombre="Oficina Virtual (servicio)",
        rol="user", cargo="Servicio", permisos=SERVICIO_PERMISOS,
    )


# ── Dependency para extraer el usuario actual ────────────────────────

_bearer = HTTPBearer(auto_error=False)


def get_current_user(request: Request,
                     creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer)) -> CurrentUser:
    if creds is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autenticado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_token(creds.credentials)
    except HTTPException:
        # ¿token de servicio de la Oficina? (ver «Token de servicio» arriba)
        servicio = usuario_de_servicio(creds.credentials, request.method, request.url.path)
        if servicio is not None:
            return servicio
        raise

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
        sin_base = _svc._sb() is None   # desarrollo local sin Supabase
        try:
            db_user = _svc.obtener_por_id(uid)
            error_db = False
        except Exception:
            db_user, error_db = None, True
        if db_user is None and sin_base:
            # Sin Supabase configurada (solo pasa en local): se confía en el JWT.
            fresh = {
                "rol": payload.get("rol", "lector"),
                "permisos": payload.get("permisos", {}) or {},
                "activo": True,
            }
        elif db_user is None and error_db:
            # La base falló (pool, timeout). Se acepta la última lectura buena
            # de hasta 15 min; sin ella se FALLA CERRADO: un token con un `sub`
            # inventado o de un usuario borrado nunca entra por esta puerta.
            if cached and (now - cached["ts"]) < 900:
                return _current_user(uid, payload, cached["data"])
            raise HTTPException(status_code=503, detail="No se pudo verificar la sesión; intenta de nuevo")
        elif db_user is None:
            # La base respondió y el usuario NO existe (borrado o `sub` falso).
            _USER_CACHE.pop(uid, None)
            raise HTTPException(status_code=401, detail="Usuario no existe")
        elif not db_user.get("activo", True):
            _USER_CACHE.pop(uid, None)
            raise HTTPException(status_code=401, detail="Usuario inactivo")
        else:
            fresh = {
                "rol": db_user.get("rol") or payload["rol"],
                "permisos": db_user.get("permisos") or {},
                "activo": True,
            }
        _USER_CACHE[uid] = {"ts": now, "data": fresh}

    return _current_user(uid, payload, fresh)


def _current_user(uid: str, payload: dict, fresh: dict) -> CurrentUser:
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
        # core.permisos no importa nada: chequear un permiso no puede
        # depender del cliente de base de datos del ERP entero.
        from backend.core.permisos import MODULOS_GRUPOS
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


def require_permission_estricto(modulo: str, accion: str):
    """Como require_permission pero SIN herencia de roles legacy:
    solo pasan admin o usuarios con permiso EXPLÍCITO en el módulo.
    'lector' y 'operador' NO pasan aunque su rol normalmente lo permita.
    Para datos sensibles (costos, precios de producción).
    """
    def _check(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not user.activo:
            raise HTTPException(403, "Usuario inactivo")
        if user.rol == "admin":
            return user
        permisos = user.permisos or {}
        acciones = permisos.get(modulo)
        ok = (isinstance(acciones, list) and accion in acciones) or \
             (isinstance(acciones, dict) and acciones.get(accion))
        if not ok:
            raise HTTPException(
                403, f"Requiere permiso explícito de '{accion}' en '{modulo}'")
        return user
    return _check


def tiene_permiso_costos(user: CurrentUser) -> bool:
    """Helper para endpoints que degradan la respuesta (ocultan valores $)
    en vez de rechazar: True solo para admin o permiso explícito."""
    if not user or not user.activo:
        return False
    if user.rol == "admin":
        return True
    acciones = (user.permisos or {}).get("produccion_costos")
    if isinstance(acciones, list):
        return "ver" in acciones
    if isinstance(acciones, dict):
        return bool(acciones.get("ver"))
    return False


def tiene_permiso(user: CurrentUser, modulo: str, accion: str) -> bool:
    """Wrapper público de _check_permiso — para lógica condicional en endpoints."""
    return _check_permiso(user, modulo, accion)


def require_permission_any(modulos: tuple, accion: str):
    """Pasa si el usuario tiene la acción en CUALQUIERA de los módulos.
    Para roles acotados (ej. cortador) que comparten endpoints con el
    módulo completo pero con permiso propio."""
    def _check(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        for m in modulos:
            if _check_permiso(user, m, accion):
                return user
        raise HTTPException(
            status_code=403,
            detail=f"Sin permiso para '{accion}' en {'/'.join(modulos)}",
        )
    return _check
