"""La página de Integraciones debe diagnosticar con el token que el OS usa.

Probaba con el `SHOPIFY_ACCESS_TOKEN` crudo: desde que revocaron el legacy
mostraba Shopify en rojo aunque el resto del OS le hablara a la tienda sin
problema. Un tablero de diagnóstico que miente es peor que no tenerlo.

`integraciones.py` es un script de Streamlit: importarlo dibuja la página y
lanza los tests de conexión de verdad (red incluida). Así que en vez de
importarlo se extraen del archivo real —con `ast`— sólo las funciones que se
prueban. Si alguien las renombra o las borra, esto falla en vez de dar verde.
"""
import ast
import os
import sys
import types
from pathlib import Path

import pytest

PAGINA = Path(__file__).resolve().parent.parent / "dashboard" / "pages" / "integraciones.py"

FUNCIONES = ("_secret", "_config_shopify", "_token_shopify")


def _cargar_helpers(secrets: dict) -> types.SimpleNamespace:
    """Ejecuta sólo las funciones de token/config, con un `st` de mentira."""
    arbol = ast.parse(PAGINA.read_text(), filename=str(PAGINA))
    elegidas = [n for n in arbol.body
                if isinstance(n, ast.FunctionDef) and n.name in FUNCIONES]
    faltan = set(FUNCIONES) - {n.name for n in elegidas}
    assert not faltan, f"integraciones.py ya no define: {sorted(faltan)}"

    # También las constantes de módulo que usan (p. ej. _CLAVES_SHOPIFY).
    asignaciones = [n for n in arbol.body if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id.isupper()
                            for t in n.targets)]

    st = types.ModuleType("streamlit")
    st.secrets = secrets
    ns: dict = {"st": st, "os": os, "sys": sys}
    exec(compile(ast.Module(body=asignaciones + elegidas, type_ignores=[]),
                 str(PAGINA), "exec"), ns)
    return types.SimpleNamespace(**{n: ns[n] for n in FUNCIONES})


@pytest.fixture(autouse=True)
def _sin_env_shopify(monkeypatch):
    for v in ("SHOPIFY_STORE", "SHOPIFY_CLIENT_ID", "SHOPIFY_CLIENT_SECRET",
              "SHOPIFY_ACCESS_TOKEN", "SHOPIFY_API_VERSION"):
        monkeypatch.delenv(v, raising=False)


def test_usa_el_token_de_shopify_auth(monkeypatch):
    """El caso que rompía: legacy revocado, app viva -> usa el de la app."""
    from backend.services import shopify_auth
    monkeypatch.setattr(shopify_auth, "token", lambda: "token_vigente_24h")
    h = _cargar_helpers({"SHOPIFY_ACCESS_TOKEN": "shpat_revocado"})
    assert h._token_shopify() == "token_vigente_24h"


def test_cae_al_legacy_si_shopify_auth_no_puede(monkeypatch):
    """Sin app configurada, el tablero sigue probando con lo que haya."""
    from backend.services import shopify_auth

    def _explota():
        raise RuntimeError("shopify_sin_credenciales")

    monkeypatch.setattr(shopify_auth, "token", _explota)
    h = _cargar_helpers({"SHOPIFY_ACCESS_TOKEN": "shpat_viejo"})
    assert h._token_shopify() == "shpat_viejo"


def test_config_lee_secrets(monkeypatch):
    h = _cargar_helpers({"SHOPIFY_STORE": "desde-secrets.myshopify.com"})
    assert h._config_shopify("SHOPIFY_STORE") == "desde-secrets.myshopify.com"


def test_config_lee_entorno_cuando_no_hay_secrets(monkeypatch):
    """En Railway la config son variables de entorno, no secrets.toml."""
    monkeypatch.setenv("SHOPIFY_STORE", "desde-entorno.myshopify.com")
    h = _cargar_helpers({})
    assert h._config_shopify("SHOPIFY_STORE") == "desde-entorno.myshopify.com"


def test_config_usa_default_si_no_hay_nada():
    h = _cargar_helpers({})
    assert h._config_shopify("SHOPIFY_API_VERSION", "2024-01") == "2024-01"


def test_puentea_secrets_al_entorno_para_shopify_auth(monkeypatch):
    """shopify_auth lee os.environ; la config del tablero vive en secrets.toml."""
    from backend.services import shopify_auth
    monkeypatch.setattr(shopify_auth, "token", lambda: "tok")
    h = _cargar_helpers({"SHOPIFY_STORE": "male-denim-5524.myshopify.com",
                         "SHOPIFY_CLIENT_ID": "cid",
                         "SHOPIFY_CLIENT_SECRET": "sec"})
    h._token_shopify()
    assert os.environ["SHOPIFY_CLIENT_ID"] == "cid"
    assert os.environ["SHOPIFY_CLIENT_SECRET"] == "sec"


def test_no_pisa_el_entorno_real(monkeypatch):
    """Si Railway ya trae la variable, secrets.toml no debe sobreescribirla."""
    from backend.services import shopify_auth
    monkeypatch.setattr(shopify_auth, "token", lambda: "tok")
    monkeypatch.setenv("SHOPIFY_CLIENT_ID", "el_de_railway")
    h = _cargar_helpers({"SHOPIFY_CLIENT_ID": "el_de_secrets"})
    h._token_shopify()
    assert os.environ["SHOPIFY_CLIENT_ID"] == "el_de_railway"
