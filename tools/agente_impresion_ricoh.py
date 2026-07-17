#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agente de impresión MALE'DENIM  →  imprime remisiones nuevas en la RICOH por IP.

Corre en un PC de la red local (la misma red donde está la impresora). Cada
pocos segundos le pregunta al sistema qué remisiones hay pendientes de imprimir,
baja el PDF y lo manda a la RICOH por su IP (puerto 9100 "RAW"/JetDirect). Al
terminar marca cada remisión como impresa para no repetirla.

No necesita que la impresora esté instalada en el PC: solo que el PC ALCANCE la
IP de la impresora (que estén en la misma red). El backend vive en la nube y por
eso NO puede hablarle directo a la impresora local — este agente es el puente.

────────────────────────────────────────────────────────────────────────────
CÓMO USARLO
────────────────────────────────────────────────────────────────────────────
1) Copia esta carpeta a un PC que esté siempre encendido en la red de la RICOH.
2) Edita  config.json  (en la misma carpeta) con:
      - backend_url : la URL del sistema (Railway)
      - email/password : un usuario del sistema con permiso de remisiones
      - printer_ip : la IP de la RICOH en tu red (ej. 192.168.1.50)
3) Arráncalo:   python3 agente_impresion_ricoh.py
   (Requiere Python 3.8+. No hay que instalar nada.)

Requisito en la RICOH: tener activado "PDF Direct Print" (impresión PDF directa
por el puerto 9100). Es una opción estándar en las RICOH MP/IM.
────────────────────────────────────────────────────────────────────────────
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

    conf = {
        "backend_url":   (g("backend_url") or "").rstrip("/"),
        "email":         g("email") or "",
        "password":      g("password") or "",
        # Método recomendado (RICOH por AirPrint/IPP en Mac/Linux): cola del sistema.
        "printer_queue": g("printer_queue") or "",
        # Alternativa (impresoras con PDF Direct Print): envío RAW a IP:9100.
        "printer_ip":    g("printer_ip") or "",
        "printer_port":  int(g("printer_port", 9100) or 9100),
        "poll_seconds":  int(g("poll_seconds", 12) or 12),
    }
    faltan = [k for k in ("backend_url", "email", "password") if not conf[k]]
    if not conf["printer_queue"] and not conf["printer_ip"]:
        faltan.append("printer_queue (recomendado) o printer_ip")
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

    def pendientes(self) -> list:
        return self._req("GET", "/api/produccion/impresion/pendientes").get("pendientes", [])

    def pdf(self, rem_id: str) -> bytes:
        return self._req("GET", f"/api/produccion/remisiones/{rem_id}/pdf", binary=True)

    def marcar_impresa(self, rem_id: str) -> None:
        self._req("POST", f"/api/produccion/impresion/{rem_id}/impresa")


# ─── Envío a la impresora ─────────────────────────────────────────────────
def imprimir(pdf: bytes, conf: dict) -> None:
    """Imprime el PDF. Método `lp` (cola del sistema — recomendado para RICOH
    por AirPrint/IPP en Mac/Linux) si hay printer_queue; si no, envío RAW por
    IP:9100 (impresoras con PDF Direct Print)."""
    if conf["printer_queue"]:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(pdf)
            ruta = f.name
        try:
            r = subprocess.run(
                ["lp", "-d", conf["printer_queue"], "-t", "Remision MALE DENIM", ruta],
                capture_output=True, text=True, timeout=60)
            if r.returncode != 0:
                raise RuntimeError(r.stderr.strip() or f"lp devolvió {r.returncode}")
        finally:
            try:
                os.remove(ruta)
            except OSError:
                pass
    else:
        with socket.create_connection((conf["printer_ip"], conf["printer_port"]), timeout=30) as s:
            s.sendall(pdf)


# ─── Bucle principal ──────────────────────────────────────────────────────
def main() -> None:
    conf = cargar_config()
    destino = (f"cola '{conf['printer_queue']}' (lp)" if conf["printer_queue"]
               else f"{conf['printer_ip']}:{conf['printer_port']} (RAW)")
    log("Agente de impresión MALE'DENIM")
    log(f"  Sistema : {conf['backend_url']}")
    log(f"  RICOH   : {destino}")
    log(f"  Chequeo : cada {conf['poll_seconds']}s")

    api = Api(conf["backend_url"], conf["email"], conf["password"])
    api.login()

    fallidas: dict = {}   # rem_id -> nº de intentos fallidos (para no spamear el log)

    while True:
        try:
            pendientes = api.pendientes()
            if pendientes:
                log(f"→ {len(pendientes)} remisión(es) pendiente(s) de imprimir.")
            for rem in pendientes:
                rid = rem["id"]
                etiqueta = rem.get("consecutivo") or rid[:8]
                try:
                    pdf = api.pdf(rid)
                    imprimir(pdf, conf)
                    api.marcar_impresa(rid)
                    fallidas.pop(rid, None)
                    log(f"  ✓ Impresa {etiqueta} ({len(pdf)//1024} KB) → RICOH")
                except Exception as e:
                    n = fallidas.get(rid, 0) + 1
                    fallidas[rid] = n
                    # No se marca impresa → se reintenta en el próximo ciclo.
                    if n <= 3 or n % 10 == 0:
                        log(f"  ✖ {etiqueta} falló (intento {n}): {e}")
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
