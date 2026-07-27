"""
backend.api.personal — Módulo Personal: Tiempo, Asistencia y Permisos.

Fase 2: cimientos. Empleados, organización, reglas y autoservicio base.
Los eventos, el motor de asistencia y los permisos llegan en Fases 3 y 4.

Todo el router vive detrás de TIME_MANAGEMENT_ENABLED — si el flag está
apagado, main.py ni siquiera lo registra.

Convenciones (espeja backend/api/produccion.py):
  · Router nunca habla con Supabase; solo servicios.
  · ValueError del servicio → HTTPException 400 con código snake_case.
  · Respuestas dict crudos, sin response_model.
  · Modelos Pydantic inline, encima del bloque que los usa.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from backend.core.flags import FLAGS_PERSONAL, flags_activos
from backend.core.security import (
    CurrentUser, get_current_user, require_permission, require_role, tiene_permiso,
)
from backend.services import personal_auditoria as aud
from backend.services import personal_empleados as emp_svc
from backend.services import personal_organizacion as org_svc
from backend.services import personal_reglas as reglas_svc
from backend.services.personal_base import TablaNoExiste

router = APIRouter(prefix="/api/personal", tags=["personal"])


# ── Helpers compartidos ──────────────────────────────────────────────────────

def _error(nombre_func: str, e: Exception) -> HTTPException:
    """Traduce excepciones del servicio al contrato HTTP del repo."""
    if isinstance(e, ValueError):
        return HTTPException(400, str(e))
    if isinstance(e, TablaNoExiste):
        return HTTPException(503, "migracion_personal_no_aplicada")
    import traceback
    traceback.print_exc()
    return HTTPException(500, f"{nombre_func}: {str(e)[:200]}")


def _actor(request: Request, user: CurrentUser) -> dict:
    """Metadatos de auditoría del request actual."""
    return {
        "actor": user.email,
        "actor_id": user.id,
        "ip": (request.client.host if request.client else None),
        "user_agent": request.headers.get("user-agent"),
        "correlation_id": request.headers.get("x-correlation-id"),
    }


def empleado_actual(user: CurrentUser = Depends(get_current_user)) -> dict:
    """Dependency del autoservicio: el empleado enlazado al JWT.

    Esta es LA frontera de seguridad de /mi-tiempo. El empleado_id sale de
    aquí, nunca de un parámetro del request. Sin RLS en Supabase, es lo único
    que impide que alguien lea la asistencia de otro cambiando un id en la URL.
    """
    e = emp_svc.obtener_por_usuario(user.id)
    if not e:
        raise HTTPException(
            404,
            "usuario_sin_empleado_vinculado: pide a Talento Humano que "
            "enlace tu usuario con tu ficha de empleado",
        )
    return e


# ═══════════════════════════════════════════════════════════════════════
# ESTADO DEL MÓDULO
# ═══════════════════════════════════════════════════════════════════════

@router.get("/health")
def health(_: CurrentUser = Depends(require_role("admin"))) -> dict:
    """Diagnóstico: flags activos y si la migración ya corrió.

    `migracion_aplicada` se infiere de poder leer una tabla del módulo, que es
    más fiable que asumirlo por el flag.
    """
    sedes = org_svc.listar_sedes()
    empleados = emp_svc.listar(limit=1)
    migracion_ok = bool(sedes) or bool(empleados)
    if not migracion_ok:
        # Distinguir "tabla vacía" de "tabla ausente" requiere intentar leer.
        from backend.services.personal_base import _sb
        sb = _sb()
        if sb is not None:
            try:
                sb.table("personal_sedes").select("id").limit(1).execute()
                migracion_ok = True
            except Exception:
                migracion_ok = False

    return {
        "modulo": "personal",
        "fase": 2,
        "flags": flags_activos(*FLAGS_PERSONAL),
        "migracion_aplicada": migracion_ok,
        "sedes": len(sedes),
        "areas": len(org_svc.listar_areas()),
    }


# ═══════════════════════════════════════════════════════════════════════
# AUTOSERVICIO — sin permiso de módulo, todo empleado con login lo tiene
# ═══════════════════════════════════════════════════════════════════════

@router.get("/mi-tiempo/perfil")
def mi_perfil(yo: dict = Depends(empleado_actual)) -> dict:
    """Ficha propia del empleado autenticado."""
    sede = org_svc.obtener_sede(yo.get("sede_id")) if yo.get("sede_id") else None
    area = org_svc.obtener_area(yo.get("area_id")) if yo.get("area_id") else None
    jefe = emp_svc.obtener(yo["supervisor_id"]) if yo.get("supervisor_id") else None
    return {
        "empleado": yo,
        "sede": sede,
        "area": area,
        "supervisor": {"id": jefe["id"], "nombre_completo": jefe["nombre_completo"]}
                      if jefe else None,
    }


# ═══════════════════════════════════════════════════════════════════════
# EMPLEADOS
# ═══════════════════════════════════════════════════════════════════════

class EmpleadoIn(BaseModel):
    nombre_completo:   str = Field(min_length=1, max_length=200)
    numero_documento:  str = Field(min_length=1, max_length=30)
    fecha_ingreso:     str                      # YYYY-MM-DD
    tipo_documento:    str = "CC"
    codigo_empleado:   Optional[str] = None
    email:             Optional[str] = None
    telefono:          Optional[str] = None
    area_id:           Optional[str] = None
    sede_id:           Optional[str] = None
    cargo:             Optional[str] = None
    supervisor_id:     Optional[str] = None
    usuario_id:        Optional[str] = None
    tipo_contrato:     str = "termino_indefinido"
    sujeto_a_jornada:  bool = True


class EmpleadoPatch(BaseModel):
    nombre_completo:  Optional[str] = None
    email:            Optional[str] = None
    telefono:         Optional[str] = None
    area_id:          Optional[str] = None
    sede_id:          Optional[str] = None
    cargo:            Optional[str] = None
    supervisor_id:    Optional[str] = None
    tipo_contrato:    Optional[str] = None
    estado_laboral:   Optional[str] = None
    fecha_retiro:     Optional[str] = None
    sujeto_a_jornada: Optional[bool] = None


class VincularUsuarioBody(BaseModel):
    usuario_id: Optional[str] = None      # None desvincula


@router.get("/empleados")
def listar_empleados(
    area_id: Optional[str] = None,
    sede_id: Optional[str] = None,
    estado_laboral: Optional[str] = None,
    solo_vigentes: bool = False,
    q: Optional[str] = None,
    limit: int = Query(200, ge=1, le=500),
    user: CurrentUser = Depends(require_permission("personal", "ver")),
) -> dict:
    """Empleados visibles para el usuario, según su alcance.

    Un jefe ve su equipo; Talento Humano ve todo. El documento va enmascarado
    salvo para quien administra el módulo.
    """
    try:
        filas = emp_svc.listar(
            area_id=area_id, sede_id=sede_id, estado_laboral=estado_laboral,
            solo_vigentes=solo_vigentes, q=q, limit=limit,
        )
        alcance = emp_svc.alcance_empleados(user)
        if alcance is not None:
            permitidos = set(alcance)
            filas = [f for f in filas if f["id"] in permitidos]

        if not tiene_permiso(user, "personal", "modificar"):
            filas = [emp_svc.para_listado_publico(f) for f in filas]

        return {"empleados": filas, "total": len(filas)}
    except Exception as e:
        raise _error("listar_empleados", e)


@router.get("/empleados/{empleado_id}")
def obtener_empleado(
    empleado_id: str,
    user: CurrentUser = Depends(require_permission("personal", "ver")),
) -> dict:
    try:
        if not emp_svc.puede_ver_empleado(user, empleado_id):
            raise HTTPException(403, "fuera_de_tu_alcance")
        e = emp_svc.obtener(empleado_id)
        if not e:
            raise HTTPException(404, "empleado_no_existe")
        if not tiene_permiso(user, "personal", "modificar"):
            e = emp_svc.para_listado_publico(e)
        return {"empleado": e}
    except HTTPException:
        raise
    except Exception as e:
        raise _error("obtener_empleado", e)


@router.post("/empleados")
def crear_empleado(
    body: EmpleadoIn,
    request: Request,
    user: CurrentUser = Depends(require_permission("personal", "modificar")),
) -> dict:
    try:
        creado = emp_svc.crear(actor=user.email, **body.model_dump(exclude_none=True))
        return {"ok": True, "empleado": creado}
    except Exception as e:
        raise _error("crear_empleado", e)


@router.patch("/empleados/{empleado_id}")
def actualizar_empleado(
    empleado_id: str,
    body: EmpleadoPatch,
    user: CurrentUser = Depends(require_permission("personal", "modificar")),
) -> dict:
    try:
        campos = body.model_dump(exclude_unset=True, exclude_none=True)
        return {"ok": True,
                "empleado": emp_svc.actualizar(empleado_id, actor=user.email, **campos)}
    except Exception as e:
        raise _error("actualizar_empleado", e)


@router.post("/empleados/{empleado_id}/vincular-usuario")
def vincular_usuario(
    empleado_id: str,
    body: VincularUsuarioBody,
    user: CurrentUser = Depends(require_permission("personal", "modificar")),
) -> dict:
    """Enlaza el empleado con un login. Es lo que le habilita el autoservicio."""
    try:
        return {"ok": True,
                "empleado": emp_svc.vincular_usuario(
                    empleado_id, body.usuario_id, actor=user.email)}
    except Exception as e:
        raise _error("vincular_usuario", e)


@router.get("/empleados/{empleado_id}/equipo")
def equipo_del_empleado(
    empleado_id: str,
    incluir_indirectos: bool = True,
    user: CurrentUser = Depends(require_permission("personal", "ver")),
) -> dict:
    try:
        if not emp_svc.puede_ver_empleado(user, empleado_id):
            raise HTTPException(403, "fuera_de_tu_alcance")
        ids = emp_svc.equipo_de(empleado_id, incluir_indirectos=incluir_indirectos)
        todos = {e["id"]: e for e in emp_svc.listar(limit=500)}
        return {"equipo": [todos[i] for i in ids if i in todos]}
    except HTTPException:
        raise
    except Exception as e:
        raise _error("equipo_del_empleado", e)


# ═══════════════════════════════════════════════════════════════════════
# ORGANIZACIÓN — sedes y áreas
# ═══════════════════════════════════════════════════════════════════════

class SedeIn(BaseModel):
    nombre:    str = Field(min_length=1, max_length=120)
    direccion: Optional[str] = None
    timezone:  str = "America/Bogota"


class SedePatch(BaseModel):
    nombre:    Optional[str] = None
    direccion: Optional[str] = None
    timezone:  Optional[str] = None
    activa:    Optional[bool] = None


class AreaIn(BaseModel):
    nombre:  str = Field(min_length=1, max_length=120)
    sede_id: Optional[str] = None


class AreaPatch(BaseModel):
    nombre:  Optional[str] = None
    sede_id: Optional[str] = None
    activa:  Optional[bool] = None


@router.get("/sedes")
def listar_sedes(
    solo_activas: bool = False,
    _: CurrentUser = Depends(require_permission("personal", "ver")),
) -> dict:
    return {"sedes": org_svc.listar_sedes(solo_activas=solo_activas)}


@router.post("/sedes")
def crear_sede(
    body: SedeIn,
    user: CurrentUser = Depends(require_permission("personal_config", "modificar")),
) -> dict:
    try:
        return {"ok": True, "sede": org_svc.crear_sede(actor=user.email,
                                                       **body.model_dump())}
    except Exception as e:
        raise _error("crear_sede", e)


@router.patch("/sedes/{sede_id}")
def actualizar_sede(
    sede_id: str,
    body: SedePatch,
    user: CurrentUser = Depends(require_permission("personal_config", "modificar")),
) -> dict:
    try:
        campos = body.model_dump(exclude_unset=True)
        return {"ok": True, "sede": org_svc.actualizar_sede(sede_id, actor=user.email,
                                                            **campos)}
    except Exception as e:
        raise _error("actualizar_sede", e)


@router.get("/areas")
def listar_areas(
    sede_id: Optional[str] = None,
    solo_activas: bool = False,
    _: CurrentUser = Depends(require_permission("personal", "ver")),
) -> dict:
    return {"areas": org_svc.listar_areas(sede_id=sede_id, solo_activas=solo_activas)}


@router.post("/areas")
def crear_area(
    body: AreaIn,
    user: CurrentUser = Depends(require_permission("personal_config", "modificar")),
) -> dict:
    try:
        return {"ok": True, "area": org_svc.crear_area(actor=user.email,
                                                       **body.model_dump())}
    except Exception as e:
        raise _error("crear_area", e)


@router.patch("/areas/{area_id}")
def actualizar_area(
    area_id: str,
    body: AreaPatch,
    user: CurrentUser = Depends(require_permission("personal_config", "modificar")),
) -> dict:
    try:
        campos = body.model_dump(exclude_unset=True)
        return {"ok": True, "area": org_svc.actualizar_area(area_id, actor=user.email,
                                                            **campos)}
    except Exception as e:
        raise _error("actualizar_area", e)


# ═══════════════════════════════════════════════════════════════════════
# REGLAS LABORALES
# ═══════════════════════════════════════════════════════════════════════

class ReglaBody(BaseModel):
    valor:     object
    ambito:    str = "empresa"
    ambito_id: Optional[str] = None
    motivo:    Optional[str] = None


@router.get("/reglas")
def listar_reglas(
    ambito: Optional[str] = None,
    _: CurrentUser = Depends(require_permission("personal_config", "ver")),
) -> dict:
    """Catálogo completo: lo configurado más los defaults sin personalizar."""
    return {"reglas": reglas_svc.listar(ambito=ambito),
            "ambitos": list(reglas_svc.AMBITOS)}


@router.get("/reglas/resueltas")
def reglas_resueltas(
    empleado_id: Optional[str] = None,
    sede_id: Optional[str] = None,
    area_id: Optional[str] = None,
    _: CurrentUser = Depends(require_permission("personal_config", "ver")),
) -> dict:
    """Qué reglas aplican realmente a un contexto, y de qué ámbito salió cada una.

    Es la herramienta de diagnóstico cuando alguien pregunta "¿por qué a esta
    persona le contó tarde si tiene tolerancia?".
    """
    r = reglas_svc.resolver(empleado_id=empleado_id, sede_id=sede_id, area_id=area_id)
    return {
        "valores": r.as_dict(),
        "origen": {k: r.origen_de(k) for k in r.as_dict()},
    }


@router.patch("/reglas/{clave}")
def establecer_regla(
    clave: str,
    body: ReglaBody,
    request: Request,
    user: CurrentUser = Depends(require_permission("personal_config", "modificar")),
) -> dict:
    """Configura una regla.

    Las reglas sensibles (descuento automático, banco positivo, revisión humana)
    exigen motivo: cambiarlas altera cómo se trata el tiempo de la gente y debe
    quedar justificado en la auditoría.
    """
    try:
        if clave in reglas_svc.REGLAS_SENSIBLES and not (body.motivo or "").strip():
            raise ValueError("motivo_requerido_para_regla_sensible")
        return {"ok": True, "regla": reglas_svc.establecer(
            clave=clave, valor=body.valor, ambito=body.ambito,
            ambito_id=body.ambito_id, motivo=body.motivo, actor=user.email,
        )}
    except Exception as e:
        raise _error("establecer_regla", e)


# ═══════════════════════════════════════════════════════════════════════
# AUDITORÍA DEL MÓDULO
# ═══════════════════════════════════════════════════════════════════════

@router.get("/auditoria")
def listar_auditoria(
    entidad: Optional[str] = None,
    entidad_id: Optional[str] = None,
    actor: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    _: CurrentUser = Depends(require_permission("personal", "modificar")),
) -> dict:
    return {"registros": aud.listar(entidad=entidad, entidad_id=entidad_id,
                                    actor=actor, limit=limit)}
