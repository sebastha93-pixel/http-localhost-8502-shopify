"""Asegura que la raíz del repo y `src/` estén en sys.path.

La raíz, para importar `backend`. Y `src/`, porque `melonn_client` vive fuera
del paquete `backend` y en producción lo carga `salud_logistica._mc()`
insertando esa misma ruta a mano.
"""
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
for ruta in (RAIZ, RAIZ / "src"):
    if str(ruta) not in sys.path:
        sys.path.insert(0, str(ruta))


@pytest.fixture(autouse=True)
def _aislamiento_supabase(monkeypatch):
    """
    Evita que cualquier prueba escriba en el caché de producción de Supabase.

    El módulo melonn_client construye un cliente Supabase (@functools.lru_cache)
    si SUPABASE_URL y SUPABASE_KEY están configuradas. Las pruebas que llaman a
    _barrido_guardar(), _marcar_fetch_api() o _sb_cache_guardar() escribirían
    en la tabla compartida (melonn_cache) que lee el dashboard en producción.

    Sin este aislamiento, un cambio de configuración o la instalación de supabase
    en .venv haría que las pruebas corrompan silenciosamente el estado del tablero,
    porque el efecto secundario de escritura no es visible en la suite de tests.

    Solución: vaciamos las credenciales para CADA prueba y limpiamos el caché del
    cliente para que uno anterior no pueda "escaparse" a pruebas sin credenciales.
    """
    # Blanquear las credenciales
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("SUPABASE_KEY", "")

    # Limpiar el caché del cliente si el módulo ya fue importado
    try:
        import melonn_client as mc
        if hasattr(mc, "_sb") and hasattr(mc._sb, "cache_clear"):
            mc._sb.cache_clear()
    except ImportError:
        # Si aún no se importó melonn_client (p.ej., test de otro módulo),
        # no hay nada que limpiar
        pass
