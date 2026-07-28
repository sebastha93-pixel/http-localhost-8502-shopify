"""
backend.services.personal_turnos — Planificación de turnos rotativos.

Por qué existe
──────────────
CC Plaza Arrayanes abre 62 h/semana y CC Florida 65. Ninguna persona puede
trabajar eso: el tope legal es 42 h (Ley 2101 de 2021, vigente desde el 15 de
julio de 2026). Las tiendas se cubren rotando gente, y este módulo es donde se
decide quién cubre qué franja.

Un turno planificado GANA sobre la plantilla de horario. Es la primera regla
de `resolver_horario()`: si hay turno para (empleado, fecha), ese manda.

Lo que NO hace
──────────────
No impide guardar una semana que exceda el tope legal. Avisa, con el número
exacto, y deja la decisión en manos de quien planifica — a veces hay una
razón (una semana de inventario, un festivo). Lo que no puede pasar es que
alguien planifique 50 horas sin enterarse.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from typing import Optional

from backend.services import personal_auditoria as aud
from backend.services.personal_base import (
    _now_iso, _sb, es_error_tabla_faltante, sb_requerido,
)

log = logging.getLogger(__name__)

# Tope legal semanal en minutos. Ley 2101 de 2021, etapa vigente desde
# 2026-07-15. Si cambia la ley, cambia aquí y en personal_reglas.
TOPE_SEMANAL_MIN = 42 * 60


def _hora(txt) -> Optional[time]:
    if not txt:
        return None
    if isinstance(txt, time):
        return txt
    p = str(txt).split(":")
    return time(int(p[0]), int(p[1]) if len(p) > 1 else 0)


def _minutos(inicio, fin, desc_ini=None, desc_fin=None,
             cruza: bool = False) -> int:
    """Minutos efectivos del turno, descontando el descanso."""
    hi, hf = _hora(inicio), _hora(fin)
    if not hi or not hf:
        return 0
    base = date(2000, 1, 1)
    a = datetime.combine(base, hi)
    b = datetime.combine(base + timedelta(days=1) if cruza else base, hf)
    if b <= a:
        b += timedelta(days=1)
    total = int((b - a).total_seconds() // 60)
    if desc_ini and desc_fin:
        d0 = datetime.combine(base, _hora(desc_ini))
        d1 = datetime.combine(base, _hora(desc_fin))
        if d1 < d0:
            d1 += timedelta(days=1)
        total -= int((d1 - d0).total_seconds() // 60)
    return max(0, total)


def lunes_de(f: date) -> date:
    """El lunes de la semana que contiene esa fecha. La semana laboral
    colombiana se cuenta de lunes a domingo."""
    return f - timedelta(days=f.weekday())


# ── Lectura ──────────────────────────────────────────────────────────────────

def listar(*, desde: date, hasta: date,
           empleado_id: Optional[str] = None,
           sede_id: Optional[str] = None) -> list[dict]:
    sb = _sb()
    if sb is None:
        return []
    try:
        q = (sb.table("personal_turnos_planificados").select("*")
             .gte("fecha", desde.isoformat()).lte("fecha", hasta.isoformat()))
        if empleado_id:
            q = q.eq("empleado_id", empleado_id)
        if sede_id:
            q = q.eq("sede_id", sede_id)
        return (q.order("fecha").execute().data) or []
    except Exception as e:
        if es_error_tabla_faltante(e):
            return []
        log.error(f"[personal.turnos] error listando: {e}")
        return []


def semana(*, lunes: date, sede_id: Optional[str] = None,
           empleados: Optional[list[str]] = None) -> dict:
    """La semana completa, con el resumen de horas por persona.

    Devuelve también `excede_tope`, que es lo que la pantalla usa para avisar
    antes de que alguien planifique 50 horas sin darse cuenta.
    """
    domingo = lunes + timedelta(days=6)
    turnos = listar(desde=lunes, hasta=domingo, sede_id=sede_id)
    if empleados is not None:
        permitidos = set(empleados)
        turnos = [t for t in turnos if t.get("empleado_id") in permitidos]

    por_empleado: dict[str, dict] = {}
    for t in turnos:
        e = por_empleado.setdefault(t["empleado_id"], {"turnos": {}, "minutos": 0})
        e["turnos"][t["fecha"][:10]] = t
        e["minutos"] += int(t.get("minutos_esperados") or 0)

    for e in por_empleado.values():
        e["horas"] = round(e["minutos"] / 60, 2)
        e["excede_tope"] = e["minutos"] > TOPE_SEMANAL_MIN
        e["minutos_sobre_tope"] = max(0, e["minutos"] - TOPE_SEMANAL_MIN)

    return {
        "lunes": lunes.isoformat(),
        "domingo": domingo.isoformat(),
        "dias": [(lunes + timedelta(days=i)).isoformat() for i in range(7)],
        "por_empleado": por_empleado,
        "tope_semanal_horas": TOPE_SEMANAL_MIN / 60,
    }


# ── Escritura ────────────────────────────────────────────────────────────────

def guardar(
    *, empleado_id: str, fecha: date, hora_inicio: Optional[str],
    hora_fin: Optional[str], sede_id: Optional[str] = None,
    descanso_inicio: Optional[str] = None, descanso_fin: Optional[str] = None,
    cruza_medianoche: bool = False, es_dia_laboral: bool = True,
    notas: Optional[str] = None, actor: str = "sistema",
) -> dict:
    """Crea o reemplaza el turno de (empleado, fecha).

    Idempotente: hay índice único en (empleado_id, fecha), así que replanificar
    el mismo día actualiza en vez de duplicar.

    Un día marcado como NO laboral es un descanso planificado explícito — muy
    distinto de "no tiene turno". El primero significa "hoy descansa"; el
    segundo, "nadie planificó este día".
    """
    if es_dia_laboral and not (hora_inicio and hora_fin):
        raise ValueError("turno_laboral_requiere_horas")

    minutos = _minutos(hora_inicio, hora_fin, descanso_inicio, descanso_fin,
                       cruza_medianoche) if es_dia_laboral else 0

    fila = {
        "empleado_id":       empleado_id,
        "fecha":             fecha.isoformat(),
        "sede_id":           sede_id,
        "es_dia_laboral":    es_dia_laboral,
        "hora_inicio":       hora_inicio if es_dia_laboral else None,
        "hora_fin":          hora_fin if es_dia_laboral else None,
        "cruza_medianoche":  cruza_medianoche,
        "descanso_inicio":   descanso_inicio if es_dia_laboral else None,
        "descanso_fin":      descanso_fin if es_dia_laboral else None,
        "minutos_esperados": minutos,
        "notas":             notas,
        "created_by":        actor,
        "updated_at":        _now_iso(),
    }

    sb = sb_requerido()
    r = sb.table("personal_turnos_planificados").upsert(
        fila, on_conflict="empleado_id,fecha").execute()
    guardado = (r.data or [fila])[0]

    aud.registrar(actor=actor, accion="planificar_turno", entidad="turno",
                  entidad_id=guardado.get("id"),
                  valores_despues={"empleado_id": empleado_id,
                                   "fecha": fecha.isoformat(),
                                   "horas": round(minutos / 60, 2)})
    _recalcular(empleado_id, fecha)
    return guardado


def guardar_semana(turnos: list[dict], *, actor: str = "sistema") -> dict:
    """Guarda varios turnos de una vez. Devuelve avisos, no bloquea.

    Los avisos de exceso son informativos a propósito: a veces hay una razón
    para una semana larga. Lo inaceptable es que nadie se entere.
    """
    guardados, errores = [], []
    afectados: set[tuple[str, date]] = set()

    for t in turnos:
        try:
            f = t["fecha"]
            f = date.fromisoformat(f) if isinstance(f, str) else f
            g = guardar(
                empleado_id=t["empleado_id"], fecha=f,
                hora_inicio=t.get("hora_inicio"), hora_fin=t.get("hora_fin"),
                sede_id=t.get("sede_id"),
                descanso_inicio=t.get("descanso_inicio"),
                descanso_fin=t.get("descanso_fin"),
                cruza_medianoche=bool(t.get("cruza_medianoche")),
                es_dia_laboral=bool(t.get("es_dia_laboral", True)),
                notas=t.get("notas"), actor=actor,
            )
            guardados.append(g)
            afectados.add((t["empleado_id"], lunes_de(f)))
        except Exception as e:
            errores.append({"empleado_id": t.get("empleado_id"),
                            "fecha": str(t.get("fecha")), "error": str(e)[:200]})

    avisos = []
    for emp_id, lun in afectados:
        s = semana(lunes=lun, empleados=[emp_id])
        datos = s["por_empleado"].get(emp_id)
        if datos and datos["excede_tope"]:
            avisos.append({
                "empleado_id": emp_id,
                "semana_del": lun.isoformat(),
                "horas": datos["horas"],
                "aviso": f"{datos['horas']} h planificadas: "
                         f"{round(datos['minutos_sobre_tope']/60, 2)} h sobre el "
                         f"tope legal de 42 h/semana",
            })

    return {"guardados": len(guardados), "errores": errores, "avisos": avisos}


def eliminar(empleado_id: str, fecha: date, *, actor: str = "sistema") -> bool:
    """Quita el turno. El día vuelve a resolverse por plantilla, o queda sin
    horario si la persona no tiene ninguna asignada."""
    sb = sb_requerido()
    r = (sb.table("personal_turnos_planificados").delete()
         .eq("empleado_id", empleado_id).eq("fecha", fecha.isoformat()).execute())
    if r.data:
        aud.registrar(actor=actor, accion="eliminar_turno", entidad="turno",
                      valores_antes={"empleado_id": empleado_id,
                                     "fecha": fecha.isoformat()})
        _recalcular(empleado_id, fecha)
        return True
    return False


def copiar_semana(*, origen: date, destino: date, sede_id: Optional[str] = None,
                  actor: str = "sistema") -> dict:
    """Copia la planificación de una semana a otra.

    En tienda los turnos se repiten con poca variación; replicar y ajustar es
    mucho más rápido que armar la grilla de cero cada lunes.
    """
    l_origen, l_destino = lunes_de(origen), lunes_de(destino)
    if l_origen == l_destino:
        raise ValueError("semana_origen_y_destino_son_la_misma")

    previos = listar(desde=l_origen, hasta=l_origen + timedelta(days=6),
                     sede_id=sede_id)
    if not previos:
        raise ValueError("la_semana_origen_no_tiene_turnos")

    desfase = (l_destino - l_origen).days
    nuevos = [{
        "empleado_id":      t["empleado_id"],
        "fecha":            (date.fromisoformat(t["fecha"][:10])
                             + timedelta(days=desfase)).isoformat(),
        "sede_id":          t.get("sede_id"),
        "hora_inicio":      t.get("hora_inicio"),
        "hora_fin":         t.get("hora_fin"),
        "descanso_inicio":  t.get("descanso_inicio"),
        "descanso_fin":     t.get("descanso_fin"),
        "cruza_medianoche": t.get("cruza_medianoche"),
        "es_dia_laboral":   t.get("es_dia_laboral", True),
        "notas":            t.get("notas"),
    } for t in previos]

    return guardar_semana(nuevos, actor=actor)


def _recalcular(empleado_id: str, fecha: date) -> None:
    """Cambiar un turno cambia lo esperado ese día: hay que recalcular.

    Best-effort: si el recálculo falla, el turno igual quedó guardado y el
    cron nocturno lo recoge.
    """
    try:
        from backend.services import personal_asistencia as asis
        asis.recalcular(empleado_id, fecha)
    except Exception as e:
        log.warning(f"[personal.turnos] recálculo tras planificar: {e}")


# ── Referencia: horas de apertura del local ──────────────────────────────────

def apertura_de_sede(sede_id: str) -> list[dict]:
    """Las horas en que abre la tienda, para mostrarlas junto a la grilla.

    No es jornada de nadie: es el rango que hay que cubrir entre todos.
    """
    sb = _sb()
    if sb is None:
        return []
    try:
        h = (sb.table("personal_horarios").select("id,nombre")
             .eq("sede_id", sede_id).eq("tipo", "rotativo")
             .limit(1).execute().data or [None])[0]
        if not h:
            return []
        return (sb.table("personal_horario_dias").select("*")
                .eq("horario_id", h["id"]).order("dia_semana").execute().data) or []
    except Exception:
        return []
