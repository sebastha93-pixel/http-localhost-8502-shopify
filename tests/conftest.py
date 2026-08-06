"""Asegura que la raíz del repo y `src/` estén en sys.path.

La raíz, para importar `backend`. Y `src/`, porque `melonn_client` vive fuera
del paquete `backend` y en producción lo carga `salud_logistica._mc()`
insertando esa misma ruta a mano.
"""
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
for ruta in (RAIZ, RAIZ / "src"):
    if str(ruta) not in sys.path:
        sys.path.insert(0, str(ruta))
