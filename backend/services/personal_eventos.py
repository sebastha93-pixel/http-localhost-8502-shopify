"""
backend.services.personal_eventos — Ingesta de eventos del control de acceso.

Responsabilidades
─────────────────
  1. Calcular la clave de idempotencia
  2. Insertar sin duplicar (los índices únicos de la tabla absorben el reenvío)
  3. Resolver el empleado vía personal_mapeo_externo
  4. Levantar incidencia si no se puede mapear — SIN descartar el evento
  5. Marcar las fechas afectadas para recálculo

INVARIANTE 1: esta capa solo INSERTA en personal_eventos_crudos. Nunca
actualiza un timestamp, una dirección ni un payload. Los únicos campos
mutables son los de procesamiento (`estado_proceso`, `procesado_at`,
`error_mensaje`), que son metadatos, no el hecho.

Un evento nunca se descarta
───────────────────────────
Si no mapea a un empleado, se guarda con `empleado_id = NULL` y se levanta
incidencia. Cuando alguien cree el mapeo, se reprocesa y el evento se
recupera. Descartarlo perdería una marcación real de una persona real.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime, timedelta
from typing import Any, Optional

from backend.core.timeutils import parse_iso
from backend.services.personal_base import (
    _now_iso, _sb, es_error_tabla_faltante, sb_requerido,
)

log = logging.getLogger(__name__)


DIRECCIONES = ("entrada", "salida", "desconocida")
RESULTADOS = ("concedido", "denegado", "desconocido")
ORIGENES = ("conector", "csv", "manual", "mock")

# Campos que definen la identidad del hecho. El hash se calcula solo sobre
# estos: si el conector reenvía el mismo evento con metadatos distintos
# (por ejemplo otro `received_at`), sigue siendo el mismo hecho.
_CAMPOS_HASH = ("id_externo_empleado", "event_timestamp", "direccion_acceso",
                "tipo_evento", "nombre_puerta", "resultado_acceso")


def calcular_hash(payload: dict) -> str:
    """Hash canónico del hecho. Determinista entre procesos y reinicios.

    `sort_keys` es lo que lo hace estable: dos dicts con el mismo contenido en
    distinto orden producen el mismo hash.
    """
    base = {k: payload.get(k) for k in _CAMPOS_HASH}
    crudo = json.dumps(base, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(crudo.encode("utf-8")).hexdigest()


def _normalizar(e: dict) -> dict:
    """Lleva un evento crudo del conector a la forma de la tabla."""
    ts = e.get("event_timestamp") or e.get("timestamp")
    if isinstance(ts, str):
        try:
            # parse_iso tolera la fracción recortada de Postgres, pero lanza
            # su propio mensaje. Se envuelve para que TODO fallo de timestamp
            # salga como el mismo código snake_case, igual que el resto del
            # API: el detalle original se conserva después de los dos puntos.
            ts = parse_iso(ts)
        except (ValueError, TypeError) as ex:
            raise ValueError(f"event_timestamp_invalido:{str(ex)[:120]}") from ex
    if not isinstance(ts, datetime):
        raise ValueError("event_timestamp_invalido:ausente_o_tipo_incorrecto")

    direccion = (e.get("direccion_acceso") or e.get("direction") or "desconocida").lower()
    if direccion in ("in", "entry", "ingreso"):
        direccion = "entrada"
    elif direccion in ("out", "exit", "egreso"):
        direccion = "salida"
    if direccion not in DIRECCIONES:
        direccion = "desconocida"

    resultado = (e.get("resultado_acceso") or e.get("result") or "concedido").lower()
    if resultado in ("granted", "success", "ok"):
        resultado = "concedido"
    elif resultado in ("denied", "fail", "failed"):
        resultado = "denegado"
    if resultado not in RESULTADOS:
        resultado = "desconocido"

    fila = {
        "id_evento_externo":    e.get("id_evento_externo") or e.get("external_event_id"),
        "id_externo_empleado":  str(e.get("id_externo_empleado")
                                    or e.get("employee_external_id") or "").strip() or None,
        "event_timestamp":      ts.isoformat(),
        "tipo_evento":          e.get("tipo_evento") or "acceso",
        "direccion_acceso":     direccion,
        "resultado_acceso":     resultado,
        "metodo_autenticacion": e.get("metodo_autenticacion") or e.get("auth_method"),
        "nombre_puerta":        e.get("nombre_puerta") or e.get("door_name"),
        "referencia_snapshot":  e.get("referencia_snapshot"),
        "raw_payload_json":     e.get("raw_payload_json") or e,
    }
    fila["payload_hash"] = calcular_hash(fila)
    return fila


# ── Mapeo empleado ───────────────────────────────────────────────────────────

def _mapa_externo(dispositivo_id: str) -> dict[str, str]:
    """id externo → empleado_id, para un dispositivo."""
    sb = _sb()
    if sb is None:
        return {}
    try:
        r = (sb.table("personal_mapeo_externo")
             .select("id_externo_empleado,empleado_id")
             .eq("dispositivo_id", dispositivo_id).eq("activo", True).execute())
        return {m["id_externo_empleado"]: m["empleado_id"] for m in (r.data or [])}
    except Exception as e:
        if not es_error_tabla_faltante(e):
            log.error(f"[personal.eventos] error leyendo mapeo: {e}")
        return {}


# ── Ingesta ──────────────────────────────────────────────────────────────────

def ingerir(
    *, dispositivo_id: str, eventos: list[dict], origen: str = "conector",
    registrado_por: Optional[str] = None, motivo_manual: Optional[str] = None,
) -> dict:
    """Ingiere un lote de eventos. Idempotente.

    Returns:
        {recibidos, nuevos, duplicados, sin_mapeo, fechas_afectadas, errores}

    `duplicados` no es un error: es la prueba de que la idempotencia funciona.
    Un conector que reintenta tras un timeout debe poder reenviar el mismo
    lote sin consecuencias.
    """
    if origen not in ORIGENES:
        raise ValueError(f"origen_invalido:{origen}")
    if origen == "manual" and not (registrado_por and motivo_manual):
        # Una marcación manual sin actor ni motivo es un agujero de auditoría.
        raise ValueError("marcacion_manual_requiere_actor_y_motivo")

    sb = sb_requerido()
    mapa = _mapa_externo(dispositivo_id)

    filas, errores = [], []
    for i, e in enumerate(eventos):
        try:
            f = _normalizar(e)
        except Exception as ex:
            errores.append({"indice": i, "error": str(ex)[:200]})
            continue
        f["dispositivo_id"] = dispositivo_id
        f["empleado_id"] = mapa.get(f["id_externo_empleado"] or "")
        f["origen"] = origen
        f["registrado_por"] = registrado_por
        f["motivo_manual"] = motivo_manual
        f["received_at"] = _now_iso()
        f["estado_proceso"] = "pendiente"
        filas.append(f)

    if not filas:
        return {"recibidos": len(eventos), "nuevos": 0, "duplicados": 0,
                "sin_mapeo": 0, "fechas_afectadas": [], "errores": errores}

    # INSERT plano, sin ON CONFLICT.
    #
    # Los índices de idempotencia son PARCIALES (uno aplica cuando hay
    # id_evento_externo, el otro cuando no). Postgres no puede inferir un
    # índice parcial en ON CONFLICT sin repetir su WHERE, y PostgREST no
    # expone esa sintaxis: el upsert fallaba con 42P10 en CADA lote y caía
    # al reintento individual. Funcionaba, pero desperdiciaba una ida y
    # vuelta por lote y llenaba el log de falsas alarmas.
    #
    # Con INSERT plano el camino feliz es una sola llamada, y el duplicado
    # lo detecta el índice único igual —solo que como excepción, que es
    # justo lo que maneja el fallback de abajo.
    insertadas = []
    try:
        r = sb.table("personal_eventos_crudos").insert(filas).execute()
        insertadas = r.data or []
    except Exception as ex:
        # Un solo duplicado tumba el lote entero, así que se reintenta fila
        # por fila para no perder los buenos. Es el caso esperado cuando el
        # conector reenvía tras un timeout.
        if not _es_duplicado(ex):
            log.warning(f"[personal.eventos] lote falló, reintento individual: {ex}")
        for f in filas:
            try:
                r = sb.table("personal_eventos_crudos").insert(f).execute()
                insertadas.extend(r.data or [])
            except Exception as ex2:
                if _es_duplicado(ex2):
                    continue
                errores.append({"hash": f["payload_hash"][:12], "error": str(ex2)[:200]})

    sin_mapeo = [f for f in filas if not f.get("empleado_id")]
    if sin_mapeo:
        _incidencias_desconocido(dispositivo_id, sin_mapeo)

    fechas = _fechas_afectadas(insertadas or filas)
    return {
        "recibidos": len(eventos),
        "nuevos": len(insertadas),
        "duplicados": len(filas) - len(insertadas),
        "sin_mapeo": len(sin_mapeo),
        "fechas_afectadas": fechas,
        "errores": errores,
    }


def _es_duplicado(e: Exception) -> bool:
    m = str(e).lower()
    return "duplicate" in m or "unique" in m or "23505" in m


def _fechas_afectadas(filas) -> list[dict]:
    """Pares (empleado_id, work_date) que hay que recalcular.

    Se marca el día del evento Y EL ANTERIOR: una marcación a las 06:00 puede
    pertenecer a un turno nocturno que empezó el día previo. Recalcular de más
    es barato (el motor es idempotente); recalcular de menos deja datos viejos.
    """
    pares = set()
    for f in filas:
        emp = f.get("empleado_id")
        if not emp:
            continue
        ts = f.get("event_timestamp")
        d = parse_iso(ts).date() if isinstance(ts, str) else ts.date()
        pares.add((emp, d.isoformat()))
        pares.add((emp, (d - timedelta(days=1)).isoformat()))
    return [{"empleado_id": e, "work_date": d} for e, d in sorted(pares)]


def _incidencias_desconocido(dispositivo_id: str, filas: list[dict]) -> None:
    """Una incidencia por id externo sin mapear, no una por evento.

    Un dispositivo mal configurado puede generar cientos de eventos del mismo
    desconocido; inundar la bandeja los volvería invisibles.
    """
    sb = _sb()
    if sb is None:
        return
    por_id: dict[str, int] = {}
    for f in filas:
        por_id[f.get("id_externo_empleado") or "(vacío)"] = \
            por_id.get(f.get("id_externo_empleado") or "(vacío)", 0) + 1
    try:
        existentes = (sb.table("personal_incidencias")
                      .select("descripcion")
                      .eq("tipo_incidencia", "empleado_desconocido")
                      .eq("dispositivo_id", dispositivo_id)
                      .in_("estado", ["abierta", "en_revision"]).execute().data) or []
        ya = {i.get("descripcion", "") for i in existentes}
        nuevas = []
        for ext, n in por_id.items():
            desc = f"Identificador «{ext}» no está mapeado a ningún empleado."
            if any(desc in d for d in ya):
                continue
            nuevas.append({
                "dispositivo_id": dispositivo_id,
                "tipo_incidencia": "empleado_desconocido",
                "severidad": "alta",
                "descripcion": f"{desc} {n} evento(s) sin asignar.",
                "estado": "abierta",
            })
        if nuevas:
            sb.table("personal_incidencias").insert(nuevas).execute()
    except Exception as e:
        if not es_error_tabla_faltante(e):
            log.error(f"[personal.eventos] no se pudo registrar desconocido: {e}")


# ── Lectura y reproceso ──────────────────────────────────────────────────────

def listar(
    *, dispositivo_id: Optional[str] = None, empleado_id: Optional[str] = None,
    estado: Optional[str] = None, desde: Optional[str] = None,
    hasta: Optional[str] = None, limit: int = 200,
) -> list[dict]:
    sb = _sb()
    if sb is None:
        return []
    try:
        q = sb.table("personal_eventos_crudos").select("*")
        if dispositivo_id:
            q = q.eq("dispositivo_id", dispositivo_id)
        if empleado_id:
            q = q.eq("empleado_id", empleado_id)
        if estado:
            q = q.eq("estado_proceso", estado)
        if desde:
            q = q.gte("event_timestamp", desde)
        if hasta:
            q = q.lte("event_timestamp", hasta)
        r = q.order("event_timestamp", desc=True).limit(min(max(limit, 1), 1000)).execute()
        return r.data or []
    except Exception as e:
        if es_error_tabla_faltante(e):
            return []
        log.error(f"[personal.eventos] error listando: {e}")
        return []


def eventos_del_dia(empleado_id: str, work_date: date) -> list[dict]:
    """Eventos que pueden pertenecer a esa jornada.

    La ventana va del día anterior a las 00:00 hasta el día siguiente a las
    12:00, para cubrir turnos que cruzan medianoche por cualquiera de los dos
    extremos. El motor decide cuáles caen realmente dentro de la jornada.
    """
    sb = _sb()
    if sb is None:
        return []
    ini = datetime.combine(work_date - timedelta(days=1), datetime.min.time())
    fin = datetime.combine(work_date + timedelta(days=1), datetime.min.time()) \
        + timedelta(hours=12)
    try:
        r = (sb.table("personal_eventos_crudos").select("*")
             .eq("empleado_id", empleado_id)
             .gte("event_timestamp", ini.isoformat())
             .lte("event_timestamp", fin.isoformat())
             .order("event_timestamp").execute())
        return r.data or []
    except Exception as e:
        if es_error_tabla_faltante(e):
            return []
        log.error(f"[personal.eventos] error del día: {e}")
        return []


def remapear_desconocidos(dispositivo_id: str) -> dict:
    """Asigna empleado a los eventos que quedaron sin mapear.

    Se corre después de crear un mapeo: recupera el histórico que había
    llegado como «desconocido». Esta es la razón por la que un evento sin
    mapeo NUNCA se descarta.
    """
    sb = sb_requerido()
    mapa = _mapa_externo(dispositivo_id)
    if not mapa:
        return {"remapeados": 0, "fechas_afectadas": []}

    huerfanos = (sb.table("personal_eventos_crudos")
                 .select("id,id_externo_empleado,event_timestamp")
                 .eq("dispositivo_id", dispositivo_id)
                 .is_("empleado_id", "null").limit(5000).execute().data) or []

    actualizados = []
    for e in huerfanos:
        emp = mapa.get(e.get("id_externo_empleado") or "")
        if not emp:
            continue
        # Solo se toca empleado_id y el estado de proceso. El hecho no cambia.
        sb.table("personal_eventos_crudos").update(
            {"empleado_id": emp, "estado_proceso": "pendiente"}
        ).eq("id", e["id"]).execute()
        actualizados.append({**e, "empleado_id": emp})

    return {"remapeados": len(actualizados),
            "fechas_afectadas": _fechas_afectadas(actualizados)}


def marcar_procesados(ids: list[str], *, error: Optional[str] = None) -> int:
    """Marca eventos como procesados. Solo toca metadatos, nunca el hecho."""
    if not ids:
        return 0
    sb = sb_requerido()
    update: dict[str, Any] = {
        "estado_proceso": "error" if error else "procesado",
        "procesado_at": _now_iso(),
    }
    if error:
        update["error_mensaje"] = error[:500]
    r = sb.table("personal_eventos_crudos").update(update).in_("id", ids).execute()
    return len(r.data or [])
