#!/usr/bin/env python3
"""
Conector Dahua → MALE DENIM OS

Corre en un equipo DENTRO de la red de la empresa, lee las marcaciones del
dispositivo de control de acceso y las envía al sistema.

Calca el patrón del agente de impresión que ya opera en la oficina: Python sin
librerías externas, config.json, bucle con reintento. Si ese funciona ahí,
este también.

  Dahua (LAN privada) ──► conector ──► cola SQLite ──HTTPS──► MALE DENIM OS

El Dahua NUNCA se expone a internet: solo hay tráfico SALIENTE del conector
hacia el sistema. No hay puertos abiertos ni redirección.

Garantías
─────────
  · Sin duplicados  — clave de idempotencia + índice único del lado del servidor
  · Sin pérdida     — cola en SQLite; se borra solo cuando el servidor confirma
  · Tolera caídas   — si no hay internet, encola y reintenta con espera creciente
  · Sin secretos en claro en los logs

Instalación
───────────
  1. Copia esta carpeta al equipo (Python 3.8+, sin librerías)
  2. Crea config.json desde config.example.json
  3. Arranca: python3 conector.py
     Arranque automático: LaunchAgent en Mac, .bat en shell:startup en Windows
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

AQUI = Path(__file__).resolve().parent
DB = AQUI / "cola.db"
LOG = AQUI / "conector.log"
VERSION = "1.0.0"


def log(msg: str) -> None:
    linea = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(linea, flush=True)
    try:
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(linea + "\n")
    except Exception:
        pass          # nunca dejar que el log tumbe el conector


def cargar_config() -> dict:
    ruta = AQUI / "config.json"
    if not ruta.exists():
        log("✗ Falta config.json. Cópialo de config.example.json y complétalo.")
        sys.exit(1)
    conf = json.loads(ruta.read_text(encoding="utf-8"))
    for k in ("backend_url", "device_token", "dispositivo_id"):
        if not conf.get(k):
            log(f"✗ Falta '{k}' en config.json")
            sys.exit(1)
    conf.setdefault("proveedor", "mock")
    conf.setdefault("poll_seconds", 60)
    conf.setdefault("lote", 100)
    return conf


# ── Cola local ───────────────────────────────────────────────────────────────

def abrir_cola() -> sqlite3.Connection:
    """SQLite local: lo que garantiza que una caída de internet no pierda nada."""
    cx = sqlite3.connect(DB)
    cx.execute("""
      CREATE TABLE IF NOT EXISTS pendientes (
        clave      TEXT PRIMARY KEY,   -- id externo o hash: evita reencolar
        payload    TEXT NOT NULL,
        creado_en  TEXT NOT NULL,
        intentos   INTEGER NOT NULL DEFAULT 0,
        ultimo_error TEXT
      )""")
    cx.execute("""
      CREATE TABLE IF NOT EXISTS estado (
        clave TEXT PRIMARY KEY, valor TEXT
      )""")
    cx.commit()
    return cx


def leer_estado(cx, clave: str, defecto=None):
    r = cx.execute("SELECT valor FROM estado WHERE clave=?", (clave,)).fetchone()
    return r[0] if r else defecto


def guardar_estado(cx, clave: str, valor: str) -> None:
    cx.execute("INSERT INTO estado(clave,valor) VALUES(?,?) "
               "ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor",
               (clave, valor))
    cx.commit()


def encolar(cx, eventos: list[dict]) -> int:
    """Mete eventos en la cola. INSERT OR IGNORE: reencolar no duplica."""
    n = 0
    for e in eventos:
        clave = e.get("id_evento_externo") or (
            f"{e.get('id_externo_empleado')}|{e.get('event_timestamp')}")
        cur = cx.execute(
            "INSERT OR IGNORE INTO pendientes(clave,payload,creado_en) VALUES(?,?,?)",
            (clave, json.dumps(e, ensure_ascii=False),
             datetime.now(timezone.utc).isoformat()))
        n += cur.rowcount
    cx.commit()
    return n


def pendientes(cx, limite: int) -> list[tuple[str, dict]]:
    filas = cx.execute(
        "SELECT clave,payload FROM pendientes ORDER BY creado_en LIMIT ?",
        (limite,)).fetchall()
    return [(c, json.loads(p)) for c, p in filas]


def confirmar(cx, claves: list[str]) -> None:
    """Solo se borra cuando el servidor confirmó. Es lo que impide perder eventos."""
    cx.executemany("DELETE FROM pendientes WHERE clave=?", [(c,) for c in claves])
    cx.commit()


def marcar_fallo(cx, claves: list[str], error: str) -> None:
    cx.executemany(
        "UPDATE pendientes SET intentos=intentos+1, ultimo_error=? WHERE clave=?",
        [(error[:200], c) for c in claves])
    cx.commit()


# ── Cliente del API ──────────────────────────────────────────────────────────

class Api:
    def __init__(self, conf: dict):
        self.base = conf["backend_url"].rstrip("/")
        self.token = conf["device_token"]
        self.dispositivo = conf["dispositivo_id"]

    def _post(self, ruta: str, cuerpo: dict, timeout: int = 30) -> dict:
        datos = json.dumps(cuerpo).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base}{ruta}", data=datos, method="POST",
            headers={"Content-Type": "application/json",
                     "X-Device-Token": self.token,
                     "X-Connector-Version": VERSION})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8") or "{}")

    def enviar_lote(self, eventos: list[dict]) -> dict:
        return self._post("/api/personal/access-events/batch", {
            "dispositivo_id": self.dispositivo,
            "version_conector": VERSION,
            "eventos": eventos,
        })

    def latido(self, salud: dict) -> dict:
        return self._post(
            f"/api/personal/dispositivos/{self.dispositivo}/latido", salud)


# ── Proveedor de eventos ─────────────────────────────────────────────────────

def construir_proveedor(conf: dict):
    """El conector es agnóstico de la fuente. Cambiar de mock a Dahua real es
    una línea en config.json, no un cambio de código."""
    tipo = conf.get("proveedor", "mock")

    if tipo == "mock":
        from proveedores.mock import MockLocal
        return MockLocal(conf.get("mock", {}))

    if tipo == "csv":
        from proveedores.csv_local import CsvLocal
        return CsvLocal(conf.get("csv", {}))

    if tipo in ("dahua_http", "dahua_sdk", "dss_express", "dss_pro"):
        log(f"✗ El proveedor '{tipo}' todavía no está implementado.")
        log("  Faltan: modelo exacto, firmware y protocolo del equipo.")
        log("  Ver DAHUA_INTEGRATION_REQUIREMENTS.md")
        log("  Mientras tanto usa proveedor='mock' o 'csv'.")
        sys.exit(1)

    log(f"✗ Proveedor desconocido: {tipo}")
    sys.exit(1)


# ── Bucle principal ──────────────────────────────────────────────────────────

def main() -> None:
    conf = cargar_config()
    cx = abrir_cola()
    api = Api(conf)
    prov = construir_proveedor(conf)

    log(f"▶ Conector Dahua v{VERSION} · proveedor={conf['proveedor']} "
        f"· cada {conf['poll_seconds']}s")
    log(f"  Sistema: {conf['backend_url']}")

    espera_error = 0        # backoff cuando el servidor no responde

    while True:
        try:
            # 1 · Leer del dispositivo desde donde quedamos
            cursor = leer_estado(cx, "cursor")
            lote = prov.obtener_eventos(cursor=cursor, limite=conf["lote"])
            if lote["eventos"]:
                nuevos = encolar(cx, lote["eventos"])
                log(f"  ← {len(lote['eventos'])} leídos del dispositivo "
                    f"({nuevos} nuevos en cola)")
            if lote.get("cursor"):
                guardar_estado(cx, "cursor", lote["cursor"])

            # 2 · Enviar lo pendiente
            porEnviar = pendientes(cx, conf["lote"])
            if porEnviar:
                claves = [c for c, _ in porEnviar]
                try:
                    r = api.enviar_lote([p for _, p in porEnviar])
                    confirmar(cx, claves)
                    log(f"  → {r.get('nuevos', 0)} nuevos, "
                        f"{r.get('duplicados', 0)} duplicados, "
                        f"{r.get('sin_mapeo', 0)} sin mapear "
                        f"({len(claves)} enviados)")
                    espera_error = 0
                except urllib.error.HTTPError as e:
                    cuerpo = e.read().decode("utf-8", "ignore")[:200]
                    if 400 <= e.code < 500 and e.code != 429:
                        # Error del payload: reintentar no lo va a arreglar.
                        # Se marca y se deja en cola para revisión humana.
                        marcar_fallo(cx, claves, f"HTTP {e.code}: {cuerpo}")
                        log(f"  ✗ Rechazado por el servidor ({e.code}): {cuerpo}")
                    else:
                        marcar_fallo(cx, claves, f"HTTP {e.code}")
                        log(f"  ⚠ Servidor respondió {e.code}. Reintento luego.")
                    espera_error = min(espera_error * 2 + 30, 600)

            # 3 · Latido: que el sistema sepa que seguimos vivos
            try:
                s = prov.salud()
                api.latido({"en_linea": True,
                            "ultimo_evento_at": s.get("ultimo_evento_at"),
                            "desfase_reloj_seg": s.get("desfase_reloj_seg"),
                            "pendientes": len(pendientes(cx, 10000)),
                            "version_conector": VERSION})
            except Exception:
                pass      # el latido nunca debe tumbar el ciclo

        except urllib.error.URLError as e:
            # Sin internet: los eventos quedan en cola, no se pierde nada.
            espera_error = min(espera_error * 2 + 30, 600)
            log(f"  ⚠ Sin conexión con el sistema ({e.reason}). "
                f"Cola intacta. Reintento en {conf['poll_seconds'] + espera_error}s")
        except Exception as e:
            log(f"  ⚠ Error inesperado: {type(e).__name__}: {str(e)[:150]}")

        time.sleep(conf["poll_seconds"] + espera_error)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Conector detenido.")
