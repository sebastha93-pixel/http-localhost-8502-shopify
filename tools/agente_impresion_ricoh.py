#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agente de impresión MALE'DENIM — imprime automáticamente lo que el sistema encola.

Atiende una o varias impresoras según su config.json:
  · "ricoh"     → remisiones PDF (corte + insumos)
  · "honeywell" → stickers de código de barras de terminación (ZPL)
  · "sat"       → instrucciones de lavado de terminación (ZPL)

Cada impresora se define por COLA del sistema (Mac/Linux, campo "queue") o por
IP directa (campo "ip", puerto 9100 RAW — típico de térmicas y Windows).

Corre en un equipo que ALCANCE esas impresoras (misma red). El backend vive en
la nube y no puede hablarles directo — este agente es el puente. Puede haber
varios agentes en redes distintas: cada uno imprime SOLO los trabajos de las
impresoras que tiene en su config; el resto los deja para otro agente.

────────────────────────────────────────────────────────────────────────────
CONFIG (config.json en la misma carpeta)
────────────────────────────────────────────────────────────────────────────
{
  "backend_url": "https://TU-BACKEND.up.railway.app",
  "email": "impresion@maledenim.com",
  "password": "...",
  "poll_seconds": 12,
  "printers": {
    "ricoh":     { "queue": "RICOH_M_320F__88a84d_" },
    "honeywell": { "ip": "192.168.19.X", "port": 9100 },
    "sat":       { "ip": "192.168.19.Y", "port": 9100 }
  }
}

Compatibilidad: la config vieja ("printer_queue" o "printer_ip" sueltos) sigue
funcionando y equivale a printers = { "ricoh": {...} }.

Arranque:  python3 agente_impresion_ricoh.py   (Python 3.8+, sin librerías)
"""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

AQUI = Path(__file__).resolve().parent


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


# ─── Config ──────────────────────────────────────────────────────────────
def cargar_config() -> dict:
    cfg: dict = {}
    f = AQUI / "config.json"
    if f.exists():
        try:
            cfg = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            log(f"⚠ config.json inválido: {e}")

    def g(k, d=None):
        return os.environ.get("AGENTE_" + k.upper(), cfg.get(k, d))

    printers = cfg.get("printers") or {}
    # Config vieja → impresora "ricoh"
    if not printers:
        if g("printer_queue"):
            printers = {"ricoh": {"queue": g("printer_queue")}}
        elif g("printer_ip"):
            printers = {"ricoh": {"ip": g("printer_ip"),
                                  "port": int(g("printer_port", 9100) or 9100)}}

    conf = {
        "backend_url":  (g("backend_url") or "").rstrip("/"),
        "email":        g("email") or "",
        "password":     g("password") or "",
        "poll_seconds": int(g("poll_seconds", 12) or 12),
        "printers":     printers,
    }
    faltan = [k for k in ("backend_url", "email", "password") if not conf[k]]
    if not printers:
        faltan.append("printers (o printer_queue / printer_ip)")
    if faltan:
        log("✖ Falta configurar: " + ", ".join(faltan))
        log("  Edita config.json (mira config.example.json) y vuelve a arrancar.")
        sys.exit(1)
    return conf


# ─── Cliente HTTP con token (re-login automático en 401) ─────────────────
class Api:
    def __init__(self, base: str, email: str, password: str):
        self.base = base
        self.email = email
        self.password = password
        self.token = ""

    def login(self) -> None:
        data = json.dumps({"email": self.email, "password": self.password}).encode()
        req = urllib.request.Request(
            self.base + "/api/auth/login", data=data,
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=30) as r:
            body = json.loads(r.read().decode())
        self.token = body["access_token"]
        log("✓ Sesión iniciada en el sistema.")

    def _req(self, method: str, path: str, *, binary: bool = False, _retry: bool = True):
        req = urllib.request.Request(
            self.base + path,
            headers={"Authorization": f"Bearer {self.token}"}, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                return raw if binary else json.loads(raw.decode() or "{}")
        except urllib.error.HTTPError as e:
            if e.code == 401 and _retry:
                self.login()
                return self._req(method, path, binary=binary, _retry=False)
            raise

    # Remisiones PDF (RICOH)
    def remisiones_pendientes(self) -> list:
        return self._req("GET", "/api/produccion/impresion/pendientes").get("pendientes", [])

    def remision_pdf(self, rem_id: str) -> bytes:
        return self._req("GET", f"/api/produccion/remisiones/{rem_id}/pdf", binary=True)

    def remision_impresa(self, rem_id: str) -> None:
        self._req("POST", f"/api/produccion/impresion/{rem_id}/impresa")

    # Trabajos de etiquetas (Honeywell / SAT)
    def trabajos_pendientes(self) -> list:
        return self._req("GET", "/api/produccion/impresion/trabajos").get("trabajos", [])

    def trabajo_contenido(self, trabajo_id: str) -> bytes:
        return self._req("GET", f"/api/produccion/impresion/trabajos/{trabajo_id}/contenido", binary=True)

    def trabajo_impreso(self, trabajo_id: str) -> None:
        self._req("POST", f"/api/produccion/impresion/trabajos/{trabajo_id}/impreso")


# ─── Envío a impresora ────────────────────────────────────────────────────
def imprimir(data: bytes, printer: dict, *, raw: bool = False, titulo: str = "MALE DENIM") -> None:
    """Cola del sistema (`lp`, Mac/Linux) si hay "queue"; socket a IP:9100 si
    hay "ip". `raw=True` para ZPL (pasa los bytes sin interpretar)."""
    if printer.get("queue"):
        sufijo = ".zpl" if raw else ".pdf"
        with tempfile.NamedTemporaryFile(suffix=sufijo, delete=False) as f:
            f.write(data)
            ruta = f.name
        try:
            cmd = ["lp", "-d", printer["queue"], "-t", titulo]
            if raw:
                cmd += ["-o", "raw"]
            r = subprocess.run(cmd + [ruta], capture_output=True, text=True, timeout=60)
            if r.returncode != 0:
                raise RuntimeError(r.stderr.strip() or f"lp devolvió {r.returncode}")
        finally:
            try:
                os.remove(ruta)
            except OSError:
                pass
    elif printer.get("ip"):
        with socket.create_connection((printer["ip"], int(printer.get("port") or 9100)),
                                      timeout=30) as s:
            s.sendall(data)
    else:
        raise RuntimeError("impresora sin 'queue' ni 'ip' en config")


def _destino_str(p: dict) -> str:
    return p.get("queue") or f"{p.get('ip')}:{p.get('port') or 9100}"


# ─── Bucle principal ──────────────────────────────────────────────────────
def main() -> None:
    conf = cargar_config()
    printers: dict = conf["printers"]
    log("Agente de impresión MALE'DENIM")
    log(f"  Sistema : {conf['backend_url']}")
    for nombre, p in printers.items():
        log(f"  {nombre:<9}: {_destino_str(p)}")
    log(f"  Chequeo : cada {conf['poll_seconds']}s")

    api = Api(conf["backend_url"], conf["email"], conf["password"])
    api.login()

    fallidas: dict = {}   # id -> intentos fallidos (para no spamear el log)

    def intento(clave: str, etiqueta: str, accion) -> None:
        try:
            accion()
            fallidas.pop(clave, None)
        except Exception as e:
            n = fallidas.get(clave, 0) + 1
            fallidas[clave] = n
            if n <= 3 or n % 10 == 0:
                log(f"  ✖ {etiqueta} falló (intento {n}): {e}")

    while True:
        try:
            # 1) Remisiones PDF → impresora "ricoh" (si este agente la atiende)
            if "ricoh" in printers:
                for rem in api.remisiones_pendientes():
                    rid, etiqueta = rem["id"], rem.get("consecutivo") or rem["id"][:8]

                    def _imprimir_rem(rid=rid, etiqueta=etiqueta):
                        pdf = api.remision_pdf(rid)
                        imprimir(pdf, printers["ricoh"], titulo=f"Remision {etiqueta}")
                        api.remision_impresa(rid)
                        log(f"  ✓ Impresa {etiqueta} ({len(pdf)//1024} KB) → ricoh")

                    intento(rid, f"remisión {etiqueta}", _imprimir_rem)

            # 2) Etiquetas térmicas → honeywell (stickers) / sat (lavado)
            trabajos = api.trabajos_pendientes()
            for t in trabajos:
                destino = t.get("destino") or ""
                if destino not in printers:
                    continue   # lo imprime otro agente (otra red)
                tid = t["id"]
                cod = (t.get("payload") or {}).get("codigo_referencia") or tid[:8]
                etiqueta = f"{t.get('tipo')} {cod}"

                def _imprimir_trab(t=t, tid=tid, destino=destino, etiqueta=etiqueta):
                    contenido = api.trabajo_contenido(tid)
                    imprimir(contenido, printers[destino],
                             raw=(t.get("formato") == "zpl"), titulo=etiqueta)
                    api.trabajo_impreso(tid)
                    log(f"  ✓ Impreso {etiqueta} → {destino}")

                intento(tid, etiqueta, _imprimir_trab)
        except urllib.error.URLError as e:
            log(f"⚠ Sin conexión con el sistema: {e}. Reintento…")
        except Exception as e:
            log(f"⚠ Error inesperado: {e}. Continúo…")
        time.sleep(conf["poll_seconds"])


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Agente detenido.")
