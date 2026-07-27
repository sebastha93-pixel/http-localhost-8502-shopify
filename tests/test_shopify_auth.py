import time
from backend.services import shopify_auth as SA


class FakeResp:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._p = payload or {}
        self.text = text
    def json(self):
        return self._p


def _limpiar(monkeypatch):
    SA.invalidar()
    monkeypatch.setenv("SHOPIFY_STORE", "male-denim-5524.myshopify.com")


def test_usa_client_credentials_si_hay_app(monkeypatch):
    _limpiar(monkeypatch)
    monkeypatch.setenv("SHOPIFY_CLIENT_ID", "cid")
    monkeypatch.setenv("SHOPIFY_CLIENT_SECRET", "sec")
    monkeypatch.setattr(SA.httpx, "post",
        lambda url, **k: FakeResp(200, {"access_token": "nuevo123",
                                        "expires_in": 86399,
                                        "scope": "write_orders"}))
    assert SA.token() == "nuevo123"
    assert SA.fuente_actual() == "client_credentials"


def test_cae_al_legacy_si_el_intercambio_falla(monkeypatch):
    # Clave: la migración NO puede tumbar el OS.
    _limpiar(monkeypatch)
    monkeypatch.setenv("SHOPIFY_CLIENT_ID", "cid")
    monkeypatch.setenv("SHOPIFY_CLIENT_SECRET", "sec")
    monkeypatch.setenv("SHOPIFY_ACCESS_TOKEN", "shpat_viejo")
    monkeypatch.setattr(SA.httpx, "post",
                        lambda url, **k: FakeResp(401, text="invalid_client"))
    assert SA.token() == "shpat_viejo"
    assert SA.fuente_actual() == "legacy"


def test_usa_legacy_si_no_hay_credenciales_de_app(monkeypatch):
    _limpiar(monkeypatch)
    monkeypatch.delenv("SHOPIFY_CLIENT_ID", raising=False)
    monkeypatch.delenv("SHOPIFY_CLIENT_SECRET", raising=False)
    monkeypatch.setenv("SHOPIFY_ACCESS_TOKEN", "shpat_viejo")
    assert SA.token() == "shpat_viejo"


def test_cachea_y_no_reintercambia(monkeypatch):
    _limpiar(monkeypatch)
    monkeypatch.setenv("SHOPIFY_CLIENT_ID", "cid")
    monkeypatch.setenv("SHOPIFY_CLIENT_SECRET", "sec")
    llamadas = []
    monkeypatch.setattr(SA.httpx, "post",
        lambda url, **k: llamadas.append(1) or FakeResp(
            200, {"access_token": "tok", "expires_in": 86399}))
    SA.token(); SA.token(); SA.token()
    assert len(llamadas) == 1     # una sola vez, el resto sale del cache


def test_refresca_cuando_esta_por_expirar(monkeypatch):
    _limpiar(monkeypatch)
    monkeypatch.setenv("SHOPIFY_CLIENT_ID", "cid")
    monkeypatch.setenv("SHOPIFY_CLIENT_SECRET", "sec")
    llamadas = []
    monkeypatch.setattr(SA.httpx, "post",
        lambda url, **k: llamadas.append(1) or FakeResp(
            200, {"access_token": f"tok{len(llamadas)}", "expires_in": 86399}))
    SA.token()
    # Simular que quedan 60s (menos que el margen de 300s)
    SA._cache["expira"] = time.time() + 60
    SA.token()
    assert len(llamadas) == 2


def test_sin_nada_configurado_lanza(monkeypatch):
    _limpiar(monkeypatch)
    for v in ("SHOPIFY_CLIENT_ID", "SHOPIFY_CLIENT_SECRET", "SHOPIFY_ACCESS_TOKEN"):
        monkeypatch.delenv(v, raising=False)
    import pytest
    with pytest.raises(RuntimeError, match="shopify_sin_credenciales"):
        SA.token()
