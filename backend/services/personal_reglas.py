"""
backend.services.personal_reglas — Reglas laborales configurables.

Las reglas NO viven dispersas como constantes en el código. Se resuelven en
cascada, de lo más específico a lo más general:

    empleado > horario > tipo_contrato > area > sede > empresa > default

La primera coincidencia gana. El diccionario REGLAS_DEFECTO es el último
recurso: garantiza que el motor funcione aunque la migración aún no se haya
aplicado o falten filas de configuración.

Advertencia sobre los valores por defecto
─────────────────────────────────────────
Los defaults de abajo son SUGERENCIAS de arranque, no política de la empresa.
Deben revisarse con Talento Humano y validarse con un abogado laboral antes
del lanzamiento. Ver TIME_MANAGEMENT_DOMAIN_RULES.md §6.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from backend.services.personal_base import (
    _sb, cache_get, cache_invalidar, cache_set, es_error_tabla_faltante,
)

log = logging.getLogger(__name__)


AMBITOS = ("empresa", "sede", "area", "tipo_contrato", "horario", "empleado")

# Orden de resolución: el primero que tenga valor gana.
_PRECEDENCIA = ("empleado", "horario", "tipo_contrato", "area", "sede", "empresa")

_CACHE_TTL = 60
_CACHE_PREFIJO = "personal:reglas:"


# ── Defaults ─────────────────────────────────────────────────────────────────
# Cada entrada: (valor, descripción legible para la pantalla de configuración)

REGLAS_DEFECTO: dict[str, Any] = {
    # Tolerancias
    "tolerancia_ingreso_min": 5,
    "tolerancia_salida_min": 5,
    "tolerancia_duplicado_seg": 30,
    "salida_intermedia_significativa_min": 10,

    # Compensación
    "max_minutos_compensables": 480,          # 8 horas
    "plazo_compensacion_dias": 7,             # misma semana
    "prorroga_maxima_dias": 15,               # hasta cierre de quincena
    "bloquear_compensacion_vencida": True,

    # Horas extras
    "requiere_autorizacion_previa_extra": True,
    "minutos_min_extra_reconocible": 15,      # menos de 15 min no se tramita

    # Incidencias
    "generar_incidencia_salida_faltante": True,
    "generar_incidencia_empleado_desconocido": True,
    "umbral_posible_extra_min": 30,           # a partir de aquí se levanta incidencia

    # Nómina — los tres que NUNCA deberían quedar en True/False al revés
    "conversion_automatica_a_descuento": False,
    "requiere_revision_humana_nomina": True,
    "banco_positivo_automatico": False,

    # Jornada
    "horas_semanales_default": 46,
    "minutos_descanso_default": 60,

    # Recargos (CST) — franja nocturna
    "hora_inicio_nocturno": "21:00",
    "hora_fin_nocturno": "06:00",

    # Periodo
    "tipo_periodo_nomina": "quincenal",
}

DESCRIPCIONES: dict[str, str] = {
    "tolerancia_ingreso_min": "Minutos de gracia al entrar antes de contar como tarde",
    "tolerancia_salida_min": "Minutos de gracia al salir antes de contar como salida anticipada",
    "tolerancia_duplicado_seg": "Dos marcaciones dentro de esta ventana se consideran la misma",
    "salida_intermedia_significativa_min": "Salidas más cortas que esto no rompen la jornada",
    "max_minutos_compensables": "Tope de tiempo que un permiso puede dejar por compensar",
    "plazo_compensacion_dias": "Días para reponer el tiempo de un permiso compensable",
    "prorroga_maxima_dias": "Extensión excepcional del plazo, con aprobación",
    "bloquear_compensacion_vencida": "Impedir reponer tiempo después del plazo",
    "requiere_autorizacion_previa_extra": "Las horas extras deben autorizarse antes de trabajarse",
    "minutos_min_extra_reconocible": "Extras por debajo de esto no se tramitan",
    "generar_incidencia_salida_faltante": "Levantar incidencia si falta la marcación de salida",
    "generar_incidencia_empleado_desconocido": "Levantar incidencia si el evento no mapea a un empleado",
    "umbral_posible_extra_min": "Permanencia extra desde la que se levanta incidencia",
    "conversion_automatica_a_descuento": "Descontar automáticamente el tiempo no repuesto (NO recomendado)",
    "requiere_revision_humana_nomina": "Toda novedad debe revisarla una persona antes de exportarse",
    "banco_positivo_automatico": "Acumular tiempo extra como saldo a favor (NO recomendado)",
    "horas_semanales_default": "Jornada semanal por defecto",
    "minutos_descanso_default": "Duración del descanso/almuerzo",
    "hora_inicio_nocturno": "Inicio de la franja de recargo nocturno",
    "hora_fin_nocturno": "Fin de la franja de recargo nocturno",
    "tipo_periodo_nomina": "Periodicidad del cierre de nómina",
}

# Reglas cuya activación es peligrosa: la UI debe pedir confirmación explícita
# y toda modificación queda auditada con motivo.
REGLAS_SENSIBLES = frozenset({
    "conversion_automatica_a_descuento",
    "banco_positivo_automatico",
    "requiere_revision_humana_nomina",   # peligrosa al DESACTIVAR
    "bloquear_compensacion_vencida",
})


class ReglasResueltas:
    """Vista inmutable de las reglas que aplican a un contexto concreto.

    Se construye una vez por cálculo de jornada y se pasa al motor, que así
    no necesita tocar la base de datos ni conocer la cascada.
    """

    __slots__ = ("_valores", "_origen")

    def __init__(self, valores: dict[str, Any], origen: dict[str, str]):
        self._valores = valores
        self._origen = origen

    def __getitem__(self, clave: str) -> Any:
        return self._valores[clave]

    def get(self, clave: str, default: Any = None) -> Any:
        return self._valores.get(clave, default)

    def origen_de(self, clave: str) -> str:
        """De qué ámbito salió el valor. Para la explicación del cálculo."""
        return self._origen.get(clave, "default")

    def as_dict(self) -> dict[str, Any]:
        return dict(self._valores)

    def __repr__(self) -> str:
        return f"ReglasResueltas({len(self._valores)} claves)"


def _leer_filas() -> list[dict]:
    """Todas las reglas activas. Cacheado — se invalida al escribir."""
    cacheado = cache_get(f"{_CACHE_PREFIJO}todas")
    if cacheado is not None:
        return cacheado
    sb = _sb()
    if sb is None:
        return cache_set(f"{_CACHE_PREFIJO}todas", [], _CACHE_TTL)
    try:
        r = sb.table("personal_reglas").select("*").eq("activa", True).execute()
        filas = r.data or []
    except Exception as e:
        if not es_error_tabla_faltante(e):
            log.error(f"[personal.reglas] error leyendo: {e}")
        filas = []
    return cache_set(f"{_CACHE_PREFIJO}todas", filas, _CACHE_TTL)


def resolver(
    *,
    empleado_id: Optional[str] = None,
    horario_id: Optional[str] = None,
    tipo_contrato: Optional[str] = None,
    area_id: Optional[str] = None,
    sede_id: Optional[str] = None,
) -> ReglasResueltas:
    """Resuelve la cascada completa para un contexto.

    Devuelve SIEMPRE un objeto usable: si no hay tabla, si está vacía o si
    Supabase no responde, caen los defaults. El motor nunca se queda sin reglas.
    """
    valores: dict[str, Any] = dict(REGLAS_DEFECTO)
    origen: dict[str, str] = {k: "default" for k in valores}

    ids_por_ambito = {
        "empleado": empleado_id,
        "horario": horario_id,
        "tipo_contrato": tipo_contrato,
        "area": area_id,
        "sede": sede_id,
        "empresa": None,
    }

    filas = _leer_filas()
    # Indexar por (ambito, ambito_id) para no recorrer N veces.
    indice: dict[tuple[str, Optional[str]], dict[str, Any]] = {}
    for f in filas:
        clave = (f.get("ambito"), f.get("ambito_id"))
        indice.setdefault(clave, {})[f.get("clave")] = f.get("valor")

    # Se recorre de MENOS a MÁS específico, sobrescribiendo. Así el más
    # específico queda arriba sin necesidad de comprobar si ya estaba puesto.
    for ambito in reversed(_PRECEDENCIA):
        ambito_id = ids_por_ambito.get(ambito)
        if ambito != "empresa" and not ambito_id:
            continue
        for clave, valor in indice.get((ambito, ambito_id), {}).items():
            if clave in valores or clave in REGLAS_DEFECTO:
                valores[clave] = _desempaquetar(valor)
                origen[clave] = ambito

    return ReglasResueltas(valores, origen)


def _desempaquetar(valor: Any) -> Any:
    """La columna es JSONB: puede venir escalar o envuelto en {"valor": x}."""
    if isinstance(valor, dict) and "valor" in valor and len(valor) == 1:
        return valor["valor"]
    return valor


def listar(*, ambito: Optional[str] = None) -> list[dict]:
    """Reglas configuradas, para la pantalla de configuración.

    Incluye las que solo existen como default, marcadas con es_default=True,
    para que la UI muestre el catálogo completo y no solo lo ya personalizado.
    """
    filas = _leer_filas()
    if ambito:
        filas = [f for f in filas if f.get("ambito") == ambito]

    configuradas = {f.get("clave") for f in filas}
    salida = [
        {**f,
         "valor": _desempaquetar(f.get("valor")),
         "descripcion": DESCRIPCIONES.get(f.get("clave"), ""),
         "es_default": False,
         "es_sensible": f.get("clave") in REGLAS_SENSIBLES}
        for f in filas
    ]
    for clave, valor in REGLAS_DEFECTO.items():
        if clave not in configuradas:
            salida.append({
                "clave": clave,
                "valor": valor,
                "ambito": "empresa",
                "ambito_id": None,
                "descripcion": DESCRIPCIONES.get(clave, ""),
                "es_default": True,
                "es_sensible": clave in REGLAS_SENSIBLES,
                "activa": True,
            })
    return sorted(salida, key=lambda r: r["clave"])


def establecer(
    *, clave: str, valor: Any, ambito: str = "empresa",
    ambito_id: Optional[str] = None, motivo: Optional[str] = None,
    actor: str = "sistema",
) -> dict:
    """Crea o actualiza una regla.

    Reglas de validación (se hacen cumplir aquí, no solo en la UI):
      - la clave debe existir en el catálogo (no se inventan reglas sueltas)
      - el ámbito debe ser conocido
      - todo ámbito distinto de 'empresa' exige ambito_id
      - el ámbito 'empleado' exige motivo — es una excepción individual y
        debe quedar justificada (la base de datos también lo obliga)
    """
    if clave not in REGLAS_DEFECTO:
        raise ValueError(f"regla_desconocida:{clave}")
    if ambito not in AMBITOS:
        raise ValueError(f"ambito_invalido:{ambito}")
    if ambito != "empresa" and not ambito_id:
        raise ValueError("ambito_id_requerido")
    if ambito == "empleado" and not (motivo or "").strip():
        raise ValueError("motivo_requerido_para_excepcion_individual")

    esperado = type(REGLAS_DEFECTO[clave])
    if esperado is bool and not isinstance(valor, bool):
        raise ValueError(f"tipo_invalido:{clave}_espera_booleano")
    if esperado is int and isinstance(valor, bool):
        raise ValueError(f"tipo_invalido:{clave}_espera_entero")
    if esperado is int and not isinstance(valor, int):
        raise ValueError(f"tipo_invalido:{clave}_espera_entero")

    from backend.services import personal_auditoria as aud
    from backend.services.personal_base import _now_iso, sb_requerido

    sb = sb_requerido()
    fila = {
        "clave": clave,
        "valor": valor,
        "ambito": ambito,
        "ambito_id": ambito_id,
        "motivo": motivo,
        "activa": True,
        "creada_por": actor,
        "updated_at": _now_iso(),
    }
    r = sb.table("personal_reglas").upsert(
        fila, on_conflict="clave,ambito,ambito_id"
    ).execute()
    cache_invalidar(_CACHE_PREFIJO)

    aud.registrar(
        actor=actor, accion="configurar_regla", entidad="regla",
        entidad_id=(r.data or [{}])[0].get("id"),
        valores_despues={"clave": clave, "valor": valor, "ambito": ambito},
        motivo=motivo,
    )
    return (r.data or [fila])[0]


def invalidar_cache() -> int:
    return cache_invalidar(_CACHE_PREFIJO)
