"""
backend.integrations.dahua.csv_provider — Eventos desde archivo.

Dos usos, ambos reales:

  1. **Carga histórica.** Antes de conectar el equipo se puede cargar lo que
     ya tiene registrado, y el motor calcula el pasado.
  2. **Respaldo cuando el conector falla.** Si el agente local se cae un fin
     de semana, se exportan los eventos desde SmartPSS y se suben. Sin esto,
     una caída del conector significa perder días de asistencia.

Es tolerante con el formato porque el export de un Dahua no lo controlamos:
reconoce variantes de encabezado, separadores y codificaciones, igual que el
importador de empleados.
"""
from __future__ import annotations

import csv
import io
import re
import unicodedata
from datetime import datetime
from typing import Any, Optional

from backend.integrations.dahua.base import (
    EmpleadoExterno, ErrorProveedor, EventoExterno, InfoDispositivo,
    LoteEventos, ResultadoConexion, SaludDispositivo,
)

# El export de Dahua/SmartPSS cambia de nombres según versión e idioma.
_ALIAS = {
    "id_empleado": ("id de usuario", "user id", "userid", "id usuario",
                    "numero de usuario", "employee id", "id empleado",
                    "codigo", "card no", "no de tarjeta", "documento"),
    "fecha_hora":  ("hora", "time", "fecha y hora", "date time", "datetime",
                    "fecha", "event time", "hora del evento", "tiempo"),
    "direccion":   ("direccion", "direction", "tipo", "type", "in out",
                    "entrada salida", "estado", "attendance status"),
    "nombre":      ("nombre", "name", "usuario", "user name", "nombre de usuario"),
    "resultado":   ("resultado", "result", "estado del evento", "verificacion"),
    "puerta":      ("puerta", "door", "door name", "dispositivo", "device",
                    "canal", "channel"),
    "metodo":      ("metodo", "method", "tipo de verificacion",
                    "verification mode", "modo"),
    "id_evento":   ("id", "id de evento", "event id", "record id", "no"),
}

_ENTRADA = {"in", "entrada", "ingreso", "entry", "check in", "check-in", "e",
            "0", "acceso", "salir no"}
_SALIDA = {"out", "salida", "egreso", "exit", "check out", "check-out", "s", "1"}


def _norm(t: Any) -> str:
    s = str(t or "").strip().lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def mapear_columnas(encabezados: list[str]) -> dict[str, int]:
    mapa: dict[str, int] = {}
    for i, h in enumerate(encabezados):
        n = _norm(h)
        if not n:
            continue
        for campo, alias in _ALIAS.items():
            if campo in mapa:
                continue
            if any(n == _norm(a) for a in alias):
                mapa[campo] = i
                break
    return mapa


def parsear_fecha_hora(v: Any) -> Optional[datetime]:
    """Los equipos escriben la fecha de mil formas. Se prueban las comunes.

    OJO: se asume día/mes (formato colombiano) cuando hay ambigüedad, igual
    que en el importador de empleados.
    """
    if isinstance(v, datetime):
        return v
    s = str(v or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y/%m/%d %H:%M:%S",
                "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d-%m-%Y %H:%M:%S",
                "%Y-%m-%d %H:%M", "%m/%d/%Y %H:%M:%S"):
        try:
            return datetime.strptime(s[:19] if len(s) > 19 else s, fmt)
        except ValueError:
            continue
    try:
        from backend.core.timeutils import parse_iso
        return parse_iso(s).replace(tzinfo=None)
    except Exception:
        return None


def _direccion(v: Any) -> str:
    n = _norm(v)
    if not n:
        return "desconocida"
    if n in _ENTRADA or "entrada" in n or n.startswith("in"):
        return "entrada"
    if n in _SALIDA or "salida" in n or n.startswith("out"):
        return "salida"
    return "desconocida"


def _resultado(v: Any) -> str:
    n = _norm(v)
    if not n:
        return "concedido"
    if any(x in n for x in ("dene", "fail", "fallo", "rechaz", "invalid")):
        return "denegado"
    if any(x in n for x in ("conce", "success", "ok", "exito", "valid", "normal")):
        return "concedido"
    return "desconocido"


class CsvAccessControlProvider:
    """Lee eventos de un CSV exportado del equipo o de SmartPSS."""

    nombre = "csv"

    def __init__(self, contenido: bytes, *, nombre_archivo: str = ""):
        self.nombre_archivo = nombre_archivo
        self._eventos = self._parsear(contenido)

    # ── Contrato ─────────────────────────────────────────────────────────

    def probar_conexion(self) -> ResultadoConexion:
        return ResultadoConexion(True, f"{len(self._eventos)} eventos leídos")

    def info_dispositivo(self) -> InfoDispositivo:
        return InfoDispositivo(fabricante="CSV", modelo=self.nombre_archivo or "archivo",
                               distingue_direccion=any(
                                   e.direccion != "desconocida" for e in self._eventos))

    def salud(self) -> SaludDispositivo:
        ultimo = max((e.timestamp for e in self._eventos), default=None)
        return SaludDispositivo(en_linea=True, ultimo_evento_at=ultimo,
                                mensaje="archivo")

    def listar_empleados(self) -> list[EmpleadoExterno]:
        vistos: dict[str, str] = {}
        for e in self._eventos:
            vistos.setdefault(e.id_empleado_externo,
                              (e.crudo or {}).get("nombre") or "")
        return [EmpleadoExterno(id_externo=k, nombre=v or None)
                for k, v in vistos.items()]

    def obtener_eventos(self, cursor: Optional[str] = None,
                        limite: int = 200) -> LoteEventos:
        desde = int(cursor or 0)
        pagina = self._eventos[desde:desde + limite]
        nuevo = desde + len(pagina)
        return LoteEventos(pagina, str(nuevo), nuevo < len(self._eventos))

    # ── Parseo ───────────────────────────────────────────────────────────

    def _parsear(self, contenido: bytes) -> list[EventoExterno]:
        texto = None
        for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
            try:
                texto = contenido.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if texto is None:
            raise ErrorProveedor("no_se_pudo_decodificar_el_archivo")

        muestra = texto[:4000]
        try:
            sep = csv.Sniffer().sniff(muestra, delimiters=";,\t|").delimiter
        except csv.Error:
            sep = ";" if muestra.count(";") > muestra.count(",") else ","

        filas = [f for f in csv.reader(io.StringIO(texto), delimiter=sep) if any(f)]
        if not filas:
            raise ErrorProveedor("archivo_vacio")

        mapa = mapear_columnas(filas[0])
        faltan = [c for c in ("id_empleado", "fecha_hora") if c not in mapa]
        if faltan:
            raise ErrorProveedor(
                f"columnas_no_encontradas:{','.join(faltan)}. "
                f"Encabezados: {', '.join(h for h in filas[0] if h)[:200]}")

        def val(f, campo):
            i = mapa.get(campo)
            return f[i] if i is not None and i < len(f) else None

        eventos, descartados = [], 0
        for fila in filas[1:]:
            emp = str(val(fila, "id_empleado") or "").strip()
            ts = parsear_fecha_hora(val(fila, "fecha_hora"))
            if not emp or not ts:
                descartados += 1
                continue
            eventos.append(EventoExterno(
                id_externo=(str(val(fila, "id_evento") or "").strip() or None),
                id_empleado_externo=emp,
                timestamp=ts,
                direccion=_direccion(val(fila, "direccion")),
                resultado=_resultado(val(fila, "resultado")),
                metodo=(str(val(fila, "metodo") or "").strip() or None),
                puerta=(str(val(fila, "puerta") or "").strip() or None),
                crudo={"origen": "csv", "archivo": self.nombre_archivo,
                       "nombre": str(val(fila, "nombre") or "").strip() or None},
            ))

        self.descartados = descartados
        eventos.sort(key=lambda e: e.timestamp)
        return eventos
