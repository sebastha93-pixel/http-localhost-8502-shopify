"""
Empleados, jerarquía y alcance de datos.

El test más importante de este archivo es `test_empleado_solo_se_ve_a_si_mismo`:
sin RLS en Supabase, `alcance_empleados()` es lo único que impide que alguien
lea la asistencia de otra persona.
"""
import pytest
from unittest.mock import MagicMock

from backend.services import personal_base as base
from backend.services import personal_empleados as svc


def setup_function():
    base.cache_invalidar()


class FakeUser:
    """Mock de CurrentUser."""
    def __init__(self, id="u1", rol="user", permisos=None, email="x@male.com"):
        self.id = id
        self.rol = rol
        self.permisos = permisos or {}
        self.email = email
        self.activo = True
        self.nombre = "Test"
        self.cargo = ""


def _emp(id, nombre="Alguien", supervisor_id=None, usuario_id=None):
    return {"id": id, "nombre_completo": nombre, "supervisor_id": supervisor_id,
            "usuario_id": usuario_id, "codigo_empleado": f"EMP-{id}",
            "numero_documento": "1234567890", "estado_laboral": "activo"}


# ── Validación ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("campo", ["nombre_completo", "numero_documento", "fecha_ingreso"])
def test_crear_exige_campos_minimos(campo):
    datos = {"nombre_completo": "Ana", "numero_documento": "123",
             "fecha_ingreso": "2026-01-01"}
    datos[campo] = ""
    with pytest.raises(ValueError, match=f"campo_requerido:{campo}"):
        svc._validar(datos, creando=True)


def test_rechaza_tipo_documento_invalido():
    with pytest.raises(ValueError, match="tipo_documento_invalido"):
        svc._validar({"tipo_documento": "XX"}, creando=False)


def test_rechaza_tipo_contrato_invalido():
    with pytest.raises(ValueError, match="tipo_contrato_invalido"):
        svc._validar({"tipo_contrato": "por_ahi"}, creando=False)


def test_rechaza_estado_laboral_invalido():
    with pytest.raises(ValueError, match="estado_laboral_invalido"):
        svc._validar({"estado_laboral": "de_paseo"}, creando=False)


def test_rechaza_email_malformado():
    with pytest.raises(ValueError, match="email_invalido"):
        svc._validar({"email": "no-es-email"}, creando=False)


def test_acepta_email_vacio():
    svc._validar({"email": ""}, creando=False)          # no lanza


def test_retirar_exige_fecha_de_retiro():
    """Sin fecha de retiro no se sabe hasta cuándo calcularle asistencia."""
    with pytest.raises(ValueError, match="fecha_retiro_requerida"):
        svc._validar({"estado_laboral": "retirado"}, creando=False)

    svc._validar({"estado_laboral": "retirado",
                  "fecha_retiro": "2026-07-31"}, creando=False)   # no lanza


# ── Consecutivo ──────────────────────────────────────────────────────────────

def test_codigo_empleado_correlativo(monkeypatch):
    monkeypatch.setattr(svc, "listar", lambda **k: [
        {"codigo_empleado": "EMP-0001"}, {"codigo_empleado": "EMP-0007"},
    ])
    assert svc._siguiente_codigo() == "EMP-0008"


def test_codigo_empleado_primero(monkeypatch):
    monkeypatch.setattr(svc, "listar", lambda **k: [])
    assert svc._siguiente_codigo() == "EMP-0001"


def test_codigo_empleado_ignora_formatos_raros(monkeypatch):
    monkeypatch.setattr(svc, "listar", lambda **k: [
        {"codigo_empleado": "EMP-0003"}, {"codigo_empleado": "VIEJO-X"},
        {"codigo_empleado": None}, {"codigo_empleado": "EMP-abc"},
    ])
    assert svc._siguiente_codigo() == "EMP-0004"


# ── Jerarquía ────────────────────────────────────────────────────────────────

ORGANIGRAMA = [
    _emp("jefe"),
    _emp("a", supervisor_id="jefe"),
    _emp("b", supervisor_id="jefe"),
    _emp("a1", supervisor_id="a"),          # nieto
    _emp("suelto"),
]


def test_equipo_directos(monkeypatch):
    monkeypatch.setattr(svc, "listar", lambda **k: ORGANIGRAMA)
    assert set(svc.equipo_de("jefe", incluir_indirectos=False)) == {"a", "b"}


def test_equipo_incluye_indirectos(monkeypatch):
    monkeypatch.setattr(svc, "listar", lambda **k: ORGANIGRAMA)
    assert set(svc.equipo_de("jefe")) == {"a", "b", "a1"}


def test_equipo_de_hoja_es_vacio(monkeypatch):
    monkeypatch.setattr(svc, "listar", lambda **k: ORGANIGRAMA)
    assert svc.equipo_de("suelto") == []


def test_equipo_no_se_cuelga_con_ciclo(monkeypatch):
    """Si un ciclo llegara a la base de datos, equipo_de debe terminar igual.

    Sin el conjunto `vistos`, esto colgaría el worker.
    """
    ciclico = [_emp("x", supervisor_id="y"), _emp("y", supervisor_id="x")]
    monkeypatch.setattr(svc, "listar", lambda **k: ciclico)
    resultado = svc.equipo_de("x")
    assert "y" in resultado
    assert len(resultado) <= 2


def test_no_puede_ser_su_propio_jefe(monkeypatch):
    monkeypatch.setattr(svc, "obtener", lambda i: _emp(i))
    monkeypatch.setattr(svc, "listar", lambda **k: ORGANIGRAMA)
    with pytest.raises(ValueError, match="su_propio_jefe"):
        svc.actualizar("a", supervisor_id="a")


def test_rechaza_ciclo_en_jerarquia(monkeypatch):
    """El jefe no puede quedar como subordinado de su propio subordinado."""
    monkeypatch.setattr(svc, "obtener", lambda i: _emp(i))
    monkeypatch.setattr(svc, "listar", lambda **k: ORGANIGRAMA)
    with pytest.raises(ValueError, match="ciclo_en_jerarquia"):
        svc.actualizar("jefe", supervisor_id="a1")


# ── Alcance de datos — la frontera de seguridad ──────────────────────────────

def test_admin_ve_todo(monkeypatch):
    assert svc.alcance_empleados(FakeUser(rol="admin")) is None


def test_talento_humano_ve_todo(monkeypatch):
    monkeypatch.setattr(svc, "listar", lambda **k: ORGANIGRAMA)
    th = FakeUser(permisos={"personal": ["ver", "modificar"]})
    assert svc.alcance_empleados(th) is None


def test_jefe_ve_su_equipo_y_a_si_mismo(monkeypatch):
    monkeypatch.setattr(svc, "listar", lambda **k: ORGANIGRAMA)
    monkeypatch.setattr(svc, "obtener_por_usuario",
                        lambda uid: _emp("jefe", usuario_id=uid))
    jefe = FakeUser(id="u-jefe", permisos={"personal_permisos": ["ver", "modificar"]})
    alcance = svc.alcance_empleados(jefe)
    assert alcance is not None
    assert set(alcance) == {"jefe", "a", "b", "a1"}


def test_empleado_solo_se_ve_a_si_mismo(monkeypatch):
    """LA prueba crítica del módulo.

    Sin RLS, si alcance_empleados devolviera None o incluyera a otros, un
    empleado podría leer la asistencia de toda la empresa cambiando un id.
    """
    monkeypatch.setattr(svc, "listar", lambda **k: ORGANIGRAMA)
    monkeypatch.setattr(svc, "obtener_por_usuario",
                        lambda uid: _emp("a", usuario_id=uid))
    empleado = FakeUser(id="u-a", permisos={})
    assert svc.alcance_empleados(empleado) == ["a"]


def test_usuario_sin_empleado_no_ve_nada(monkeypatch):
    """[] y None son opuestos: [] = ninguno, None = todos."""
    monkeypatch.setattr(svc, "obtener_por_usuario", lambda uid: None)
    assert svc.alcance_empleados(FakeUser(permisos={})) == []


def test_puede_ver_empleado_respeta_alcance(monkeypatch):
    monkeypatch.setattr(svc, "listar", lambda **k: ORGANIGRAMA)
    monkeypatch.setattr(svc, "obtener_por_usuario",
                        lambda uid: _emp("a", usuario_id=uid))
    empleado = FakeUser(id="u-a", permisos={})
    assert svc.puede_ver_empleado(empleado, "a") is True
    assert svc.puede_ver_empleado(empleado, "b") is False
    assert svc.puede_ver_empleado(FakeUser(rol="admin"), "b") is True


# ── Enmascaramiento en listados ──────────────────────────────────────────────

def test_listado_publico_enmascara_documento():
    salida = svc.para_listado_publico(_emp("a"))
    assert salida["numero_documento"] == "···7890"
    assert salida["nombre_completo"] == "Alguien"


def test_listado_publico_tolera_vacio():
    assert svc.para_listado_publico({}) == {}


# ── Degradación sin migración ────────────────────────────────────────────────

def test_listar_sin_supabase_devuelve_vacio(monkeypatch):
    monkeypatch.setattr(svc, "_sb", lambda: None)
    assert svc.listar() == []


def test_listar_sin_tabla_devuelve_vacio(monkeypatch):
    """Con la migración sin aplicar, la UI debe mostrarse vacía, no reventar."""
    class SinTabla:
        def table(self, n): return self
        def select(self, *a, **k): return self
        def order(self, *a, **k): return self
        def limit(self, *a, **k): return self
        def execute(self):
            raise Exception('relation "personal_empleados" does not exist')

    monkeypatch.setattr(svc, "_sb", lambda: SinTabla())
    assert svc.listar() == []
