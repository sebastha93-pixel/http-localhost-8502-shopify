from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.api import postventa as api_postventa
from backend.core.security import get_current_user, CurrentUser


def _app(monkeypatch):
    app = FastAPI()
    app.include_router(api_postventa.router)
    # Bypass auth: usuario admin de prueba
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id="u1", email="t@t.com", nombre="Test", rol="admin", activo=True, permisos={}
    )
    return app


def test_listar_casos_endpoint(monkeypatch):
    monkeypatch.setattr(api_postventa.svc, "listar_casos",
                        lambda status=None: [{"id": "c1", "status": "creado"}])
    client = TestClient(_app(monkeypatch))
    r = client.get("/api/postventa/casos")
    assert r.status_code == 200
    assert r.json()[0]["id"] == "c1"


def test_crear_caso_endpoint(monkeypatch):
    monkeypatch.setattr(api_postventa.svc, "crear_caso",
                        lambda **k: {"id": "c9", "case_number": "PV-2026-0009", **k})
    monkeypatch.setattr(api_postventa.svc, "registrar_evento",
                        lambda *a, **k: {"id": "e1"})
    client = TestClient(_app(monkeypatch))
    r = client.post("/api/postventa/casos",
                    json={"tipo": "cambio_talla", "reason": "talla_pequena",
                          "customer_email": "a@b.com"})
    assert r.status_code == 200
    assert r.json()["case_number"] == "PV-2026-0009"
