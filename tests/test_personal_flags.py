"""
Feature flags del módulo Personal.

El repo tenía tres formas distintas de parsear flags y una estaba rota:
`BOT_AUTO_ENABLED=1` no activaba nada porque comparaba con "true" exacto.
Estos tests fijan que eso no vuelva a pasar.
"""
import pytest

from backend.core import flags


# ── Formas de decir "sí" ─────────────────────────────────────────────────────

@pytest.mark.parametrize("valor", [
    "1", "true", "TRUE", "True", "yes", "YES", "y", "on", "ON", "si", "sí",
    "  true  ",          # con espacios: Railway a veces los deja al pegar
])
def test_valores_verdaderos(monkeypatch, valor):
    monkeypatch.setenv("X_TEST_FLAG", valor)
    assert flags.flag("X_TEST_FLAG") is True


@pytest.mark.parametrize("valor", ["0", "false", "FALSE", "no", "n", "off", "OFF"])
def test_valores_falsos(monkeypatch, valor):
    monkeypatch.setenv("X_TEST_FLAG", valor)
    # default=True para probar que el valor gana sobre el default
    assert flags.flag("X_TEST_FLAG", default=True) is False


def test_el_caso_que_estaba_roto(monkeypatch):
    """`=1` DEBE activar. Es la forma más común de poner un flag a mano."""
    monkeypatch.setenv("X_TEST_FLAG", "1")
    assert flags.flag("X_TEST_FLAG") is True


# ── Defaults y valores raros ─────────────────────────────────────────────────

def test_variable_ausente_usa_default(monkeypatch):
    monkeypatch.delenv("X_TEST_FLAG", raising=False)
    assert flags.flag("X_TEST_FLAG") is False
    assert flags.flag("X_TEST_FLAG", default=True) is True


def test_valor_vacio_usa_default(monkeypatch):
    monkeypatch.setenv("X_TEST_FLAG", "")
    assert flags.flag("X_TEST_FLAG", default=True) is True


def test_typo_no_activa(monkeypatch):
    """Un typo NO debe activar un módulo entero. Ante la duda, el default."""
    monkeypatch.setenv("X_TEST_FLAG", "ture")
    assert flags.flag("X_TEST_FLAG") is False
    # Y tampoco debe DESactivar algo que estaba encendido por default
    assert flags.flag("X_TEST_FLAG", default=True) is True


# ── Jerarquía de los flags del módulo ────────────────────────────────────────

def test_modulo_apagado_por_defecto(monkeypatch):
    for f in flags.FLAGS_PERSONAL:
        monkeypatch.delenv(f, raising=False)
    assert flags.personal_habilitado() is False


def test_subflags_requieren_el_flag_principal(monkeypatch):
    """Activar el conector con el módulo apagado no debe habilitar nada.

    Si no fuera jerárquico, alguien podría dejar DAHUA_CONNECTOR_ENABLED=true
    y creer que el conector funciona mientras el módulo está apagado.
    """
    monkeypatch.setenv("TIME_MANAGEMENT_ENABLED", "false")
    monkeypatch.setenv("DAHUA_CONNECTOR_ENABLED", "true")
    monkeypatch.setenv("PAYROLL_EXPORT_ENABLED", "true")
    monkeypatch.setenv("TIME_MANAGEMENT_AI_INSIGHTS_ENABLED", "true")

    assert flags.conector_dahua_habilitado() is False
    assert flags.export_nomina_habilitado() is False
    assert flags.ia_personal_habilitada() is False


def test_subflags_con_modulo_activo(monkeypatch):
    monkeypatch.setenv("TIME_MANAGEMENT_ENABLED", "true")
    monkeypatch.setenv("DAHUA_CONNECTOR_ENABLED", "1")
    monkeypatch.delenv("PAYROLL_EXPORT_ENABLED", raising=False)

    assert flags.personal_habilitado() is True
    assert flags.conector_dahua_habilitado() is True
    # No basta con que el módulo esté activo: cada subflag es opt-in aparte.
    assert flags.export_nomina_habilitado() is False


def test_flags_activos_reporta_todos(monkeypatch):
    monkeypatch.setenv("TIME_MANAGEMENT_ENABLED", "true")
    monkeypatch.delenv("DAHUA_CONNECTOR_ENABLED", raising=False)
    estado = flags.flags_activos(*flags.FLAGS_PERSONAL)
    assert estado["TIME_MANAGEMENT_ENABLED"] is True
    assert estado["DAHUA_CONNECTOR_ENABLED"] is False
    assert len(estado) == 4
