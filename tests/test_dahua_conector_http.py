"""
Proveedor HTTP del Dahua real (dahua-connector/proveedores/dahua_http.py).

Estos tests NO tocan el equipo: le inyectan las respuestas EXACTAS que dio el
DHI-ASI6213S de MALE DENIM el 2026-08-18. Cada uno vigila una forma concreta de
corromper la asistencia en silencio:

  · leer el epoch como hora local  → toda la nómina corrida 5 horas
  · creerle el `Type=Entry`        → nadie sale nunca, jornadas infinitas
  · contar intentos fallidos       → horas regaladas a una cara no reconocida
  · contar aperturas sin lector    → horas atribuidas a nadie
  · usar `offset` como cursor      → se saltan o repiten marcaciones al purgar
  · excluir sin decirlo            → un conteo incompleto que se lee completo

Ninguno de esos errores da excepción. Todos dan números plausibles y falsos.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import pytest

# El conector es un programa aparte (solo stdlib, corre en la red del cliente),
# así que no está en el paquete backend. Se importa por ruta.
_CONECTOR = Path(__file__).resolve().parents[1] / "dahua-connector"
if str(_CONECTOR) not in sys.path:
    sys.path.insert(0, str(_CONECTOR))

from proveedores.dahua_http import METODOS, DahuaHttp  # noqa: E402


# ── Respuestas reales del equipo ─────────────────────────────────────────────
# Copiadas literalmente de la salida del 2026-08-18. Los tres casos que
# importan: marcación buena, apertura sin lector, intento fallido.

MARCACION = {                             # RecNo 4780 del equipo
    "RecNo": "4780", "UserID": "017", "CardName": "Manuela Gomez Gomez",
    "CreateTime": "1787062023",           # 14:07:03 UTC = 09:07:03 Bogotá
    "Status": "1", "ErrorCode": "0", "Method": "15", "ReaderID": "1",
    "Type": "Entry", "AttendanceState": "0", "Door": "0",
}
SIN_LECTOR = {                            # RecNo 4782 — se abrió la puerta,
    "RecNo": "4782", "UserID": "", "CardName": "",   # sin lector y sin persona
    "CreateTime": "1787062570",           # 14:16:10 UTC = 09:16:10 Bogotá
    "Status": "1", "ErrorCode": "0", "Method": "4", "ReaderID": "",
    "Type": "Entry", "AttendanceState": "0", "Door": "0",
}
FALLIDO = {                               # RecNo 4739 — cara no reconocida
    "RecNo": "4739", "UserID": "", "CardName": "",
    "CreateTime": "1786806808",           # 15:13:28 UTC = 10:13:28 Bogotá
    "Status": "0", "ErrorCode": "16", "Method": "15", "ReaderID": "1",
    "Type": "Entry", "AttendanceState": "0", "Door": "0",
}

CONF = {"dahua_host": "10.30.1.4", "dahua_usuario": "admin",
        "dahua_password": "no-se-usa-en-estos-tests"}


class DahuaFalso(DahuaHttp):
    """Mismo proveedor, transporte sustituido. La lógica bajo prueba es la real."""

    def __init__(self, registros, conf=None):
        super().__init__({**CONF, **(conf or {})})
        self.registros = registros
        self.llamadas: list[tuple[int, int]] = []

    def _total(self):
        return len(self.registros)

    def _pagina(self, offset, cuantos):
        self.llamadas.append((offset, cuantos))
        return self.registros[offset:offset + cuantos]


def _provee(registros, **conf):
    return DahuaFalso(registros, conf)


# ── 1. Zona horaria: el error de 5 horas ─────────────────────────────────────

def test_createtime_se_interpreta_como_utc_y_se_convierte_a_bogota():
    """1787144823 es 14:07:03 UTC = 09:07:03 en Bogotá.

    Si alguien "arregla" esto leyendo el epoch como hora local, el test cae con
    14:07 — que es justo el número que hace que la nómina cuadre mal sin que
    nadie vea un error.
    """
    ev = _provee([MARCACION])._traducir(MARCACION)
    t = datetime.fromisoformat(ev["event_timestamp"])
    assert (t.hour, t.minute, t.second) == (9, 7, 3)
    assert t.utcoffset() == timedelta(hours=-5), "debe emitir el offset explícito"


def test_el_timestamp_emitido_no_es_ambiguo():
    """Sin offset, quien lo reciba tiene que adivinar la zona. Adivinar mal
    son 5 horas."""
    ev = _provee([MARCACION])._traducir(MARCACION)
    assert ev["event_timestamp"].endswith("-05:00")


def test_createtime_no_numerico_se_descarta_sin_reventar():
    assert _provee([]) ._traducir({**MARCACION, "CreateTime": ""}) is None
    assert _provee([])._traducir({**MARCACION, "CreateTime": "ayer"}) is None


# ── 2. El equipo no distingue entrada de salida ──────────────────────────────

def test_nunca_se_emite_entrada_aunque_el_equipo_diga_Entry():
    """El equipo pone Type=Entry en los 4785 registros, incluidas las salidas.

    Repetirlo sería inventar un hecho: el motor dejaría todas las jornadas
    abiertas porque nadie sale nunca. Se emite 'desconocida' para que alterne.
    """
    for r in (MARCACION, SIN_LECTOR, FALLIDO):
        ev = _provee([r])._traducir(r)
        assert ev["direccion_acceso"] == "desconocida"
        assert r["Type"] == "Entry", "el fixture debe conservar el dato original"


def test_el_dato_original_del_equipo_queda_en_el_payload():
    """Se descarta para decidir, pero se conserva como hecho: si mañana
    habilitan el lector de salida, el histórico explica por qué venía así."""
    ev = _provee([MARCACION])._traducir(MARCACION)
    assert ev["raw_payload_json"]["Type"] == "Entry"
    assert ev["raw_payload_json"]["AttendanceState"] == "0"


# ── 3. Clasificación: qué es una marcación de verdad ─────────────────────────

@pytest.mark.parametrize("registro,esperado", [
    (MARCACION, "marcacion"),
    (SIN_LECTOR, "sin_lector"),
    (FALLIDO, "fallido"),
    ({**MARCACION, "UserID": "   "}, "sin_lector"),   # blancos ≠ identificado
    ({**MARCACION, "Status": "0"}, "fallido"),
])
def test_clasificacion(registro, esperado):
    assert DahuaHttp._clasificar(registro) == esperado


def test_solo_las_marcaciones_atribuibles_salen_por_defecto():
    p = _provee([MARCACION, SIN_LECTOR, FALLIDO])
    r = p.obtener_eventos(cursor=0, limite=100)
    assert [e["id_externo_empleado"] for e in r["eventos"]] == ["017"]


def test_lo_excluido_siempre_se_reporta():
    """Un resumen que no dice qué dejó afuera se lee como completo.
    Es el mismo error que un fetch paginado que corta en silencio."""
    r = _provee([MARCACION, SIN_LECTOR, FALLIDO]).obtener_eventos(cursor=0, limite=100)
    assert r["resumen"]["revisados"] == 3
    assert r["resumen"]["emitidos"] == 1
    assert r["resumen"]["excluidos_sin_lector"] == 1
    assert r["resumen"]["excluidos_fallidos"] == 1


def test_se_pueden_incluir_los_no_atribuibles_a_proposito():
    r = _provee([MARCACION, SIN_LECTOR, FALLIDO],
                dahua_incluir_no_atribuibles=True).obtener_eventos(cursor=0, limite=100)
    assert len(r["eventos"]) == 3
    assert r["resumen"]["excluidos_sin_lector"] == 0
    # y quedan distinguibles por tipo, no confundidos con marcaciones
    assert {e["tipo_evento"] for e in r["eventos"]} == {"acceso", "sin_lector", "fallido"}


def test_un_fallido_nunca_se_reporta_como_concedido():
    ev = _provee([FALLIDO], dahua_incluir_no_atribuibles=True)._traducir(FALLIDO)
    assert ev["resultado_acceso"] == "denegado"


# ── 4. Cursor: RecNo, no offset ──────────────────────────────────────────────

def test_el_cursor_es_recno_no_posicion():
    """El equipo es un búfer circular. Si el cursor fuera un offset, al purgar
    lo viejo las posiciones se corren y se saltan o repiten marcaciones."""
    regs = [{**MARCACION, "RecNo": str(n), "UserID": "017"} for n in (10, 11, 12)]
    r = _provee(regs).obtener_eventos(cursor="11", limite=100)
    assert [e["id_evento_externo"] for e in r["eventos"]] == ["AccessControlCardRec-12"]
    assert r["cursor"] == "12"


def test_cursor_al_dia_no_devuelve_nada():
    regs = [{**MARCACION, "RecNo": str(n)} for n in (1, 2, 3)]
    r = _provee(regs).obtener_eventos(cursor="3", limite=100)
    assert r["eventos"] == [] and r["hay_mas"] is False


def test_si_el_buffer_se_reinicia_el_cursor_se_reinicia():
    """Cursor 9000 contra un equipo que ahora tiene 2 registros: el búfer se
    vació. Reprocesar es inocuo (el backend deduplica); saltárselo perdería
    marcaciones para siempre."""
    regs = [{**MARCACION, "RecNo": "1"}, {**MARCACION, "RecNo": "2"}]
    r = _provee(regs).obtener_eventos(cursor="9000", limite=100)
    assert len(r["eventos"]) == 2
    assert r["resumen"]["cursor_previo"] == 0


def test_buffer_purgado_no_se_confunde_con_buffer_reiniciado():
    """El caso que rompía: el equipo purgó lo viejo y quedó con los RecNo
    4700–4785, o sea total=86. Comparar el cursor (4780) contra el TOTAL (86)
    concluye "se reinició" y rebarre los 4785 registros en cada poll, para
    siempre. Hay que compararlo contra el RecNo más alto que existe (4785).

    No da error ni corrompe datos —el backend deduplica—, solo martilla el
    equipo en silencio. Por eso necesita test.
    """
    regs = [{**MARCACION, "RecNo": str(n)} for n in range(4700, 4786)]
    p = _provee(regs, dahua_pagina=300)
    r = p.obtener_eventos(cursor="4780", limite=100)
    recnos = [int(e["id_evento_externo"].rsplit("-", 1)[1]) for e in r["eventos"]]
    assert recnos == [4781, 4782, 4783, 4784, 4785]
    assert r["resumen"]["cursor_previo"] == 4780, "no debía reiniciarse"
    assert r["resumen"]["revisados"] == 5, "no debía rebarrer el histórico"


def test_el_limite_corta_pero_el_cursor_no_se_adelanta():
    """Cortar el lote no puede perder los que no salieron."""
    regs = [{**MARCACION, "RecNo": str(n)} for n in range(1, 11)]
    r = _provee(regs).obtener_eventos(cursor=0, limite=4)
    assert len(r["eventos"]) == 4
    assert int(r["cursor"]) == 4, "el cursor solo avanza hasta lo emitido"
    assert r["hay_mas"] is True
    # la siguiente pasada continúa exactamente donde quedó, sin huecos
    r2 = _provee(regs).obtener_eventos(cursor=r["cursor"], limite=4)
    assert [e["id_evento_externo"] for e in r2["eventos"]][0] == "AccessControlCardRec-5"


def test_los_eventos_salen_en_orden_cronologico():
    regs = [{**MARCACION, "RecNo": str(n)} for n in range(1, 8)]
    r = _provee(regs).obtener_eventos(cursor=0, limite=100)
    recnos = [int(e["id_evento_externo"].rsplit("-", 1)[1]) for e in r["eventos"]]
    assert recnos == sorted(recnos)


def test_en_operacion_normal_lee_una_sola_pagina():
    """Poll de 60 s con 2 marcaciones nuevas no debe barrer los 4785 registros."""
    regs = [{**MARCACION, "RecNo": str(n)} for n in range(1, 501)]
    p = _provee(regs, dahua_pagina=300)
    p.obtener_eventos(cursor="498", limite=100)
    assert len(p.llamadas) == 1, f"leyó {len(p.llamadas)} páginas"


# ── 5. Idempotencia ──────────────────────────────────────────────────────────

def test_el_id_externo_es_estable_entre_lecturas():
    """Es la llave de idempotencia del backend: si cambiara entre pasadas, el
    mismo hecho entraría dos veces y las horas se duplicarían."""
    a = _provee([MARCACION])._traducir(MARCACION)
    b = _provee([MARCACION])._traducir(MARCACION)
    assert a["id_evento_externo"] == b["id_evento_externo"] == "AccessControlCardRec-4780"


def test_misma_lectura_dos_veces_da_lo_mismo():
    regs = [{**MARCACION, "RecNo": str(n)} for n in range(1, 6)]
    p = _provee(regs)
    assert p.obtener_eventos(cursor="2", limite=10) == p.obtener_eventos(cursor="2", limite=10)


# ── 6. La clave no se filtra ──────────────────────────────────────────────────

def test_la_clave_no_queda_en_el_objeto():
    """El name mangling no basta: renombra el atributo pero sigue en __dict__.
    Aquí vive en un closure."""
    p = DahuaHttp({**CONF, "dahua_password": "clave-secreta-123"})
    assert "clave-secreta-123" not in repr(p.__dict__)
    assert "clave-secreta-123" not in repr(p)
    assert all("clave-secreta-123" != str(v) for v in vars(p).values())


def test_la_clave_sigue_siendo_usable():
    """Esconderla no sirve si se pierde."""
    p = DahuaHttp({**CONF, "dahua_password": "clave-secreta-123"})
    assert p._clave() == "clave-secreta-123"


# ── 7. Método de autenticación ───────────────────────────────────────────────

def test_metodo_15_es_facial():
    """Los 3787 registros atribuibles del equipo vienen con Method=15."""
    assert METODOS["15"] == "facial"
    assert _provee([MARCACION])._traducir(MARCACION)["metodo_autenticacion"] == "facial"


def test_metodo_desconocido_se_conserva_crudo():
    """Inventar una etiqueta sería peor que mostrar el número."""
    ev = _provee([])._traducir({**MARCACION, "Method": "99"})
    assert ev["metodo_autenticacion"] == "99"
