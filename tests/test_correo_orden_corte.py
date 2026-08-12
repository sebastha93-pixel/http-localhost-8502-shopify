"""El correo de la orden de corte tiene que poder decir si llegó o no.

La orden 2607-0017 salió a barreto.corte@hotmail.com en vez de
johnj2397@hotmail.com y nadie se enteró: el sistema no registraba el envío y
un fallo de Resend se tragaba en un print. Estas pruebas fijan que eso no
vuelva a pasar en silencio.
"""
import pytest

from backend.services import produccion as svc


@pytest.mark.parametrize("evento,esperado", [
    ("sent", "enviado"),
    ("delivered", "entregado"),
    ("bounced", "rebotado"),
    ("complained", "spam"),
    ("delivery_delayed", "demorado"),
    ("failed", "fallido"),
    ("suppressed", "suprimido"),
])
def test_traduce_cada_evento_de_resend(evento, esperado):
    """Los 7 estados de entrega documentados por Resend."""
    assert svc._estado_desde_last_event(evento) == esperado


@pytest.mark.parametrize("evento", ["opened", "clicked"])
def test_abierto_y_clickeado_cuentan_como_entregado(evento):
    """No mostramos apertura, pero si Resend dice `opened` el correo LLEGÓ.

    Tratarlo como 'enviado' dejaría la orden consultando a Resend para
    siempre, porque nunca alcanzaría un estado definitivo.
    """
    assert svc._estado_desde_last_event(evento) == "entregado"


def test_evento_desconocido_queda_en_curso():
    """Un evento que Resend agregue mañana no puede mentir que se entregó."""
    assert svc._estado_desde_last_event("evento_del_futuro") == "enviado"
    assert svc._estado_desde_last_event(None) == "enviado"


def test_los_estados_definitivos_no_incluyen_los_que_siguen_cambiando():
    """'enviado' y 'demorado' todavía pueden moverse: hay que reconsultarlos."""
    assert "enviado" not in svc._ESTADOS_DEFINITIVOS
    assert "demorado" not in svc._ESTADOS_DEFINITIVOS
    assert {"entregado", "rebotado", "error_envio"} <= svc._ESTADOS_DEFINITIVOS


# ── Envío por Resend ──────────────────────────────────────────────────

class _RespuestaFalsa:
    def __init__(self, status_code, payload=None, texto=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = texto

    def json(self):
        return self._payload


def test_envio_exitoso_devuelve_el_id_de_resend(monkeypatch):
    import httpx
    monkeypatch.setenv("RESEND_API_KEY", "re_falsa")
    monkeypatch.setattr(httpx, "post",
                        lambda *a, **k: _RespuestaFalsa(200, {"id": "abc-123"}))

    r = svc._enviar_por_resend(["cortador@ejemplo.com"], "Asunto", "Cuerpo")

    assert r["estado"] == "enviado"
    assert r["resend_id"] == "abc-123"
    assert r["error"] is None


def test_resend_rechaza_y_queda_registrado_como_error(monkeypatch):
    """EL DEFECTO QUE MOTIVÓ TODO: un 403 de Resend NO puede pasar por éxito.

    Antes: se imprimía y se caía a mailto, la pantalla decía 'Orden
    autorizada' y nadie se enteraba de que el correo nunca salió.
    """
    import httpx
    monkeypatch.setenv("RESEND_API_KEY", "re_falsa")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _RespuestaFalsa(
        403, texto='{"message":"The maledenim.com domain is not verified"}'))

    r = svc._enviar_por_resend(["cortador@ejemplo.com"], "Asunto", "Cuerpo")

    assert r["estado"] == "error_envio"
    assert r["resend_id"] is None
    assert "403" in r["error"]
    assert "not verified" in r["error"]


def test_si_resend_se_cae_no_lanza(monkeypatch):
    """Un timeout de red no puede tumbar la autorización de la orden."""
    import httpx

    def _revienta(*a, **k):
        raise httpx.ConnectTimeout("se cayó la red")

    monkeypatch.setenv("RESEND_API_KEY", "re_falsa")
    monkeypatch.setattr(httpx, "post", _revienta)

    r = svc._enviar_por_resend(["cortador@ejemplo.com"], "Asunto", "Cuerpo")

    assert r["estado"] == "error_envio"
    assert "ConnectTimeout" in r["error"]


def test_sin_api_key_es_error_no_silencio(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    r = svc._enviar_por_resend(["cortador@ejemplo.com"], "Asunto", "Cuerpo")
    assert r["estado"] == "error_envio"
    assert r["error"] == "sin_RESEND_API_KEY"


def test_sin_destinatarios_es_error(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_falsa")
    r = svc._enviar_por_resend([], "Asunto", "Cuerpo")
    assert r["estado"] == "error_envio"
    assert r["error"] == "sin_destinatarios"
