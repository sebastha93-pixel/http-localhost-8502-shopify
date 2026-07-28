#!/usr/bin/env python3
"""
Descubrimiento del Dahua — qué habla realmente este equipo.

Lo corres TÚ, en un equipo de la red. Te pide la clave del dispositivo, la usa
solo en memoria para hacer las consultas, y te imprime qué endpoints responden
y con qué forma vienen los datos.

    python3 descubrir.py 10.30.1.4

La contraseña NO se guarda en ningún archivo, no se imprime, y no sale de tu
equipo. Se pide con getpass, así que ni siquiera aparece en pantalla mientras
la escribes.

Qué hace falta después
──────────────────────
Pégame la salida (o guárdala con `> salida.txt`). Con eso ajusto el conector a
lo que este equipo entrega de verdad, en vez de a lo que la documentación dice
que debería entregar.

Ojo: el reporte incluye UN evento de muestra para ver la forma de los campos.
Si te incomoda que salga un nombre real, edita esa línea antes de mandarlo.
"""
from __future__ import annotations

import getpass
import json
import ssl
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta

# El equipo trae certificado autofirmado: es una LAN privada y el certificado
# no aporta nada aquí. La conexión sigue siendo local.
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def cliente(host: str, usuario: str, clave: str):
    """urllib con Digest, que es lo que pide este equipo."""
    mgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    mgr.add_password(None, f"https://{host}/", usuario, clave)
    return urllib.request.build_opener(
        urllib.request.HTTPDigestAuthHandler(mgr),
        urllib.request.HTTPSHandler(context=CTX),
    )


def probar(op, host: str, ruta: str, etiqueta: str, *, mostrar: int = 0):
    url = f"https://{host}/cgi-bin/{ruta}"
    try:
        with op.open(url, timeout=20) as r:
            cuerpo = r.read().decode("utf-8", "ignore")
            print(f"  ✓ {etiqueta}")
            if mostrar:
                for linea in cuerpo.splitlines()[:mostrar]:
                    print(f"      {linea[:150]}")
            return cuerpo
    except urllib.error.HTTPError as e:
        detalle = e.read().decode("utf-8", "ignore")[:120].replace("\n", " ")
        print(f"  ✗ {etiqueta}  → HTTP {e.code} {detalle}")
    except Exception as e:
        print(f"  ✗ {etiqueta}  → {type(e).__name__}: {str(e)[:90]}")
    return None


def main() -> None:
    host = sys.argv[1] if len(sys.argv) > 1 else input("IP del dispositivo: ").strip()
    usuario = input("Usuario del dispositivo [admin]: ").strip() or "admin"
    clave = getpass.getpass("Clave (no se muestra ni se guarda): ")

    op = cliente(host, usuario, clave)
    print(f"\n{'='*66}\nDESCUBRIMIENTO · {host} · {datetime.now():%Y-%m-%d %H:%M}\n{'='*66}")

    print("\n── 1. Identidad del equipo ──")
    probar(op, host, "magicBox.cgi?action=getDeviceType", "getDeviceType", mostrar=2)
    probar(op, host, "magicBox.cgi?action=getSoftwareVersion", "getSoftwareVersion", mostrar=2)
    probar(op, host, "magicBox.cgi?action=getSerialNo", "getSerialNo", mostrar=1)

    print("\n── 2. Hora del equipo (un reloj corrido arruina toda la asistencia) ──")
    cuerpo = probar(op, host, "global.cgi?action=getCurrentTime", "getCurrentTime", mostrar=1)
    if cuerpo and "=" in cuerpo:
        try:
            equipo = datetime.strptime(cuerpo.split("=", 1)[1].strip(),
                                       "%Y-%m-%d %H:%M:%S")
            desfase = (datetime.now() - equipo).total_seconds()
            print(f"      → desfase contra este equipo: {desfase:+.0f} segundos"
                  f"{'  ⚠️ REVISAR' if abs(desfase) > 60 else '  ✓ ok'}")
        except Exception:
            pass

    print("\n── 3. Registros de acceso (LO IMPORTANTE) ──")
    ayer = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d%%20%H:%M:%S")
    hoy = datetime.now().strftime("%Y-%m-%d%%20%H:%M:%S")

    for nombre in ("AccessControlCardRec", "AttendanceRecord", "AccessControlRecord"):
        cond = (f"condition.StartTime={ayer}&condition.EndTime={hoy}")
        probar(op, host,
               f"recordFinder.cgi?action=getQuerySize&name={nombre}&{cond}",
               f"getQuerySize · {nombre}", mostrar=2)

    print("\n  Un registro de muestra (para ver la forma de los campos):")
    probar(op, host,
           f"recordFinder.cgi?action=find&name=AccessControlCardRec"
           f"&condition.StartTime={ayer}&condition.EndTime={hoy}&count=1",
           "find · 1 registro", mostrar=25)

    print("\n── 4. Usuarios registrados en el equipo ──")
    probar(op, host, "recordFinder.cgi?action=getQuerySize&name=AccessControlCard",
           "getQuerySize · tarjetas", mostrar=2)
    probar(op, host, "accessControlManager.cgi?action=getUserInfoCount",
           "getUserInfoCount", mostrar=2)
    probar(op, host, "recordFinder.cgi?action=find&name=AccessControlCard&count=1",
           "find · 1 usuario", mostrar=12)

    print("\n── 5. ¿Distingue entrada de salida? ──")
    probar(op, host, "configManager.cgi?action=getConfig&name=AccessControl",
           "config AccessControl", mostrar=30)

    print("\n── 6. ¿Soporta suscripción en tiempo real? ──")
    print("     (si responde, el conector puede recibir eventos al instante")
    print("      en vez de consultar cada minuto)")
    probar(op, host, "eventManager.cgi?action=getEventIndexes&code=AccessControl",
           "eventManager getEventIndexes", mostrar=5)

    print(f"\n{'='*66}")
    print("Listo. Pásame esta salida para ajustar el conector.")
    print("Si algún nombre real te incomoda, bórralo antes de enviarla.")
    print("="*66)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelado.")
