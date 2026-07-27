"""
backend.services.personal_permisos — Solicitudes, aprobaciones y compensaciones.

Cablea el FSM puro (personal_permisos_logic) con Supabase, el libro de tiempo
y el recálculo de jornadas.

Cadena de efectos al aprobar un permiso compensable:

    aprobar_th()
      → estado = en_compensacion
      → crea personal_planes_compensacion
      → asiento `permiso_debito` en el libro     ← la deuda nace aquí
      → recalcula las jornadas afectadas         ← el motor ya ve el permiso

Y al validar la reposición:

    validar_compensacion()
      → lee los minutos REALES de la jornada     ← no los planeados
      → asiento `compensacion_credito`           ← la deuda se salda aquí
      → si se cubrió el total: permiso `completada`
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Optional

from backend.core.timeutils import parse_iso
from backend.services import personal_asistencia as asis_svc
from backend.services import personal_auditoria as aud
from backend.services import personal_libro as libro
from backend.services import personal_permisos_logic as L
from backend.services import personal_reglas as reglas_svc
from backend.services.personal_base import (
    _now_iso, _sb, es_error_tabla_faltante, hoy_bogota, sb_requerido,
)

log = logging.getLogger(__name__)


# ── Lectura ──────────────────────────────────────────────────────────────────

def obtener(permiso_id: str) -> Optional[dict]:
    sb = _sb()
    if sb is None:
        return None
    try:
        r = (sb.table("personal_solicitudes_permiso").select("*")
             .eq("id", permiso_id).limit(1).execute())
        return (r.data or [None])[0]
    except Exception:
        return None


def listar(*, empleado_id: Optional[str] = None, estado: Optional[str] = None,
           supervisor_id: Optional[str] = None, desde: Optional[str] = None,
           empleados_permitidos: Optional[list[str]] = None,
           limit: int = 200) -> list[dict]:
    sb = _sb()
    if sb is None:
        return []
    try:
        q = sb.table("personal_solicitudes_permiso").select("*")
        if empleado_id:
            q = q.eq("empleado_id", empleado_id)
        if estado:
            q = q.eq("estado", estado)
        if supervisor_id:
            q = q.eq("supervisor_id", supervisor_id)
        if desde:
            q = q.gte("inicio_solicitado_at", desde)
        r = q.order("created_at", desc=True).limit(min(max(limit, 1), 1000)).execute()
        filas = r.data or []
    except Exception as e:
        if es_error_tabla_faltante(e):
            return []
        log.error(f"[personal.permisos] error listando: {e}")
        return []

    # El alcance se aplica al final: ningún filtro del request lo amplía.
    if empleados_permitidos is not None:
        permitidos = set(empleados_permitidos)
        filas = [f for f in filas if f.get("empleado_id") in permitidos]
    return filas


def tipo_permiso(tipo_id: str) -> Optional[dict]:
    sb = _sb()
    if sb is None:
        return None
    try:
        r = (sb.table("personal_tipos_permiso").select("*")
             .eq("id", tipo_id).limit(1).execute())
        return (r.data or [None])[0]
    except Exception:
        return None


def listar_tipos(*, solo_activos: bool = True) -> list[dict]:
    sb = _sb()
    if sb is None:
        return []
    try:
        q = sb.table("personal_tipos_permiso").select("*")
        if solo_activos:
            q = q.eq("activo", True)
        return (q.order("nombre").execute().data) or []
    except Exception as e:
        if es_error_tabla_faltante(e):
            return []
        return []


# ── Creación ─────────────────────────────────────────────────────────────────

def crear(
    *, empleado_id: str, tipo_permiso_id: str, inicio: datetime, fin: datetime,
    motivo: str, archivo_soporte: Optional[str] = None,
    notas_cobertura: Optional[str] = None, actor: str = "sistema",
    enviar: bool = False,
) -> dict:
    """Crea una solicitud. Nace en `borrador` salvo que se pida enviarla ya."""
    tipo = tipo_permiso(tipo_permiso_id)
    if not tipo:
        raise ValueError("tipo_permiso_no_existe")
    if not tipo.get("activo", True):
        raise ValueError("tipo_permiso_inactivo")

    L.validar_clasificacion(tipo["categoria"], bool(tipo.get("es_compensable")))

    reglas = reglas_svc.resolver(empleado_id=empleado_id)
    minutos = L.validar_solicitud(
        inicio=inicio, fin=fin, motivo=motivo,
        minutos_max=tipo.get("minutos_max_solicitud"),
        requiere_soporte=bool(tipo.get("requiere_soporte")),
        tiene_soporte=bool(archivo_soporte),
        es_compensable=bool(tipo.get("es_compensable")),
        max_compensable=reglas.get("max_minutos_compensables"),
    )

    L.validar_sin_cruces(inicio, fin, _vigentes_del_empleado(empleado_id))

    from backend.services import personal_empleados as emp_svc
    emp = emp_svc.obtener(empleado_id)
    if not emp:
        raise ValueError("empleado_no_existe")

    fila = {
        "empleado_id":          empleado_id,
        "tipo_permiso_id":      tipo_permiso_id,
        "inicio_solicitado_at": inicio.isoformat(),
        "fin_solicitado_at":    fin.isoformat(),
        "minutos_solicitados":  minutos,
        "motivo":               motivo.strip()[:1000],
        "archivo_soporte":      archivo_soporte,
        "notas_cobertura":      notas_cobertura,
        "estado":               "borrador",
        "supervisor_id":        emp.get("supervisor_id"),
        "tratamiento_nomina":   L.tratamiento_nomina(tipo["categoria"]),
        "updated_at":           _now_iso(),
    }

    sb = sb_requerido()
    r = sb.table("personal_solicitudes_permiso").insert(fila).execute()
    creado = (r.data or [fila])[0]

    aud.registrar(actor=actor, accion="crear_permiso", entidad="solicitud_permiso",
                  entidad_id=creado.get("id"),
                  valores_despues={"tipo": tipo["codigo"], "minutos": minutos},
                  motivo=motivo)

    if enviar:
        return _transicionar(creado["id"], "enviada", actor=actor,
                             extra={"solicitada_at": _now_iso()})
    return creado


def _vigentes_del_empleado(empleado_id: str) -> list[dict]:
    """Permisos que podrían cruzarse con uno nuevo, con fechas ya parseadas."""
    sb = _sb()
    if sb is None:
        return []
    try:
        r = (sb.table("personal_solicitudes_permiso")
             .select("id,estado,inicio_solicitado_at,fin_solicitado_at")
             .eq("empleado_id", empleado_id)
             .in_("estado", ["enviada", "pendiente_jefe", "pendiente_th",
                             "aprobada", "en_compensacion"])
             .limit(200).execute())
        salida = []
        for p in (r.data or []):
            try:
                salida.append({**p,
                               "_inicio": parse_iso(p["inicio_solicitado_at"]).replace(tzinfo=None),
                               "_fin": parse_iso(p["fin_solicitado_at"]).replace(tzinfo=None)})
            except Exception:
                continue
        return salida
    except Exception:
        return []


# ── Transiciones ─────────────────────────────────────────────────────────────

def _transicionar(permiso_id: str, nuevo: str, *, actor: str,
                  extra: Optional[dict] = None, motivo: str = "") -> dict:
    """Cambio de estado validado por el FSM, con auditoría.

    Es el único camino para mover un permiso de estado. Nada lo hace por fuera.
    """
    actual_fila = obtener(permiso_id)
    if not actual_fila:
        raise ValueError("permiso_no_existe")
    actual = actual_fila.get("estado") or "borrador"

    if not L.transicion_valida(actual, nuevo):
        raise ValueError(f"transicion_invalida:{actual}__{nuevo}")

    update = {"estado": nuevo, "updated_at": _now_iso(), **(extra or {})}
    sb = sb_requerido()
    r = (sb.table("personal_solicitudes_permiso").update(update)
         .eq("id", permiso_id).eq("estado", actual).execute())
    if not r.data:
        # El .eq("estado", actual) es un claim optimista: si otro request ya
        # movió el permiso, este falla en vez de pisar su decisión.
        raise ValueError("permiso_cambio_de_estado_concurrentemente")

    aud.registrar(actor=actor, accion=f"permiso_{nuevo}", entidad="solicitud_permiso",
                  entidad_id=permiso_id,
                  valores_antes={"estado": actual}, valores_despues={"estado": nuevo},
                  motivo=motivo or None)
    return r.data[0]


def enviar(permiso_id: str, *, actor: str) -> dict:
    p = _transicionar(permiso_id, "enviada", actor=actor,
                      extra={"solicitada_at": _now_iso()})
    return _transicionar(permiso_id, "pendiente_jefe", actor=actor)


def aprobar_jefe(permiso_id: str, *, actor: str, notas: str = "") -> dict:
    return _transicionar(permiso_id, "pendiente_th", actor=actor,
                         extra={"decision_jefe_at": _now_iso(),
                                "notas_jefe": notas or None})


def rechazar_jefe(permiso_id: str, *, actor: str, notas: str) -> dict:
    if not (notas or "").strip():
        raise ValueError("motivo_de_rechazo_requerido")
    return _transicionar(permiso_id, "rechazada", actor=actor, motivo=notas,
                         extra={"decision_jefe_at": _now_iso(), "notas_jefe": notas})


def aprobar_th(permiso_id: str, *, actor: str, clasificacion_final: Optional[str] = None,
               notas: str = "") -> dict:
    """Talento Humano valida la clasificación y decide el camino.

    Puede RECLASIFICAR: el empleado pide "permiso personal compensable" y TH lo
    convierte en "calamidad doméstica" — que es legal, remunerado y NO
    compensable. Esa es la razón de ser de este paso.
    """
    p = obtener(permiso_id)
    if not p:
        raise ValueError("permiso_no_existe")

    tipo = tipo_permiso(p["tipo_permiso_id"]) or {}
    categoria = clasificacion_final or tipo.get("categoria")
    L.validar_clasificacion(categoria, bool(tipo.get("es_compensable")))

    # Solo lo compensable abre plan de reposición.
    compensable = bool(tipo.get("es_compensable")) and categoria == "personal_compensable"
    nuevo = "en_compensacion" if compensable else "aprobada"

    actualizado = _transicionar(
        permiso_id, nuevo, actor=actor,
        extra={"decision_th_at": _now_iso(), "revisor_th": actor,
               "notas_th": notas or None,
               "clasificacion_final": categoria,
               "tratamiento_nomina": L.tratamiento_nomina(categoria)})

    if compensable:
        _abrir_plan_compensacion(actualizado, actor=actor)

    _recalcular_afectadas(actualizado)
    return actualizado


def rechazar_th(permiso_id: str, *, actor: str, notas: str) -> dict:
    if not (notas or "").strip():
        raise ValueError("motivo_de_rechazo_requerido")
    return _transicionar(permiso_id, "rechazada", actor=actor, motivo=notas,
                         extra={"decision_th_at": _now_iso(), "revisor_th": actor,
                                "notas_th": notas})


def cancelar(permiso_id: str, *, actor: str, motivo: str = "") -> dict:
    p = obtener(permiso_id)
    if not p:
        raise ValueError("permiso_no_existe")
    if not L.puede_cancelar(p.get("estado") or ""):
        raise ValueError(f"no_cancelable_en_estado:{p.get('estado')}")
    cancelado = _transicionar(permiso_id, "cancelada", actor=actor, motivo=motivo)
    _recalcular_afectadas(cancelado)
    return cancelado


# ── Compensación ─────────────────────────────────────────────────────────────

def _abrir_plan_compensacion(permiso: dict, *, actor: str) -> dict:
    """Crea el plan y registra la DEUDA en el libro de tiempo."""
    reglas = reglas_svc.resolver(empleado_id=permiso["empleado_id"])
    inicio = parse_iso(permiso["inicio_solicitado_at"]).date()
    limite = L.fecha_limite_compensacion(
        inicio, plazo_dias=int(reglas.get("plazo_compensacion_dias", 7)))
    minutos = int(permiso["minutos_solicitados"])

    fila = {
        "solicitud_permiso_id": permiso["id"],
        "empleado_id":          permiso["empleado_id"],
        "minutos_a_compensar":  minutos,
        "minutos_compensados":  0,
        "minutos_pendientes":   minutos,
        "fecha_limite":         limite.isoformat(),
        "fecha_limite_original": limite.isoformat(),
        "estado":               "activo",
        "aprobado_por":         actor,
        "aprobado_at":          _now_iso(),
        "updated_at":           _now_iso(),
    }
    sb = sb_requerido()
    r = sb.table("personal_planes_compensacion").insert(fila).execute()
    plan = (r.data or [fila])[0]

    # La deuda nace aquí. Débito: el empleado DEBE ese tiempo.
    libro.registrar(
        empleado_id=permiso["empleado_id"], tipo_asiento="permiso_debito",
        minutos=minutos, tipo_origen="solicitud_permiso", origen_id=permiso["id"],
        fecha_efectiva=inicio, actor=actor,
        descripcion=f"Permiso compensable de {minutos} min · repone hasta {limite}",
    )
    return plan


def programar_bloques(plan_id: str, bloques: list[dict], *, actor: str) -> list[dict]:
    """Programa cuándo se va a reponer el tiempo. Programar no compensa."""
    plan = _obtener_plan(plan_id)
    if not plan:
        raise ValueError("plan_no_existe")
    if plan.get("estado") != "activo":
        raise ValueError(f"plan_no_activo:{plan.get('estado')}")

    limite = date.fromisoformat(plan["fecha_limite"][:10])
    reglas = reglas_svc.resolver(empleado_id=plan["empleado_id"])

    filas = []
    for b in bloques:
        ini = b["inicio"] if isinstance(b["inicio"], datetime) else parse_iso(b["inicio"])
        fin = b["fin"] if isinstance(b["fin"], datetime) else parse_iso(b["fin"])
        if fin <= ini:
            raise ValueError("rango_invalido")
        if ini.date() > limite and reglas.get("bloquear_compensacion_vencida", True):
            raise ValueError(f"bloque_despues_del_plazo:{limite}")
        filas.append({
            "plan_id":           plan_id,
            "fecha_programada":  ini.date().isoformat(),
            "inicio_planeado_at": ini.isoformat(),
            "fin_planeado_at":   fin.isoformat(),
            "minutos_planeados": int((fin - ini).total_seconds() // 60),
            "estado":            "programado",
            "updated_at":        _now_iso(),
        })

    sb = sb_requerido()
    r = sb.table("personal_bloques_compensacion").insert(filas).execute()
    aud.registrar(actor=actor, accion="programar_compensacion",
                  entidad="plan_compensacion", entidad_id=plan_id,
                  valores_despues={"bloques": len(filas)})

    for f in filas:
        asis_svc.recalcular(plan["empleado_id"], date.fromisoformat(f["fecha_programada"]))
    return r.data or filas


def validar_compensacion(plan_id: str, *, actor: str) -> dict:
    """Confronta lo programado con lo REALMENTE trabajado.

    Los minutos salen de personal_jornadas, nunca de lo planeado. Programar no
    es compensar: si no marcó, no repuso.
    """
    plan = _obtener_plan(plan_id)
    if not plan:
        raise ValueError("plan_no_existe")

    sb = sb_requerido()
    bloques = (sb.table("personal_bloques_compensacion").select("*")
               .eq("plan_id", plan_id).execute().data) or []

    total_real = 0
    for b in bloques:
        d = date.fromisoformat(b["fecha_programada"][:10])
        jornada = asis_svc.obtener(plan["empleado_id"], d)
        reales = int((jornada or {}).get("minutos_compensacion_aprob") or 0)
        estado = ("cumplido" if reales >= int(b["minutos_planeados"])
                  else "parcial" if reales > 0 else "incumplido")
        sb.table("personal_bloques_compensacion").update({
            "minutos_reales": reales, "estado": estado,
            "jornada_id": (jornada or {}).get("id"),
            "validado_at": _now_iso(), "updated_at": _now_iso(),
        }).eq("id", b["id"]).execute()
        total_real += reales

    ya_acreditado = int(plan.get("minutos_compensados") or 0)
    nuevo_credito = max(0, total_real - ya_acreditado)
    if nuevo_credito:
        # La deuda se salda aquí, y solo por lo efectivamente trabajado.
        libro.registrar(
            empleado_id=plan["empleado_id"], tipo_asiento="compensacion_credito",
            minutos=nuevo_credito, tipo_origen="plan_compensacion", origen_id=plan_id,
            actor=actor, descripcion=f"Reposición validada contra marcaciones reales",
        )

    limite = date.fromisoformat(plan["fecha_limite"][:10])
    estado_plan = L.estado_del_plan(int(plan["minutos_a_compensar"]),
                                    total_real, limite, hoy_bogota())

    r = sb.table("personal_planes_compensacion").update({
        "minutos_compensados": total_real,
        "minutos_pendientes": L.minutos_pendientes(int(plan["minutos_a_compensar"]),
                                                   total_real),
        "estado": estado_plan, "updated_at": _now_iso(),
    }).eq("id", plan_id).execute()

    if estado_plan == "completado":
        try:
            _transicionar(plan["solicitud_permiso_id"], "completada", actor=actor)
        except ValueError:
            pass          # ya estaba completada
    elif estado_plan == "vencido":
        _marcar_vencido(plan, actor=actor)

    return (r.data or [plan])[0]


def _marcar_vencido(plan: dict, *, actor: str) -> None:
    """Un plazo vencido NO se descuenta solo: genera novedad para revisión.

    INVARIANTE 4. La conversión automática a descuento está desactivada por
    diseño y protegida por test.
    """
    try:
        _transicionar(plan["solicitud_permiso_id"], "vencida", actor="sistema")
    except ValueError:
        pass

    pendientes = L.minutos_pendientes(int(plan["minutos_a_compensar"]),
                                      int(plan.get("minutos_compensados") or 0))
    if not pendientes:
        return
    sb = sb_requerido()
    try:
        sb.table("personal_novedades_nomina").insert({
            "empleado_id": plan["empleado_id"],
            "tipo_novedad": "compensacion_vencida",
            "tipo_origen": "plan_compensacion",
            "origen_id": plan["id"],
            "minutos": pendientes,
            "estado": "propuesta",     # ← nace como PROPUESTA, no aplicada
            "notas": f"Venció el plazo con {pendientes} min sin reponer. "
                     f"Requiere decisión de Talento Humano.",
        }).execute()
    except Exception as e:
        if not es_error_tabla_faltante(e):
            log.error(f"[personal.permisos] no se pudo crear novedad: {e}")


def _obtener_plan(plan_id: str) -> Optional[dict]:
    sb = _sb()
    if sb is None:
        return None
    try:
        r = (sb.table("personal_planes_compensacion").select("*")
             .eq("id", plan_id).limit(1).execute())
        return (r.data or [None])[0]
    except Exception:
        return None


def listar_planes(*, empleado_id: Optional[str] = None, estado: Optional[str] = None,
                  limit: int = 200) -> list[dict]:
    sb = _sb()
    if sb is None:
        return []
    try:
        q = sb.table("personal_planes_compensacion").select("*")
        if empleado_id:
            q = q.eq("empleado_id", empleado_id)
        if estado:
            q = q.eq("estado", estado)
        return (q.order("fecha_limite").limit(limit).execute().data) or []
    except Exception:
        return []


# ── Recálculo tras un cambio ─────────────────────────────────────────────────

def _recalcular_afectadas(permiso: dict) -> None:
    """Aprobar o cancelar un permiso cambia las jornadas que toca."""
    try:
        ini = parse_iso(permiso["inicio_solicitado_at"]).date()
        fin = parse_iso(permiso["fin_solicitado_at"]).date()
        dias = (fin - ini).days + 1
        for i in range(min(dias, 60)):
            asis_svc.recalcular(permiso["empleado_id"], ini + timedelta(days=i))
    except Exception as e:
        log.warning(f"[personal.permisos] recálculo tras cambio falló: {e}")
