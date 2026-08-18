"""
backend.services.personal_asistencia — Orquesta el motor con la persistencia.

El motor (personal_motor) es puro: recibe datos y devuelve datos. Este módulo
es el que va a Supabase, arma los insumos, lo invoca y guarda el resultado.

Idempotencia en la persistencia
───────────────────────────────
Que el motor sea determinista no basta: guardar dos veces no debe duplicar
nada. Por eso:

  · La jornada se hace UPSERT por (empleado_id, work_date) — hay índice único.
  · Los segmentos se BORRAN y se reescriben: son 100% derivados.
  · Las incidencias ABIERTAS se reemplazan; las resueltas o en revisión se
    respetan. Recalcular no puede borrar el trabajo de una persona.

Jornadas bloqueadas
───────────────────
Una jornada con `bloqueado_at` pertenece a un periodo cerrado y NO se
recalcula. Para tocarla hay que reabrir el periodo, con motivo y auditoría.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from typing import Optional

from backend.core.timeutils import parse_iso
from backend.services import personal_eventos as ev_svc
from backend.services import personal_motor as motor
from backend.services import personal_reglas as reglas_svc
from backend.services.personal_base import (
    BOGOTA, _now_iso, _sb, cache_get, cache_set, es_error_tabla_faltante,
    sb_requerido,
)

log = logging.getLogger(__name__)

_CACHE_FESTIVOS = "personal:festivos"
_TTL_FESTIVOS = 3600


# ── Carga de insumos ─────────────────────────────────────────────────────────

def _festivos() -> set[date]:
    cacheado = cache_get(_CACHE_FESTIVOS)
    if cacheado is not None:
        return cacheado
    sb = _sb()
    if sb is None:
        return set()
    try:
        r = sb.table("personal_festivos").select("fecha").eq("pais", "CO").execute()
        fechas = {date.fromisoformat(f["fecha"][:10]) for f in (r.data or [])}
    except Exception as e:
        if not es_error_tabla_faltante(e):
            log.error(f"[personal.asistencia] error leyendo festivos: {e}")
        fechas = set()
    return cache_set(_CACHE_FESTIVOS, fechas, _TTL_FESTIVOS)


def _hora(txt) -> Optional[time]:
    if not txt:
        return None
    if isinstance(txt, time):
        return txt
    partes = str(txt).split(":")
    return time(int(partes[0]), int(partes[1]) if len(partes) > 1 else 0)


def resolver_horario(empleado_id: str, work_date: date) -> Optional[motor.HorarioDia]:
    """Resuelve el horario del día, en orden estricto de precedencia:

        1. turno planificado para (empleado, fecha)  → rotación de tienda
        2. asignación vigente + plantilla del día de semana
        3. ninguno → None, y el motor levanta incidencia

    Nunca se asume un horario por defecto: un empleado sin horario es un
    problema de configuración que alguien debe ver.
    """
    sb = _sb()
    if sb is None:
        return None

    # 1 · Turno planificado (gana sobre todo)
    try:
        r = (sb.table("personal_turnos_planificados").select("*")
             .eq("empleado_id", empleado_id).eq("fecha", work_date.isoformat())
             .limit(1).execute())
        t = (r.data or [None])[0]
        if t:
            return motor.HorarioDia(
                inicio=_hora(t.get("hora_inicio")) or time(0, 0),
                fin=_hora(t.get("hora_fin")) or time(0, 0),
                cruza_medianoche=bool(t.get("cruza_medianoche")),
                descanso_inicio=_hora(t.get("descanso_inicio")),
                descanso_fin=_hora(t.get("descanso_fin")),
                minutos_esperados=int(t.get("minutos_esperados") or 0),
                es_dia_laboral=bool(t.get("es_dia_laboral", True)),
                sede_id=t.get("sede_id"),
                turno_id=t.get("id"),
            )
    except Exception as e:
        if not es_error_tabla_faltante(e):
            log.error(f"[personal.asistencia] error leyendo turno: {e}")

    # 2 · Asignación vigente + plantilla
    try:
        r = (sb.table("personal_asignacion_horario")
             .select("horario_id,valid_from,valid_to")
             .eq("empleado_id", empleado_id)
             .lte("valid_from", work_date.isoformat())
             .order("valid_from", desc=True).limit(10).execute())
        vigente = None
        for a in (r.data or []):
            hasta = a.get("valid_to")
            if hasta and date.fromisoformat(hasta[:10]) < work_date:
                continue
            vigente = a
            break
        if not vigente:
            return None

        hid = vigente["horario_id"]
        cab = (sb.table("personal_horarios").select("*")
               .eq("id", hid).limit(1).execute().data or [None])[0]
        dia = (sb.table("personal_horario_dias").select("*")
               .eq("horario_id", hid).eq("dia_semana", work_date.weekday())
               .limit(1).execute().data or [None])[0]
        if not dia:
            return None

        return motor.HorarioDia(
            inicio=_hora(dia.get("hora_inicio")) or time(0, 0),
            fin=_hora(dia.get("hora_fin")) or time(0, 0),
            cruza_medianoche=bool(dia.get("cruza_medianoche")),
            descanso_inicio=_hora(dia.get("descanso_inicio")),
            descanso_fin=_hora(dia.get("descanso_fin")),
            minutos_esperados=int(dia.get("minutos_esperados") or 0),
            es_dia_laboral=bool(dia.get("es_dia_laboral", True)),
            sede_id=(cab or {}).get("sede_id"),
            horario_id=hid,
        )
    except Exception as e:
        if not es_error_tabla_faltante(e):
            log.error(f"[personal.asistencia] error resolviendo horario: {e}")
        return None


def a_local(valor) -> datetime:
    """TIMESTAMPTZ de la base → hora de pared de Bogotá, sin zona.

    El motor trabaja en horas de pared: compara una marcación contra un horario
    escrito como "08:30". Para que esa comparación signifique algo, ambos lados
    tienen que estar en el mismo marco.

    Postgres guarda TIMESTAMPTZ en UTC y PostgREST lo devuelve como
    `2026-08-11T13:19:38+00:00`. Hacer `.replace(tzinfo=None)` ahí NO convierte:
    deja `13:19:38` como si fuera hora local, y esa persona entró a las 08:19.

    Cinco horas de corrimiento que no producen ningún error: producen tardanzas
    inventadas y recargos nocturnos donde no los hubo.
    """
    dt = parse_iso(valor) if isinstance(valor, str) else valor
    if dt.tzinfo is None:
        # Ya viene sin zona: se asume que es hora de pared local, que es lo
        # único que tiene sentido en este módulo.
        return dt
    return dt.astimezone(BOGOTA).replace(tzinfo=None)


def de_local(dt: Optional[datetime]) -> Optional[str]:
    """Hora de pared de Bogotá → ISO con offset, para guardar en TIMESTAMPTZ.

    El complemento de `a_local`. Sin el offset explícito, Postgres interpreta
    el naive según la zona de la sesión (UTC) y el horario de las 08:30 queda
    guardado como las 03:30 de Bogotá.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=BOGOTA)
    return dt.isoformat()


def _ventana(work_date: date) -> tuple[str, str]:
    """Ventana amplia para CONSULTAR; el motor decide qué cae dentro.

    Va con offset de Bogotá: sin él, Postgres lee el naive como UTC y la
    ventana queda corrida 5 horas. Con ±1 día de holgura no se perdía nada,
    pero una ventana que miente sobre lo que pide es una trampa esperando.
    """
    ini = datetime.combine(work_date - timedelta(days=1), time(0, 0), BOGOTA)
    fin = datetime.combine(work_date + timedelta(days=1), time(23, 59), BOGOTA)
    return ini.isoformat(), fin.isoformat()


def _permisos(empleado_id: str, work_date: date) -> list[motor.Permiso]:
    """Solo los permisos ya APROBADOS cuentan para el cálculo."""
    sb = _sb()
    if sb is None:
        return []
    ini, fin = _ventana(work_date)
    try:
        r = (sb.table("personal_solicitudes_permiso")
             .select("id,inicio_solicitado_at,fin_solicitado_at,minutos_solicitados,"
                     "estado,tipo_permiso_id")
             .eq("empleado_id", empleado_id)
             .in_("estado", ["aprobada", "en_compensacion", "completada"])
             .lte("inicio_solicitado_at", fin)
             .gte("fin_solicitado_at", ini).execute())
        return [motor.Permiso(
            id=p["id"],
            inicio=a_local(p["inicio_solicitado_at"]),
            fin=a_local(p["fin_solicitado_at"]),
            minutos=int(p.get("minutos_solicitados") or 0),
        ) for p in (r.data or [])]
    except Exception as e:
        if not es_error_tabla_faltante(e):
            log.error(f"[personal.asistencia] error leyendo permisos: {e}")
        return []


def _compensaciones(empleado_id: str, work_date: date) -> list[motor.Compensacion]:
    sb = _sb()
    if sb is None:
        return []
    try:
        planes = (sb.table("personal_planes_compensacion").select("id")
                  .eq("empleado_id", empleado_id).eq("estado", "activo")
                  .execute().data) or []
        if not planes:
            return []
        r = (sb.table("personal_bloques_compensacion").select("*")
             .in_("plan_id", [p["id"] for p in planes])
             .eq("fecha_programada", work_date.isoformat())
             .in_("estado", ["programado", "parcial"]).execute())
        return [motor.Compensacion(
            id=b["id"],
            inicio=a_local(b["inicio_planeado_at"]),
            fin=a_local(b["fin_planeado_at"]),
            minutos_planeados=int(b.get("minutos_planeados") or 0),
        ) for b in (r.data or [])]
    except Exception as e:
        if not es_error_tabla_faltante(e):
            log.error(f"[personal.asistencia] error leyendo compensaciones: {e}")
        return []


def _extras(empleado_id: str, work_date: date) -> list[motor.Extra]:
    """Solo las extras APROBADAS. Sin autorización previa no hay extra."""
    sb = _sb()
    if sb is None:
        return []
    try:
        r = (sb.table("personal_solicitudes_extra").select("*")
             .eq("empleado_id", empleado_id)
             .eq("fecha", work_date.isoformat())
             .in_("estado", ["aprobada", "ejecutada"]).execute())
        return [motor.Extra(
            id=x["id"],
            inicio=a_local(x["inicio_at"]),
            fin=a_local(x["fin_at"]),
            minutos_autorizados=int(x.get("minutos_solicitados") or 0),
        ) for x in (r.data or [])]
    except Exception as e:
        if not es_error_tabla_faltante(e):
            log.error(f"[personal.asistencia] error leyendo extras: {e}")
        return []


def _empleado(empleado_id: str) -> Optional[motor.Empleado]:
    from backend.services import personal_empleados as emp_svc
    e = emp_svc.obtener(empleado_id)
    if not e:
        return None
    return motor.Empleado(
        id=e["id"],
        sujeto_a_jornada=bool(e.get("sujeto_a_jornada", True)),
        rota_entre_sedes=bool(e.get("rota_entre_sedes", False)),
        controla_asistencia=bool(e.get("controla_asistencia", True)),
        sede_id=e.get("sede_id"),
        estado_laboral=e.get("estado_laboral") or "activo",
        fecha_ingreso=date.fromisoformat(e["fecha_ingreso"][:10]) if e.get("fecha_ingreso") else None,
        fecha_retiro=date.fromisoformat(e["fecha_retiro"][:10]) if e.get("fecha_retiro") else None,
    )


def _a_eventos_motor(filas: list[dict]) -> list[motor.Evento]:
    from backend.services import personal_organizacion as org
    salida = []
    for f in filas:
        try:
            ts = a_local(f["event_timestamp"])
        except Exception:
            continue
        salida.append(motor.Evento(
            id=f["id"],
            timestamp=ts,
            direccion=f.get("direccion_acceso") or "desconocida",
            dispositivo_id=f.get("dispositivo_id"),
            sede_id=_sede_de_dispositivo(f.get("dispositivo_id")),
            resultado=f.get("resultado_acceso") or "concedido",
        ))
    return salida


def _sede_de_dispositivo(dispositivo_id: Optional[str]) -> Optional[str]:
    if not dispositivo_id:
        return None
    key = f"personal:disp_sede:{dispositivo_id}"
    cacheado = cache_get(key)
    if cacheado is not None:
        return cacheado or None
    sb = _sb()
    if sb is None:
        return None
    try:
        r = (sb.table("personal_dispositivos").select("sede_id")
             .eq("id", dispositivo_id).limit(1).execute())
        sede = ((r.data or [{}])[0] or {}).get("sede_id")
    except Exception:
        sede = None
    cache_set(key, sede or "", 300)
    return sede


# ── Recálculo ────────────────────────────────────────────────────────────────

def recalcular(empleado_id: str, work_date: date, *, forzar: bool = False) -> dict:
    """Recalcula un día y lo persiste.

    Args:
        forzar: recalcula aunque la jornada esté bloqueada. Solo debería
                usarse tras reabrir un periodo, con auditoría.

    Returns:
        {ok, jornada, incidencias, motivo} — `motivo` explica por qué se
        omitió, cuando se omite.
    """
    sb = _sb()
    if sb is None:
        return {"ok": False, "motivo": "supabase_no_configurado"}

    if not forzar and _esta_bloqueada(empleado_id, work_date):
        return {"ok": False, "motivo": "jornada_bloqueada_por_cierre_de_periodo"}

    emp = _empleado(empleado_id)
    if not emp:
        return {"ok": False, "motivo": "empleado_no_existe"}

    horario = resolver_horario(empleado_id, work_date)
    eventos = _a_eventos_motor(ev_svc.eventos_del_dia(empleado_id, work_date))
    r = reglas_svc.resolver(empleado_id=empleado_id, sede_id=emp.sede_id,
                            horario_id=horario.horario_id if horario else None)

    resultado = motor.calcular_jornada(
        empleado=emp, work_date=work_date, horario=horario, eventos=eventos,
        permisos=_permisos(empleado_id, work_date),
        compensaciones=_compensaciones(empleado_id, work_date),
        extras=_extras(empleado_id, work_date),
        festivos=_festivos(), reglas=r.as_dict(),
    )

    jornada = _persistir(resultado)
    return {"ok": True, "jornada": jornada,
            "incidencias": [i.tipo for i in resultado.incidencias]}


def _esta_bloqueada(empleado_id: str, work_date: date) -> bool:
    sb = _sb()
    if sb is None:
        return False
    try:
        r = (sb.table("personal_jornadas").select("bloqueado_at")
             .eq("empleado_id", empleado_id).eq("work_date", work_date.isoformat())
             .limit(1).execute())
        return bool(((r.data or [{}])[0] or {}).get("bloqueado_at"))
    except Exception:
        return False


def _persistir(res: motor.Resultado) -> dict:
    """Guarda jornada + segmentos + incidencias. Idempotente."""
    sb = sb_requerido()
    j = res.jornada

    fila = {
        "empleado_id":                j.empleado_id,
        "work_date":                  j.work_date.isoformat(),
        "horario_id":                 j.horario_id,
        "turno_planificado_id":       j.turno_planificado_id,
        "sede_id":                    j.sede_id,
        "inicio_programado":          de_local(j.inicio_programado),
        "fin_programado":             de_local(j.fin_programado),
        "primera_entrada_at":         de_local(j.primera_entrada_at),
        "ultima_salida_at":           de_local(j.ultima_salida_at),
        "minutos_esperados":          j.minutos_esperados,
        "minutos_trabajados":         j.minutos_trabajados,
        "minutos_permiso_autorizado": j.minutos_permiso_autorizado,
        "minutos_tarde":              j.minutos_tarde,
        "minutos_salida_anticipada":  j.minutos_salida_anticipada,
        "minutos_exceso_descanso":    j.minutos_exceso_descanso,
        "minutos_compensacion_aprob": j.minutos_compensacion_aprob,
        "minutos_posible_extra":      j.minutos_posible_extra,
        "minutos_extra_aprobada":     j.minutos_extra_aprobada,
        "minutos_recargo_nocturno":   j.minutos_recargo_nocturno,
        "minutos_dominical_festivo":  j.minutos_dominical_festivo,
        "estado_asistencia":          j.estado_asistencia,
        "version_calculo":            j.version_calculo,
        "parametros_usados":          j.parametros_usados,
        "explicacion":                j.explicacion,
        "calculado_at":               _now_iso(),
        "updated_at":                 _now_iso(),
    }

    r = sb.table("personal_jornadas").upsert(
        fila, on_conflict="empleado_id,work_date").execute()
    guardada = (r.data or [fila])[0]
    jid = guardada.get("id")

    if jid:
        # Los segmentos son 100% derivados: se reescriben enteros.
        sb.table("personal_segmentos").delete().eq("jornada_id", jid).execute()
        if res.segmentos:
            sb.table("personal_segmentos").insert([{
                "jornada_id":        jid,
                "evento_entrada_id": s.evento_entrada_id,
                "evento_salida_id":  s.evento_salida_id,
                "entrada_at":        de_local(s.entrada_at),
                "salida_at":         de_local(s.salida_at),
                "minutos_trabajados": s.minutos,
                "tipo_segmento":     s.tipo,
                "estado":            s.estado,
            } for s in res.segmentos if s.entrada_at or s.salida_at]).execute()

        _sincronizar_incidencias(jid, j, res.incidencias)

    return guardada


def _sincronizar_incidencias(jornada_id: str, j: motor.Jornada,
                             incidencias: list[motor.Incidencia]) -> None:
    """Reemplaza las incidencias ABIERTAS; respeta las que alguien ya tocó.

    Recalcular no puede borrar el trabajo de una persona: si Talento Humano
    ya resolvió o está revisando una incidencia, se queda.
    """
    sb = sb_requerido()
    try:
        sb.table("personal_incidencias").delete() \
          .eq("jornada_id", jornada_id).eq("estado", "abierta").execute()
        if incidencias:
            sb.table("personal_incidencias").insert([{
                "empleado_id":     j.empleado_id,
                "jornada_id":      jornada_id,
                "work_date":       j.work_date.isoformat(),
                "tipo_incidencia": i.tipo,
                "severidad":       i.severidad,
                "descripcion":     i.descripcion,
                "estado":          "abierta",
            } for i in incidencias]).execute()
    except Exception as e:
        if not es_error_tabla_faltante(e):
            log.error(f"[personal.asistencia] error sincronizando incidencias: {e}")


def recalcular_muchos(pares: list[dict], *, forzar: bool = False) -> dict:
    """Recalcula varios (empleado_id, work_date). Para la ingesta y el cron."""
    ok, omitidos, errores = 0, [], []
    for p in pares:
        try:
            d = p["work_date"]
            d = date.fromisoformat(d) if isinstance(d, str) else d
            r = recalcular(p["empleado_id"], d, forzar=forzar)
            if r.get("ok"):
                ok += 1
            else:
                omitidos.append({**p, "motivo": r.get("motivo")})
        except Exception as e:
            errores.append({**p, "error": str(e)[:200]})
    return {"recalculadas": ok, "omitidas": omitidos, "errores": errores}


def recalcular_rango(empleado_id: str, desde: date, hasta: date, *,
                     forzar: bool = False) -> dict:
    if hasta < desde:
        raise ValueError("rango_invalido")
    if (hasta - desde).days > 400:
        raise ValueError("rango_demasiado_amplio:max_400_dias")
    pares = [{"empleado_id": empleado_id, "work_date": desde + timedelta(days=i)}
             for i in range((hasta - desde).days + 1)]
    return recalcular_muchos(pares, forzar=forzar)


# ── Lectura ──────────────────────────────────────────────────────────────────

def listar(*, desde: Optional[str] = None, hasta: Optional[str] = None,
           empleado_id: Optional[str] = None, estado: Optional[str] = None,
           empleados_permitidos: Optional[list[str]] = None,
           limit: int = 500) -> list[dict]:
    sb = _sb()
    if sb is None:
        return []
    try:
        q = sb.table("personal_jornadas").select("*")
        if empleado_id:
            q = q.eq("empleado_id", empleado_id)
        if desde:
            q = q.gte("work_date", desde)
        if hasta:
            q = q.lte("work_date", hasta)
        if estado:
            q = q.eq("estado_asistencia", estado)
        r = q.order("work_date", desc=True).limit(min(max(limit, 1), 2000)).execute()
        filas = r.data or []
    except Exception as e:
        if es_error_tabla_faltante(e):
            return []
        log.error(f"[personal.asistencia] error listando: {e}")
        return []

    # El alcance se aplica SIEMPRE al final: ningún filtro del request puede
    # ampliarlo.
    if empleados_permitidos is not None:
        permitidos = set(empleados_permitidos)
        filas = [f for f in filas if f.get("empleado_id") in permitidos]
    return filas


def obtener(empleado_id: str, work_date: date) -> Optional[dict]:
    sb = _sb()
    if sb is None:
        return None
    try:
        r = (sb.table("personal_jornadas").select("*")
             .eq("empleado_id", empleado_id).eq("work_date", work_date.isoformat())
             .limit(1).execute())
        return (r.data or [None])[0]
    except Exception:
        return None
