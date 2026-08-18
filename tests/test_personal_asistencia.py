"""
Frontera de zona horaria entre la base y el motor.

El motor compara horas de pared: una marcación contra un horario escrito como
"08:30". Para que esa comparación signifique algo, los dos lados tienen que
estar en el mismo marco.

Postgres guarda TIMESTAMPTZ en UTC y PostgREST lo devuelve con `+00:00`. El
código hacía `.replace(tzinfo=None)`, que NO convierte: deja `13:19:38` como si
fuera hora local cuando la persona entró a las 08:19.

Cinco horas de corrimiento que no producen ningún error. Producen tardanzas
inventadas, recargos nocturnos donde no los hubo, y jornadas atribuidas al día
equivocado. Encontrado con datos de producción el 2026-08-18.
"""
from datetime import date, datetime, time, timedelta, timezone

import pytest

from backend.services import personal_asistencia as asis
from backend.services.personal_base import BOGOTA


# ── De la base al motor ──────────────────────────────────────────────────────

def test_utc_de_postgrest_se_convierte_a_hora_de_pared():
    """El caso literal: una marcación real del Dahua tal como la devuelve la
    base. 13:19:38 UTC son las 08:19:38 en Bogotá."""
    assert asis.a_local("2026-08-11T13:19:38+00:00") == datetime(2026, 8, 11, 8, 19, 38)


def test_no_se_queda_con_la_hora_utc():
    """Si alguien "simplifica" esto a .replace(tzinfo=None), este test cae con
    las 13:19 — que es justo el número que descuadra la nómina sin avisar."""
    r = asis.a_local("2026-08-11T13:19:38+00:00")
    assert r.hour == 8, f"quedó en {r.hour}:00 — la zona se quitó sin convertir"


def test_cruce_de_medianoche_cambia_el_dia():
    """02:00 UTC del día 12 son las 21:00 del día 11 en Bogotá. Si no se
    convierte, la marcación se le carga a la jornada equivocada."""
    assert asis.a_local("2026-08-12T02:00:00+00:00") == datetime(2026, 8, 11, 21, 0)


def test_acepta_offset_de_bogota_directo():
    assert asis.a_local("2026-08-11T08:19:38-05:00") == datetime(2026, 8, 11, 8, 19, 38)


def test_un_naive_se_deja_como_esta():
    """Sin zona, lo único que tiene sentido en este módulo es que ya sea hora
    de pared local. Convertirlo otra vez lo correría de nuevo."""
    assert asis.a_local(datetime(2026, 8, 11, 8, 19)) == datetime(2026, 8, 11, 8, 19)


def test_acepta_datetime_ademas_de_texto():
    aware = datetime(2026, 8, 11, 13, 19, 38, tzinfo=timezone.utc)
    assert asis.a_local(aware) == datetime(2026, 8, 11, 8, 19, 38)


def test_tolera_la_fraccion_recortada_de_postgres():
    """Postgres recorta a 5 dígitos y Python 3.10 revienta con eso. Es el bug
    que motivó timeutils.parse_iso; aquí no puede volver."""
    assert asis.a_local("2026-08-11T13:19:38.12345+00:00").hour == 8


# ── Del motor a la base ──────────────────────────────────────────────────────

def test_se_guarda_con_offset_explicito():
    """Sin offset, Postgres lee el naive según la zona de la sesión (UTC) y el
    horario de las 08:30 queda guardado como las 03:30 de Bogotá."""
    guardado = asis.de_local(datetime(2026, 8, 11, 8, 30))
    assert guardado.endswith("-05:00")
    assert guardado.startswith("2026-08-11T08:30:00")


def test_none_sigue_siendo_none():
    assert asis.de_local(None) is None


def test_un_aware_conserva_su_instante():
    aware = datetime(2026, 8, 11, 13, 30, tzinfo=timezone.utc)
    assert datetime.fromisoformat(asis.de_local(aware)) == aware


@pytest.mark.parametrize("momento", [
    datetime(2026, 8, 11, 8, 30),
    datetime(2026, 1, 1, 0, 0),
    datetime(2026, 12, 31, 23, 59, 59),
])
def test_ida_y_vuelta_no_pierde_nada(momento):
    """a_local(de_local(x)) == x. Si esto falla, cada recálculo corre la hora
    un poco más."""
    assert asis.a_local(asis.de_local(momento)) == momento


# ── La ventana de consulta ───────────────────────────────────────────────────

def test_la_ventana_de_consulta_lleva_zona():
    """Una ventana sin zona pide 5 horas corridas de lo que dice pedir."""
    ini, fin = asis._ventana(date(2026, 8, 11))
    assert ini.endswith("-05:00") and fin.endswith("-05:00")
    assert datetime.fromisoformat(ini) == datetime(2026, 8, 10, 0, 0, tzinfo=BOGOTA)


def test_la_ventana_cubre_el_dia_anterior_y_el_siguiente():
    """Amplia a propósito: un turno nocturno desborda por los dos extremos.
    Acotar al día es trabajo del motor, no de la consulta."""
    ini, fin = asis._ventana(date(2026, 8, 11))
    assert datetime.fromisoformat(ini).date() == date(2026, 8, 10)
    assert datetime.fromisoformat(fin).date() == date(2026, 8, 12)
