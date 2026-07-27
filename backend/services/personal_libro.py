"""
backend.services.personal_libro — Libro mayor de tiempo. APPEND-ONLY.

INVARIANTE 3
────────────
Nunca se hace UPDATE de `minutos` ni de `direccion`. El saldo de un empleado
ES la suma de sus asientos vigentes, jamás una columna almacenada.

Corregir un asiento equivocado = asiento de `reversion` que apunta al
original + asiento nuevo con el valor correcto. La historia de las
correcciones queda visible.

Por qué importa
───────────────
Un saldo editable es un saldo negociable. Con libro mayor, cada minuto tiene
origen, aprobador y fecha; y si alguien se equivocó, se ve que se equivocó y
quién lo corrigió. Es la diferencia entre un sistema que sirve de prueba y uno
que sirve de opinión.

Este módulo NO expone ninguna función que actualice un asiento. Es deliberado:
si no existe el método, nadie lo llama por descuido.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from backend.services import personal_auditoria as aud
from backend.services.personal_base import (
    _now_iso, _sb, es_error_tabla_faltante, sb_requerido,
)

log = logging.getLogger(__name__)


TIPOS_ASIENTO = ("permiso_debito", "compensacion_credito", "ajuste_manual",
                 "conversion_nomina", "cancelacion", "reversion")

DIRECCIONES = ("debito", "credito")

TIPOS_ORIGEN = ("solicitud_permiso", "plan_compensacion", "bloque_compensacion",
                "jornada", "novedad_nomina", "manual")

# Qué dirección corresponde a cada tipo. Que el caller no pueda equivocarse:
# un permiso SIEMPRE debita, una compensación SIEMPRE acredita.
_DIRECCION_POR_TIPO = {
    "permiso_debito":       "debito",
    "compensacion_credito": "credito",
    "conversion_nomina":    "credito",   # el descuento salda la deuda de tiempo
    "cancelacion":          "credito",
}


def _direccion_de(tipo: str, explicita: Optional[str]) -> str:
    fija = _DIRECCION_POR_TIPO.get(tipo)
    if fija:
        if explicita and explicita != fija:
            raise ValueError(f"direccion_incompatible:{tipo}_siempre_es_{fija}")
        return fija
    # ajuste_manual y reversion pueden ir en cualquier dirección
    if explicita not in DIRECCIONES:
        raise ValueError(f"direccion_requerida_para:{tipo}")
    return explicita


def registrar(
    *, empleado_id: str, tipo_asiento: str, minutos: int, tipo_origen: str,
    descripcion: str, origen_id: Optional[str] = None,
    direccion: Optional[str] = None, fecha_efectiva: Optional[date] = None,
    aprobado_por: Optional[str] = None, creado_por_sistema: bool = True,
    actor: str = "sistema", reversa_a_id: Optional[str] = None,
) -> dict:
    """Escribe un asiento. Es la ÚNICA forma de mover el saldo.

    Raises:
        ValueError: con código snake_case si algo no cuadra.
    """
    if tipo_asiento not in TIPOS_ASIENTO:
        raise ValueError(f"tipo_asiento_invalido:{tipo_asiento}")
    if tipo_origen not in TIPOS_ORIGEN:
        raise ValueError(f"tipo_origen_invalido:{tipo_origen}")
    if not isinstance(minutos, int) or minutos <= 0:
        # Un asiento de 0 minutos no dice nada, y uno negativo es una
        # dirección disfrazada. La dirección se declara, no se codifica en
        # el signo.
        raise ValueError("minutos_debe_ser_entero_positivo")
    if not (descripcion or "").strip():
        raise ValueError("descripcion_requerida")

    # Un ajuste manual SIEMPRE necesita un aprobador humano identificado.
    # La base de datos también lo exige con un CHECK.
    if tipo_asiento == "ajuste_manual" and not (aprobado_por or "").strip():
        raise ValueError("ajuste_manual_requiere_aprobador")
    if tipo_asiento == "reversion" and not reversa_a_id:
        raise ValueError("reversion_requiere_asiento_origen")

    fila = {
        "empleado_id":        empleado_id,
        "tipo_asiento":       tipo_asiento,
        "direccion":          _direccion_de(tipo_asiento, direccion),
        "minutos":            minutos,
        "tipo_origen":        tipo_origen,
        "origen_id":          origen_id,
        "reversa_a_id":       reversa_a_id,
        "fecha_efectiva":     (fecha_efectiva or date.today()).isoformat(),
        "estado":             "vigente",
        "descripcion":        descripcion.strip()[:500],
        "creado_por_sistema": creado_por_sistema,
        "aprobado_por":       aprobado_por,
    }

    sb = sb_requerido()
    r = sb.table("personal_libro_tiempo").insert(fila).execute()
    creado = (r.data or [fila])[0]

    aud.registrar(
        actor=actor, accion=f"libro_{tipo_asiento}", entidad="libro_tiempo",
        entidad_id=creado.get("id"),
        valores_despues={"minutos": minutos, "direccion": fila["direccion"],
                         "empleado_id": empleado_id},
        motivo=descripcion,
    )
    return creado


def reversar(asiento_id: str, *, motivo: str, actor: str) -> dict:
    """Anula un asiento creando su reversión. NO lo edita ni lo borra.

    El original queda marcado como `reversado` —eso sí es metadato, no valor—
    y nace un asiento espejo en la dirección contraria. El saldo vuelve a
    donde estaba y la historia queda completa.

    Para corregir un valor: reversar + registrar el correcto. Dos asientos,
    no una edición.
    """
    if not (motivo or "").strip():
        raise ValueError("motivo_requerido_para_reversar")

    sb = sb_requerido()
    r = (sb.table("personal_libro_tiempo").select("*")
         .eq("id", asiento_id).limit(1).execute())
    original = (r.data or [None])[0]
    if not original:
        raise ValueError("asiento_no_existe")
    if original.get("estado") != "vigente":
        raise ValueError(f"asiento_no_vigente:{original.get('estado')}")
    if original.get("tipo_asiento") == "reversion":
        raise ValueError("no_se_reversa_una_reversion")

    contraria = "credito" if original["direccion"] == "debito" else "debito"
    espejo = registrar(
        empleado_id=original["empleado_id"],
        tipo_asiento="reversion",
        direccion=contraria,
        minutos=original["minutos"],
        tipo_origen=original["tipo_origen"],
        origen_id=original.get("origen_id"),
        reversa_a_id=asiento_id,
        descripcion=f"Reversión de {asiento_id}: {motivo}",
        aprobado_por=actor,
        creado_por_sistema=False,
        actor=actor,
    )

    # Solo se marca el estado. minutos y direccion quedan intactos.
    sb.table("personal_libro_tiempo").update(
        {"estado": "reversado"}).eq("id", asiento_id).execute()

    return espejo


def asientos(empleado_id: str, *, desde: Optional[str] = None,
             hasta: Optional[str] = None, limit: int = 500) -> list[dict]:
    """Movimientos del empleado, más recientes primero."""
    sb = _sb()
    if sb is None:
        return []
    try:
        q = (sb.table("personal_libro_tiempo").select("*")
             .eq("empleado_id", empleado_id))
        if desde:
            q = q.gte("fecha_efectiva", desde)
        if hasta:
            q = q.lte("fecha_efectiva", hasta)
        r = q.order("fecha_efectiva", desc=True).order("created_at", desc=True) \
             .limit(min(max(limit, 1), 2000)).execute()
        return r.data or []
    except Exception as e:
        if es_error_tabla_faltante(e):
            return []
        log.error(f"[personal.libro] error listando: {e}")
        return []


def calcular_saldo(movimientos: list[dict]) -> dict:
    """El saldo ES esta suma. Función pura, testeable sin base de datos.

    Convención de signo: positivo = el empleado DEBE tiempo (débito neto).
    Es la lectura natural del caso de uso — "¿cuánto le falta por reponer?".
    """
    debito = sum(m["minutos"] for m in movimientos
                 if m.get("estado") == "vigente" and m.get("direccion") == "debito")
    credito = sum(m["minutos"] for m in movimientos
                  if m.get("estado") == "vigente" and m.get("direccion") == "credito")
    return {
        "minutos_debito":   debito,
        "minutos_credito":  credito,
        "saldo_pendiente":  max(0, debito - credito),
        "saldo_neto":       debito - credito,
        "movimientos":      len([m for m in movimientos if m.get("estado") == "vigente"]),
        "reversados":       len([m for m in movimientos if m.get("estado") == "reversado"]),
    }


def saldo(empleado_id: str) -> dict:
    return calcular_saldo(asientos(empleado_id, limit=2000))


def extracto(empleado_id: str, *, desde: Optional[str] = None,
             hasta: Optional[str] = None) -> dict:
    """Vista tipo extracto bancario para el autoservicio.

    Nunca expone una forma de editar el saldo — solo de leerlo y ver de dónde
    salió cada movimiento.
    """
    movs = asientos(empleado_id, desde=desde, hasta=hasta)
    return {
        "resumen": calcular_saldo(movs),
        "movimientos": [{
            "id":              m.get("id"),
            "fecha":           m.get("fecha_efectiva"),
            "tipo":            m.get("tipo_asiento"),
            "direccion":       m.get("direccion"),
            "minutos":         m.get("minutos"),
            "descripcion":     m.get("descripcion"),
            "origen":          m.get("tipo_origen"),
            "aprobado_por":    m.get("aprobado_por"),
            "estado":          m.get("estado"),
            "automatico":      m.get("creado_por_sistema"),
        } for m in movs],
    }
