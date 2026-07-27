"""Tests del parser ISO tolerante compartido (backend/core/timeutils.py).

El bug que motiva esto: Postgres (timestamptz) recorta los ceros finales de la
fracción de segundo, así que un valor escrito '...19.142540' vuelve
'...19.14254+00:00' (5 dígitos). datetime.fromisoformat en Python < 3.11 solo
acepta fracciones de 3 o 6 dígitos → ValueError con 1/2/4/5 dígitos.
"""
from datetime import datetime, timezone, timedelta

import pytest

from backend.core.timeutils import parse_iso, parse_iso_naive


# --- El corazón del bug: fracciones de cualquier longitud -------------------

@pytest.mark.parametrize("frac,esperado_us", [
    ("1", 100000),
    ("14", 140000),
    ("142", 142000),
    ("1425", 142500),
    ("14254", 142540),     # 5 dígitos: el caso que reventaba
    ("142540", 142540),    # 6 dígitos
    ("1425401", 142540),   # >6 dígitos: se trunca a microsegundos
])
def test_fraccion_de_cualquier_longitud(frac, esperado_us):
    dt = parse_iso(f"2026-07-15T19:14:25.{frac}+00:00")
    assert dt.microsecond == esperado_us
    assert dt.year == 2026 and dt.hour == 19 and dt.second == 25


# --- Zona horaria: se conserva para cálculos de antigüedad -------------------

def test_z_suffix_es_utc_aware():
    dt = parse_iso("2026-07-15T19:14:25.14254Z")
    assert dt.tzinfo is not None
    assert dt.utcoffset() == timedelta(0)


def test_offset_utc_es_aware():
    dt = parse_iso("2026-07-15T19:14:25.142540+00:00")
    assert dt.utcoffset() == timedelta(0)


def test_offset_no_utc_se_conserva():
    dt = parse_iso("2026-07-15T14:14:25-05:00")
    assert dt.utcoffset() == timedelta(hours=-5)
    # mismo instante que las 19:14:25Z
    assert dt.astimezone(timezone.utc).hour == 19


def test_offset_de_dos_digitos():
    # Postgres a veces devuelve el offset sin minutos: '+00'
    dt = parse_iso("2026-07-15T19:14:25.14254+00")
    assert dt.utcoffset() == timedelta(0)


def test_sin_zona_es_naive():
    dt = parse_iso("2026-07-15T19:14:25.14254")
    assert dt.tzinfo is None


def test_separador_espacio():
    dt = parse_iso("2026-07-15 19:14:25.14254+00:00")
    assert dt.hour == 19 and dt.utcoffset() == timedelta(0)


def test_sin_fraccion():
    dt = parse_iso("2026-07-15T19:14:25+00:00")
    assert dt.microsecond == 0 and dt.utcoffset() == timedelta(0)


def test_solo_fecha_es_medianoche_naive():
    dt = parse_iso("2026-07-15")
    assert (dt.year, dt.month, dt.day) == (2026, 7, 15)
    assert dt.hour == 0 and dt.tzinfo is None


# --- Comparabilidad: el uso real en los call sites --------------------------

def test_aware_comparable_con_now_utc():
    dt = parse_iso("2020-01-01T00:00:00.5Z")
    # No debe lanzar TypeError naive-vs-aware
    assert dt < datetime.now(timezone.utc)


# --- parse_iso_naive: para sitios de caché/TTL que comparan contra utcnow ----

def test_naive_convierte_a_utc_y_quita_tz():
    dt = parse_iso_naive("2026-07-15T14:14:25.14254-05:00")
    assert dt.tzinfo is None
    assert dt.hour == 19  # -05:00 → UTC
    assert dt.microsecond == 142540


def test_naive_desde_utc():
    dt = parse_iso_naive("2026-07-15T19:14:25.14254+00:00")
    assert dt.tzinfo is None and dt.hour == 19


def test_naive_pasa_datetime_naive_tal_cual():
    dt = parse_iso_naive("2026-07-15T19:14:25.14254")
    assert dt.tzinfo is None and dt.hour == 19


# --- Entradas inválidas: deben lanzar para que el try/except del caller actúe -

@pytest.mark.parametrize("bad", [None, "", "   ", "no-es-fecha", "2026-13-99xx"])
def test_invalido_lanza(bad):
    with pytest.raises((ValueError, TypeError)):
        parse_iso(bad)


def test_datetime_pasa_tal_cual():
    d = datetime(2026, 7, 15, 19, 14, 25, tzinfo=timezone.utc)
    assert parse_iso(d) is d
