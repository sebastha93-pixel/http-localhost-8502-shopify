"""`MelonnIO`: qué entiende de cada respuesta de Melonn. Sin red: `requests`
y el cliente del OS se falsean enteros (la tanda de dominio no los tiene).

Lo que se cuida es UNA distinción, la misma tres veces: «no existe» no es «no
pude preguntar», y «no se envió» no es «no sé si se creó».
"""
import asyncio
import sys
import types

import pytest

from backend.modules.retail.infrastructure.melonn import despacho as d


class _Respuesta:
    def __init__(self, estado, cuerpo=None, texto=""):
        self.status_code = estado
        self._cuerpo = cuerpo
        self.text = texto or ("" if cuerpo is None else str(cuerpo))
        self.content = b"x" if (cuerpo is not None or texto) else b""

    def json(self):
        if self._cuerpo is None:
            raise ValueError("sin cuerpo")
        return self._cuerpo


@pytest.fixture
def melonn(monkeypatch):
    """Devuelve una función: `melonn(respuesta)` deja lista la próxima."""
    estado = {"r": None, "pedidas": []}

    def request(metodo, url, **kw):
        estado["pedidas"].append((metodo, url, kw.get("json")))
        return estado["r"]
    monkeypatch.setitem(sys.modules, "requests",
                        types.SimpleNamespace(request=request))
    mc = types.ModuleType("melonn_client")
    mc._BASE_URL = "https://melonn.falso"
    mc._api_key = lambda: "llave"
    mc._rate_limiter = types.SimpleNamespace(wait=lambda: None)
    mc._es_cuota_agotada = lambda r: "Limit Exceeded" in (r.text or "")
    mc._marcar_cuota_agotada = lambda: estado.__setitem__("cuota", True)
    monkeypatch.setitem(sys.modules, "melonn_client", mc)

    def poner(respuesta):
        estado["r"] = respuesta
        return estado
    return poner


def _leer(numero="FERPOS-2538"):
    return asyncio.run(d.MelonnIO().leer_pedido(numero))


def _crear():
    return asyncio.run(d.MelonnIO().crear_pedido({"external_order_number": "FERPOS-2538"}))


def test_leer_un_pedido_que_existe(melonn):
    e = melonn(_Respuesta(200, {"internal_order_number": "M1", "state": {"id": 2}}))
    assert _leer()["internal_order_number"] == "M1"
    assert e["pedidas"][0][:2] == ("GET", "https://melonn.falso/sell-orders/FERPOS-2538")


def test_solo_el_404_es_no_existe(melonn):
    melonn(_Respuesta(404, {"message": "Order not found"}))
    assert _leer() is None


@pytest.mark.parametrize("respuesta", [
    _Respuesta(200), _Respuesta(200, {}), _Respuesta(200, []),
    _Respuesta(200, {"message": "ok"}), _Respuesta(500, texto="boom"),
    _Respuesta(401, texto="Unauthorized"), _Respuesta(403, texto="Forbidden")])
def test_un_200_raro_o_un_error_NO_es_no_existe(melonn, respuesta):
    """Con cualquiera de éstos el POS crearía un pedido que quizá ya existe, o
    anularía una venta creyendo que Melonn no tiene nada."""
    melonn(respuesta)
    with pytest.raises(Exception) as e:
        _leer()
    assert not isinstance(e.value, (d.CuotaAgotada, d.MelonnOcupado))


def test_sin_cuota_y_ocupado_se_distinguen(melonn):
    melonn(_Respuesta(429, texto='{"message": "Limit Exceeded"}'))
    with pytest.raises(d.CuotaAgotada):
        _leer()
    melonn(_Respuesta(429, texto="Too Many Requests"))
    with pytest.raises(d.MelonnOcupado):
        _leer()
    melonn(_Respuesta(503, texto="Service Unavailable"))
    with pytest.raises(d.MelonnOcupado):
        _leer()                     # al PREGUNTAR, un 503 es sólo «más tarde»


def test_crear_devuelve_lo_que_contesta_melonn(melonn):
    melonn(_Respuesta(201, {"sell_order": {"internal_order_number": "M1"}}))
    assert _crear()["sell_order"]["internal_order_number"] == "M1"


def test_un_4xx_al_crear_es_rechazo_no_se_creo(melonn):
    melonn(_Respuesta(400, {"message": "No stock available"}))
    with pytest.raises(d.RechazoDeMelonn, match="No stock available"):
        _crear()


def test_un_429_al_crear_es_no_se_envio(melonn):
    melonn(_Respuesta(429, texto="Too Many Requests"))
    with pytest.raises(d.MelonnOcupado):
        _crear()


@pytest.mark.parametrize("estado", [500, 502, 503, 504])
def test_un_5xx_al_crear_es_NO_SE_SABE(melonn, estado):
    """Incluido el 503: una pasarela puede devolverlo después de que Melonn
    aceptó el pedido. Tratarlo como «no salió» lo volvía a pedir a los tres
    minutos, sin la espera."""
    melonn(_Respuesta(estado, texto="upstream"))
    with pytest.raises(Exception) as e:
        _crear()
    assert not isinstance(e.value, (d.RechazoDeMelonn, d.MelonnOcupado,
                                    d.CuotaAgotada))
