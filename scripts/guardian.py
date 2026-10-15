#!/usr/bin/env python3
"""
Guardián de MALE DENIM OS — corta en el push las CLASES de bug que ya nos han
mordido más de una vez. No policía todo el código viejo: mira SOLO lo que estás
subiendo (el diff contra main), así que se adopta sin arreglar nada primero y
frena lo NUEVO. Con `--full` lista además la deuda vieja (informativo).

Reglas (sobre líneas AÑADIDAS en .py de backend/ y src/):
  [E1] `.limit(N)` con N > 1000 en una lectura de Supabase → PostgREST corta en
       1.000 filas, así que un limit mayor SIEMPRE miente (mide sobre datos
       incompletos, y el día grande sale corto). Paginar con `.range(a, a+999)`
       o hacer la consulta acotada.
  [E2] `datetime.fromisoformat(` / `.fromisoformat(` directo → en Railway
       (Py 3.10) revienta con las fracciones de segundo que Postgres recorta.
       Usar `backend.core.fechas.parse_iso_utc`.

Escape puntual y a la vista en el diff: agregar  `# guardian: ok`  a la línea
(hay que justificar por qué es seguro).

Exit 1 si hay algún ERROR en lo añadido. `--full` nunca falla (solo reporta).
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from typing import Iterable

RE_LIMIT = re.compile(r"\.limit\(\s*(\d+)\s*\)")
RE_ISO = re.compile(r"\bfromisoformat\s*\(")
ESCAPE = "guardian: ok"
ISO_ESCAPE = "guardian: iso-ok"   # marca la línea del propio helper / manejo seguro

DIRS = ("backend/", "src/")
SELF = "scripts/guardian.py"
HELPER = "backend/core/fechas.py"


def _es_objetivo(path: str) -> bool:
    return (path.endswith(".py") and path.startswith(DIRS)
            and "__pycache__" not in path and path != SELF)


def _violaciones(path: str, lineno: int, texto: str) -> list[str]:
    out: list[str] = []
    if ESCAPE in texto:
        return out
    m = RE_LIMIT.search(texto)
    if m and int(m.group(1)) > 1000:
        out.append(f"E1 {path}:{lineno}  .limit({m.group(1)}) > 1000 — "
                   f"PostgREST corta en 1.000; pagina con .range() o consulta acotada")
    if RE_ISO.search(texto) and ISO_ESCAPE not in texto and path != HELPER:
        out.append(f"E2 {path}:{lineno}  fromisoformat directo — usa "
                   f"backend.core.fechas.parse_iso_utc (Py 3.10 revienta con la fracción)")
    return out


# ── Modo diff: solo lo que se está subiendo ──────────────────────────────────

def _base_ref() -> str:
    for cand in (os.environ.get("GUARDIAN_BASE", ""), "origin/main"):
        if not cand:
            continue
        if subprocess.run(["git", "rev-parse", "--verify", "--quiet", cand],
                          capture_output=True).returncode == 0:
            return cand
    return "HEAD~1"


def _lineas_anadidas(base: str) -> Iterable[tuple[str, int, str]]:
    """(path, lineno_nuevo, texto) de cada línea AÑADIDA en el diff base...HEAD."""
    diff = subprocess.run(
        ["git", "diff", "--unified=0", "--no-color", f"{base}...HEAD"],
        capture_output=True, text=True).stdout
    path = None
    nuevo = 0
    for ln in diff.splitlines():
        if ln.startswith("+++ b/"):
            path = ln[6:]
        elif ln.startswith("@@"):
            m = re.search(r"\+(\d+)", ln)
            nuevo = int(m.group(1)) if m else 0
        elif ln.startswith("+") and not ln.startswith("+++"):
            if path and _es_objetivo(path):
                yield path, nuevo, ln[1:]
            nuevo += 1
        elif not ln.startswith("-"):
            # línea de contexto (con unified=0 no debería haber, pero por si acaso)
            nuevo += 1


def modo_diff() -> int:
    base = _base_ref()
    errores: list[str] = []
    for path, lineno, texto in _lineas_anadidas(base):
        errores.extend(_violaciones(path, lineno, texto))
    if errores:
        print(f"🛡️  Guardián: {len(errores)} violación(es) NUEVA(s) (vs {base}):\n")
        for e in errores:
            print("   ✗ " + e)
        print("\nArréglalo o justifica con `# guardian: ok`. No se sube así.")
        return 1
    print(f"🛡️  Guardián OK — sin violaciones nuevas vs {base}.")
    return 0


# ── Modo full: deuda vieja (informativo) ─────────────────────────────────────

def modo_full() -> int:
    total = 0
    for raiz in DIRS:
        for base_dir, _, files in os.walk(raiz):
            if "__pycache__" in base_dir:
                continue
            for f in files:
                if not f.endswith(".py"):
                    continue
                path = os.path.join(base_dir, f)
                if path == SELF:
                    continue
                try:
                    with open(path, encoding="utf-8") as fh:
                        for i, texto in enumerate(fh, 1):
                            for v in _violaciones(path, i, texto):
                                print("   • " + v)
                                total += 1
                except Exception:
                    pass
    print(f"\n🛡️  Deuda total detectada: {total} (informativo, no bloquea). "
          f"Ir bajándola convierte cada línea en definitivamente blindada.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true",
                    help="Escanear TODO el repo (reporte de deuda, no bloquea)")
    args = ap.parse_args()
    return modo_full() if args.full else modo_diff()


if __name__ == "__main__":
    sys.exit(main())
