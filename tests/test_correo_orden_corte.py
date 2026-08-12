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


class _SupabaseFalso:
    """Traga cualquier .table(...).update(...).eq(...).execute() sin hacer nada."""

    def table(self, _nombre):
        return self

    def update(self, *_a, **_k):
        return self

    def insert(self, *_a, **_k):
        return self

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def execute(self):
        return type("R", (), {"data": []})()


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


# ── Registro del intento ──────────────────────────────────────────────

def test_autorizar_registra_el_intento_incluso_cuando_falla(monkeypatch):
    """Autorizar SIEMPRE deja rastro: salga o no salga el correo.

    Sin esto no hay forma de auditar. Es el Defecto 2: hoy el resultado del
    envío solo viaja en la respuesta HTTP y se pierde ahí.
    """
    filas = []

    monkeypatch.setattr(svc, "_enviar_por_resend", lambda *a, **k: {
        "resend_id": None, "estado": "error_envio", "error": "resend 403: nope"})
    monkeypatch.setattr(svc, "_registrar_correo_corte",
                        lambda oc_id, **kw: filas.append({"oc_id": oc_id, **kw}))
    monkeypatch.setattr(svc, "_sb", lambda: _SupabaseFalso())
    monkeypatch.setattr(svc, "obtener_orden_corte", lambda _id: {
        "id": "oc-1", "consecutivo": "2608-0009", "estado": "autorizada",
        "destinatarios_correo": ["malo@ejemplo.com"], "indicaciones": "",
        "curva_trazo": {}, "referencia": {"codigo_referencia": "93634"},
    })

    res = svc.autorizar_orden_corte("oc-1", destinatarios=["malo@ejemplo.com"],
                                    usuario="diseno@maledenim.com")

    assert len(filas) == 1, "el intento fallido tiene que quedar registrado"
    assert filas[0]["resultado"]["estado"] == "error_envio"
    assert res["correo"]["estado"] == "error_envio"
    assert res["correo"]["enviado_por"] is None, \
        "un fallo NO puede reportarse como enviado"


# ── Consulta del estado de entrega ────────────────────────────────────

def test_no_reconsulta_un_correo_ya_entregado(monkeypatch):
    """Un estado definitivo no cambia: consultarlo otra vez es gasto puro."""
    llamadas = []
    monkeypatch.setattr(svc, "_consultar_estado_resend",
                        lambda rid: llamadas.append(rid))

    correos = [{"id": "c1", "resend_id": "abc", "estado": "entregado"}]
    r = svc.refrescar_estados_correo(correos)

    assert llamadas == [], "no debió llamar a Resend"
    assert r[0]["estado"] == "entregado"


def test_reconsulta_un_correo_en_curso_y_persiste(monkeypatch):
    """'enviado' todavía puede volverse 'rebotado': hay que preguntar."""
    guardado = {}
    monkeypatch.setattr(svc, "_consultar_estado_resend", lambda rid: "bounced")
    monkeypatch.setattr(svc, "_guardar_estado_correo",
                        lambda cid, estado: guardado.update({cid: estado}))

    correos = [{"id": "c1", "resend_id": "abc", "estado": "enviado"}]
    r = svc.refrescar_estados_correo(correos)

    assert r[0]["estado"] == "rebotado"
    assert guardado == {"c1": "rebotado"}


def test_sin_resend_id_no_consulta(monkeypatch):
    """Un error_envio nunca creó un correo en Resend: no hay qué consultar."""
    llamadas = []
    monkeypatch.setattr(svc, "_consultar_estado_resend",
                        lambda rid: llamadas.append(rid))

    correos = [{"id": "c1", "resend_id": None, "estado": "error_envio"}]
    r = svc.refrescar_estados_correo(correos)

    assert llamadas == []
    assert r[0]["estado"] == "error_envio"


def test_si_resend_no_responde_conserva_el_estado(monkeypatch):
    """Que Resend esté caído no puede borrar lo que ya sabíamos."""
    monkeypatch.setattr(svc, "_consultar_estado_resend", lambda rid: None)

    correos = [{"id": "c1", "resend_id": "abc", "estado": "enviado"}]
    r = svc.refrescar_estados_correo(correos)

    assert r[0]["estado"] == "enviado"
