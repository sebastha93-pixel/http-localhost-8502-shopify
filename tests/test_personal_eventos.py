"""
Ingesta de eventos del control de acceso.

Lo que protegen estos tests: que reenviar un lote no duplique, que un evento
sin mapear NO se pierda, y que el hecho sea inmutable.
"""
from datetime import datetime, timedelta

import pytest
from unittest.mock import MagicMock

from backend.services import personal_eventos as svc


class FakeSB:
    """Mock encadenable del cliente supabase, al estilo de test_postventa_service."""
    def __init__(self, data=None):
        self.inserted, self.upserted, self.updated = [], [], []
        self._data = data or []
        self._tabla = None

    def table(self, n):
        self._tabla = n
        return self

    def insert(self, d):
        self.inserted.append((self._tabla, d))
        self._payload = d
        return self

    def upsert(self, d, **k):
        self.upserted.append((self._tabla, d, k))
        self._payload = d
        return self

    def update(self, d):
        self.updated.append((self._tabla, d))
        self._payload = d
        return self

    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def gte(self, *a, **k): return self
    def lte(self, *a, **k): return self
    def in_(self, *a, **k): return self
    def is_(self, *a, **k): return self
    def order(self, *a, **k): return self
    def limit(self, *a, **k): return self

    def execute(self):
        r = MagicMock()
        p = getattr(self, "_payload", None)
        r.data = p if isinstance(p, list) else ([p] if p else self._data)
        self._payload = None
        return r


def _ev(hhmm="08:00", ext="1001", direccion="entrada", eid=None, dia="2026-07-27"):
    return {
        "id_evento_externo": eid,
        "id_externo_empleado": ext,
        "event_timestamp": f"{dia}T{hhmm}:00-05:00",
        "direccion_acceso": direccion,
    }


# ── Hash de idempotencia ─────────────────────────────────────────────────────

def test_hash_es_determinista():
    a = svc.calcular_hash({"id_externo_empleado": "1", "event_timestamp": "x",
                           "direccion_acceso": "entrada"})
    b = svc.calcular_hash({"direccion_acceso": "entrada", "event_timestamp": "x",
                           "id_externo_empleado": "1"})
    assert a == b, "el orden de las claves no debe cambiar el hash"


def test_hash_cambia_con_el_hecho():
    a = svc.calcular_hash({"id_externo_empleado": "1", "event_timestamp": "08:00"})
    b = svc.calcular_hash({"id_externo_empleado": "1", "event_timestamp": "08:01"})
    assert a != b


def test_hash_ignora_metadatos_de_transporte():
    """Reenviar el mismo hecho con otro `received_at` sigue siendo el mismo hecho."""
    base = {"id_externo_empleado": "1", "event_timestamp": "08:00",
            "direccion_acceso": "entrada"}
    a = svc.calcular_hash({**base, "received_at": "10:00", "reintento": 1})
    b = svc.calcular_hash({**base, "received_at": "11:00", "reintento": 5})
    assert a == b


# ── Normalización ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("crudo,esperado", [
    ("in", "entrada"), ("IN", "entrada"), ("entry", "entrada"), ("ingreso", "entrada"),
    ("out", "salida"), ("exit", "salida"), ("egreso", "salida"),
    ("cualquier_cosa", "desconocida"),
])
def test_normaliza_direccion(crudo, esperado):
    f = svc._normalizar({**_ev(), "direccion_acceso": crudo})
    assert f["direccion_acceso"] == esperado


@pytest.mark.parametrize("crudo,esperado", [
    ("granted", "concedido"), ("success", "concedido"),
    ("denied", "denegado"), ("failed", "denegado"),
])
def test_normaliza_resultado(crudo, esperado):
    f = svc._normalizar({**_ev(), "resultado_acceso": crudo})
    assert f["resultado_acceso"] == esperado


def test_normaliza_timestamp_con_fraccion_recortada():
    """El caso que motivó timeutils: Postgres devuelve 5 dígitos de fracción."""
    f = svc._normalizar({**_ev(), "event_timestamp": "2026-07-27T08:00:19.14254+00:00"})
    assert f["event_timestamp"].startswith("2026-07-27T08:00:19")


def test_timestamp_invalido_es_error():
    with pytest.raises(ValueError, match="event_timestamp_invalido"):
        svc._normalizar({"id_externo_empleado": "1", "event_timestamp": "no-es-fecha"})


def test_conserva_el_payload_original():
    """INVARIANTE 1: el hecho original se guarda completo, aunque no lo entendamos."""
    crudo = {**_ev(), "campo_raro_del_dahua": {"x": 1}}
    f = svc._normalizar(crudo)
    assert f["raw_payload_json"]["campo_raro_del_dahua"] == {"x": 1}


# ── Ingesta ──────────────────────────────────────────────────────────────────

def test_ingesta_basica(monkeypatch):
    fake = FakeSB()
    monkeypatch.setattr(svc, "sb_requerido", lambda: fake)
    monkeypatch.setattr(svc, "_sb", lambda: fake)
    monkeypatch.setattr(svc, "_mapa_externo", lambda d: {"1001": "EMP-1"})

    r = svc.ingerir(dispositivo_id="D1", eventos=[_ev("08:00"), _ev("18:00", direccion="salida")])
    assert r["recibidos"] == 2
    assert r["sin_mapeo"] == 0


def test_evento_sin_mapeo_se_guarda_igual(monkeypatch):
    """LA regla: un evento nunca se descarta. Es la marcación de una persona real."""
    fake = FakeSB()
    monkeypatch.setattr(svc, "sb_requerido", lambda: fake)
    monkeypatch.setattr(svc, "_sb", lambda: fake)
    monkeypatch.setattr(svc, "_mapa_externo", lambda d: {})
    monkeypatch.setattr(svc, "_incidencias_desconocido", lambda *a: None)

    r = svc.ingerir(dispositivo_id="D1", eventos=[_ev(ext="9999")])
    assert r["sin_mapeo"] == 1
    enviados = fake.upserted or fake.inserted
    assert enviados, "el evento debe haberse enviado a la base pese a no mapear"
    filas = enviados[0][1]
    assert filas[0]["empleado_id"] is None
    assert filas[0]["id_externo_empleado"] == "9999"


def test_evento_invalido_no_tumba_el_lote(monkeypatch):
    fake = FakeSB()
    monkeypatch.setattr(svc, "sb_requerido", lambda: fake)
    monkeypatch.setattr(svc, "_sb", lambda: fake)
    monkeypatch.setattr(svc, "_mapa_externo", lambda d: {"1001": "EMP-1"})

    r = svc.ingerir(dispositivo_id="D1",
                    eventos=[_ev("08:00"), {"basura": True}, _ev("18:00", direccion="salida")])
    assert len(r["errores"]) == 1
    assert r["recibidos"] == 3


def test_marcacion_manual_exige_actor_y_motivo():
    """Sin actor ni motivo, una marcación manual es un agujero de auditoría."""
    with pytest.raises(ValueError, match="requiere_actor_y_motivo"):
        svc.ingerir(dispositivo_id="D1", eventos=[_ev()], origen="manual")


def test_origen_invalido_se_rechaza():
    with pytest.raises(ValueError, match="origen_invalido"):
        svc.ingerir(dispositivo_id="D1", eventos=[_ev()], origen="telepatia")


# ── Fechas a recalcular ──────────────────────────────────────────────────────

def test_marca_el_dia_y_el_anterior():
    """Una marcación a las 06:00 puede ser de un turno que empezó ayer.

    Recalcular de más es barato (el motor es idempotente); recalcular de menos
    deja datos viejos en pantalla.
    """
    filas = [{"empleado_id": "E1", "event_timestamp": "2026-07-27T06:00:00-05:00"}]
    fechas = svc._fechas_afectadas(filas)
    dias = {f["work_date"] for f in fechas}
    assert dias == {"2026-07-27", "2026-07-26"}


def test_ignora_eventos_sin_empleado():
    filas = [{"empleado_id": None, "event_timestamp": "2026-07-27T08:00:00-05:00"}]
    assert svc._fechas_afectadas(filas) == []


def test_deduplica_las_fechas():
    filas = [{"empleado_id": "E1", "event_timestamp": f"2026-07-27T0{h}:00:00-05:00"}
             for h in range(1, 6)]
    fechas = svc._fechas_afectadas(filas)
    assert len(fechas) == 2          # el día y el anterior, una sola vez


# ── Degradación ──────────────────────────────────────────────────────────────

def test_listar_sin_supabase(monkeypatch):
    monkeypatch.setattr(svc, "_sb", lambda: None)
    assert svc.listar() == []


def test_mapa_externo_sin_tabla(monkeypatch):
    class SinTabla(FakeSB):
        def execute(self):
            raise Exception('relation "personal_mapeo_externo" does not exist')
    monkeypatch.setattr(svc, "_sb", lambda: SinTabla())
    assert svc._mapa_externo("D1") == {}
