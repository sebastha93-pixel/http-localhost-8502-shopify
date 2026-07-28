"""
Planificación de turnos rotativos.

Lo que más importa: que el cálculo de horas semanales sea correcto, porque de
ahí sale el aviso de exceder el tope legal de 42 h. Un aviso que no aparece
cuando debe es peor que no tenerlo.
"""
from datetime import date

import pytest
from unittest.mock import MagicMock

from backend.services import personal_turnos as svc


# ── Minutos de un turno ──────────────────────────────────────────────────────

def test_turno_simple():
    assert svc._minutos("11:00", "20:00") == 540          # 9 h


def test_turno_con_descanso():
    assert svc._minutos("09:00", "17:00", "13:00", "13:30") == 450   # 8 h − 30 min


def test_turno_que_cruza_medianoche():
    assert svc._minutos("22:00", "06:00", cruza=True) == 480


def test_turno_sin_bandera_pero_fin_menor_se_asume_nocturno():
    """Defensa: si el fin es menor que el inicio, solo puede ser nocturno."""
    assert svc._minutos("22:00", "06:00") == 480


def test_turno_sin_horas_es_cero():
    assert svc._minutos(None, "20:00") == 0
    assert svc._minutos("11:00", None) == 0


# ── Semana laboral ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("f,esperado", [
    (date(2026, 7, 28), date(2026, 7, 27)),   # martes → lunes
    (date(2026, 7, 27), date(2026, 7, 27)),   # lunes → él mismo
    (date(2026, 8, 2),  date(2026, 7, 27)),   # domingo → lunes de esa semana
])
def test_lunes_de(f, esperado):
    assert svc.lunes_de(f) == esperado


# ── Resumen semanal y tope legal ─────────────────────────────────────────────

def _turno(emp, dia, ini, fin, minutos):
    return {"empleado_id": emp, "fecha": f"2026-07-{dia:02d}",
            "hora_inicio": ini, "hora_fin": fin, "minutos_esperados": minutos}


def test_suma_horas_de_la_semana(monkeypatch):
    monkeypatch.setattr(svc, "listar", lambda **k: [
        _turno("E1", 27, "11:00", "20:00", 540),
        _turno("E1", 28, "11:00", "20:00", 540),
        _turno("E1", 29, "11:00", "20:00", 540),
    ])
    s = svc.semana(lunes=date(2026, 7, 27))
    assert s["por_empleado"]["E1"]["horas"] == 27.0
    assert s["por_empleado"]["E1"]["excede_tope"] is False


def test_avisa_cuando_excede_el_tope(monkeypatch):
    """5 turnos de 9 h = 45 h: 3 sobre el tope de 42."""
    monkeypatch.setattr(svc, "listar", lambda **k: [
        _turno("E1", d, "11:00", "20:00", 540) for d in range(27, 32)
    ])
    s = svc.semana(lunes=date(2026, 7, 27))
    e = s["por_empleado"]["E1"]
    assert e["horas"] == 45.0
    assert e["excede_tope"] is True
    assert e["minutos_sobre_tope"] == 180


def test_justo_en_el_tope_no_avisa(monkeypatch):
    """42 h exactas están dentro de la ley. El aviso es por EXCEDER."""
    monkeypatch.setattr(svc, "listar", lambda **k: [
        _turno("E1", 27, "11:00", "20:00", 42 * 60),
    ])
    assert svc.semana(lunes=date(2026, 7, 27))["por_empleado"]["E1"]["excede_tope"] is False


def test_la_semana_trae_los_siete_dias(monkeypatch):
    monkeypatch.setattr(svc, "listar", lambda **k: [])
    s = svc.semana(lunes=date(2026, 7, 27))
    assert s["dias"] == [f"2026-07-{d}" for d in range(27, 32)] + \
                        ["2026-08-01", "2026-08-02"]
    assert s["domingo"] == "2026-08-02"


def test_filtra_por_alcance(monkeypatch):
    """Un jefe solo debe ver la grilla de su equipo."""
    monkeypatch.setattr(svc, "listar", lambda **k: [
        _turno("E1", 27, "11:00", "20:00", 540),
        _turno("AJENO", 27, "11:00", "20:00", 540),
    ])
    s = svc.semana(lunes=date(2026, 7, 27), empleados=["E1"])
    assert set(s["por_empleado"]) == {"E1"}


# ── Validación al guardar ────────────────────────────────────────────────────

def test_turno_laboral_exige_horas():
    with pytest.raises(ValueError, match="turno_laboral_requiere_horas"):
        svc.guardar(empleado_id="E1", fecha=date(2026, 7, 28),
                    hora_inicio=None, hora_fin=None)


class FakeSB:
    def __init__(self): self.upserted = []
    def table(self, n): self._t = n; return self
    def upsert(self, d, **k): self.upserted.append(d); self._p = d; return self
    def delete(self): self._p = None; return self
    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def gte(self, *a, **k): return self
    def lte(self, *a, **k): return self
    def order(self, *a, **k): return self
    def limit(self, *a, **k): return self
    def execute(self):
        r = MagicMock(); p = getattr(self, "_p", None)
        r.data = [p] if p else []; return r


@pytest.fixture
def sb(monkeypatch):
    f = FakeSB()
    monkeypatch.setattr(svc, "sb_requerido", lambda: f)
    monkeypatch.setattr(svc, "_sb", lambda: f)
    monkeypatch.setattr(svc.aud, "registrar", lambda **k: None)
    monkeypatch.setattr(svc, "_recalcular", lambda *a: None)
    return f


def test_guardar_calcula_los_minutos(sb):
    svc.guardar(empleado_id="E1", fecha=date(2026, 7, 28),
                hora_inicio="11:00", hora_fin="20:00")
    assert sb.upserted[0]["minutos_esperados"] == 540


def test_dia_de_descanso_planificado(sb):
    """Marcar descanso NO es lo mismo que no tener turno.

    El primero dice 'hoy descansa'; el segundo, 'nadie planificó este día'.
    """
    svc.guardar(empleado_id="E1", fecha=date(2026, 7, 28),
                hora_inicio=None, hora_fin=None, es_dia_laboral=False)
    g = sb.upserted[0]
    assert g["es_dia_laboral"] is False
    assert g["minutos_esperados"] == 0
    assert g["hora_inicio"] is None


def test_guardar_semana_reporta_errores_sin_abortar(sb, monkeypatch):
    """Un turno malo no debe tumbar los otros seis."""
    monkeypatch.setattr(svc, "semana",
                        lambda **k: {"por_empleado": {}})
    r = svc.guardar_semana([
        {"empleado_id": "E1", "fecha": "2026-07-28",
         "hora_inicio": "11:00", "hora_fin": "20:00"},
        {"empleado_id": "E2", "fecha": "2026-07-28"},          # sin horas
    ])
    assert r["guardados"] == 1
    assert len(r["errores"]) == 1
    assert "requiere_horas" in r["errores"][0]["error"]


def test_guardar_semana_avisa_del_exceso(sb, monkeypatch):
    monkeypatch.setattr(svc, "semana", lambda **k: {"por_empleado": {
        "E1": {"horas": 48.0, "excede_tope": True, "minutos_sobre_tope": 360}}})
    r = svc.guardar_semana([{"empleado_id": "E1", "fecha": "2026-07-28",
                             "hora_inicio": "11:00", "hora_fin": "20:00"}])
    assert len(r["avisos"]) == 1
    assert "48.0 h" in r["avisos"][0]["aviso"]
    assert "42 h" in r["avisos"][0]["aviso"]


def test_el_aviso_no_bloquea_el_guardado(sb, monkeypatch):
    """Avisar no es impedir: a veces hay una razón para una semana larga."""
    monkeypatch.setattr(svc, "semana", lambda **k: {"por_empleado": {
        "E1": {"horas": 50.0, "excede_tope": True, "minutos_sobre_tope": 480}}})
    r = svc.guardar_semana([{"empleado_id": "E1", "fecha": "2026-07-28",
                             "hora_inicio": "11:00", "hora_fin": "21:00"}])
    assert r["guardados"] == 1
    assert r["avisos"]


# ── Copiar semana ────────────────────────────────────────────────────────────

def test_copiar_desplaza_las_fechas(sb, monkeypatch):
    monkeypatch.setattr(svc, "listar", lambda **k: [
        {"empleado_id": "E1", "fecha": "2026-07-27",
         "hora_inicio": "11:00", "hora_fin": "20:00", "es_dia_laboral": True},
    ])
    capturado = {}
    monkeypatch.setattr(svc, "guardar_semana",
                        lambda t, **k: capturado.update(turnos=t) or {"guardados": len(t)})
    svc.copiar_semana(origen=date(2026, 7, 27), destino=date(2026, 8, 3))
    assert capturado["turnos"][0]["fecha"] == "2026-08-03"


def test_copiar_a_la_misma_semana_se_rechaza(sb):
    with pytest.raises(ValueError, match="misma"):
        svc.copiar_semana(origen=date(2026, 7, 27), destino=date(2026, 7, 29))


def test_copiar_semana_vacia_se_rechaza(sb, monkeypatch):
    monkeypatch.setattr(svc, "listar", lambda **k: [])
    with pytest.raises(ValueError, match="no_tiene_turnos"):
        svc.copiar_semana(origen=date(2026, 7, 20), destino=date(2026, 7, 27))


# ── El tope legal está donde debe ────────────────────────────────────────────

def test_el_tope_es_42_horas():
    """Ley 2101 de 2021, etapa vigente desde el 15 de julio de 2026.

    Si cambia la ley este test falla y obliga a revisar también
    personal_reglas y la documentación.
    """
    assert svc.TOPE_SEMANAL_MIN == 42 * 60
