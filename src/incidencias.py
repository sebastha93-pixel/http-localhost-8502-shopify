"""
Motor de clasificación de incidencias logísticas.
Toma la novedad cruda de Melonn y retorna categoría, peso de riesgo y flags.
"""

import json
import unicodedata
from pathlib import Path
from dataclasses import dataclass

CONFIG_PATH = Path(__file__).parent.parent / "config" / "incidencias.json"


@dataclass
class IncidenciaInfo:
    incidencia_raw: str
    incidencia_normalizada: str
    categoria: str           # CLIENTE / TRANSPORTADORA / SEGUIMIENTO / OK
    descripcion: str
    peso_riesgo: int         # Puntos que suma al score de riesgo
    es_critica: bool         # True si activa nivel CRÍTICO directamente
    requiere_contacto: bool  # True si alguien debe llamar al cliente


def _normalizar(texto: str) -> str:
    if not texto:
        return ""
    texto = texto.upper().strip()
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return texto


def _cargar_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def _construir_indice(config: dict) -> "dict[str, tuple]":
    """Construye índice normalizado: incidencia_normalizada → (categoria, peso)."""
    indice = {}
    for categoria, datos in config["categorias"].items():
        for inc in datos["incidencias"]:
            clave = _normalizar(inc)
            indice[clave] = (categoria, datos["peso_riesgo"], datos["descripcion"])
    return indice


_config = _cargar_config()
_indice = _construir_indice(_config)
_criticas = {_normalizar(i) for i in _config["incidencias_criticas"]}
_contacto_cliente = {"CLIENTE"}  # Categorías que requieren llamar al cliente


def clasificar_incidencia(incidencia_raw: str) -> IncidenciaInfo:
    """
    Clasifica una novedad logística cruda.

    Args:
        incidencia_raw: Texto tal como viene del CSV de Melonn.

    Returns:
        IncidenciaInfo con categoría, peso y flags operativos.
    """
    normalizada = _normalizar(incidencia_raw)
    resultado = _indice.get(normalizada)

    if resultado:
        categoria, peso, descripcion = resultado
    else:
        # Búsqueda parcial: si alguna incidencia conocida está contenida en el texto
        categoria, peso, descripcion = None, None, None
        for clave, (cat, p, desc) in _indice.items():
            if clave and clave in normalizada:
                categoria, peso, descripcion = cat, p, desc
                break

        if categoria is None:
            categoria = _config["categoria_default"]
            peso = _config["peso_default"]
            descripcion = "Novedad no reconocida — revisar manualmente"

    es_critica = normalizada in _criticas
    requiere_contacto = categoria in _contacto_cliente

    return IncidenciaInfo(
        incidencia_raw=incidencia_raw,
        incidencia_normalizada=normalizada,
        categoria=categoria,
        descripcion=descripcion,
        peso_riesgo=peso,
        es_critica=es_critica,
        requiere_contacto=requiere_contacto,
    )


def listar_incidencias() -> None:
    """Imprime el catálogo completo de incidencias configuradas."""
    for categoria, datos in _config["categorias"].items():
        print(f"\n[{categoria}] — peso: {datos['peso_riesgo']}")
        for inc in datos["incidencias"]:
            critica = " ⚠ CRÍTICA" if _normalizar(inc) in _criticas else ""
            print(f"  · {inc or '(vacío)'}{critica}")


if __name__ == "__main__":
    casos = [
        "NINGUNO",
        "NO SE LOGRARON COMUNICAR",
        "DIRECCION INCORRECTA",
        "NO CANCELA RECAUDO",
        "DESTINO",
        "TRANSPORTADORA",
        "PAQUETE EXTRAVIADO",
        "1 ENTREGA",
        "",                          # vacío → OK
        "novedad desconocida xyz",   # no mapeada → default
        "direccion incorrecta",      # minúsculas → debe funcionar
    ]

    print(f"{'Incidencia raw':<30} {'Categoría':<16} {'Peso':<6} {'Crítica':<9} {'Contacto'}")
    print("-" * 80)
    for raw in casos:
        r = clasificar_incidencia(raw)
        label = raw if raw else "(vacío)"
        print(
            f"{label:<30} {r.categoria:<16} {r.peso_riesgo:<6} "
            f"{'SÍ' if r.es_critica else 'no':<9} {'SÍ' if r.requiere_contacto else 'no'}"
        )

    print("\n--- Catálogo completo ---")
    listar_incidencias()
