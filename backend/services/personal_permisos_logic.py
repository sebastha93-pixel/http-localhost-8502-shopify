"""
backend.services.personal_permisos_logic — Reglas puras de permisos.

Sin I/O, como personal_motor. Espeja el patrón de postventa_logic.py, que es
el único FSM formal que ya tenía el repo.

Por qué doble aprobación
────────────────────────
El jefe evalúa la AFECTACIÓN OPERATIVA: "¿puedo cubrir la tienda sin esta
persona el jueves?". Talento Humano valida la CLASIFICACIÓN: "¿esto es
calamidad doméstica o permiso personal?".

Son juicios distintos, hechos por gente distinta, con consecuencias distintas.
Por eso son dos pasos y no uno: el jefe no debería decidir si algo es una
licencia de ley, y TH no debería decidir si la tienda queda cubierta.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

# ── Estados ──────────────────────────────────────────────────────────────────

ESTADOS: set[str] = {
    "borrador", "enviada", "pendiente_jefe", "pendiente_th", "aprobada",
    "rechazada", "cancelada", "en_compensacion", "completada", "vencida",
    "enviada_a_nomina",
}

ESTADOS_TERMINALES: set[str] = {"rechazada", "cancelada", "completada",
                                "enviada_a_nomina"}

# El empleado puede cancelar mientras nadie haya decidido todavía.
ESTADOS_CANCELABLES: set[str] = {"borrador", "enviada", "pendiente_jefe",
                                 "pendiente_th"}

# Estados en los que el permiso ya cuenta como autorizado para el motor.
ESTADOS_VIGENTES: set[str] = {"aprobada", "en_compensacion", "completada"}

TRANSICIONES: dict[str, set[str]] = {
    "borrador":         {"enviada", "cancelada"},
    "enviada":          {"pendiente_jefe", "cancelada"},
    "pendiente_jefe":   {"pendiente_th", "rechazada", "cancelada"},
    "pendiente_th":     {"aprobada", "en_compensacion", "rechazada", "cancelada"},
    "aprobada":         {"completada", "cancelada"},
    "en_compensacion":  {"completada", "vencida", "cancelada"},
    "vencida":          {"enviada_a_nomina", "completada"},
    "completada":       set(),
    "rechazada":        set(),
    "cancelada":        set(),
    "enviada_a_nomina": set(),
}


def transicion_valida(actual: str, nuevo: str) -> bool:
    return nuevo in TRANSICIONES.get(actual, set())


def es_terminal(estado: str) -> bool:
    return estado in ESTADOS_TERMINALES


def puede_cancelar(estado: str) -> bool:
    return estado in ESTADOS_CANCELABLES


# ── Clasificación ────────────────────────────────────────────────────────────

CATEGORIAS = ("legal_remunerado", "empresarial_remunerado", "personal_compensable",
              "no_remunerado", "incapacidad", "vacaciones")

TRATAMIENTOS_NOMINA = ("sin_efecto", "descuento", "compensacion",
                       "licencia_no_remunerada")


def tratamiento_nomina(categoria: str) -> str:
    """Qué le pasa a este permiso en nómina, según su clasificación."""
    return {
        "legal_remunerado":       "sin_efecto",
        "empresarial_remunerado": "sin_efecto",
        "personal_compensable":   "compensacion",
        "no_remunerado":          "licencia_no_remunerada",
        "incapacidad":            "sin_efecto",
        "vacaciones":             "sin_efecto",
    }.get(categoria, "sin_efecto")


def validar_clasificacion(categoria: str, es_compensable: bool) -> None:
    """La regla que protege al trabajador.

    Un permiso de ley NUNCA puede volverse deuda de tiempo. Convertir una
    licencia de luto o el ejercicio del voto en horas por reponer sería
    contrario a la ley.

    La base de datos también lo impide con un CHECK; esto lo valida antes
    para dar un error legible en vez de un 500 de Postgres.
    """
    if categoria not in CATEGORIAS:
        raise ValueError(f"categoria_invalida:{categoria}")
    if categoria == "legal_remunerado" and es_compensable:
        raise ValueError("permiso_legal_no_puede_ser_compensable")
    if categoria == "incapacidad" and es_compensable:
        raise ValueError("incapacidad_no_puede_ser_compensable")


# ── Validación de la solicitud ───────────────────────────────────────────────

def minutos_solicitados(inicio: datetime, fin: datetime) -> int:
    if fin <= inicio:
        raise ValueError("rango_invalido:fin_debe_ser_posterior_a_inicio")
    return int((fin - inicio).total_seconds() // 60)


def validar_solicitud(
    *, inicio: datetime, fin: datetime, motivo: str,
    minutos_max: Optional[int] = None, requiere_soporte: bool = False,
    tiene_soporte: bool = False, max_compensable: Optional[int] = None,
    es_compensable: bool = False,
) -> int:
    """Valida y devuelve los minutos. Lanza ValueError con código snake_case."""
    minutos = minutos_solicitados(inicio, fin)

    if not (motivo or "").strip():
        raise ValueError("motivo_requerido")
    if minutos_max and minutos > minutos_max:
        raise ValueError(f"excede_maximo_del_tipo:{minutos_max}")
    if requiere_soporte and not tiene_soporte:
        raise ValueError("soporte_requerido_para_este_tipo")
    if es_compensable and max_compensable and minutos > max_compensable:
        raise ValueError(f"excede_maximo_compensable:{max_compensable}")
    return minutos


def hay_cruce(inicio_a: datetime, fin_a: datetime,
              inicio_b: datetime, fin_b: datetime) -> bool:
    """¿Se solapan dos rangos? Los extremos que se tocan NO cruzan.

    Un permiso de 08:00-10:00 y otro de 10:00-12:00 son contiguos, no
    solapados: pedirlos ambos es legítimo.
    """
    return inicio_a < fin_b and inicio_b < fin_a


def validar_sin_cruces(inicio: datetime, fin: datetime,
                       existentes: list[dict]) -> None:
    """Rechaza si cruza con otro permiso vigente del mismo empleado."""
    for p in existentes:
        if p.get("estado") not in ESTADOS_VIGENTES and \
           p.get("estado") not in {"pendiente_jefe", "pendiente_th", "enviada"}:
            continue
        pi, pf = p.get("_inicio"), p.get("_fin")
        if pi and pf and hay_cruce(inicio, fin, pi, pf):
            raise ValueError(f"cruza_con_permiso_existente:{p.get('id', '?')}")


# ── Compensación ─────────────────────────────────────────────────────────────

def fecha_limite_compensacion(
    fecha_permiso: date, *, plazo_dias: int = 7,
) -> date:
    """Hasta cuándo hay para reponer el tiempo.

    Por defecto la misma semana. La prórroga excepcional (hasta cierre de
    quincena) la aprueba Talento Humano y se registra con motivo.
    """
    return fecha_permiso + timedelta(days=plazo_dias)


def esta_vencida(fecha_limite: date, hoy: date) -> bool:
    """Vencida = ya pasó el plazo. El día del plazo todavía cuenta."""
    return hoy > fecha_limite


def estado_del_plan(minutos_total: int, minutos_compensados: int,
                    fecha_limite: date, hoy: date) -> str:
    """Estado derivado del plan de compensación. Nunca se digita a mano."""
    if minutos_compensados >= minutos_total:
        return "completado"
    if esta_vencida(fecha_limite, hoy):
        return "vencido"
    return "activo"


def minutos_pendientes(minutos_total: int, minutos_compensados: int) -> int:
    return max(0, minutos_total - minutos_compensados)


# ── Quién puede hacer qué ────────────────────────────────────────────────────

def siguiente_paso(estado: str) -> Optional[str]:
    """Quién tiene la pelota. Para la bandeja y las notificaciones."""
    return {
        "borrador":        "empleado",
        "enviada":         "jefe",
        "pendiente_jefe":  "jefe",
        "pendiente_th":    "talento_humano",
        "en_compensacion": "empleado",
        "vencida":         "talento_humano",
    }.get(estado)
