"""Los pedidos de Melonn traen nombre, teléfono, correo y valor COD de las
compradoras: ninguna de estas rutas puede responder sin sesión.

Hasta nov-2026 `/api/melonn/pedidos`, `/api/melonn/pedidos/{orden}`,
`/api/melonn/status` y `/api/metricas` no pedían login y cualquiera con la URL
leía los datos (y con ?refresh=true gastaba la cuota diaria de Melonn).
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import melonn as api_melonn
from backend.api import metricas as api_metricas
from backend.core.security import CurrentUser, get_current_user

RUTAS = [
    "/api/melonn/pedidos",
    "/api/melonn/pedidos?refresh=true",
    "/api/melonn/pedidos/12345",
    "/api/melonn/status",
    "/api/metricas",
    "/api/metricas?refresh=true",
]


def _app(con_sesion: bool):
    app = FastAPI()
    app.include_router(api_melonn.router)
    app.include_router(api_metricas.router)
    if con_sesion:
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            id="u1", email="t@t.com", nombre="Test", rol="lector",
            activo=True, permisos={})
    return app


@pytest.fixture
def sin_melonn(monkeypatch):
    """Si alguna ruta llegara al servicio sin sesión, el test lo detecta."""
    llamadas = []

    def falso(*a, **k):
        llamadas.append(k)
        return {"pedidos": [], "total": 0, "fuente": "cache", "stale": False,
                "fetched_at": "2026-11-08T00:00:00Z"}

    monkeypatch.setattr(api_melonn.svc, "obtener_pedidos", falso)
    monkeypatch.setattr(api_melonn.overrides_svc, "cargar_map", lambda: {})
    monkeypatch.setattr(api_metricas.melonn_svc, "obtener_pedidos", falso)
    return llamadas


@pytest.mark.parametrize("ruta", RUTAS)
def test_sin_token_responde_401_y_no_toca_melonn(ruta, sin_melonn):
    r = TestClient(_app(con_sesion=False)).get(ruta)
    assert r.status_code in (401, 403), (ruta, r.status_code, r.text[:200])
    assert sin_melonn == [], f"{ruta} llamó a Melonn sin sesión"


def test_con_sesion_sigue_funcionando(sin_melonn):
    r = TestClient(_app(con_sesion=True)).get("/api/melonn/pedidos")
    assert r.status_code == 200, r.text[:300]
    assert sin_melonn, "con sesión debe consultar los pedidos"
