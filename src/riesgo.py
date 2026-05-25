"""
Motor de riesgo logístico.
Combina zona + incidencia + días en tránsito + contraentrega
para producir un score (0-100+) y nivel NORMAL / RIESGO / CRÍTICO.
"""

import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import List

from zonas import clasificar_zona, evaluar_tiempo, ZonaInfo
from incidencias import clasificar_incidencia, IncidenciaInfo

CONFIG_PATH = Path(__file__).parent.parent / "config" / "scoring_rules.json"


@dataclass
class ResultadoRiesgo:
    score: int
    nivel: str                  # NORMAL / RIESGO / CRÍTICO
    motivos: List[str]          # Razones que subieron el score
    requiere_accion: bool
    prioridad: int              # 1 = más urgente
    zona_info: ZonaInfo
    incidencia_info: IncidenciaInfo
    nivel_tiempo: str           # NORMAL / RIESGO / CRÍTICO (solo por tiempo)


def _cargar_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


_rules = _cargar_config()
_pesos = _rules["pesos"]
_niveles = _rules["niveles"]
_overrides = {i.upper().strip() for i in _rules["overrides_criticos"]}


def calcular_riesgo(
    ciudad: str,
    dias_en_transito: int,
    incidencia_raw: str,
    es_contraentrega: bool,
    es_reexpedido: bool = False,
    horas_sin_actualizacion: int = 0,
) -> ResultadoRiesgo:
    """
    Calcula el nivel de riesgo de un pedido.

    Args:
        ciudad: Ciudad destino.
        dias_en_transito: Días desde fecha de despacho hasta hoy.
        incidencia_raw: Novedad tal como viene de Melonn.
        es_contraentrega: True si el pago es contraentrega.
        es_reexpedido: True si el pedido fue relanzado.
        horas_sin_actualizacion: Horas desde el último cambio de estado.

    Returns:
        ResultadoRiesgo con score, nivel, motivos y prioridad.
    """
    zona = clasificar_zona(ciudad, es_reexpedido=es_reexpedido)
    incidencia = clasificar_incidencia(incidencia_raw)
    nivel_tiempo = evaluar_tiempo(dias_en_transito, zona)

    score = 0
    motivos = []

    # Override directo a CRÍTICO por incidencias gravísimas
    if incidencia.incidencia_normalizada in {i.upper() for i in _overrides}:
        score = 100
        motivos.append(f"INCIDENCIA CRÍTICA: {incidencia.incidencia_raw}")

    else:
        # Contraentrega
        if es_contraentrega:
            score += _pesos["es_contraentrega"]
            motivos.append("Contraentrega")

        # Tiempo en tránsito
        if nivel_tiempo == "CRITICO":
            score += _pesos["tiempo_critico"]
            motivos.append(f"Tiempo crítico ({dias_en_transito}d en zona {zona.zona})")
        elif nivel_tiempo == "RIESGO":
            score += _pesos["tiempo_riesgo"]
            motivos.append(f"Tiempo en riesgo ({dias_en_transito}d en zona {zona.zona})")

        # Incidencia por categoría
        if incidencia.categoria == "TRANSPORTADORA":
            score += _pesos["incidencia_transportadora"]
            motivos.append(f"Novedad transportadora: {incidencia.incidencia_raw}")
        elif incidencia.categoria == "CLIENTE":
            score += _pesos["incidencia_cliente"]
            motivos.append(f"Novedad cliente: {incidencia.incidencia_raw}")
        elif incidencia.categoria == "SEGUIMIENTO":
            score += _pesos["incidencia_seguimiento"]
            motivos.append(f"Novedad seguimiento: {incidencia.incidencia_raw}")

        # Sin actualizaciones recientes
        if horas_sin_actualizacion >= 24:
            score += _pesos["sin_actualizacion_24h"]
            motivos.append(f"Sin actualización hace {horas_sin_actualizacion}h")

    # Calcular nivel
    score_capped = min(score, 100)
    nivel = _calcular_nivel(score_capped)

    # Prioridad operativa (para ordenar la lista de trabajo)
    prioridad = _calcular_prioridad(nivel, es_contraentrega, incidencia)

    return ResultadoRiesgo(
        score=score_capped,
        nivel=nivel,
        motivos=motivos,
        requiere_accion=nivel in ("RIESGO", "CRITICO"),
        prioridad=prioridad,
        zona_info=zona,
        incidencia_info=incidencia,
        nivel_tiempo=nivel_tiempo,
    )


def _calcular_nivel(score: int) -> str:
    for nivel, rango in _niveles.items():
        if rango["min"] <= score <= rango["max"]:
            return nivel
    return "CRITICO"


def _calcular_prioridad(nivel: str, es_contraentrega: bool, incidencia: IncidenciaInfo) -> int:
    """
    Retorna un número de prioridad para ordenar la lista de trabajo.
    Menor número = más urgente.

    Escala:
      1 → CRÍTICO contraentrega con incidencia crítica
      2 → CRÍTICO contraentrega
      3 → CRÍTICO sin contraentrega
      4 → RIESGO contraentrega
      5 → RIESGO sin contraentrega
      9 → NORMAL (no aparece en lista de trabajo)
    """
    if nivel == "CRITICO":
        if es_contraentrega and incidencia.es_critica:
            return 1
        if es_contraentrega:
            return 2
        return 3
    if nivel == "RIESGO":
        return 4 if es_contraentrega else 5
    return 9


if __name__ == "__main__":
    casos = [
        # (ciudad, dias, incidencia, contraentrega, reexpedido, descripcion)
        ("Medellín",     0, "NINGUNO",                  False, False, "Medellin recién despachado"),
        ("Medellín",     2, "NINGUNO",                  True,  False, "Medellin 2d COD → CRÍTICO"),
        ("Bogotá",       3, "NINGUNO",                  True,  False, "Bogotá 3d COD → RIESGO"),
        ("Bogotá",       4, "NO SE LOGRARON COMUNICAR", True,  False, "Bogotá 4d + no contesta + COD"),
        ("Cali",         5, "PAQUETE EXTRAVIADO",       True,  False, "Extraviado COD → siempre CRÍTICO"),
        ("Barranquilla", 3, "DIRECCION INCORRECTA",     False, False, "Dir incorrecta sin COD"),
        ("San Pelayo",   6, "1 ENTREGA",                True,  False, "Pueblo 6d + 1 intento + COD"),
        ("Medellín",     7, "NINGUNO",                  False, True,  "Reexpedido día 7"),
        ("Pereira",      2, "NO CANCELA RECAUDO",       True,  False, "No paga → siempre CRÍTICO"),
        ("Envigado",     1, "NINGUNO",                  False, False, "Zona rápida normal"),
    ]

    print(f"{'Descripción':<42} {'Zona':<16} {'Score':<7} {'Nivel':<10} {'Prior':<7} {'Motivo principal'}")
    print("-" * 115)
    for ciudad, dias, inc, cod, reexp, desc in casos:
        r = calcular_riesgo(ciudad, dias, inc, cod, reexp)
        motivo = r.motivos[0] if r.motivos else "—"
        print(
            f"{desc:<42} {r.zona_info.zona:<16} {r.score:<7} {r.nivel:<10} "
            f"{r.prioridad:<7} {motivo}"
        )
