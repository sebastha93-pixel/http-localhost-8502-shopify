"""Token de servicio de la Oficina Virtual (auditoría de seguridad 2026-11-08, Oficina #26a).

Antes el motor de la Oficina firmaba su propio token con AUTH_JWT_SECRET y «rol: admin»:
quien comprometiera el motor era admin de todo el OS. Además, desde el 10-nov (sesión revalidada
contra la base) ese token ya no entraba: su `sub` no es un usuario y el OS respondía 503, así
que las herramientas de Producción, Financiero y Logística llevaban días sin datos.

Ahora hay un token de servicio firmado con OFICINA_SERVICIO_SECRET (otro secreto) que solo abre
los endpoints que usa el motor. Se prueba con una app mínima y las dependencias REALES de
seguridad, sin importar backend.api.produccion (en el .venv local falta python-multipart).
"""
import time

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from backend.core import security
from backend.core.config import settings
from backend.core.security import (
    CurrentUser,
    SERVICIO_AUD,
    SERVICIO_SUB,
    create_access_token,
    get_current_user,
    require_permission_any,
    require_permission_estricto,
    require_role,
)
from backend.services import usuarios

SERVICIO = "secreto-de-servicio-de-prueba-0123456789abcdef"


def _app() -> TestClient:
    app = FastAPI()

    @app.get("/api/produccion/costeo-real")
    def costeo(_: CurrentUser = Depends(require_permission_estricto("produccion_costos", "ver"))):
        return {"ok": True}

    @app.post("/api/produccion/rutas/{ruta_id}/notas")
    def nota(ruta_id: str, u: CurrentUser = Depends(require_permission_any(
            ("produccion_remisiones", "produccion_cortador"), "modificar"))):
        return {"ok": True, "autor": u.email}

    @app.delete("/api/produccion/rutas/{ruta_id}/notas")
    def borrar_nota(ruta_id: str, _: CurrentUser = Depends(get_current_user)):
        return {"ok": True}

    @app.get("/api/finanzas/resumen")
    def finanzas(_: CurrentUser = Depends(get_current_user)):
        return {"ok": True}

    @app.get("/api/dashboard/overview")
    def overview(_: CurrentUser = Depends(get_current_user)):
        return {"ok": True}

    @app.get("/api/melonn/pedidos")
    def pedidos(_: CurrentUser = Depends(get_current_user)):
        return {"ok": True}

    @app.get("/api/usuarios")
    def usuarios_admin(_: CurrentUser = Depends(require_role("admin"))):
        return {"ok": True}

    @app.get("/api/produccion/costeo-real-extra")
    def parecida(_: CurrentUser = Depends(get_current_user)):
        return {"ok": True}

    return TestClient(app)


def _servicio(**cambios) -> dict:
    ahora = int(time.time())
    datos = {"sub": SERVICIO_SUB, "aud": SERVICIO_AUD, "iat": ahora, "exp": ahora + 300}
    datos.update(cambios)
    secreto = datos.pop("_secreto", SERVICIO)
    datos = {k: v for k, v in datos.items() if v is not None}
    return {"Authorization": "Bearer " + jwt.encode(datos, secreto, algorithm="HS256")}


@pytest.fixture(autouse=True)
def configurado(monkeypatch):
    monkeypatch.setattr(settings, "oficina_servicio_secret", SERVICIO)
    security._USER_CACHE.clear()
    monkeypatch.setattr(usuarios, "_sb", lambda: object())       # "hay Supabase"
    monkeypatch.setattr(usuarios, "obtener_por_id", lambda uid: None)  # nadie existe
    yield
    security._USER_CACHE.clear()


# ------------------------------------------------------------- lo que sí abre
@pytest.mark.parametrize("metodo,ruta", [
    ("GET", "/api/produccion/costeo-real"),
    ("POST", "/api/produccion/rutas/r-123/notas"),
    ("GET", "/api/finanzas/resumen"),
    ("GET", "/api/dashboard/overview"),
    ("GET", "/api/melonn/pedidos"),
])
def test_el_token_de_servicio_abre_los_endpoints_del_motor(metodo, ruta):
    r = _app().request(metodo, ruta, headers=_servicio(), json={"mensaje": "x"} if metodo == "POST" else None)
    assert r.status_code == 200, r.text


def test_la_nota_queda_firmada_por_la_oficina():
    r = _app().post("/api/produccion/rutas/r-1/notas", headers=_servicio(), json={"mensaje": "x"})
    assert r.json()["autor"] == "oficina@maledenim.com"


# ------------------------------------------------------------ lo que no abre
@pytest.mark.parametrize("metodo,ruta", [
    ("GET", "/api/usuarios"),                               # admin
    ("DELETE", "/api/produccion/rutas/r-123/notas"),        # método fuera de la lista
    ("GET", "/api/produccion/costeo-real-extra"),           # ruta parecida
])
def test_fuera_de_la_lista_el_token_de_servicio_da_403(metodo, ruta):
    assert _app().request(metodo, ruta, headers=_servicio()).status_code == 403


@pytest.mark.parametrize("cambios", [
    {"_secreto": "otro-secreto-cualquiera-0123456789abcdef"},  # firmado con otro secreto
    {"aud": "authenticated"},                                  # otra audiencia
    {"aud": None},                                             # sin audiencia
    {"exp": None},                                             # sin vencimiento
    {"exp": int(time.time()) - 60},                            # vencido
    {"sub": "oficina-produccion"},                             # otro sub
])
def test_un_token_de_servicio_alterado_no_entra(cambios):
    assert _app().get("/api/finanzas/resumen", headers=_servicio(**cambios)).status_code == 401


def test_sin_secreto_configurado_el_token_de_servicio_no_se_acepta(monkeypatch):
    monkeypatch.setattr(settings, "oficina_servicio_secret", "")
    assert _app().get("/api/finanzas/resumen", headers=_servicio()).status_code == 401


def test_el_secreto_de_servicio_no_firma_sesiones_de_persona():
    """Un token «de persona» (rol admin) firmado con el secreto de servicio no vale."""
    t = jwt.encode({"sub": "u-1", "email": "x@x.co", "nombre": "X", "rol": "admin",
                    "permisos": {}, "exp": int(time.time()) + 300}, SERVICIO, algorithm="HS256")
    r = _app().get("/api/usuarios", headers={"Authorization": f"Bearer {t}"})
    assert r.status_code == 401


# ---------------------------------------------------- las personas, igual que antes
def test_las_sesiones_de_persona_siguen_funcionando(monkeypatch):
    monkeypatch.setattr(usuarios, "obtener_por_id",
                        lambda uid: {"id": uid, "activo": True, "rol": "admin", "permisos": {}})
    t = create_access_token(CurrentUser(id="u-1", email="s@x.co", nombre="S", rol="admin"))
    r = _app().get("/api/usuarios", headers={"Authorization": f"Bearer {t}"})
    assert r.status_code == 200


def test_el_token_viejo_de_la_oficina_con_rol_admin_no_entra():
    """El que firmaba el motor con AUTH_JWT_SECRET: su sub no es un usuario."""
    ahora = int(time.time())
    t = jwt.encode({"sub": "oficina-produccion", "email": "oficina@maledenim.com",
                    "nombre": "Jefe de Producción IA", "rol": "admin", "permisos": {},
                    "iat": ahora, "exp": ahora + 300}, settings.auth_jwt_secret, algorithm="HS256")
    r = _app().get("/api/usuarios", headers={"Authorization": f"Bearer {t}"})
    assert r.status_code == 401
