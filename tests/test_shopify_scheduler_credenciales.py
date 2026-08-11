"""El scheduler debe reconocer el modelo 2026 (client_credentials).

`_credenciales_ok()` era la última compuerta del OS que sólo miraba el
`SHOPIFY_ACCESS_TOKEN` legacy. Con el token revocado (o simplemente borrado de
Railway) la compuerta daba False y el scheduler dejaba de sincronizar **en
silencio** — sin error, sin log, sin sync — aunque el intercambio
client_credentials funcionara perfectamente.
"""
import shopify_scheduler as SS


def _sin_shopify(monkeypatch):
    for v in ("SHOPIFY_ACCESS_TOKEN", "SHOPIFY_CLIENT_ID", "SHOPIFY_CLIENT_SECRET"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("SHOPIFY_STORE", "male-denim-5524.myshopify.com")


def test_ok_solo_con_credenciales_de_app(monkeypatch):
    """El caso que rompía: app configurada, legacy ausente."""
    _sin_shopify(monkeypatch)
    monkeypatch.setenv("SHOPIFY_CLIENT_ID", "cid")
    monkeypatch.setenv("SHOPIFY_CLIENT_SECRET", "sec")
    assert SS._credenciales_ok() is True


def test_ok_solo_con_legacy(monkeypatch):
    """No romper lo que ya venía funcionando."""
    _sin_shopify(monkeypatch)
    monkeypatch.setenv("SHOPIFY_ACCESS_TOKEN", "shpat_viejo")
    assert SS._credenciales_ok() is True


def test_falso_sin_ninguna_credencial(monkeypatch):
    _sin_shopify(monkeypatch)
    assert SS._credenciales_ok() is False


def test_falso_sin_store(monkeypatch):
    _sin_shopify(monkeypatch)
    monkeypatch.setenv("SHOPIFY_CLIENT_ID", "cid")
    monkeypatch.setenv("SHOPIFY_CLIENT_SECRET", "sec")
    monkeypatch.setenv("SHOPIFY_STORE", "")
    assert SS._credenciales_ok() is False


def test_ignora_placeholders(monkeypatch):
    """Los .env de ejemplo traen 'xxxx' / 'tu-tienda'; no son credenciales."""
    _sin_shopify(monkeypatch)
    monkeypatch.setenv("SHOPIFY_ACCESS_TOKEN", "shpat_xxxx")
    assert SS._credenciales_ok() is False

    _sin_shopify(monkeypatch)
    monkeypatch.setenv("SHOPIFY_CLIENT_ID", "cid")
    monkeypatch.setenv("SHOPIFY_CLIENT_SECRET", "sec")
    monkeypatch.setenv("SHOPIFY_STORE", "tu-tienda.myshopify.com")
    assert SS._credenciales_ok() is False


def test_app_incompleta_no_cuenta(monkeypatch):
    """Sólo el client_id (sin secret) no permite el intercambio."""
    _sin_shopify(monkeypatch)
    monkeypatch.setenv("SHOPIFY_CLIENT_ID", "cid")
    assert SS._credenciales_ok() is False
