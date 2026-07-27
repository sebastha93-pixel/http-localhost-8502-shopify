"""
Contrato del API del módulo Personal.

Cubre lo que no se ve en los tests de servicio: orden de rutas, aislamiento
por alcance y que el autoservicio no exija permiso de módulo.
"""
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ["TIME_MANAGEMENT_ENABLED"] = "true"

from backend.api import personal as api            # noqa: E402
from backend.core.security import CurrentUser, get_current_user  # noqa: E402


def _app(user: CurrentUser) -> TestClient:
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


ADMIN = CurrentUser(id="u-admin", email="admin@male.com", nombre="Admin", rol="admin")
EMPLEADO = CurrentUser(id="u-emp", email="emp@male.com", nombre="Emp", rol="user",
                       permisos={})
JEFE = CurrentUser(id="u-jefe", email="jefe@male.com", nombre="Jefe", rol="user",
                   permisos={"personal_permisos": ["ver", "modificar"]})
TECNICO = CurrentUser(id="u-tec", email="tec@male.com", nombre="Tec", rol="user",
                      permisos={"personal_dispositivos": ["ver", "modificar"]})


# ── Orden de rutas ───────────────────────────────────────────────────────────

def test_permisos_tipos_no_se_confunde_con_un_id(monkeypatch):
    """Bug clásico de FastAPI: /permisos/{id} declarado antes se comería
    /permisos/tipos y devolvería 404 buscando un permiso con id 'tipos'."""
    monkeypatch.setattr(api.perm_svc, "listar_tipos", lambda **k: [{"codigo": "LUTO"}])
    r = _app(EMPLEADO).get("/api/personal/permisos/tipos")
    assert r.status_code == 200
    assert r.json()["tipos"][0]["codigo"] == "LUTO"


def test_mi_tiempo_no_choca_con_otras_rutas(monkeypatch):
    monkeypatch.setattr(api.emp_svc, "obtener_por_usuario", lambda uid: None)
    r = _app(EMPLEADO).get("/api/personal/mi-tiempo/perfil")
    assert r.status_code == 200


# ── Autoservicio ─────────────────────────────────────────────────────────────

def test_mi_perfil_no_exige_permiso_de_modulo(monkeypatch):
    """El empleado sin ningún permiso debe poder ver lo suyo."""
    monkeypatch.setattr(api.emp_svc, "obtener_por_usuario",
                        lambda uid: {"id": "E1", "nombre_completo": "Ana",
                                     "sede_id": None, "area_id": None,
                                     "supervisor_id": None})
    r = _app(EMPLEADO).get("/api/personal/mi-tiempo/perfil")
    assert r.status_code == 200
    assert r.json()["aplica"] is True


def test_cuenta_que_no_es_empleado_recibe_aplica_false(monkeypatch):
    """Terceros y cuentas de servicio: no es un error, simplemente no aplica.

    Un 404 los mandaría a una pantalla roja por algo perfectamente normal.
    """
    monkeypatch.setattr(api.emp_svc, "obtener_por_usuario", lambda uid: None)
    r = _app(EMPLEADO).get("/api/personal/mi-tiempo/perfil")
    assert r.status_code == 200
    assert r.json()["aplica"] is False
    assert r.json()["empleado"] is None


def test_saldo_de_un_tercero_da_404_neutro(monkeypatch):
    monkeypatch.setattr(api.emp_svc, "obtener_por_usuario", lambda uid: None)
    r = _app(EMPLEADO).get("/api/personal/mi-tiempo/saldo")
    assert r.status_code == 404
    assert "no aplica" in r.json()["detail"]


# ── Aislamiento por alcance ──────────────────────────────────────────────────

def test_empleado_sin_permiso_no_lista_asistencia_ajena():
    r = _app(EMPLEADO).get("/api/personal/asistencia")
    assert r.status_code == 403


def test_tecnico_no_ve_permisos():
    """Separación de funciones: el admin técnico configura dispositivos,
    no aprueba permisos."""
    r = _app(TECNICO).get("/api/personal/permisos")
    assert r.status_code == 403


def test_jefe_solo_ve_su_alcance(monkeypatch):
    """El filtro del request no puede ampliar el alcance del rol."""
    todos = [{"id": "P1", "empleado_id": "E1"}, {"id": "P2", "empleado_id": "AJENO"}]
    monkeypatch.setattr(api.perm_svc, "listar",
                        lambda **k: [p for p in todos
                                     if k.get("empleados_permitidos") is None
                                     or p["empleado_id"] in k["empleados_permitidos"]])
    monkeypatch.setattr(api.emp_svc, "alcance_empleados", lambda u: ["E1"])

    r = _app(JEFE).get("/api/personal/permisos")
    assert r.status_code == 200
    ids = {p["empleado_id"] for p in r.json()["permisos"]}
    assert ids == {"E1"}


def test_no_se_puede_ver_permiso_fuera_del_alcance(monkeypatch):
    monkeypatch.setattr(api.perm_svc, "obtener",
                        lambda pid: {"id": pid, "empleado_id": "AJENO"})
    monkeypatch.setattr(api.emp_svc, "puede_ver_empleado", lambda u, e: False)
    r = _app(JEFE).get("/api/personal/permisos/P1")
    assert r.status_code == 403


def test_no_se_solicita_permiso_a_nombre_de_otro_sin_rol(monkeypatch):
    monkeypatch.setattr(api.emp_svc, "obtener_por_usuario",
                        lambda uid: {"id": "E1"})
    r = _app(EMPLEADO).post("/api/personal/permisos", json={
        "tipo_permiso_id": "T1", "inicio": "2026-08-03T08:00:00",
        "fin": "2026-08-03T10:00:00", "motivo": "cita",
        "empleado_id": "OTRO",
    })
    assert r.status_code == 403
    assert "nombre_de_otro" in r.json()["detail"]


def test_empleado_no_gestiona_solicitudes_ajenas(monkeypatch):
    monkeypatch.setattr(api.perm_svc, "obtener",
                        lambda pid: {"id": pid, "empleado_id": "AJENO"})
    monkeypatch.setattr(api.emp_svc, "obtener_por_usuario", lambda uid: {"id": "E1"})
    r = _app(EMPLEADO).post("/api/personal/permisos/P1/cancelar", json={})
    assert r.status_code == 403


# ── Recálculo forzado ────────────────────────────────────────────────────────

def test_forzar_recalculo_exige_permiso_de_borrar(monkeypatch):
    """Forzar salta el bloqueo de un periodo cerrado: es lo más cerca de
    reescribir historia que hay en el módulo."""
    supervisor = CurrentUser(id="u-th", email="th@male.com", nombre="TH", rol="user",
                             permisos={"personal_asistencia": ["ver", "modificar"]})
    r = _app(supervisor).post("/api/personal/asistencia/recalcular", json={
        "empleado_id": "E1", "desde": "2026-07-01", "forzar": True})
    assert r.status_code == 403
    assert "borrar" in r.json()["detail"]


def test_recalculo_normal_no_lo_exige(monkeypatch):
    monkeypatch.setattr(api.asis_svc, "recalcular_rango",
                        lambda *a, **k: {"recalculadas": 1, "omitidas": [], "errores": []})
    monkeypatch.setattr(api.aud, "registrar", lambda **k: None)
    th = CurrentUser(id="u-th", email="th@male.com", nombre="TH", rol="user",
                     permisos={"personal_asistencia": ["ver", "modificar"]})
    r = _app(th).post("/api/personal/asistencia/recalcular",
                      json={"empleado_id": "E1", "desde": "2026-07-01"})
    assert r.status_code == 200
    assert r.json()["recalculadas"] == 1


def test_recalculo_exige_empleado():
    r = _app(ADMIN).post("/api/personal/asistencia/recalcular",
                         json={"desde": "2026-07-01"})
    assert r.status_code == 400


@pytest.mark.parametrize("fecha", ["ayer", "2026-13-45", ""])
def test_fecha_invalida_da_400(fecha):
    r = _app(ADMIN).post("/api/personal/asistencia/recalcular",
                         json={"empleado_id": "E1", "desde": fecha})
    assert r.status_code in (400, 422)


# ── Validación de entrada ────────────────────────────────────────────────────

def test_motivo_muy_corto_se_rechaza(monkeypatch):
    monkeypatch.setattr(api.emp_svc, "obtener_por_usuario", lambda uid: {"id": "E1"})
    r = _app(EMPLEADO).post("/api/personal/permisos", json={
        "tipo_permiso_id": "T1", "inicio": "2026-08-03T08:00:00",
        "fin": "2026-08-03T10:00:00", "motivo": "x"})
    assert r.status_code == 422


def test_error_de_servicio_sale_como_400(monkeypatch):
    """Los ValueError con código snake_case llegan al cliente como 400."""
    def explota(**k):
        raise ValueError("permiso_legal_no_puede_ser_compensable")
    monkeypatch.setattr(api.emp_svc, "obtener_por_usuario", lambda uid: {"id": "E1"})
    monkeypatch.setattr(api.perm_svc, "crear", explota)
    r = _app(EMPLEADO).post("/api/personal/permisos", json={
        "tipo_permiso_id": "T1", "inicio": "2026-08-03T08:00:00",
        "fin": "2026-08-03T10:00:00", "motivo": "permiso personal"})
    assert r.status_code == 400
    assert r.json()["detail"] == "permiso_legal_no_puede_ser_compensable"


# ── Salud del módulo ─────────────────────────────────────────────────────────

def test_health_es_solo_admin():
    r = _app(JEFE).get("/api/personal/health")
    assert r.status_code == 403


def test_health_reporta_flags(monkeypatch):
    monkeypatch.setattr(api.org_svc, "listar_sedes", lambda **k: [])
    monkeypatch.setattr(api.org_svc, "listar_areas", lambda **k: [])
    monkeypatch.setattr(api.emp_svc, "listar", lambda **k: [])
    monkeypatch.setattr("backend.services.personal_base._sb", lambda: None)
    r = _app(ADMIN).get("/api/personal/health")
    assert r.status_code == 200
    assert r.json()["flags"]["TIME_MANAGEMENT_ENABLED"] is True
