"""Un token solo vale mientras su usuario exista y esté activo en la base.

Hasta nov-2026 `get_current_user` caía al rol del JWT con `activo=True` cuando
`obtener_por_id` devolvía None: un usuario BORRADO (o un token forjado con un
`sub` inventado) seguía entrando con su rol, admin incluido, y la renovación
automática (`main.renovar_sesion`) lo mantenía vivo para siempre.
"""
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from backend.core import security
from backend.core.security import CurrentUser, create_access_token, get_current_user
from backend.services import usuarios


def _token(uid="u-borrado", rol="admin"):
    return create_access_token(CurrentUser(id=uid, email="x@x.com", nombre="X", rol=rol))


def _cliente():
    app = FastAPI()

    @app.get("/privado")
    def privado(u: CurrentUser = Depends(get_current_user)):
        return {"rol": u.rol}

    return TestClient(app)


@pytest.fixture(autouse=True)
def limpiar_cache(monkeypatch):
    security._USER_CACHE.clear()
    monkeypatch.setattr(usuarios, "_sb", lambda: object())   # "hay Supabase"
    yield
    security._USER_CACHE.clear()


def _get(token):
    return _cliente().get("/privado", headers={"Authorization": f"Bearer {token}"})


def test_usuario_borrado_no_entra(monkeypatch):
    monkeypatch.setattr(usuarios, "obtener_por_id", lambda uid: None)
    r = _get(_token())
    assert r.status_code == 401


def test_usuario_inactivo_no_entra(monkeypatch):
    monkeypatch.setattr(usuarios, "obtener_por_id", lambda uid: {"id": uid, "activo": False, "rol": "admin"})
    assert _get(_token()).status_code == 401


def test_usuario_activo_entra_con_el_rol_de_la_base(monkeypatch):
    monkeypatch.setattr(usuarios, "obtener_por_id", lambda uid: {"id": uid, "activo": True, "rol": "lector", "permisos": {}})
    r = _get(_token(rol="admin"))          # el token dice admin; la base manda
    assert r.status_code == 200 and r.json()["rol"] == "lector"


def test_base_caida_sin_cache_falla_cerrado(monkeypatch):
    def revienta(uid):
        raise RuntimeError("pool agotado")
    monkeypatch.setattr(usuarios, "obtener_por_id", revienta)
    assert _get(_token()).status_code == 503


def test_base_caida_con_lectura_reciente_deja_seguir(monkeypatch):
    monkeypatch.setattr(usuarios, "obtener_por_id", lambda uid: {"id": uid, "activo": True, "rol": "lector", "permisos": {}})
    assert _get(_token()).status_code == 200
    # la lectura buena queda en caché; la forzamos a "vieja" (>30 s, <15 min)
    security._USER_CACHE["u-borrado"]["ts"] -= 120

    def revienta(uid):
        raise RuntimeError("timeout")
    monkeypatch.setattr(usuarios, "obtener_por_id", revienta)
    r = _get(_token())
    assert r.status_code == 200 and r.json()["rol"] == "lector"


def test_renovacion_no_se_da_a_peticiones_rechazadas(monkeypatch):
    """El middleware solo entrega X-Token-Renovado si la petición pasó."""
    pytest.importorskip("pandas")   # backend.main importa todo el OS
    from backend import main
    monkeypatch.setattr(usuarios, "obtener_por_id", lambda uid: None)
    monkeypatch.setattr(security, "renovar_token_si_conviene", lambda t: "TOKEN-NUEVO")
    c = TestClient(main.app)
    r = c.get("/api/auth/me", headers={"Authorization": f"Bearer {_token()}"})
    assert r.status_code == 401
    assert "x-token-renovado" not in {k.lower() for k in r.headers}
