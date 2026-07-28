"""
Adaptadores de control de acceso: mock, CSV y el placeholder del Dahua.

El test que más importa es `test_placeholder_no_finge_funcionar`: el adaptador
real debe fallar RUIDOSAMENTE mientras no tengamos los datos del equipo. Una
lista vacía se confundiría con "no hubo eventos hoy" y enmascararía el problema
hasta que alguien notara que la asistencia lleva una semana en blanco.
"""
from datetime import date, datetime

import pytest

from backend.integrations.dahua.base import (
    EventoExterno, ProveedorControlAcceso, ProveedorNoConfigurado,
)
from backend.integrations.dahua.csv_provider import (
    CsvAccessControlProvider, parsear_fecha_hora,
)
from backend.integrations.dahua.dahua_placeholder import DahuaProviderPlaceholder
from backend.integrations.dahua.mock import MockAccessControlProvider


# ── Contrato ─────────────────────────────────────────────────────────────────

def test_mock_cumple_el_contrato():
    assert isinstance(MockAccessControlProvider(), ProveedorControlAcceso)


def test_csv_cumple_el_contrato():
    p = CsvAccessControlProvider(b"user id;time\n1001;2026-07-27 08:00:00\n")
    assert isinstance(p, ProveedorControlAcceso)


def test_placeholder_cumple_el_contrato():
    assert isinstance(DahuaProviderPlaceholder(), ProveedorControlAcceso)


def test_evento_se_convierte_al_payload_del_api():
    e = EventoExterno(id_externo="X1", id_empleado_externo="1001",
                      timestamp=datetime(2026, 7, 27, 8, 30),
                      direccion="entrada")
    p = e.a_payload()
    assert p["id_evento_externo"] == "X1"
    assert p["id_externo_empleado"] == "1001"
    assert p["event_timestamp"].startswith("2026-07-27T08:30")
    assert p["direccion_acceso"] == "entrada"


# ── Simulador ────────────────────────────────────────────────────────────────

def test_mock_genera_un_dia():
    m = MockAccessControlProvider(empleados=["1001", "1002"], caos=0)
    n = m.generar_dia(date(2026, 7, 27))
    assert n > 0
    assert m.obtener_eventos().eventos


def test_mock_es_determinista():
    """Misma semilla, mismos eventos. Sin esto, un test que falla no se
    puede reproducir."""
    a = MockAccessControlProvider(empleados=["1001"], semilla=7)
    b = MockAccessControlProvider(empleados=["1001"], semilla=7)
    a.generar_semana(date(2026, 7, 27))
    b.generar_semana(date(2026, 7, 27))
    ea = [(e.id_empleado_externo, e.timestamp, e.direccion)
          for e in a.obtener_eventos(limite=999).eventos]
    eb = [(e.id_empleado_externo, e.timestamp, e.direccion)
          for e in b.obtener_eventos(limite=999).eventos]
    assert ea == eb


def test_mock_sin_caos_es_limpio():
    """caos=0 debe dar días perfectos: sirve de línea base en los tests."""
    m = MockAccessControlProvider(empleados=["1001"], caos=0)
    m.generar_dia(date(2026, 7, 27), con_almuerzo=False)
    evs = m.obtener_eventos(limite=99).eventos
    assert [e.direccion for e in evs] == ["entrada", "salida"]


def test_mock_con_caos_produce_anomalias():
    """Con caos alto deben aparecer los defectos que tiene un equipo real."""
    m = MockAccessControlProvider(
        empleados=[f"10{i:02d}" for i in range(20)], caos=1.0, semilla=3)
    m.generar_semana(date(2026, 7, 27))
    evs = m.obtener_eventos(limite=9999).eventos
    assert any(e.resultado == "denegado" for e in evs), "faltan accesos denegados"
    assert any(e.id_empleado_externo == "9999" for e in evs), "falta el desconocido"


def test_mock_pagina_correctamente():
    m = MockAccessControlProvider(empleados=["1001", "1002", "1003"], caos=0)
    m.generar_semana(date(2026, 7, 27))
    p1 = m.obtener_eventos(limite=5)
    assert len(p1.eventos) == 5 and p1.hay_mas
    p2 = m.obtener_eventos(cursor=p1.cursor, limite=5)
    assert p2.eventos[0].timestamp >= p1.eventos[-1].timestamp


def test_mock_sin_direccion_marca_desconocida():
    """Si el equipo no distingue entrada de salida, hay que decirlo."""
    m = MockAccessControlProvider(empleados=["1001"], caos=0,
                                  distingue_direccion=False)
    m.generar_dia(date(2026, 7, 27))
    assert all(e.direccion == "desconocida" for e in m.obtener_eventos().eventos)
    assert m.info_dispositivo().distingue_direccion is False


# ── CSV ──────────────────────────────────────────────────────────────────────

CSV_BASICO = ("ID de usuario;Hora;Direccion\n"
              "1001;2026-07-27 08:30:00;Entrada\n"
              "1001;2026-07-27 17:05:00;Salida\n")


def test_csv_lee_lo_basico():
    p = CsvAccessControlProvider(CSV_BASICO.encode("utf-8"))
    evs = p.obtener_eventos().eventos
    assert len(evs) == 2
    assert evs[0].id_empleado_externo == "1001"
    assert evs[0].direccion == "entrada"
    assert evs[1].direccion == "salida"


@pytest.mark.parametrize("encabezado", [
    "User ID", "UserID", "ID de usuario", "Codigo", "Documento", "Card No",
])
def test_csv_reconoce_variantes_de_usuario(encabezado):
    datos = f"{encabezado};Hora\n1001;2026-07-27 08:00:00\n"
    p = CsvAccessControlProvider(datos.encode("utf-8"))
    assert p.obtener_eventos().eventos[0].id_empleado_externo == "1001"


def test_csv_con_coma_y_en_latin1():
    """Excel en Windows exporta en cp1252, y a veces con coma."""
    datos = "User ID,Time,Direction\n1001,2026-07-27 08:00:00,In\n"
    p = CsvAccessControlProvider(datos.encode("cp1252"))
    assert len(p.obtener_eventos().eventos) == 1


@pytest.mark.parametrize("crudo,esperado", [
    ("In", "entrada"), ("Entrada", "entrada"), ("Check In", "entrada"),
    ("Out", "salida"), ("Salida", "salida"), ("Egreso", "salida"),
    ("cualquier cosa", "desconocida"), ("", "desconocida"),
])
def test_csv_normaliza_direccion(crudo, esperado):
    datos = f"User ID;Time;Direction\n1001;2026-07-27 08:00:00;{crudo}\n"
    p = CsvAccessControlProvider(datos.encode("utf-8"))
    assert p.obtener_eventos().eventos[0].direccion == esperado


@pytest.mark.parametrize("valor,esperado", [
    ("2026-07-27 08:30:00", datetime(2026, 7, 27, 8, 30)),
    ("27/07/2026 08:30:00", datetime(2026, 7, 27, 8, 30)),
    ("2026/07/27 08:30:00", datetime(2026, 7, 27, 8, 30)),
    ("27-07-2026 08:30:00", datetime(2026, 7, 27, 8, 30)),
])
def test_csv_parsea_formatos_de_fecha(valor, esperado):
    assert parsear_fecha_hora(valor) == esperado


def test_csv_descarta_filas_sin_fecha_pero_no_revienta():
    datos = ("User ID;Time\n"
             "1001;2026-07-27 08:00:00\n"
             "1002;no es una fecha\n"
             ";2026-07-27 09:00:00\n")
    p = CsvAccessControlProvider(datos.encode("utf-8"))
    assert len(p.obtener_eventos().eventos) == 1
    assert p.descartados == 2


def test_csv_sin_columnas_obligatorias_falla_con_mensaje_util():
    with pytest.raises(Exception, match="columnas_no_encontradas"):
        CsvAccessControlProvider(b"Cargo;Area\nAsesora;Comercial\n")


def test_csv_lista_los_empleados_que_aparecen():
    datos = ("User ID;Time;Name\n1001;2026-07-27 08:00:00;Ana\n"
             "1002;2026-07-27 08:05:00;Luis\n1001;2026-07-27 17:00:00;Ana\n")
    p = CsvAccessControlProvider(datos.encode("utf-8"))
    assert {e.id_externo for e in p.listar_empleados()} == {"1001", "1002"}


def test_csv_ordena_por_fecha():
    datos = ("User ID;Time\n1001;2026-07-27 17:00:00\n1001;2026-07-27 08:00:00\n")
    p = CsvAccessControlProvider(datos.encode("utf-8"))
    evs = p.obtener_eventos().eventos
    assert evs[0].timestamp < evs[1].timestamp


# ── Placeholder del Dahua ────────────────────────────────────────────────────

def test_placeholder_no_finge_funcionar():
    """LA prueba de este archivo.

    Mientras no tengamos los datos del equipo, el adaptador debe fallar
    ruidosamente. Si devolviera [] se confundiría con 'no hubo eventos hoy' y
    nadie se enteraría hasta que la asistencia llevara una semana vacía.
    """
    p = DahuaProviderPlaceholder(host="192.168.1.50")
    for metodo in (p.info_dispositivo, p.salud, p.listar_empleados,
                   p.obtener_eventos):
        with pytest.raises(ProveedorNoConfigurado):
            metodo()


def test_placeholder_explica_que_falta():
    p = DahuaProviderPlaceholder(host="192.168.1.50")
    with pytest.raises(ProveedorNoConfigurado, match="modelo_exacto"):
        p.obtener_eventos()


def test_probar_conexion_si_responde_con_el_diagnostico():
    """La pantalla de dispositivos necesita mostrar QUÉ falta, no un error seco."""
    sin_host = DahuaProviderPlaceholder()
    assert sin_host.probar_conexion().ok is False
    assert "IP" in sin_host.probar_conexion().mensaje

    sin_protocolo = DahuaProviderPlaceholder(host="192.168.1.50")
    r = sin_protocolo.probar_conexion()
    assert r.ok is False
    assert "modelo" in r.mensaje.lower() or "protocolo" in r.mensaje.lower()


def test_la_contrasena_no_aparece_en_el_repr():
    """Un repr con la clave adentro termina en un log o en un traceback."""
    p = DahuaProviderPlaceholder(host="10.0.0.5", usuario="admin",
                                 password="SuperSecreta123")
    assert "SuperSecreta123" not in repr(p)
    assert "SuperSecreta123" not in str(p.__dict__)


def test_normalizar_evento_dahua():
    """La FORMA del evento sí la conocemos, aunque no el transporte."""
    e = DahuaProviderPlaceholder.normalizar_evento({
        "RecNo": 12345, "UserID": "1001",
        "CreateTime": "2026-07-27T08:30:00", "Direction": "1",
        "Status": 1, "DoorName": "Principal",
    })
    assert e.id_externo == "12345"
    assert e.id_empleado_externo == "1001"
    assert e.direccion == "entrada"
    assert e.resultado == "concedido"


def test_normalizar_evento_con_epoch():
    e = DahuaProviderPlaceholder.normalizar_evento({
        "UserID": "1001", "CreateTime": 1785000000, "Direction": "2",
    })
    assert e.direccion == "salida"
    assert isinstance(e.timestamp, datetime)


def test_normalizar_sin_timestamp_falla():
    with pytest.raises(Exception, match="timestamp"):
        DahuaProviderPlaceholder.normalizar_evento({"UserID": "1001"})
