"""Vigía de la base (17-nov-2026): la base estuvo caída 2,5 h sin que nadie
supiera. Estas pruebas cuidan que avise a tiempo, que no moleste por un
parpadeo, que recuerde sin llenar el correo y que avise cuando vuelve."""
from datetime import datetime, timedelta, timezone

import pytest

from backend.services import vigia_base as vb


@pytest.fixture
def vigia(monkeypatch):
    vb._estado.update({"fallos_seguidos": 0, "caida_desde": None, "alertado_at": None,
                       "ultimo_ok": None, "ultimo_error": "", "ultima_latencia_ms": None})
    respuestas = []
    avisos = []
    monkeypatch.setattr(vb, "probar", lambda timeout=10: respuestas.pop(0))
    monkeypatch.setattr(vb, "_avisar", lambda asunto, html, texto: avisos.append(asunto) or 1)
    return respuestas, avisos


T0 = datetime(2026, 11, 17, 13, 57, tzinfo=timezone.utc)   # 8:57 a. m. en Bogotá


def _vuelta(n_min):
    return vb.revisar_una_vez(T0 + timedelta(minutes=n_min))


def test_un_parpadeo_no_avisa(vigia):
    respuestas, avisos = vigia
    respuestas += [(False, "HTTP 522", None), (True, "ok", 40)]
    assert _vuelta(0)["accion"] == "fallo"
    assert _vuelta(2)["accion"] == "ok"
    assert avisos == []


def test_tres_fallos_seguidos_avisan_una_vez(vigia):
    respuestas, avisos = vigia
    respuestas += [(False, "timeout", None)] * 5
    acciones = [_vuelta(m)["accion"] for m in (0, 2, 4, 6, 8)]
    assert acciones == ["fallo", "fallo", "aviso_caida", "fallo_ya_avisado", "fallo_ya_avisado"]
    assert avisos == ["🔴 La base de datos del OS no responde"]


def test_recuerda_cada_media_hora_mientras_siga_caida(vigia):
    respuestas, avisos = vigia
    respuestas += [(False, "timeout", None)] * 4
    for m in (0, 2, 4):
        _vuelta(m)
    assert _vuelta(35)["accion"] == "recordatorio"
    assert avisos[-1] == "🔴 SIGUE CAÍDA la base de datos del OS"


def test_avisa_cuando_vuelve_y_reinicia_la_cuenta(vigia):
    respuestas, avisos = vigia
    respuestas += [(False, "timeout", None)] * 3 + [(True, "ok", 50), (False, "timeout", None)]
    for m in (0, 2, 4):
        _vuelta(m)
    assert _vuelta(150)["accion"] == "aviso_volvio"
    assert avisos[-1] == "🟢 La base de datos del OS volvió"
    assert vb._estado["caida_desde"] is None
    assert _vuelta(152)["accion"] == "fallo"      # una racha nueva empieza de cero


def test_si_nunca_se_aviso_la_caida_no_avisa_que_volvio(vigia):
    respuestas, avisos = vigia
    respuestas += [(False, "timeout", None), (True, "ok", 30)]
    _vuelta(0)
    assert _vuelta(2)["accion"] == "ok"
    assert avisos == []


def test_sin_credenciales_no_hay_falsa_alarma(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("SUPABASE_KEY", "")
    ok, detalle, _ = vb.probar()
    assert ok and detalle == "sin_credenciales"


def test_la_hora_del_aviso_va_en_hora_de_colombia():
    assert vb._hora(T0) == "8:57 a. m."
    assert vb._duracion(150 * 60) == "2 h 30 min"
