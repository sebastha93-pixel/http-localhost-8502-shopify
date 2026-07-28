"""Lee eventos de un CSV exportado del Dahua o de SmartPSS.

Es el respaldo cuando el conector estuvo caído: se exportan los eventos del
periodo perdido y se cargan. Sin esto, una caída de fin de semana significa
perder esos días de asistencia.
"""
from __future__ import annotations

import csv
import io
import re
import unicodedata
from datetime import datetime
from pathlib import Path

AQUI = Path(__file__).resolve().parent.parent

ALIAS = {
    "id_empleado": ("id de usuario", "user id", "userid", "id usuario",
                    "employee id", "codigo", "card no", "documento"),
    "fecha_hora":  ("hora", "time", "fecha y hora", "date time", "datetime",
                    "fecha", "event time"),
    "direccion":   ("direccion", "direction", "tipo", "type", "in out", "estado"),
    "id_evento":   ("id", "id de evento", "event id", "record id", "no"),
    "puerta":      ("puerta", "door", "door name", "dispositivo", "canal"),
}


def _norm(t) -> str:
    s = str(t or "").strip().lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", s)).strip()


def _fecha(v):
    s = str(v or "").strip()
    for f in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y %H:%M:%S",
              "%d/%m/%Y %H:%M", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s[:19] if len(s) > 19 else s, f)
        except ValueError:
            continue
    return None


class CsvLocal:
    def __init__(self, conf: dict):
        ruta = Path(conf.get("ruta") or "eventos.csv")
        if not ruta.is_absolute():
            ruta = AQUI / ruta
        if not ruta.exists():
            raise SystemExit(f"✗ No existe el archivo CSV: {ruta}")
        self._eventos = self._leer(ruta.read_bytes())

    def _leer(self, contenido: bytes) -> list[dict]:
        texto = None
        for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
            try:
                texto = contenido.decode(enc); break
            except UnicodeDecodeError:
                continue
        if texto is None:
            raise SystemExit("✗ No se pudo leer el archivo (codificación)")

        sep = ";" if texto[:2000].count(";") > texto[:2000].count(",") else ","
        filas = [f for f in csv.reader(io.StringIO(texto), delimiter=sep) if any(f)]
        if not filas:
            raise SystemExit("✗ El archivo está vacío")

        mapa = {}
        for i, h in enumerate(filas[0]):
            n = _norm(h)
            for campo, alias in ALIAS.items():
                if campo not in mapa and any(n == _norm(a) for a in alias):
                    mapa[campo] = i
        for c in ("id_empleado", "fecha_hora"):
            if c not in mapa:
                raise SystemExit(
                    f"✗ No encontré la columna '{c}'. "
                    f"Encabezados: {', '.join(h for h in filas[0] if h)}")

        def v(f, c):
            i = mapa.get(c)
            return f[i] if i is not None and i < len(f) else None

        out, malos = [], 0
        for f in filas[1:]:
            emp = str(v(f, "id_empleado") or "").strip()
            t = _fecha(v(f, "fecha_hora"))
            if not emp or not t:
                malos += 1
                continue
            d = _norm(v(f, "direccion"))
            direccion = ("entrada" if d.startswith(("in", "entrada", "ingreso"))
                         else "salida" if d.startswith(("out", "salida", "egreso"))
                         else "desconocida")
            out.append({
                "id_evento_externo": str(v(f, "id_evento") or "").strip() or None,
                "id_externo_empleado": emp,
                "event_timestamp": t.isoformat(),
                "direccion_acceso": direccion,
                "resultado_acceso": "concedido",
                "nombre_puerta": str(v(f, "puerta") or "").strip() or None,
                "raw_payload_json": {"origen": "csv"},
            })
        if malos:
            print(f"  ⚠ {malos} fila(s) sin fecha o sin usuario: se omitieron")
        out.sort(key=lambda e: e["event_timestamp"])
        return out

    def obtener_eventos(self, cursor=None, limite=100) -> dict:
        i = int(cursor or 0)
        pagina = self._eventos[i:i + limite]
        return {"eventos": pagina, "cursor": str(i + len(pagina)),
                "hay_mas": i + len(pagina) < len(self._eventos)}

    def salud(self) -> dict:
        return {"en_linea": True,
                "ultimo_evento_at": self._eventos[-1]["event_timestamp"]
                                    if self._eventos else None}
