"""
backend.services.personal_empleados — Empleados, jerarquía y alcance de datos.

Relación con `usuarios`
───────────────────────
Son tablas distintas a propósito:

    usuarios            = credenciales de acceso al sistema (login)
    personal_empleados  = personas de la empresa

Un operario de corte marca en el Dahua y aparece en los reportes sin necesitar
login. Un usuario técnico puede existir sin ser empleado. El puente es
`usuario_id`, NULLABLE, con ON DELETE SET NULL: borrar un usuario nunca borra
el histórico de asistencia de esa persona.

Alcance de datos
────────────────
`personal_permisos:ver` no significa "ver los permisos de todos". Un jefe ve
su equipo; Talento Humano ve todo. Eso se resuelve con `alcance_empleados()`,
siguiendo el patrón de `_es_solo_cortador()` del módulo Producción.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from backend.services import personal_auditoria as aud
from backend.services.personal_base import (
    _now_iso, _sb, cache_get, cache_invalidar, cache_set,
    enmascarar_documento, es_error_tabla_faltante, sb_requerido,
)

log = logging.getLogger(__name__)


TIPOS_DOCUMENTO = ("CC", "CE", "PA", "PEP", "PPT", "TI", "NIT")
TIPOS_CONTRATO = ("termino_indefinido", "termino_fijo", "obra_labor",
                  "aprendizaje", "prestacion_servicios")
ESTADOS_LABORALES = ("activo", "incapacidad", "vacaciones", "licencia",
                     "suspendido", "retirado")

# Estados en los que la persona sigue vinculada y se le calcula asistencia.
ESTADOS_VIGENTES = ("activo", "incapacidad", "vacaciones", "licencia")

_CACHE_PREFIJO = "personal:empleados:"
_CACHE_TTL = 30

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_COLS = ("id,codigo_empleado,usuario_id,tipo_documento,numero_documento,"
         "nombre_completo,email,telefono,area_id,sede_id,cargo,supervisor_id,"
         "tipo_contrato,estado_laboral,fecha_ingreso,fecha_retiro,"
         "sujeto_a_jornada,consentimiento_datos_at,created_at,updated_at")

# Campos que un PATCH puede tocar. Todo lo demás se ignora en silencio —
# whitelist explícita, igual que actualizar_ruta_lote en produccion.py.
_CAMPOS_EDITABLES = frozenset({
    "nombre_completo", "email", "telefono", "area_id", "sede_id", "cargo",
    "supervisor_id", "tipo_contrato", "estado_laboral", "fecha_retiro",
    "sujeto_a_jornada", "consentimiento_datos_at", "consentimiento_documento",
    "tipo_documento", "numero_documento", "usuario_id",
})


# ── Lectura ──────────────────────────────────────────────────────────────────

def listar(
    *, area_id: Optional[str] = None, sede_id: Optional[str] = None,
    estado_laboral: Optional[str] = None, supervisor_id: Optional[str] = None,
    solo_vigentes: bool = False, q: Optional[str] = None, limit: int = 200,
) -> list[dict]:
    """Empleados con filtros. Degrada a [] si la migración no se aplicó."""
    sb = _sb()
    if sb is None:
        return []
    try:
        query = sb.table("personal_empleados").select(_COLS)
        if area_id:
            query = query.eq("area_id", area_id)
        if sede_id:
            query = query.eq("sede_id", sede_id)
        if estado_laboral:
            query = query.eq("estado_laboral", estado_laboral)
        if supervisor_id:
            query = query.eq("supervisor_id", supervisor_id)
        if solo_vigentes:
            query = query.in_("estado_laboral", list(ESTADOS_VIGENTES))
        r = query.order("nombre_completo").limit(min(max(limit, 1), 500)).execute()
        filas = r.data or []
    except Exception as e:
        if es_error_tabla_faltante(e):
            return []
        log.error(f"[personal.empleados] error listando: {e}")
        return []

    if q:
        term = q.strip().lower()
        filas = [
            f for f in filas
            if term in (f.get("nombre_completo") or "").lower()
            or term in (f.get("codigo_empleado") or "").lower()
            or term in (f.get("numero_documento") or "")
        ]
    return filas


def obtener(empleado_id: str) -> Optional[dict]:
    sb = _sb()
    if sb is None:
        return None
    try:
        r = (sb.table("personal_empleados").select(_COLS)
             .eq("id", empleado_id).limit(1).execute())
        return (r.data or [None])[0]
    except Exception as e:
        if es_error_tabla_faltante(e):
            return None
        log.error(f"[personal.empleados] error obteniendo {empleado_id}: {e}")
        return None


def obtener_por_usuario(usuario_id: str) -> Optional[dict]:
    """El empleado enlazado a un login. Corazón del autoservicio.

    Cacheado 30 s: se consulta en cada request de /mi-tiempo.
    """
    if not usuario_id:
        return None
    key = f"{_CACHE_PREFIJO}por_usuario:{usuario_id}"
    cacheado = cache_get(key)
    if cacheado is not None:
        return cacheado or None      # se cachea {} para "no existe"

    sb = _sb()
    if sb is None:
        return None
    try:
        r = (sb.table("personal_empleados").select(_COLS)
             .eq("usuario_id", usuario_id).limit(1).execute())
        fila = (r.data or [None])[0]
    except Exception as e:
        if es_error_tabla_faltante(e):
            return None
        log.error(f"[personal.empleados] error por usuario {usuario_id}: {e}")
        return None
    cache_set(key, fila or {}, _CACHE_TTL)
    return fila


def obtener_por_codigo(codigo: str) -> Optional[dict]:
    sb = _sb()
    if sb is None:
        return None
    try:
        r = (sb.table("personal_empleados").select(_COLS)
             .eq("codigo_empleado", codigo).limit(1).execute())
        return (r.data or [None])[0]
    except Exception:
        return None


# ── Jerarquía y alcance ──────────────────────────────────────────────────────

def equipo_de(supervisor_id: str, *, incluir_indirectos: bool = True) -> list[str]:
    """IDs de los empleados a cargo de un supervisor.

    Con incluir_indirectos, baja por todo el árbol (el equipo del equipo).
    Con ~25 empleados el árbol es diminuto; se recorre en memoria.

    Protegido contra ciclos: si alguien quedara como supervisor de su propio
    jefe, el `vistos` corta el recorrido en vez de colgar el proceso.
    """
    if not supervisor_id:
        return []
    todos = listar(limit=500)
    hijos_por_jefe: dict[str, list[str]] = {}
    for e in todos:
        jefe = e.get("supervisor_id")
        if jefe:
            hijos_por_jefe.setdefault(jefe, []).append(e["id"])

    directos = hijos_por_jefe.get(supervisor_id, [])
    if not incluir_indirectos:
        return directos

    resultado: list[str] = []
    vistos = {supervisor_id}
    pila = list(directos)
    while pila:
        actual = pila.pop()
        if actual in vistos:
            continue
        vistos.add(actual)
        resultado.append(actual)
        pila.extend(hijos_por_jefe.get(actual, []))
    return resultado


def alcance_empleados(user) -> Optional[list[str]]:
    """Qué empleados puede ver este usuario.

    Returns:
        None  → todos (admin, Talento Humano, gerencia con vista global)
        list  → solo esos IDs (un jefe: su equipo + él mismo)
        []    → ninguno (usuario sin vínculo ni permisos)

    None y [] significan cosas opuestas, así que los callers deben distinguir
    `if alcance is None` de `if not alcance`.
    """
    from backend.core.security import tiene_permiso

    if getattr(user, "rol", None) == "admin":
        return None
    # Vista global: quien administra asistencia o ve el módulo completo.
    if tiene_permiso(user, "personal", "ver") or \
       tiene_permiso(user, "personal_asistencia", "modificar"):
        return None

    propio = obtener_por_usuario(getattr(user, "id", "") or "")
    if not propio:
        return []

    ids = [propio["id"]]
    if tiene_permiso(user, "personal_permisos", "ver"):
        ids.extend(equipo_de(propio["id"]))
    return list(dict.fromkeys(ids))


def puede_ver_empleado(user, empleado_id: str) -> bool:
    """Chequeo puntual de acceso a un empleado concreto."""
    alcance = alcance_empleados(user)
    return alcance is None or empleado_id in alcance


# ── Escritura ────────────────────────────────────────────────────────────────

def _validar(datos: dict, *, creando: bool) -> None:
    if creando:
        for campo in ("nombre_completo", "numero_documento", "fecha_ingreso"):
            if not (datos.get(campo) or "").strip():
                raise ValueError(f"campo_requerido:{campo}")

    td = datos.get("tipo_documento")
    if td and td not in TIPOS_DOCUMENTO:
        raise ValueError(f"tipo_documento_invalido:{td}")

    tc = datos.get("tipo_contrato")
    if tc and tc not in TIPOS_CONTRATO:
        raise ValueError(f"tipo_contrato_invalido:{tc}")

    el = datos.get("estado_laboral")
    if el and el not in ESTADOS_LABORALES:
        raise ValueError(f"estado_laboral_invalido:{el}")

    email = (datos.get("email") or "").strip()
    if email and not _EMAIL_RE.match(email):
        raise ValueError("email_invalido")

    # Retirado exige fecha de retiro: sin ella no se sabe hasta cuándo
    # calcularle asistencia.
    if el == "retirado" and not datos.get("fecha_retiro"):
        raise ValueError("fecha_retiro_requerida_al_retirar")


def _siguiente_codigo() -> str:
    """Consecutivo simple EMP-0001.

    No usa la RPC atómica de producción a propósito: los empleados se crean de
    a uno, a mano, por Talento Humano. No hay concurrencia real. Si algún día
    se importan en lote, migrar a next_consecutivo().
    """
    existentes = listar(limit=500)
    maximo = 0
    for e in existentes:
        cod = e.get("codigo_empleado") or ""
        if cod.startswith("EMP-"):
            try:
                maximo = max(maximo, int(cod.split("-")[1]))
            except (ValueError, IndexError):
                continue
    return f"EMP-{maximo + 1:04d}"


def crear(*, actor: str = "sistema", **datos) -> dict:
    """Crea un empleado. `codigo_empleado` se autogenera si no se pasa."""
    _validar(datos, creando=True)

    if datos.get("supervisor_id") and not obtener(datos["supervisor_id"]):
        raise ValueError("supervisor_no_existe")

    fila = {k: v for k, v in datos.items() if k in _CAMPOS_EDITABLES}
    fila["codigo_empleado"] = datos.get("codigo_empleado") or _siguiente_codigo()
    fila.setdefault("tipo_documento", "CC")
    fila.setdefault("tipo_contrato", "termino_indefinido")
    fila.setdefault("estado_laboral", "activo")
    fila.setdefault("sujeto_a_jornada", True)
    fila["fecha_ingreso"] = datos["fecha_ingreso"]
    fila["updated_at"] = _now_iso()

    sb = sb_requerido()
    try:
        r = sb.table("personal_empleados").insert(fila).execute()
    except Exception as e:
        msg = str(e).lower()
        if "duplicate" in msg or "unique" in msg:
            if "documento" in msg:
                raise ValueError("documento_ya_registrado")
            if "codigo" in msg:
                raise ValueError("codigo_ya_registrado")
            if "usuario_id" in msg:
                raise ValueError("usuario_ya_vinculado_a_otro_empleado")
            raise ValueError("empleado_duplicado")
        raise

    creado = (r.data or [fila])[0]
    cache_invalidar(_CACHE_PREFIJO)
    aud.registrar(
        actor=actor, accion="crear_empleado", entidad="empleado",
        entidad_id=creado.get("id"),
        valores_despues={"codigo_empleado": creado.get("codigo_empleado"),
                         "nombre_completo": creado.get("nombre_completo")},
    )
    return creado


def actualizar(empleado_id: str, *, actor: str = "sistema", **campos) -> dict:
    """Actualiza campos permitidos. Audita solo el delta."""
    antes = obtener(empleado_id)
    if not antes:
        raise ValueError("empleado_no_existe")

    _validar(campos, creando=False)

    if campos.get("supervisor_id"):
        nuevo_jefe = campos["supervisor_id"]
        if nuevo_jefe == empleado_id:
            raise ValueError("empleado_no_puede_ser_su_propio_jefe")
        # Un ciclo en la jerarquía rompería equipo_de() y los reportes.
        if nuevo_jefe in equipo_de(empleado_id):
            raise ValueError("ciclo_en_jerarquia")
        if not obtener(nuevo_jefe):
            raise ValueError("supervisor_no_existe")

    update = {k: v for k, v in campos.items() if k in _CAMPOS_EDITABLES}
    if not update:
        raise ValueError("nada_que_actualizar")
    update["updated_at"] = _now_iso()

    sb = sb_requerido()
    r = sb.table("personal_empleados").update(update).eq("id", empleado_id).execute()
    if not r.data:
        raise ValueError("empleado_no_existe")

    despues = r.data[0]
    cache_invalidar(_CACHE_PREFIJO)
    aud.registrar_cambio(
        actor=actor, accion="actualizar_empleado", entidad="empleado",
        entidad_id=empleado_id, antes=antes, despues=despues,
    )
    return despues


def vincular_usuario(empleado_id: str, usuario_id: Optional[str], *,
                     actor: str = "sistema") -> dict:
    """Enlaza (o desenlaza con None) un empleado con su login.

    Es lo que habilita el autoservicio para esa persona.
    """
    if usuario_id:
        ya = obtener_por_usuario(usuario_id)
        if ya and ya["id"] != empleado_id:
            raise ValueError("usuario_ya_vinculado_a_otro_empleado")
    return actualizar(empleado_id, actor=actor, usuario_id=usuario_id)


def para_listado_publico(empleado: dict) -> dict:
    """Versión reducida para vistas donde no hace falta el documento completo."""
    if not empleado:
        return {}
    salida = dict(empleado)
    salida["numero_documento"] = enmascarar_documento(empleado.get("numero_documento"))
    return salida
