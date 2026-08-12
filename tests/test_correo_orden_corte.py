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
