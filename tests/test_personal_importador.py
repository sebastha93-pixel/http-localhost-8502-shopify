"""
Importador de empleados desde CSV/Excel.

Lo que más importa aquí es la fecha: en Colombia el formato es DD/MM/AAAA, y
leer '03/04/2026' como 4 de marzo en vez de 3 de abril le corre la antigüedad
a una persona. Cuando la lectura es ambigua, el importador avisa en vez de
decidir en silencio.
"""
from datetime import date

import pytest

from backend.services import personal_importador as imp


# ── Reconocimiento de columnas ───────────────────────────────────────────────

@pytest.mark.parametrize("encabezado", [
    "Nombre completo", "NOMBRES Y APELLIDOS", "nombre", "Empleado",
    "Nombre del Empleado", "TRABAJADOR",
])
def test_reconoce_variantes_de_nombre(encabezado):
    assert "nombre_completo" in imp.mapear_columnas([encabezado, "Cédula"])


@pytest.mark.parametrize("encabezado", [
    "Cédula", "CEDULA", "Documento", "Identificación", "No. Documento",
    "Nro Documento", "C.C.", "Número de identificación",
])
def test_reconoce_variantes_de_documento(encabezado):
    assert "numero_documento" in imp.mapear_columnas(["Nombre", encabezado])


@pytest.mark.parametrize("encabezado", [
    "Fecha de ingreso", "FECHA INGRESO", "Ingreso", "Fecha de vinculación",
    "Fecha de contratación",
])
def test_reconoce_variantes_de_fecha_ingreso(encabezado):
    assert "fecha_ingreso" in imp.mapear_columnas(["Nombre", "Cédula", encabezado])


def test_tildes_y_mayusculas_no_importan():
    m = imp.mapear_columnas(["NOMBRE COMPLETO", "Cédula", "Fecha De Ingreso"])
    assert set(m) >= {"nombre_completo", "numero_documento", "fecha_ingreso"}


def test_columnas_desconocidas_se_reportan():
    filas = [["Nombre", "Cédula", "Fecha ingreso", "Columna Rara"],
             ["Ana Pérez", "1017123456", "2026-01-15", "x"]]
    plan = imp.analizar(filas)
    assert "Columna Rara" in plan["columnas_ignoradas"]


# ── Limpieza de documento ────────────────────────────────────────────────────

@pytest.mark.parametrize("crudo,esperado", [
    ("1.017.123.456", "1017123456"),
    ("1017123456", "1017123456"),
    ("  1017 123 456 ", "1017123456"),
    ("900123456-7", "900123456"),        # NIT con dígito de verificación
    ("1,017,123,456", "1017123456"),
    ("", ""),
    (None, ""),
])
def test_limpiar_documento(crudo, esperado):
    assert imp.limpiar_documento(crudo) == esperado


# ── Fechas — lo más delicado ─────────────────────────────────────────────────

def test_fecha_iso():
    f, aviso = imp.parsear_fecha("2026-01-15")
    assert f == date(2026, 1, 15) and aviso is None


def test_fecha_colombiana_dia_mes():
    """25/12/2025 solo puede ser 25 de diciembre: sin ambigüedad."""
    f, aviso = imp.parsear_fecha("25/12/2025")
    assert f == date(2025, 12, 25) and aviso is None


def test_fecha_ambigua_avisa():
    """03/04/2026 se lee como 3 de abril (formato colombiano), pero avisa."""
    f, aviso = imp.parsear_fecha("03/04/2026")
    assert f == date(2026, 4, 3)
    assert aviso and "mes/día" in aviso


def test_fecha_imposible_como_dia_mes_se_reinterpreta():
    """'05/13/2026' no puede ser mes 13, así que se lee al revés — y se avisa,
    porque significa que el archivo NO usa el formato colombiano."""
    f, aviso = imp.parsear_fecha("05/13/2026")
    assert f == date(2026, 5, 13)
    assert "mes/día" in aviso


def test_fecha_con_anio_de_dos_digitos():
    f, _ = imp.parsear_fecha("15/01/26")
    assert f == date(2026, 1, 15)


def test_serial_de_excel():
    """Excel guarda fechas como días desde 1899-12-30."""
    f, aviso = imp.parsear_fecha("46037")
    assert f == date(2026, 1, 15)
    assert aviso is None


def test_objeto_date_pasa_directo():
    f, aviso = imp.parsear_fecha(date(2026, 1, 15))
    assert f == date(2026, 1, 15) and aviso is None


def test_fecha_ilegible_devuelve_aviso():
    f, aviso = imp.parsear_fecha("el año pasado")
    assert f is None and "no reconocido" in aviso


def test_fecha_vacia():
    assert imp.parsear_fecha("") == (None, None)
    assert imp.parsear_fecha(None) == (None, None)


# ── Normalizaciones ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("crudo,esperado", [
    ("CC", "CC"), ("C.C.", "CC"), ("Cédula de ciudadanía", "CC"),
    ("CE", "CE"), ("Cédula de extranjería", "CE"),
    ("PA", "PA"), ("Pasaporte", "PA"), ("", "CC"), (None, "CC"),
])
def test_tipo_documento(crudo, esperado):
    assert imp.normalizar_tipo_documento(crudo) == esperado


@pytest.mark.parametrize("crudo,esperado", [
    ("Indefinido", "termino_indefinido"),
    ("A TÉRMINO FIJO", "termino_fijo"),
    ("Obra o labor", "obra_labor"),
    ("Aprendizaje SENA", "termino_indefinido"),     # no exacto → default seguro
    ("Aprendiz", "aprendizaje"),
    ("", "termino_indefinido"),
])
def test_tipo_contrato(crudo, esperado):
    assert imp.normalizar_contrato(crudo) == esperado


def test_nombre_conserva_mayusculas():
    """No se 'arregla' el nombre: los apellidos compuestos salen mal."""
    assert imp.limpiar_nombre("MARCELA ARBOLEDA  NARANJO") == "MARCELA ARBOLEDA NARANJO"


# ── Lectura de archivo ───────────────────────────────────────────────────────

def test_csv_con_punto_y_coma():
    """El export colombiano usa ';' porque es el separador de lista es-CO."""
    filas = imp.leer_csv("Nombre;Cédula\nAna Pérez;1017123456\n".encode("utf-8"))
    assert filas[1] == ["Ana Pérez", "1017123456"]


def test_csv_con_coma():
    filas = imp.leer_csv(b"Nombre,Cedula\nAna,1017123456\n")
    assert filas[1] == ["Ana", "1017123456"]


def test_csv_en_latin1():
    """Excel en Windows exporta en cp1252, no UTF-8."""
    filas = imp.leer_csv("Nombre;Cédula\nJosé Muñoz;123456\n".encode("cp1252"))
    assert "José Muñoz" in filas[1][0]


def test_csv_con_bom():
    filas = imp.leer_csv("﻿Nombre;Cédula\nAna;123456\n".encode("utf-8"))
    assert filas[0][0] == "Nombre"


def test_xls_antiguo_da_mensaje_util():
    with pytest.raises(ValueError, match="guarda_como_xlsx_o_csv"):
        imp.leer(b"cualquier cosa", "empleados.xls")


# ── Análisis ─────────────────────────────────────────────────────────────────

CABECERA = ["Nombre completo", "Cédula", "Fecha de ingreso", "Cargo"]


def test_plan_basico():
    filas = [CABECERA,
             ["Ana Pérez", "1.017.123.456", "15/01/2024", "Asesora"],
             ["Luis Gómez", "71.234.567", "01/03/2025", "Cortador"]]
    plan = imp.analizar(filas)
    assert plan["total"] == 2
    assert len(plan["crear"]) == 2
    assert plan["crear"][0]["numero_documento"] == "1017123456"
    assert plan["crear"][0]["fecha_ingreso"] == "2024-01-15"
    assert not plan["errores"]


def test_falta_columna_obligatoria():
    with pytest.raises(ValueError, match="columnas_obligatorias_no_encontradas"):
        imp.analizar([["Cargo", "Área"], ["Asesora", "Comercial"]])


def test_archivo_vacio():
    with pytest.raises(ValueError, match="archivo_vacio"):
        imp.analizar([])


def test_fila_sin_documento_es_error():
    filas = [CABECERA, ["Ana Pérez", "", "15/01/2024", "Asesora"]]
    plan = imp.analizar(filas)
    assert plan["errores"][0]["error"] == "sin número de documento"
    assert plan["total"] == 0


def test_documento_repetido_se_detecta():
    filas = [CABECERA,
             ["Ana Pérez", "1017123456", "15/01/2024", "Asesora"],
             ["Ana P.",    "1017123456", "15/01/2024", "Asesora"]]
    plan = imp.analizar(filas)
    assert "repetido" in plan["errores"][0]["error"]
    assert len(plan["crear"]) == 1


def test_documento_muy_corto_se_rechaza():
    filas = [CABECERA, ["Ana", "123", "15/01/2024", "x"]]
    plan = imp.analizar(filas)
    assert "corto" in plan["errores"][0]["error"]


def test_sin_fecha_de_ingreso_es_error():
    filas = [CABECERA, ["Ana Pérez", "1017123456", "", "Asesora"]]
    plan = imp.analizar(filas)
    assert "ingreso" in plan["errores"][0]["error"]


def test_retiro_antes_del_ingreso_es_error():
    filas = [["Nombre", "Cédula", "Fecha ingreso", "Fecha retiro"],
             ["Ana", "1017123456", "15/01/2025", "15/01/2024"]]
    plan = imp.analizar(filas)
    assert "anterior al ingreso" in plan["errores"][0]["error"]


def test_con_retiro_queda_como_retirado():
    filas = [["Nombre", "Cédula", "Fecha ingreso", "Fecha retiro"],
             ["Ana", "1017123456", "15/01/2024", "30/06/2026"]]
    plan = imp.analizar(filas)
    assert plan["crear"][0]["estado_laboral"] == "retirado"


def test_filas_en_blanco_se_ignoran():
    filas = [CABECERA,
             ["Ana Pérez", "1017123456", "15/01/2024", "Asesora"],
             ["", "", "", ""]]
    plan = imp.analizar(filas)
    assert plan["total"] == 1 and not plan["errores"]


def test_fecha_futura_avisa_pero_no_bloquea():
    filas = [CABECERA, ["Ana", "1017123456", "01/01/2099", "x"]]
    plan = imp.analizar(filas)
    assert plan["total"] == 1
    assert any("futuro" in a["aviso"] for a in plan["avisos"])


# ── Idempotencia: existentes se actualizan, no se duplican ───────────────────

def test_existente_va_a_actualizar():
    existentes = {"1017123456": {"id": "E1", "nombre_completo": "Ana Pérez",
                                 "fecha_ingreso": "2024-01-15", "cargo": "Asesora"}}
    filas = [CABECERA, ["Ana Pérez", "1017123456", "15/01/2024", "Asesora"]]
    plan = imp.analizar(filas, existentes)
    assert not plan["crear"]
    assert len(plan["actualizar"]) == 1


def test_sin_cambios_no_reporta_cambios():
    """Volver a subir el mismo archivo no debe decir 'actualizar 21'."""
    existentes = {"1017123456": {"id": "E1", "nombre_completo": "Ana Pérez",
                                 "fecha_ingreso": "2024-01-15", "cargo": "Asesora",
                                 "estado_laboral": "activo",
                                 "tipo_contrato": "termino_indefinido"}}
    filas = [CABECERA, ["Ana Pérez", "1017123456", "15/01/2024", "Asesora"]]
    plan = imp.analizar(filas, existentes)
    assert plan["actualizar"][0]["_cambios"] == {}


def test_detecta_el_cambio_real():
    existentes = {"1017123456": {"id": "E1", "nombre_completo": "Ana Pérez",
                                 "fecha_ingreso": "2024-01-15", "cargo": "Asesora",
                                 "estado_laboral": "activo",
                                 "tipo_contrato": "termino_indefinido"}}
    filas = [CABECERA, ["Ana Pérez", "1017123456", "15/01/2024", "Administradora"]]
    plan = imp.analizar(filas, existentes)
    cambios = plan["actualizar"][0]["_cambios"]
    assert cambios["cargo"] == {"antes": "Asesora", "despues": "Administradora"}


# ── El archivo real de MALE DENIM ────────────────────────────────────────────

def test_ejemplo_realista_con_el_organigrama():
    """Simula el export de Siigo Nómina con gente del organigrama real."""
    filas = [
        ["NOMBRES Y APELLIDOS", "C.C.", "FECHA DE INGRESO", "CARGO", "ÁREA", "SEDE"],
        ["SEBASTIAN HURTADO ALVAREZ", "71.234.755", "01/02/2019", "Gerente general", "Administrativo", "Oficina administrativa"],
        ["MARCELA ARBOLEDA NARANJO", "1.017.321.821", "15/03/2023", "Administradora", "Tiendas físicas", "CC Plaza Arrayanes"],
        ["LAURA GARCIA VELEZ", "1.020.449.980", "02/05/2024", "Auxiliar administrativo", "Administrativo", "Oficina administrativa"],
        ["", "", "", "", "", ""],
    ]
    plan = imp.analizar(filas)
    assert plan["total"] == 3
    assert not plan["errores"]
    assert plan["crear"][0]["numero_documento"] == "71234755"
    assert plan["crear"][1]["fecha_ingreso"] == "2023-03-15"
    assert plan["crear"][1]["_sede_texto"] == "CC Plaza Arrayanes"
    assert set(plan["columnas_detectadas"]) >= {
        "nombre_completo", "numero_documento", "fecha_ingreso", "cargo", "area", "sede"}
