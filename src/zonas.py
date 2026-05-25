"""
Motor de clasificación de zonas logísticas.
Toma una ciudad destino y retorna zona + SLA esperado.
"""

import json
import unicodedata
from pathlib import Path
from dataclasses import dataclass
from typing import Union

CONFIG_PATH = Path(__file__).parent.parent / "config" / "zonas.json"


@dataclass
class ZonaInfo:
    zona: str
    descripcion: str
    sla_normal_max: int
    sla_riesgo: int
    sla_critico: int


def _normalizar(texto: str) -> str:
    """Quita tildes, pasa a mayúsculas, elimina espacios extras."""
    if not texto:
        return ""
    texto = texto.upper().strip()
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return texto


def _cargar_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def _construir_indice(config: dict) -> "dict[str, str]":
    """Construye un índice normalizado: ciudad_normalizada → nombre_zona."""
    indice = {}
    for nombre_zona, datos in config["zonas"].items():
        for ciudad in datos["ciudades"]:
            clave = _normalizar(ciudad)
            indice[clave] = nombre_zona
    return indice


# Cache en módulo para no releer disco en cada llamada
_config = _cargar_config()
_indice = _construir_indice(_config)


def clasificar_zona(ciudad: str, es_reexpedido: bool = False) -> ZonaInfo:
    """
    Clasifica un pedido en su zona logística y devuelve los SLAs.

    Args:
        ciudad: Ciudad destino del pedido (acepta tildes, minúsculas, etc.)
        es_reexpedido: True si el pedido fue relanzado tras devolución.

    Returns:
        ZonaInfo con zona, descripción y días SLA.
    """
    if es_reexpedido:
        nombre_zona = "REEXPEDIDO"
    else:
        clave = _normalizar(ciudad)
        nombre_zona = _indice.get(clave, _config["zona_default"])

    datos = _config["zonas"][nombre_zona]
    return ZonaInfo(
        zona=nombre_zona,
        descripcion=datos["descripcion"],
        sla_normal_max=datos["sla_normal_max"],
        sla_riesgo=datos["sla_riesgo"],
        sla_critico=datos["sla_critico"],
    )


def evaluar_tiempo(dias_en_transito: int, zona_info: ZonaInfo) -> str:
    """
    Dado cuántos días lleva un pedido en tránsito, retorna el nivel de tiempo.

    Returns:
        'NORMAL', 'RIESGO', o 'CRITICO'
    """
    if dias_en_transito >= zona_info.sla_critico:
        return "CRITICO"
    elif dias_en_transito >= zona_info.sla_riesgo:
        return "RIESGO"
    else:
        return "NORMAL"


def agregar_ciudades(ciudad_o_ciudades: Union[str, list], zona: str) -> None:
    """
    Agrega ciudades nuevas a una zona en zonas.json.
    Útil para expandir cobertura sin editar el JSON a mano.

    Args:
        ciudad_o_ciudades: Una ciudad o lista de ciudades.
        zona: Nombre de la zona destino (ej. 'PRINCIPALES').
    """
    if zona not in _config["zonas"]:
        raise ValueError(f"Zona '{zona}' no existe en zonas.json")

    if isinstance(ciudad_o_ciudades, str):
        ciudad_o_ciudades = [ciudad_o_ciudades]

    nuevas = [c.upper().strip() for c in ciudad_o_ciudades]
    existentes = set(_config["zonas"][zona]["ciudades"])
    agregadas = [c for c in nuevas if c not in existentes]

    _config["zonas"][zona]["ciudades"].extend(agregadas)

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(_config, f, ensure_ascii=False, indent=2)

    # Reconstruir índice en memoria
    global _indice
    _indice = _construir_indice(_config)

    if agregadas:
        print(f"Agregadas a {zona}: {agregadas}")
    else:
        print("Todas las ciudades ya existían.")


if __name__ == "__main__":
    # Pruebas rápidas
    casos = [
        ("Medellín", False),
        ("medellin", False),
        ("BOGOTÁ", False),
        ("Rionegro", False),
        ("Cali", False),
        ("Barranquilla", False),
        ("Mitú", False),
        ("San Pelayo", False),        # pueblo → SECUNDARIAS
        ("cualquier cosa", True),     # reexpedido
    ]

    print(f"{'Ciudad':<25} {'Zona':<15} {'Normal':<8} {'Riesgo':<8} {'Crítico'}")
    print("-" * 75)
    for ciudad, reexp in casos:
        z = clasificar_zona(ciudad, es_reexpedido=reexp)
        label = f"{ciudad} {'(reexp)' if reexp else ''}"
        print(f"{label:<25} {z.zona:<15} {z.sla_normal_max:<8} {z.sla_riesgo:<8} {z.sla_critico}")
