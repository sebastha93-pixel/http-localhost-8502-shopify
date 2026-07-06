import pytest
from unittest.mock import MagicMock
from backend.services import postventa as svc


class FakeSupabase:
    """Mock mínimo del cliente supabase: encadena table().insert().execute() etc."""
    def __init__(self):
        self.inserted = []
        self._count_resp = 3  # ya existen 3 casos este año

    def table(self, name):
        self._table = name
        return self

    def insert(self, data):
        self.inserted.append((self._table, data))
        self._payload = data
        return self

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        resp = MagicMock()
        resp.data = [self._payload] if getattr(self, "_payload", None) else []
        resp.count = self._count_resp
        return resp


def test_crear_caso_valida_tipo(monkeypatch):
    monkeypatch.setattr(svc, "_sb", lambda: FakeSupabase())
    monkeypatch.setattr(svc, "_siguiente_consecutivo", lambda anio: 4)
    caso = svc.crear_caso(tipo="cambio_talla", reason="talla_pequena",
                          customer_email="a@b.com")
    assert caso["case_number"].startswith("PV-")
    assert caso["case_number"].endswith("0004")
    assert caso["status"] == "creado"
    assert caso["source"] == "interno"


def test_crear_caso_tipo_invalido(monkeypatch):
    monkeypatch.setattr(svc, "_sb", lambda: FakeSupabase())
    with pytest.raises(ValueError, match="tipo_invalido"):
        svc.crear_caso(tipo="xxx", reason="talla_pequena")
