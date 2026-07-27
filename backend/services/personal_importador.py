"""
backend.services.personal_importador — Carga masiva de empleados desde CSV/Excel.

Pensado para tragarse el export de Siigo Nómina tal como salga, sin pedirle a
nadie que arregle el archivo antes.

Dos capas
─────────
  · `analizar()` es PURO: recibe filas, devuelve un plan. Sin base de datos.
  · `aplicar()` ejecuta ese plan contra Supabase.

Siempre en dos pasos
────────────────────
Nunca se importa a ciegas. Primero se previsualiza (qué se crea, qué se
actualiza, qué está mal y por qué), y solo después se confirma. Importar 21
cédulas equivocadas es fácil de hacer y molesto de deshacer.

Idempotente
───────────
La llave es (tipo_documento, numero_documento). Volver a subir el mismo
archivo actualiza en vez de duplicar.
"""
from __future__ import annotations

import csv
import io
import logging
import re
import unicodedata
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Optional

log = logging.getLogger(__name__)


# ── Reconocimiento de columnas ───────────────────────────────────────────────
# Cada export nombra las cosas distinto. En vez de exigir un formato, se
# reconocen las variantes que realmente aparecen.

_ALIAS: dict[str, tuple[str, ...]] = {
    "nombre_completo": (
        "nombre completo", "nombres y apellidos", "nombre", "empleado",
        "nombre del empleado", "nombres", "apellidos y nombres",
        "nombre y apellido", "trabajador",
    ),
    "numero_documento": (
        "cedula", "documento", "identificacion", "numero de documento",
        "no documento", "nro documento", "num documento", "cc", "nit",
        "numero de identificacion", "documento de identidad", "id",
    ),
    "tipo_documento": (
        "tipo de documento", "tipo documento", "tipo doc", "tipo de identificacion",
    ),
    "fecha_ingreso": (
        "fecha de ingreso", "fecha ingreso", "ingreso", "fecha de admision",
        "fecha admision", "fecha de vinculacion", "fecha vinculacion",
        "fecha de contratacion",
    ),
    "fecha_retiro": (
        "fecha de retiro", "fecha retiro", "retiro", "fecha de salida",
        "fecha terminacion",
    ),
    "cargo": ("cargo", "puesto", "posicion", "denominacion del cargo", "rol"),
    "area": ("area", "departamento", "seccion", "centro de costo", "dependencia"),
    "sede": ("sede", "sucursal", "tienda", "ubicacion", "centro de trabajo"),
    "email": ("email", "correo", "correo electronico", "e-mail", "mail"),
    "telefono": ("telefono", "celular", "movil", "tel", "numero de contacto"),
    "tipo_contrato": ("tipo de contrato", "tipo contrato", "contrato", "modalidad"),
    "codigo_empleado": ("codigo", "codigo empleado", "codigo de empleado", "cod"),
}

_TIPOS_DOC = {
    "cc": "CC", "c.c.": "CC", "cedula": "CC", "cedula de ciudadania": "CC",
    "ce": "CE", "c.e.": "CE", "cedula de extranjeria": "CE",
    "pa": "PA", "pasaporte": "PA",
    "pep": "PEP", "ppt": "PPT",
    "ti": "TI", "tarjeta de identidad": "TI",
    "nit": "NIT",
}

_CONTRATOS = {
    "indefinido": "termino_indefinido", "termino indefinido": "termino_indefinido",
    "a termino indefinido": "termino_indefinido",
    "fijo": "termino_fijo", "termino fijo": "termino_fijo",
    "a termino fijo": "termino_fijo",
    "obra": "obra_labor", "obra o labor": "obra_labor", "obra labor": "obra_labor",
    "aprendizaje": "aprendizaje", "sena": "aprendizaje", "aprendiz": "aprendizaje",
    "prestacion de servicios": "prestacion_servicios",
    "servicios": "prestacion_servicios",
}


def _norm(txt: Any) -> str:
    """Minúsculas, sin tildes, sin puntuación, espacios colapsados.

    El colapso final importa: 'No.  Documento' quedaría con doble espacio y no
    casaría con ningún alias.
    """
    s = str(txt or "").strip().lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _compacto(txt: Any) -> str:
    """Como _norm pero sin espacios: hace que 'C.C.' case con 'cc'."""
    return _norm(txt).replace(" ", "")


def mapear_columnas(encabezados: Iterable[str]) -> dict[str, int]:
    """Encabezado del archivo → campo interno. Devuelve {campo: índice}.

    Compara en dos formas —con y sin espacios— porque los encabezados reales
    vienen con puntuación arbitraria: 'C.C.', 'No. Documento', 'Nro. Doc'.
    """
    mapa: dict[str, int] = {}
    for i, h in enumerate(encabezados):
        n, c = _norm(h), _compacto(h)
        if not n:
            continue
        for campo, alias in _ALIAS.items():
            if campo in mapa:
                continue
            if any(n == _norm(a) or c == _compacto(a) for a in alias):
                mapa[campo] = i
                break
    return mapa


# ── Limpieza de valores ──────────────────────────────────────────────────────

def limpiar_documento(v: Any) -> str:
    """'1.017.123.456' → '1017123456'. Quita puntos, comas, espacios y guiones.

    También corta el dígito de verificación si viene como '900123456-7'.
    """
    s = str(v or "").strip()
    if not s:
        return ""
    s = s.split("-")[0]                       # NIT con DV
    s = re.sub(r"[^\d]", "", s)
    return s


def parsear_fecha(v: Any) -> tuple[Optional[date], Optional[str]]:
    """Devuelve (fecha, aviso). El aviso señala ambigüedad, no error.

    En Colombia el formato es DD/MM/AAAA. '03/04/2026' es 3 de abril, no 4 de
    marzo. Cuando ambos números son ≤ 12 la lectura es ambigua y se avisa,
    porque una fecha de ingreso mal leída corre la antigüedad de una persona.
    """
    if v in (None, ""):
        return None, None
    if isinstance(v, datetime):
        return v.date(), None
    if isinstance(v, date):
        return v, None

    s = str(v).strip()

    # Serial de Excel (días desde 1899-12-30)
    if re.fullmatch(r"\d{5}", s):
        try:
            return date(1899, 12, 30) + timedelta(days=int(s)), None
        except Exception:
            pass

    # ISO: 2026-07-27
    m = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})", s)
    if m:
        try:
            return date(int(m[1]), int(m[2]), int(m[3])), None
        except ValueError:
            return None, f"fecha fuera de rango: {s}"

    # DD/MM/AAAA — el formato colombiano
    m = re.match(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})", s)
    if m:
        d, mes, a = int(m[1]), int(m[2]), int(m[3])
        if a < 100:
            a += 2000 if a < 70 else 1900
        aviso = None
        if d <= 12 and mes <= 12 and d != mes:
            aviso = (f"'{s}' se leyó como {d}/{mes} (día/mes). "
                     f"Si el archivo usa mes/día, sería {mes}/{d}")
        try:
            return date(a, mes, d), aviso
        except ValueError:
            # Puede que sí fuera MM/DD
            try:
                return date(a, d, mes), f"'{s}' solo es válida leída como mes/día"
            except ValueError:
                return None, f"fecha inválida: {s}"

    return None, f"formato de fecha no reconocido: {s}"


def normalizar_tipo_documento(v: Any) -> str:
    return _TIPOS_DOC.get(_norm(v), "CC")


def normalizar_contrato(v: Any) -> str:
    n = _norm(v)
    if not n:
        return "termino_indefinido"
    return _CONTRATOS.get(n, "termino_indefinido")


def limpiar_nombre(v: Any) -> str:
    """Colapsa espacios. NO cambia mayúsculas: 'MARCELA ARBOLEDA  NARANJO'
    se queda como está — normalizar apellidos compuestos sale mal."""
    return re.sub(r"\s+", " ", str(v or "").strip())


# ── Lectura del archivo ──────────────────────────────────────────────────────

def leer_csv(contenido: bytes) -> list[list[str]]:
    """Lee CSV detectando separador y codificación.

    El export colombiano suele venir con ';' y en cp1252 o latin-1, no UTF-8.
    """
    texto = None
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            texto = contenido.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if texto is None:
        raise ValueError("no_se_pudo_decodificar_el_archivo")

    muestra = texto[:4000]
    try:
        sep = csv.Sniffer().sniff(muestra, delimiters=";,\t|").delimiter
    except csv.Error:
        sep = ";" if muestra.count(";") > muestra.count(",") else ","

    return [f for f in csv.reader(io.StringIO(texto), delimiter=sep) if any(f)]


def leer_excel(contenido: bytes) -> list[list[Any]]:
    """Lee la primera hoja de un .xlsx con openpyxl (ya es dependencia)."""
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(contenido), read_only=True, data_only=True)
    hoja = wb[wb.sheetnames[0]]
    filas = [list(f) for f in hoja.iter_rows(values_only=True)]
    wb.close()
    return [f for f in filas if any(c not in (None, "") for c in f)]


def leer(contenido: bytes, nombre_archivo: str = "") -> list[list[Any]]:
    if nombre_archivo.lower().endswith((".xlsx", ".xlsm")):
        return leer_excel(contenido)
    if nombre_archivo.lower().endswith(".xls"):
        raise ValueError("formato_xls_antiguo_no_soportado:guarda_como_xlsx_o_csv")
    return leer_csv(contenido)


# ── Análisis (PURO) ──────────────────────────────────────────────────────────

def analizar(filas: list[list[Any]],
             existentes: Optional[dict[str, dict]] = None) -> dict:
    """Convierte filas crudas en un plan revisable. Sin tocar la base.

    Args:
        existentes: {numero_documento_limpio: empleado} ya en el sistema.

    Returns:
        {columnas_detectadas, columnas_ignoradas, crear, actualizar,
         errores, avisos, total}
    """
    existentes = existentes or {}
    if not filas:
        raise ValueError("archivo_vacio")

    encabezados = [str(c or "") for c in filas[0]]
    mapa = mapear_columnas(encabezados)

    faltan = [c for c in ("nombre_completo", "numero_documento") if c not in mapa]
    if faltan:
        raise ValueError(
            f"columnas_obligatorias_no_encontradas:{','.join(faltan)}. "
            f"Encabezados leídos: {', '.join(h for h in encabezados if h)[:200]}")

    crear, actualizar, errores, avisos = [], [], [], []
    vistos: dict[str, int] = {}

    def val(fila, campo):
        i = mapa.get(campo)
        return fila[i] if i is not None and i < len(fila) else None

    for n, fila in enumerate(filas[1:], start=2):
        nombre = limpiar_nombre(val(fila, "nombre_completo"))
        doc = limpiar_documento(val(fila, "numero_documento"))

        if not nombre and not doc:
            continue                                    # fila en blanco
        if not nombre:
            errores.append({"fila": n, "error": "sin nombre", "documento": doc})
            continue
        if not doc:
            errores.append({"fila": n, "error": "sin número de documento",
                            "nombre": nombre})
            continue
        if len(doc) < 5:
            errores.append({"fila": n, "nombre": nombre,
                            "error": f"documento sospechosamente corto: {doc}"})
            continue
        if doc in vistos:
            errores.append({"fila": n, "nombre": nombre,
                            "error": f"documento repetido (ya venía en la fila {vistos[doc]})"})
            continue
        vistos[doc] = n

        ingreso, aviso_i = parsear_fecha(val(fila, "fecha_ingreso"))
        retiro, aviso_r = parsear_fecha(val(fila, "fecha_retiro"))
        for a in (aviso_i, aviso_r):
            if a:
                avisos.append({"fila": n, "nombre": nombre, "aviso": a})

        if not ingreso:
            errores.append({"fila": n, "nombre": nombre,
                            "error": "fecha de ingreso ausente o ilegible"})
            continue
        if ingreso > date.today():
            avisos.append({"fila": n, "nombre": nombre,
                           "aviso": f"fecha de ingreso en el futuro: {ingreso}"})
        if retiro and retiro < ingreso:
            errores.append({"fila": n, "nombre": nombre,
                            "error": "fecha de retiro anterior al ingreso"})
            continue

        registro = {
            "fila":             n,
            "nombre_completo":  nombre,
            "tipo_documento":   normalizar_tipo_documento(val(fila, "tipo_documento")),
            "numero_documento": doc,
            "fecha_ingreso":    ingreso.isoformat(),
            "fecha_retiro":     retiro.isoformat() if retiro else None,
            "estado_laboral":   "retirado" if retiro else "activo",
            "cargo":            limpiar_nombre(val(fila, "cargo")) or None,
            "email":            (str(val(fila, "email") or "").strip() or None),
            "telefono":         (str(val(fila, "telefono") or "").strip() or None),
            "tipo_contrato":    normalizar_contrato(val(fila, "tipo_contrato")),
            "_area_texto":      limpiar_nombre(val(fila, "area")) or None,
            "_sede_texto":      limpiar_nombre(val(fila, "sede")) or None,
        }
        cod = limpiar_nombre(val(fila, "codigo_empleado"))
        if cod:
            registro["codigo_empleado"] = cod

        if doc in existentes:
            registro["_id_existente"] = existentes[doc]["id"]
            registro["_cambios"] = _cambios(existentes[doc], registro)
            actualizar.append(registro)
        else:
            crear.append(registro)

    return {
        "columnas_detectadas": {k: encabezados[v] for k, v in mapa.items()},
        "columnas_ignoradas": [h for i, h in enumerate(encabezados)
                               if h and i not in mapa.values()],
        "crear": crear,
        "actualizar": actualizar,
        "errores": errores,
        "avisos": avisos,
        "total": len(crear) + len(actualizar),
    }


def _cambios(actual: dict, nuevo: dict) -> dict:
    """Qué cambiaría en un empleado que ya existe. Para que la vista previa
    no diga 'actualizar 21' cuando en realidad no cambia nada."""
    campos = ("nombre_completo", "fecha_ingreso", "fecha_retiro", "cargo",
              "email", "telefono", "tipo_contrato", "estado_laboral")
    d = {}
    for c in campos:
        viejo, nvo = actual.get(c), nuevo.get(c)
        if nvo is not None and str(viejo or "")[:10] != str(nvo or "")[:10]:
            d[c] = {"antes": viejo, "despues": nvo}
    return d


# ── Aplicación ───────────────────────────────────────────────────────────────

def previsualizar(contenido: bytes, nombre_archivo: str = "") -> dict:
    """Paso 1: lee el archivo y devuelve el plan, sin escribir nada."""
    from backend.services import personal_empleados as emp_svc

    filas = leer(contenido, nombre_archivo)
    existentes = {}
    for e in emp_svc.listar(limit=500):
        doc = limpiar_documento(e.get("numero_documento"))
        if doc:
            existentes[doc] = e
    return analizar(filas, existentes)


def aplicar(plan: dict, *, actor: str, actualizar_existentes: bool = True) -> dict:
    """Paso 2: ejecuta el plan ya revisado.

    Resuelve área y sede por NOMBRE contra los catálogos; si no coincide, deja
    el campo vacío y lo reporta, en vez de inventar una sede nueva.
    """
    from backend.services import personal_empleados as emp_svc
    from backend.services import personal_organizacion as org_svc

    areas = {_norm(a["nombre"]): a["id"] for a in org_svc.listar_areas()}
    sedes = {_norm(s["nombre"]): s["id"] for s in org_svc.listar_sedes()}

    creados, actualizados, fallidos, sin_resolver = [], [], [], []

    def resolver(reg):
        campos = {k: v for k, v in reg.items()
                  if not k.startswith("_") and k != "fila"}
        for texto, catalogo, campo in ((reg.get("_area_texto"), areas, "area_id"),
                                       (reg.get("_sede_texto"), sedes, "sede_id")):
            if not texto:
                continue
            encontrado = catalogo.get(_norm(texto))
            if encontrado:
                campos[campo] = encontrado
            else:
                sin_resolver.append({"nombre": reg["nombre_completo"],
                                     "valor": texto, "campo": campo})
        return campos

    for reg in plan.get("crear", []):
        try:
            creados.append(emp_svc.crear(actor=actor, **resolver(reg)))
        except Exception as e:
            fallidos.append({"fila": reg.get("fila"), "nombre": reg["nombre_completo"],
                             "error": str(e)[:200]})

    if actualizar_existentes:
        for reg in plan.get("actualizar", []):
            if not reg.get("_cambios"):
                continue                       # no cambia nada: no se toca
            try:
                campos = resolver(reg)
                campos.pop("numero_documento", None)   # la llave no se reescribe
                campos.pop("tipo_documento", None)
                campos.pop("codigo_empleado", None)
                actualizados.append(
                    emp_svc.actualizar(reg["_id_existente"], actor=actor, **campos))
            except Exception as e:
                fallidos.append({"fila": reg.get("fila"),
                                 "nombre": reg["nombre_completo"],
                                 "error": str(e)[:200]})

    return {
        "creados": len(creados),
        "actualizados": len(actualizados),
        "omitidos": len([r for r in plan.get("actualizar", []) if not r.get("_cambios")]),
        "fallidos": fallidos,
        "sin_resolver": sin_resolver,
    }
