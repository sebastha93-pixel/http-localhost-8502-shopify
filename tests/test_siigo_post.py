import pytest
from backend.services import siigo


class FakeResp:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text
        self.headers = {}

    def json(self):
        return self._payload


def test_siigo_post_exitoso(monkeypatch):
    monkeypatch.setattr(siigo, "_get_token", lambda: "tok")
    monkeypatch.setattr(siigo.httpx, "post",
                        lambda url, **k: FakeResp(201, {"id": "nc-1"}))
    r = siigo.siigo_post("/credit-notes", {"a": 1})
    assert r["id"] == "nc-1"


def test_siigo_post_error_lanza(monkeypatch):
    monkeypatch.setattr(siigo, "_get_token", lambda: "tok")
    monkeypatch.setattr(siigo.httpx, "post",
                        lambda url, **k: FakeResp(400, text="payload malo"))
    with pytest.raises(RuntimeError, match="siigo_post"):
        siigo.siigo_post("/credit-notes", {"a": 1})
