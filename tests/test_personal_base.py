"""
Cimientos del módulo Personal: caché, enmascaramiento y aritmética de tiempo.

Son utilidades pequeñas, pero el motor de asistencia se apoya entero en ellas:
un error de redondeo aquí se convierte en minutos mal contados a una persona.
"""
from datetime import date, datetime, timedelta, timezone

import pytest

from backend.services import personal_base as base


# ── Caché ────────────────────────────────────────────────────────────────────

def setup_function():
    base.cache_invalidar()


def test_cache_guarda_y_devuelve():
    base.cache_set("k1", {"a": 1}, ttl_seg=60)
    assert base.cache_get("k1") == {"a": 1}


def test_cache_miss_devuelve_none():
    assert base.cache_get("no-existe") is None


def test_cache_expira(monkeypatch):
    base.cache_set("k1", "valor", ttl_seg=10)
    assert base.cache_get("k1") == "valor"
    # Avanzar el reloj más allá del TTL
    real = base.time.time
    monkeypatch.setattr(base.time, "time", lambda: real() + 11)
    assert base.cache_get("k1") is None


def test_cache_respeta_el_ttl_de_escritura(monkeypatch):
    """El TTL lo fija cache_set, no cache_get.

    produccion.py tiene el bug de que _cache_get recibe ttl_seg y lo ignora.
    Aquí cache_get ni siquiera lo acepta, así que no hay ambigüedad.
    """
    base.cache_set("corto", 1, ttl_seg=5)
    base.cache_set("largo", 2, ttl_seg=600)
    real = base.time.time
    monkeypatch.setattr(base.time, "time", lambda: real() + 10)
    assert base.cache_get("corto") is None
    assert base.cache_get("largo") == 2


def test_invalidar_por_prefijo():
    base.cache_set("personal:reglas:a", 1, 60)
    base.cache_set("personal:reglas:b", 2, 60)
    base.cache_set("personal:otro:c", 3, 60)
    n = base.cache_invalidar("personal:reglas:")
    assert n == 2
    assert base.cache_get("personal:reglas:a") is None
    assert base.cache_get("personal:otro:c") == 3


def test_invalidar_todo():
    base.cache_set("a", 1, 60)
    base.cache_set("b", 2, 60)
    assert base.cache_invalidar() == 2
    assert base.cache_get("a") is None


# ── Enmascaramiento ──────────────────────────────────────────────────────────

def test_enmascarar_ip_deja_ver_la_red():
    assert base.enmascarar_ip("192.168.1.50") == "192.168.x.x"


def test_enmascarar_ip_maneja_basura():
    assert base.enmascarar_ip("no-es-una-ip") == "···"
    assert base.enmascarar_ip(None) is None
    assert base.enmascarar_ip("") == ""


def test_enmascarar_serie():
    assert base.enmascarar_serie("ABC123456789") == "ABC…789"
    assert base.enmascarar_serie("corto") == "···"
    assert base.enmascarar_serie(None) is None


def test_enmascarar_documento():
    assert base.enmascarar_documento("1234567890") == "···7890"
    assert base.enmascarar_documento("123") == "···"


# ── Aritmética de tiempo ─────────────────────────────────────────────────────

def test_minutos_entre_basico():
    a = datetime(2026, 7, 27, 8, 0, tzinfo=timezone.utc)
    b = datetime(2026, 7, 27, 17, 30, tzinfo=timezone.utc)
    assert base.minutos_entre(a, b) == 570      # 9h 30m


def test_minutos_entre_trunca_no_redondea():
    """7 min 59 s son 7 minutos, no 8.

    Reconocer de más no es defendible ante una discusión laboral;
    reconocer de menos es conservador y explicable.
    """
    a = datetime(2026, 7, 27, 8, 0, 0, tzinfo=timezone.utc)
    b = datetime(2026, 7, 27, 8, 7, 59, tzinfo=timezone.utc)
    assert base.minutos_entre(a, b) == 7


def test_minutos_entre_nunca_negativo():
    a = datetime(2026, 7, 27, 17, 0, tzinfo=timezone.utc)
    b = datetime(2026, 7, 27, 8, 0, tzinfo=timezone.utc)
    assert base.minutos_entre(a, b) == 0


def test_minutos_entre_tolera_none():
    a = datetime(2026, 7, 27, 8, 0, tzinfo=timezone.utc)
    assert base.minutos_entre(None, a) == 0
    assert base.minutos_entre(a, None) == 0


def test_minutos_entre_cruzando_medianoche():
    """Turno nocturno: entra 22:00, sale 06:00 del día siguiente."""
    a = datetime(2026, 7, 27, 22, 0, tzinfo=timezone.utc)
    b = datetime(2026, 7, 28, 6, 0, tzinfo=timezone.utc)
    assert base.minutos_entre(a, b) == 480       # 8h


@pytest.mark.parametrize("minutos,esperado", [
    (450, "7h 30m"), (480, "8h"), (45, "45m"), (0, "0m"), (-30, "-30m"),
    (-90, "-1h 30m"),
])
def test_minutos_a_hhmm(minutos, esperado):
    assert base.minutos_a_hhmm(minutos) == esperado


# ── Quincenas (periodo de nómina de MALE DENIM) ──────────────────────────────

def test_quincena_primera():
    assert base.quincena_de(date(2026, 7, 8)) == (date(2026, 7, 1), date(2026, 7, 15))


def test_quincena_segunda():
    assert base.quincena_de(date(2026, 7, 20)) == (date(2026, 7, 16), date(2026, 7, 31))


def test_quincena_bordes():
    assert base.quincena_de(date(2026, 7, 15))[1] == date(2026, 7, 15)
    assert base.quincena_de(date(2026, 7, 16))[0] == date(2026, 7, 16)


def test_quincena_febrero_no_bisiesto():
    assert base.quincena_de(date(2026, 2, 20)) == (date(2026, 2, 16), date(2026, 2, 28))


def test_quincena_febrero_bisiesto():
    assert base.quincena_de(date(2028, 2, 20)) == (date(2028, 2, 16), date(2028, 2, 29))


def test_quincena_diciembre_no_desborda_de_anio():
    """Diciembre es el caso donde un `mes + 1` ingenuo revienta."""
    assert base.quincena_de(date(2026, 12, 20)) == (date(2026, 12, 16), date(2026, 12, 31))


# ── Zona horaria ─────────────────────────────────────────────────────────────

def test_hoy_bogota_usa_utc_menos_5(monkeypatch):
    """A las 20:00 de Bogotá ya es el día siguiente en UTC.

    Si el motor usara date.today() en Railway, adelantaría un día la jornada
    de la noche y la asignaría a la fecha equivocada.
    """
    class FakeDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            # 2026-07-28 01:00 UTC == 2026-07-27 20:00 Bogotá
            utc = datetime(2026, 7, 28, 1, 0, tzinfo=timezone.utc)
            return utc.astimezone(tz) if tz else utc

    monkeypatch.setattr(base, "datetime", FakeDatetime)
    assert base.hoy_bogota() == date(2026, 7, 27)


# ── Detección de migración faltante ──────────────────────────────────────────

@pytest.mark.parametrize("mensaje", [
    'relation "personal_empleados" does not exist',
    "42P01: undefined_table",
    "Could not find the table 'public.personal_sedes' in the schema cache",
])
def test_detecta_tabla_faltante(mensaje):
    assert base.es_error_tabla_faltante(Exception(mensaje)) is True


def test_no_confunde_otros_errores():
    assert base.es_error_tabla_faltante(Exception("connection timeout")) is False
    assert base.es_error_tabla_faltante(Exception("duplicate key value")) is False
