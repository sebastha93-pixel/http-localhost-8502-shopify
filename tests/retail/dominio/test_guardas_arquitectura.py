"""Guardas de arquitectura del módulo retail.

Las reglas del diseño (docs/retail-pos/01-ARQUITECTURA.md §8) no son
recomendaciones que alguien recuerda en la revisión: son pruebas que fallan el
build. Una regla que sólo vive en un documento se rompe en el tercer mes.

Estas tres son las que sostienen todo lo demás:

  1. `domain/` no importa framework ni I/O — es lo que permite probar las
     reglas del dinero sin base de datos, sin red y en milisegundos.
  2. No hay `float` en el dominio — ADR-008, y hay un precedente caro.
  3. El código compila bajo Python 3.10 — Railway corre sobre `jammy`, cuyo
     Python es 3.10, aunque en local haya uno más nuevo. Escribir sintaxis de
     3.12 aquí produce un error que sólo aparece en el despliegue.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import List

RAIZ = Path(__file__).resolve().parents[3]
DOMINIO = RAIZ / "backend" / "modules" / "retail" / "domain"
MODULO = RAIZ / "backend" / "modules" / "retail"

# Todo lo que significa "esto ya no es dominio puro".
PROHIBIDOS_EN_DOMINIO = {
    "fastapi", "starlette", "pydantic",
    "sqlalchemy", "alembic", "psycopg", "psycopg2", "asyncpg",
    "supabase", "postgrest",
    "httpx", "requests", "aiohttp", "urllib", "socket",
    "redis",
    "os", "pathlib", "subprocess", "sys",
}

# La versión de Python que realmente corre en producción (Dockerfile: jammy).
PYTHON_PRODUCCION = (3, 10)


def _archivos(directorio: Path) -> List[Path]:
    """Los .py a revisar — y se niega a devolver una lista vacía.

    Una guarda que escanea cero archivos pasa en verde sin haber medido nada.
    Si alguien mueve el módulo de carpeta, el resultado sería "todo bien" sobre
    un directorio inexistente. Prefiero que reviente.
    """
    assert directorio.is_dir(), f"no existe el directorio a revisar: {directorio}"
    archivos = sorted(p for p in directorio.rglob("*.py") if p.name != "__init__.py")
    assert archivos, (
        f"no se encontró ningún .py bajo {directorio}. Una guarda sin archivos "
        f"que revisar no está probando nada."
    )
    return archivos


def _raiz_del_import(nodo: ast.AST) -> List[str]:
    if isinstance(nodo, ast.Import):
        return [a.name.split(".")[0] for a in nodo.names]
    if isinstance(nodo, ast.ImportFrom):
        # `from . import x` no tiene módulo; los relativos son del propio dominio.
        if nodo.level and nodo.level > 0:
            return []
        return [(nodo.module or "").split(".")[0]]
    return []


def test_el_dominio_no_importa_framework_ni_io():
    infracciones = []
    for archivo in _archivos(DOMINIO):
        arbol = ast.parse(archivo.read_text(encoding="utf-8"))
        for nodo in ast.walk(arbol):
            for raiz in _raiz_del_import(nodo):
                if raiz in PROHIBIDOS_EN_DOMINIO:
                    rel = archivo.relative_to(RAIZ)
                    infracciones.append(f"{rel}:{nodo.lineno} importa `{raiz}`")

    assert not infracciones, (
        "El dominio dejó de ser puro. Eso rompe la promesa de poder probar las "
        "reglas del dinero sin levantar nada:\n  " + "\n  ".join(infracciones)
    )


def test_no_hay_float_en_el_dominio():
    """ADR-008. El precedente: 169.900 salió facturado como 67.960."""
    infracciones = []
    for archivo in _archivos(DOMINIO):
        arbol = ast.parse(archivo.read_text(encoding="utf-8"))
        for nodo in ast.walk(arbol):
            # Una llamada a float(...)
            if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name) \
                    and nodo.func.id == "float":
                infracciones.append(
                    f"{archivo.relative_to(RAIZ)}:{nodo.lineno} llama a float()")
            # Un literal decimal escrito directamente
            if isinstance(nodo, ast.Constant) and isinstance(nodo.value, float):
                infracciones.append(
                    f"{archivo.relative_to(RAIZ)}:{nodo.lineno} "
                    f"tiene el literal float {nodo.value!r}")

    assert not infracciones, (
        "Apareció aritmética de punto flotante en el dominio. Usa int (centavos) "
        "o Decimal:\n  " + "\n  ".join(infracciones)
    )


def test_el_dominio_no_lee_el_reloj_por_su_cuenta():
    """La hora entra como argumento, nunca se consulta desde el dominio.

    Dos razones. La primera es que una regla que llama a `datetime.now()` no se
    puede probar: el resultado cambia cada vez que corre. La segunda es
    operativa — la hora de una venta la pone el SERVIDOR, no el dispositivo
    (riesgo R7: una tablet con el reloj corrido tres horas manda ventas al
    turno que no es).
    """
    prohibidos = {"now", "utcnow", "today", "time", "monotonic"}
    infracciones = []
    for archivo in _archivos(DOMINIO):
        arbol = ast.parse(archivo.read_text(encoding="utf-8"))
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Attribute) \
                    and nodo.func.attr in prohibidos:
                infracciones.append(
                    f"{archivo.relative_to(RAIZ)}:{nodo.lineno} "
                    f"llama a .{nodo.func.attr}()")

    assert not infracciones, (
        "El dominio está leyendo el reloj. Recibe la hora como argumento:\n  "
        + "\n  ".join(infracciones))


def test_el_modulo_compila_en_la_version_de_produccion():
    """Railway corre Python 3.10. En local hay uno más nuevo, así que la
    sintaxis moderna pasa aquí y revienta allá — con la tienda abierta."""
    infracciones = []
    for archivo in _archivos(MODULO):
        fuente = archivo.read_text(encoding="utf-8")
        try:
            ast.parse(fuente, feature_version=PYTHON_PRODUCCION)
        except SyntaxError as e:
            infracciones.append(
                f"{archivo.relative_to(RAIZ)}:{e.lineno} no compila en "
                f"Python {PYTHON_PRODUCCION[0]}.{PYTHON_PRODUCCION[1]}: {e.msg}")

    assert not infracciones, (
        "Hay sintaxis que Railway no puede ejecutar:\n  " + "\n  ".join(infracciones))


def test_las_guardas_de_verdad_detectan_algo(tmp_path):
    """Una guarda que nunca ha fallado puede estar rota y nadie lo sabría.

    Se le da código malo a propósito y se confirma que lo señala.
    """
    malo = tmp_path / "malo.py"
    malo.write_text("import httpx\nx = float(1.5)\n", encoding="utf-8")
    arbol = ast.parse(malo.read_text(encoding="utf-8"))

    importa_prohibido = any(
        raiz in PROHIBIDOS_EN_DOMINIO
        for nodo in ast.walk(arbol) for raiz in _raiz_del_import(nodo))
    tiene_float = any(
        isinstance(n, ast.Constant) and isinstance(n.value, float)
        for n in ast.walk(arbol))

    assert importa_prohibido, "la guarda de imports no detectaría `import httpx`"
    assert tiene_float, "la guarda de float no detectaría el literal 1.5"
