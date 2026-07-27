"""
backend.api.personal — Módulo Personal: Tiempo, Asistencia y Permisos.

Cubre empleados, organización, reglas, asistencia, permisos, compensaciones,
incidencias y autoservicio. El frontend llega en la Fase 5.

Todo el router vive detrás de TIME_MANAGEMENT_ENABLED — si el flag está
apagado, main.py ni siquiera lo registra.

Convenciones (espeja backend/api/produccion.py):
  · Router nunca habla con Supabase; solo servicios.
  · ValueError del servicio → HTTPException 400 con código snake_case.
  · Respuestas dict crudos, sin response_model.
  · Modelos Pydantic inline, encima del bloque que los usa.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from fastapi import (APIRouter, Depends, File, Form, HTTPException, Query,
                     Request, UploadFile)
from pydantic import BaseModel, Field

from backend.core.flags import FLAGS_PERSONAL, flags_activos
from backend.core.security import (
    CurrentUser, get_current_user, require_permission, require_role, tiene_permiso,
)
from backend.services import personal_asistencia as asis_svc
from backend.services import personal_auditoria as aud
from backend.services import personal_empleados as emp_svc
from backend.services import personal_importador as importador
from backend.services import personal_libro as libro_svc
from backend.services import personal_organizacion as org_svc
from backend.services import personal_permisos as perm_svc
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
        # Neutro a propósito. No todo usuario del sistema es empleado de
        # nómina: hay cuentas de servicio (Agente Impresión) y terceros con
        # acceso (cortador, financiero externo). Decirles "pide que te
        # enlacen" sería incorrecto — no deben tener ficha.
        raise HTTPException(404, "el modulo de asistencia no aplica para esta cuenta")
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
        "backend_completo": True,      # Fases 0-4; el frontend llega en la 5
        "flags": flags_activos(*FLAGS_PERSONAL),
        "migracion_aplicada": migracion_ok,
        "sedes": len(sedes),
        "areas": len(org_svc.listar_areas()),
    }


# ═══════════════════════════════════════════════════════════════════════
# AUTOSERVICIO — sin permiso de módulo, todo empleado con login lo tiene
# ═══════════════════════════════════════════════════════════════════════

@router.get("/mi-tiempo/perfil")
def mi_perfil(user: CurrentUser = Depends(get_current_user)) -> dict:
    """Ficha propia del empleado autenticado.

    Devuelve 200 con `aplica: false` en vez de 404 cuando la cuenta no
    corresponde a un empleado. Es la sonda que usa el frontend para decidir
    si mostrar "Mi tiempo": como ese link no exige permiso, lo alcanzan
    también cuentas de servicio y terceros, y para ellos NO es un error —
    simplemente no les aplica. Un 404 los mandaría a una pantalla roja por
    una situación perfectamente normal.
    """
    yo = emp_svc.obtener_por_usuario(user.id)
    if not yo:
        return {"aplica": False, "empleado": None,
                "motivo": "esta cuenta no corresponde a un empleado de nomina"}

    sede = org_svc.obtener_sede(yo.get("sede_id")) if yo.get("sede_id") else None
    area = org_svc.obtener_area(yo.get("area_id")) if yo.get("area_id") else None
    jefe = emp_svc.obtener(yo["supervisor_id"]) if yo.get("supervisor_id") else None
    return {
        "aplica": True,
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


@router.post("/empleados/importar/previsualizar")
async def previsualizar_importacion(
    archivo: UploadFile = File(...),
    _: CurrentUser = Depends(require_permission("personal", "modificar")),
) -> dict:
    """Paso 1 de la carga masiva: lee el archivo y muestra qué haría.

    No escribe nada. Devuelve qué se crearía, qué se actualizaría, qué filas
    tienen error y por qué, y avisos de fechas ambiguas.

    Nunca se importa a ciegas: 21 cédulas mal cargadas son fáciles de meter y
    molestas de deshacer.
    """
    try:
        contenido = await archivo.read()
        if not contenido:
            raise HTTPException(400, "archivo_vacio")
        if len(contenido) > 5 * 1024 * 1024:
            raise HTTPException(413, "archivo_demasiado_grande:max_5mb")
        return {"ok": True, "plan": importador.previsualizar(
            contenido, archivo.filename or "")}
    except HTTPException:
        raise
    except Exception as e:
        raise _error("previsualizar_importacion", e)


@router.post("/empleados/importar")
async def importar_empleados(
    archivo: UploadFile = File(...),
    confirmar: bool = Form(False),
    actualizar_existentes: bool = Form(True),
    user: CurrentUser = Depends(require_permission("personal", "modificar")),
) -> dict:
    """Paso 2: ejecuta la carga. Exige `confirmar=true` explícito.

    Idempotente por (tipo_documento, numero_documento): volver a subir el
    mismo archivo actualiza en vez de duplicar.
    """
    try:
        if not confirmar:
            raise HTTPException(
                400, "debes_confirmar:revisa_primero_con_/importar/previsualizar")
        contenido = await archivo.read()
        if not contenido:
            raise HTTPException(400, "archivo_vacio")
        if len(contenido) > 5 * 1024 * 1024:
            raise HTTPException(413, "archivo_demasiado_grande:max_5mb")

        plan = importador.previsualizar(contenido, archivo.filename or "")
        resultado = importador.aplicar(plan, actor=user.email,
                                       actualizar_existentes=actualizar_existentes)
        aud.registrar(actor=user.email, accion="importar_empleados",
                      entidad="empleado",
                      valores_despues={"archivo": archivo.filename, **resultado})
        return {"ok": True, **resultado,
                "errores_del_archivo": plan.get("errores", []),
                "avisos": plan.get("avisos", [])}
    except HTTPException:
        raise
    except Exception as e:
        raise _error("importar_empleados", e)


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
# ASISTENCIA
# ═══════════════════════════════════════════════════════════════════════

class RecalcularBody(BaseModel):
    empleado_id: Optional[str] = None
    desde:       str                       # YYYY-MM-DD
    hasta:       Optional[str] = None
    forzar:      bool = False              # ignora el bloqueo de periodo cerrado


@router.get("/asistencia")
def listar_asistencia(
    desde: Optional[str] = None,
    hasta: Optional[str] = None,
    empleado_id: Optional[str] = None,
    estado: Optional[str] = None,
    limit: int = Query(500, ge=1, le=2000),
    user: CurrentUser = Depends(require_permission("personal_asistencia", "ver")),
) -> dict:
    try:
        alcance = emp_svc.alcance_empleados(user)
        filas = asis_svc.listar(desde=desde, hasta=hasta, empleado_id=empleado_id,
                                estado=estado, empleados_permitidos=alcance,
                                limit=limit)
        return {"jornadas": filas, "total": len(filas)}
    except Exception as e:
        raise _error("listar_asistencia", e)


@router.get("/asistencia/{empleado_id}/{fecha}")
def obtener_asistencia(
    empleado_id: str,
    fecha: str,
    user: CurrentUser = Depends(require_permission("personal_asistencia", "ver")),
) -> dict:
    """Jornada de un día, con la explicación de cómo se calculó.

    La explicación es lo que convierte un número en una conversación posible:
    "llegaste 12 min tarde porque tu horario empieza 8:00, marcaste 8:12 y la
    tolerancia son 5 min".
    """
    try:
        if not emp_svc.puede_ver_empleado(user, empleado_id):
            raise HTTPException(403, "fuera_de_tu_alcance")
        j = asis_svc.obtener(empleado_id, _fecha(fecha))
        if not j:
            raise HTTPException(404, "jornada_no_calculada")
        return {"jornada": j}
    except HTTPException:
        raise
    except Exception as e:
        raise _error("obtener_asistencia", e)


@router.post("/asistencia/recalcular")
def recalcular_asistencia(
    body: RecalcularBody,
    user: CurrentUser = Depends(require_permission("personal_asistencia", "modificar")),
) -> dict:
    """Reprocesa un rango. Idempotente: correrlo dos veces da lo mismo.

    `forzar` salta el bloqueo de las jornadas de periodos cerrados y exige
    permiso de borrar — es lo más cerca de reescribir historia que hay aquí.
    """
    try:
        if body.forzar and not tiene_permiso(user, "personal_asistencia", "borrar"):
            raise HTTPException(403, "forzar_requiere_permiso_de_borrar")
        desde = _fecha(body.desde)
        hasta = _fecha(body.hasta) if body.hasta else desde
        if not body.empleado_id:
            raise HTTPException(400, "empleado_id_requerido")
        r = asis_svc.recalcular_rango(body.empleado_id, desde, hasta, forzar=body.forzar)
        aud.registrar(actor=user.email, accion="recalcular_asistencia",
                      entidad="jornada", entidad_id=body.empleado_id,
                      valores_despues={"desde": body.desde, "hasta": body.hasta,
                                       "forzar": body.forzar})
        return {"ok": True, **r}
    except HTTPException:
        raise
    except Exception as e:
        raise _error("recalcular_asistencia", e)


def _fecha(txt: str) -> date:
    try:
        return date.fromisoformat(txt[:10])
    except Exception:
        raise HTTPException(400, f"fecha_invalida:{txt}")


# ═══════════════════════════════════════════════════════════════════════
# PERMISOS
# ═══════════════════════════════════════════════════════════════════════

class PermisoIn(BaseModel):
    tipo_permiso_id:  str
    inicio:           str                  # ISO 8601
    fin:              str
    motivo:           str = Field(min_length=3, max_length=1000)
    empleado_id:      Optional[str] = None  # si se omite, el del JWT
    archivo_soporte:  Optional[str] = None
    notas_cobertura:  Optional[str] = None
    enviar:           bool = False


class DecisionBody(BaseModel):
    notas:                Optional[str] = None
    clasificacion_final:  Optional[str] = None


@router.get("/permisos/tipos")
def listar_tipos_permiso(
    _: CurrentUser = Depends(get_current_user),
) -> dict:
    """Catálogo de tipos. Lo consulta cualquier empleado para solicitar."""
    return {"tipos": perm_svc.listar_tipos()}


@router.get("/permisos")
def listar_permisos(
    estado: Optional[str] = None,
    empleado_id: Optional[str] = None,
    limit: int = Query(200, ge=1, le=1000),
    user: CurrentUser = Depends(require_permission("personal_permisos", "ver")),
) -> dict:
    try:
        alcance = emp_svc.alcance_empleados(user)
        filas = perm_svc.listar(estado=estado, empleado_id=empleado_id,
                                empleados_permitidos=alcance, limit=limit)
        return {"permisos": filas, "total": len(filas)}
    except Exception as e:
        raise _error("listar_permisos", e)


@router.get("/permisos/{permiso_id}")
def obtener_permiso(
    permiso_id: str,
    user: CurrentUser = Depends(require_permission("personal_permisos", "ver")),
) -> dict:
    try:
        p = perm_svc.obtener(permiso_id)
        if not p:
            raise HTTPException(404, "permiso_no_existe")
        if not emp_svc.puede_ver_empleado(user, p["empleado_id"]):
            raise HTTPException(403, "fuera_de_tu_alcance")
        return {"permiso": p}
    except HTTPException:
        raise
    except Exception as e:
        raise _error("obtener_permiso", e)


@router.post("/permisos")
def crear_permiso(
    body: PermisoIn,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Crea una solicitud.

    Sin `empleado_id` la crea para uno mismo (autoservicio). Pedirla a nombre
    de otro exige permiso de modificar — es la vía para que Talento Humano
    registre el permiso de quien no tiene login.
    """
    try:
        if body.empleado_id:
            if not tiene_permiso(user, "personal_permisos", "modificar"):
                raise HTTPException(403, "no_puedes_solicitar_a_nombre_de_otro")
            empleado_id = body.empleado_id
        else:
            empleado_id = empleado_actual(user)["id"]

        return {"ok": True, "permiso": perm_svc.crear(
            empleado_id=empleado_id, tipo_permiso_id=body.tipo_permiso_id,
            inicio=_instante(body.inicio), fin=_instante(body.fin),
            motivo=body.motivo, archivo_soporte=body.archivo_soporte,
            notas_cobertura=body.notas_cobertura, actor=user.email,
            enviar=body.enviar)}
    except HTTPException:
        raise
    except Exception as e:
        raise _error("crear_permiso", e)


def _instante(txt: str) -> datetime:
    from backend.core.timeutils import parse_iso
    try:
        return parse_iso(txt).replace(tzinfo=None)
    except Exception:
        raise HTTPException(400, f"fecha_hora_invalida:{txt}")


@router.post("/permisos/{permiso_id}/enviar")
def enviar_permiso(permiso_id: str,
                   user: CurrentUser = Depends(get_current_user)) -> dict:
    try:
        _solo_propio_o_con_permiso(user, permiso_id)
        return {"ok": True, "permiso": perm_svc.enviar(permiso_id, actor=user.email)}
    except HTTPException:
        raise
    except Exception as e:
        raise _error("enviar_permiso", e)


@router.post("/permisos/{permiso_id}/aprobar-jefe")
def aprobar_jefe(
    permiso_id: str, body: DecisionBody,
    user: CurrentUser = Depends(require_permission("personal_permisos", "modificar")),
) -> dict:
    """El jefe evalúa la AFECTACIÓN OPERATIVA, no la clasificación."""
    try:
        return {"ok": True, "permiso": perm_svc.aprobar_jefe(
            permiso_id, actor=user.email, notas=body.notas or "")}
    except Exception as e:
        raise _error("aprobar_jefe", e)


@router.post("/permisos/{permiso_id}/rechazar-jefe")
def rechazar_jefe(
    permiso_id: str, body: DecisionBody,
    user: CurrentUser = Depends(require_permission("personal_permisos", "modificar")),
) -> dict:
    try:
        return {"ok": True, "permiso": perm_svc.rechazar_jefe(
            permiso_id, actor=user.email, notas=body.notas or "")}
    except Exception as e:
        raise _error("rechazar_jefe", e)


@router.post("/permisos/{permiso_id}/aprobar-th")
def aprobar_th(
    permiso_id: str, body: DecisionBody,
    user: CurrentUser = Depends(require_permission("personal_permisos", "modificar")),
) -> dict:
    """Talento Humano valida la CLASIFICACIÓN y puede reclasificar."""
    try:
        return {"ok": True, "permiso": perm_svc.aprobar_th(
            permiso_id, actor=user.email,
            clasificacion_final=body.clasificacion_final, notas=body.notas or "")}
    except Exception as e:
        raise _error("aprobar_th", e)


@router.post("/permisos/{permiso_id}/rechazar-th")
def rechazar_th(
    permiso_id: str, body: DecisionBody,
    user: CurrentUser = Depends(require_permission("personal_permisos", "modificar")),
) -> dict:
    try:
        return {"ok": True, "permiso": perm_svc.rechazar_th(
            permiso_id, actor=user.email, notas=body.notas or "")}
    except Exception as e:
        raise _error("rechazar_th", e)


@router.post("/permisos/{permiso_id}/cancelar")
def cancelar_permiso(permiso_id: str, body: DecisionBody,
                     user: CurrentUser = Depends(get_current_user)) -> dict:
    try:
        _solo_propio_o_con_permiso(user, permiso_id)
        return {"ok": True, "permiso": perm_svc.cancelar(
            permiso_id, actor=user.email, motivo=body.notas or "")}
    except HTTPException:
        raise
    except Exception as e:
        raise _error("cancelar_permiso", e)


def _solo_propio_o_con_permiso(user: CurrentUser, permiso_id: str) -> dict:
    """Un empleado puede mover SUS solicitudes; para las ajenas hace falta rol."""
    p = perm_svc.obtener(permiso_id)
    if not p:
        raise HTTPException(404, "permiso_no_existe")
    if tiene_permiso(user, "personal_permisos", "modificar"):
        return p
    yo = emp_svc.obtener_por_usuario(user.id)
    if not yo or yo["id"] != p["empleado_id"]:
        raise HTTPException(403, "solo_puedes_gestionar_tus_propias_solicitudes")
    return p


# ═══════════════════════════════════════════════════════════════════════
# COMPENSACIONES
# ═══════════════════════════════════════════════════════════════════════

class BloqueIn(BaseModel):
    inicio: str
    fin:    str


class BloquesBody(BaseModel):
    bloques: list[BloqueIn] = Field(min_length=1, max_length=30)


@router.get("/compensaciones")
def listar_compensaciones(
    estado: Optional[str] = None,
    empleado_id: Optional[str] = None,
    user: CurrentUser = Depends(require_permission("personal_permisos", "ver")),
) -> dict:
    try:
        alcance = emp_svc.alcance_empleados(user)
        planes = perm_svc.listar_planes(empleado_id=empleado_id, estado=estado)
        if alcance is not None:
            permitidos = set(alcance)
            planes = [p for p in planes if p.get("empleado_id") in permitidos]
        return {"planes": planes, "total": len(planes)}
    except Exception as e:
        raise _error("listar_compensaciones", e)


@router.post("/compensaciones/{plan_id}/bloques")
def programar_bloques(
    plan_id: str, body: BloquesBody,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Programa cuándo se repone. Programar no compensa: solo cuenta lo que
    después confirmen las marcaciones reales."""
    try:
        bloques = [{"inicio": _instante(b.inicio), "fin": _instante(b.fin)}
                   for b in body.bloques]
        return {"ok": True, "bloques": perm_svc.programar_bloques(
            plan_id, bloques, actor=user.email)}
    except HTTPException:
        raise
    except Exception as e:
        raise _error("programar_bloques", e)


@router.post("/compensaciones/{plan_id}/validar")
def validar_compensacion(
    plan_id: str,
    user: CurrentUser = Depends(require_permission("personal_permisos", "modificar")),
) -> dict:
    """Confronta lo programado con lo realmente trabajado y acredita el libro."""
    try:
        return {"ok": True, "plan": perm_svc.validar_compensacion(
            plan_id, actor=user.email)}
    except Exception as e:
        raise _error("validar_compensacion", e)


# ═══════════════════════════════════════════════════════════════════════
# MI TIEMPO — saldo y extracto
# ═══════════════════════════════════════════════════════════════════════

@router.get("/mi-tiempo/saldo")
def mi_saldo(yo: dict = Depends(empleado_actual)) -> dict:
    """Extracto del libro de tiempo. Solo lectura: el saldo no se edita."""
    return libro_svc.extracto(yo["id"])


@router.get("/mi-tiempo/historial")
def mi_historial(
    desde: Optional[str] = None, hasta: Optional[str] = None,
    limit: int = Query(60, ge=1, le=400),
    yo: dict = Depends(empleado_actual),
) -> dict:
    return {"jornadas": asis_svc.listar(empleado_id=yo["id"], desde=desde,
                                        hasta=hasta, limit=limit)}


@router.get("/mi-tiempo/permisos")
def mis_permisos(yo: dict = Depends(empleado_actual)) -> dict:
    return {"permisos": perm_svc.listar(empleado_id=yo["id"], limit=200)}


# ═══════════════════════════════════════════════════════════════════════
# DASHBOARD
# ═══════════════════════════════════════════════════════════════════════

@router.get("/dashboard")
def dashboard(
    fecha: Optional[str] = None,
    user: CurrentUser = Depends(require_permission("personal", "ver")),
) -> dict:
    """Foto del día: quién está, quién falta, qué hay pendiente.

    Respeta el alcance del rol: un jefe ve su equipo, TH ve todo.
    """
    from backend.services.personal_base import _sb, hoy_bogota, quincena_de

    try:
        hoy = _fecha(fecha) if fecha else hoy_bogota()
        alcance = emp_svc.alcance_empleados(user)

        empleados = emp_svc.listar(solo_vigentes=True, limit=500)
        if alcance is not None:
            permitidos = set(alcance)
            empleados = [e for e in empleados if e["id"] in permitidos]
        ids = {e["id"] for e in empleados}

        jornadas = [j for j in asis_svc.listar(desde=hoy.isoformat(),
                                               hasta=hoy.isoformat(), limit=500)
                    if j.get("empleado_id") in ids]

        def cuenta(*estados):
            return sum(1 for j in jornadas if j.get("estado_asistencia") in estados)

        # Un empleado sin jornada calculada hoy no es "ausente": puede que el
        # motor aún no haya corrido. Se cuenta aparte para no alarmar.
        sin_calcular = len(ids) - len(jornadas)

        permisos = perm_svc.listar(limit=500,
                                   empleados_permitidos=alcance)
        pendientes = [p for p in permisos
                      if p.get("estado") in ("pendiente_jefe", "pendiente_th")]

        sb = _sb()
        incidencias_abiertas = 0
        if sb is not None:
            try:
                r = (sb.table("personal_incidencias").select("id", count="exact")
                     .in_("estado", ["abierta", "en_revision"]).execute())
                incidencias_abiertas = r.count or 0
            except Exception:
                pass

        planes = perm_svc.listar_planes(estado="activo", limit=200)
        if alcance is not None:
            planes = [p for p in planes if p.get("empleado_id") in ids]
        por_compensar = sum(int(p.get("minutos_pendientes") or 0) for p in planes)

        ini_q, fin_q = quincena_de(hoy)
        return {
            "fecha": hoy.isoformat(),
            "quincena": {"desde": ini_q.isoformat(), "hasta": fin_q.isoformat()},
            "programados": len(ids),
            "presentes": cuenta("completa", "tarde", "salida_anticipada", "incompleta"),
            "ausentes": cuenta("ausente"),
            "tarde": cuenta("tarde"),
            "en_permiso": cuenta("permiso", "vacaciones", "incapacidad"),
            "descanso": cuenta("descanso", "festivo"),
            "sin_calcular": max(0, sin_calcular),
            "solicitudes_pendientes": len(pendientes),
            "incidencias_abiertas": incidencias_abiertas,
            "minutos_por_compensar": por_compensar,
            "posible_extra_hoy": sum(int(j.get("minutos_posible_extra") or 0)
                                     for j in jornadas),
            "extra_aprobada_hoy": sum(int(j.get("minutos_extra_aprobada") or 0)
                                      for j in jornadas),
            "puntualidad_pct": _puntualidad(jornadas),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise _error("dashboard", e)


def _puntualidad(jornadas: list[dict]) -> Optional[float]:
    """% de quienes llegaron a tiempo, sobre los que efectivamente vinieron.

    Devuelve None si nadie tenía jornada: 100% sobre cero personas es una
    cifra engañosa en un tablero.
    """
    con_entrada = [j for j in jornadas if j.get("primera_entrada_at")]
    if not con_entrada:
        return None
    a_tiempo = sum(1 for j in con_entrada if not int(j.get("minutos_tarde") or 0))
    return round(a_tiempo * 100 / len(con_entrada), 1)


# ═══════════════════════════════════════════════════════════════════════
# INCIDENCIAS
# ═══════════════════════════════════════════════════════════════════════

@router.get("/incidencias")
def listar_incidencias(
    estado: Optional[str] = None,
    tipo: Optional[str] = None,
    limit: int = Query(200, ge=1, le=1000),
    user: CurrentUser = Depends(require_permission("personal_asistencia", "ver")),
) -> dict:
    from backend.services.personal_base import _sb
    sb = _sb()
    if sb is None:
        return {"incidencias": []}
    try:
        q = sb.table("personal_incidencias").select("*")
        if estado:
            q = q.eq("estado", estado)
        if tipo:
            q = q.eq("tipo_incidencia", tipo)
        filas = (q.order("detectada_at", desc=True).limit(limit).execute().data) or []
        alcance = emp_svc.alcance_empleados(user)
        if alcance is not None:
            permitidos = set(alcance)
            filas = [f for f in filas
                     if not f.get("empleado_id") or f["empleado_id"] in permitidos]
        return {"incidencias": filas, "total": len(filas)}
    except Exception as e:
        raise _error("listar_incidencias", e)


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
