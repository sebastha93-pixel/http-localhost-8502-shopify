"""Proveedor real: terminal facial Dahua por HTTP CGI.

Verificado contra el equipo de MALE DENIM el 2026-08-18
────────────────────────────────────────────────────────
    modelo    DHI-ASI6213S
    firmware  3.004.0000001.0.R, build 2025-09-19
    serial    BF0FBC9PAJA4EBF

Todo lo que sigue se MIDIÓ contra ese equipo, no se copió de la documentación.
Cada decisión rara de este archivo tiene una razón medida, anotada donde va.

Lo que se comprobó, y por qué importa
─────────────────────────────────────
1. Solo habla HTTPS (certificado autofirmado) con **Digest**. El puerto 80 no
   contesta y el 37777 (NetSDK) está cerrado.

2. **El filtro de fechas SE IGNORA EN SILENCIO.** `condition.StartTime` /
   `condition.EndTime` devuelven `count=4785` para cualquier rango — incluso
   para el año 2050, donde debería dar 0. Un conector que confíe en ese filtro
   cree que trae "el último día" y en realidad trae el comienzo del búfer.
   Por eso aquí se pagina con `offset` y se corta por `RecNo`.

3. `beginNumber` se ignora; **`offset` sí funciona**. (Probados los dos.)

4. **`CreateTime` es epoch UTC de verdad** → hay que restar 5 h para Bogotá.
   Se verificó con dos pruebas independientes:
     · leer el epoch como hora local pone 24 registros en el FUTURO (imposible);
     · convirtiendo UTC→Bogotá, el 100 % de las marcaciones cae entre 06:00 y
       21:00, con pico a las 08h (1250) y a las 17h (791) — que es exactamente
       una oficina de 8:30 a 17:00.
   Leerlo mal desplaza toda la asistencia 5 horas.

5. **El equipo NO distingue entrada de salida.** `Type=Entry` en los 4785
   registros, `AttendanceState=0` en todos, un solo `Door=0` / `ReaderID=1`, y
   la config trae `OutDoorMethodEnable=false`. Por eso se envía
   `direccion_acceso='desconocida'`: que el motor alterne. Mandar 'entrada'
   sería inventar un hecho que el equipo no reporta.

6. Los registros se clasifican en tres cosas distintas:
     · `Status=1` + `UserID` → marcación atribuible  (3787)
     · `Status=1` sin `UserID` → la puerta se abrió sin lector: botón de salida
       o apertura remota. Es un hecho real, pero de NADIE. (863)
     · `Status=0` (`ErrorCode` 16/20) → intento fallido, cara no reconocida (135)
   Solo las primeras son marcaciones. Las otras dos NO deben volverse horas.

7. `RecNo` es monótono creciente y sin huecos (1…4785 verificado), así que
   sirve de cursor. Pero es un búfer circular: `offset` es posicional, y si el
   equipo purga lo viejo, `offset N` deja de ser `RecNo N+1`. Por eso el cursor
   es el **RecNo**, y se lee desde el final hacia atrás hasta encontrarlo.

8. El equipo duplica marcaciones: 581 de 2422 intervalos consecutivos son de
   ≤10 s. La distribución es bimodal (pico ≤10 s, valle, y luego actividad real
   >15 min), así que la ventana de deduplicación correcta es **60 s**. Aquí NO
   se deduplica: el hecho crudo se guarda entero y el motor colapsa. Se anota
   porque es la regla `tolerancia_duplicado_seg` que hay que dejar en 60.
"""
from __future__ import annotations

import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone

# El nombre del conjunto de registros. Los otros que se probaron
# (AttendanceRecord, AccessControlRecord, RecordSet) dan HTTP 400.
CONJUNTO = "AccessControlCardRec"

# El equipo guarda el epoch en UTC (punto 4 del encabezado).
UTC = timezone.utc

# Método de autenticación → etiqueta. Medido: los 3787 registros atribuibles
# vienen con Method=15. Los demás valores se dejan por si cambia la config.
METODOS = {
    "1": "tarjeta", "2": "huella", "3": "clave", "4": "boton_salida",
    "15": "facial", "63": "multiple",
}


def _con_recno(lote: list[dict]) -> list[dict]:
    """Solo los registros con RecNo numérico. Sin RecNo no hay llave de
    idempotencia ni cursor posible, así que no se pueden procesar."""
    return [r for r in lote if (r.get("RecNo") or "").strip().isdigit()]


class DahuaHttp:
    """Lee marcaciones del Dahua. Solo lectura: nunca escribe en el equipo."""

    def __init__(self, conf: dict):
        self.host = conf["dahua_host"]
        self.usuario = conf.get("dahua_usuario", "admin")
        # La clave se guarda en un CLOSURE, no como atributo: así no aparece
        # en __dict__, ni en un repr(), ni en un volcado de excepción. El name
        # mangling (self.__clave) NO sirve para esto — solo renombra a
        # _DahuaHttp__clave y sigue estando en __dict__.
        clave = conf["dahua_password"]
        self._clave = (lambda c: (lambda: c))(clave)

        # Cuántos registros pedir por llamada. 300 va bien; 400 también
        # respondió, pero no hay razón para apretar.
        self.pagina = int(conf.get("dahua_pagina", 300))
        # Si se incluyen los eventos no atribuibles (punto 6). Por defecto NO:
        # son 863 hechos sin sujeto, que no aportan una sola hora y en cambio
        # dejarían una incidencia 'empleado_desconocido' imposible de resolver.
        # Se EXCLUYEN, pero el resumen siempre dice cuántos — nunca en silencio.
        self.incluir_no_atribuibles = bool(conf.get("dahua_incluir_no_atribuibles", False))

        self._ctx = ssl.create_default_context()
        self._ctx.check_hostname = False      # certificado autofirmado, LAN privada
        self._ctx.verify_mode = ssl.CERT_NONE
        self.ultimo_resumen: dict = {}

    # ── transporte ────────────────────────────────────────────────────────

    def _get(self, ruta: str, *, timeout: int = 60) -> str:
        mgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        mgr.add_password(None, f"https://{self.host}/", self.usuario, self._clave())
        op = urllib.request.build_opener(
            urllib.request.HTTPDigestAuthHandler(mgr),
            urllib.request.HTTPSHandler(context=self._ctx),
        )
        url = f"https://{self.host}/cgi-bin/{ruta}"
        with op.open(url, timeout=timeout) as r:
            return r.read().decode("utf-8", "ignore")

    @staticmethod
    def _parsear(cuerpo: str) -> list[dict]:
        """`records[3].UserID=017` → [{...}, ...] ordenado por índice."""
        acc: dict[int, dict] = defaultdict(dict)
        for idx, campo, valor in re.findall(r"records\[(\d+)\]\.(\S+?)=(.*)", cuerpo):
            acc[int(idx)][campo] = valor.strip()
        return [acc[i] for i in sorted(acc)]

    def _total(self) -> int:
        cuerpo = self._get(f"recordFinder.cgi?action=getQuerySize&name={CONJUNTO}")
        m = re.search(r"count=(\d+)", cuerpo)
        if not m:
            raise RuntimeError(f"getQuerySize sin count: {cuerpo[:120]}")
        return int(m.group(1))

    def _pagina(self, offset: int, cuantos: int) -> list[dict]:
        return self._parsear(self._get(
            f"recordFinder.cgi?action=find&name={CONJUNTO}"
            f"&count={cuantos}&offset={offset}"))

    # ── traducción ────────────────────────────────────────────────────────

    @staticmethod
    def _clasificar(r: dict) -> str:
        """'marcacion' | 'sin_lector' | 'fallido'."""
        if r.get("Status") != "1":
            return "fallido"
        return "marcacion" if (r.get("UserID") or "").strip() else "sin_lector"

    def _traducir(self, r: dict) -> dict | None:
        crudo = (r.get("CreateTime") or "").strip()
        if not crudo.isdigit():
            return None
        # UTC → Bogotá. Se emite CON offset explícito para que nadie más
        # adelante tenga que adivinar la zona (punto 4).
        t = datetime.fromtimestamp(int(crudo), tz=UTC).astimezone(timezone(timedelta(hours=-5)))

        clase = self._clasificar(r)
        return {
            # RecNo es único por equipo → llave de idempotencia natural.
            "id_evento_externo":    f"{CONJUNTO}-{r.get('RecNo')}",
            "id_externo_empleado":  (r.get("UserID") or "").strip() or None,
            "event_timestamp":      t.isoformat(),
            "tipo_evento":          "acceso" if clase == "marcacion" else clase,
            # 'desconocida' A PROPÓSITO: el equipo dice Entry siempre (punto 5).
            "direccion_acceso":     "desconocida",
            "resultado_acceso":     "concedido" if r.get("Status") == "1" else "denegado",
            "metodo_autenticacion": METODOS.get(r.get("Method", ""), r.get("Method") or None),
            "nombre_puerta":        "Puerta Principal",
            "raw_payload_json": {
                "RecNo": r.get("RecNo"), "CreateTime": crudo,
                "Status": r.get("Status"), "ErrorCode": r.get("ErrorCode"),
                "Method": r.get("Method"), "ReaderID": r.get("ReaderID"),
                "Type": r.get("Type"), "AttendanceState": r.get("AttendanceState"),
                "CardName": r.get("CardName"),
                # Qué se sabía del equipo cuando se leyó: si mañana cambia el
                # firmware y la forma de los datos, esto explica el histórico.
                "_lectura": {"modelo": "DHI-ASI6213S", "tz_origen": "UTC",
                             "clase": clase},
            },
        }

    # ── interfaz del conector ─────────────────────────────────────────────

    def obtener_eventos(self, cursor=None, limite: int = 100) -> dict:
        """Devuelve eventos con RecNo > cursor, del más viejo al más nuevo.

        El cursor es el último `RecNo` procesado (no un offset): el equipo es
        un búfer circular y las posiciones se corren cuando purga (punto 7).
        """
        desde = int(cursor or 0)
        total = self._total()
        if total <= 0:
            self.ultimo_resumen = {"total_en_equipo": 0, "cursor_previo": desde,
                                   "cursor_nuevo": desde, "revisados": 0, "emitidos": 0,
                                   "excluidos_sin_lector": 0, "excluidos_fallidos": 0}
            return {"eventos": [], "cursor": str(desde), "hay_mas": False,
                    "resumen": self.ultimo_resumen}

        # Se lee desde el FINAL hacia atrás. En operación normal (poll de 60 s
        # con 2 o 3 marcaciones nuevas) esto es UNA sola llamada.
        fin = total
        arranque = max(0, fin - self.pagina)
        lote = self._pagina(arranque, fin - arranque)
        ultima_pagina = _con_recno(lote)

        # ¿Se purgó o reinició el búfer? Se compara el cursor contra el RecNo
        # MÁS ALTO que el equipo tiene ahora — no contra el total.
        #
        # Comparar con el total era un bug: son unidades distintas. Un equipo
        # que purgó lo viejo y quedó con los RecNo 4700–4785 reporta total=86,
        # que es menor que cualquier cursor razonable → el conector concluía
        # "se reinició" y rebarría los 4785 registros en CADA poll, para
        # siempre. El backend deduplica, así que no corrompía nada: solo
        # martillaba el equipo sin que ningún error lo delatara.
        tope = max(int(r["RecNo"]) for r in ultima_pagina) if ultima_pagina else 0
        if tope < desde:
            desde = 0

        nuevos = [r for r in ultima_pagina if int(r["RecNo"]) > desde]
        # Mientras la página venga entera nueva, puede haber más atrás.
        while len(nuevos) and len(nuevos) == len(ultima_pagina) and arranque > 0:
            fin = arranque
            arranque = max(0, fin - self.pagina)
            lote = self._pagina(arranque, fin - arranque)
            ultima_pagina = _con_recno(lote)
            if not ultima_pagina:
                break
            frescos = [r for r in ultima_pagina if int(r["RecNo"]) > desde]
            nuevos = frescos + nuevos
            if len(frescos) < len(ultima_pagina):
                break

        nuevos.sort(key=lambda r: int(r["RecNo"]))

        conteo = {"marcacion": 0, "sin_lector": 0, "fallido": 0}
        eventos, ultimo = [], desde
        for r in nuevos:
            clase = self._clasificar(r)
            conteo[clase] += 1
            ultimo = max(ultimo, int(r["RecNo"]))
            if clase != "marcacion" and not self.incluir_no_atribuibles:
                continue
            ev = self._traducir(r)
            if ev:
                eventos.append(ev)
            if len(eventos) >= limite:
                # Se corta el lote, pero el cursor solo avanza hasta lo emitido:
                # el resto vuelve en la siguiente pasada. Nada se pierde.
                ultimo = int(r["RecNo"])
                break

        # El resumen SIEMPRE dice qué se dejó afuera. Un conteo que no reporta
        # cómo terminó se lee como prueba de completitud y no lo es.
        self.ultimo_resumen = {
            "total_en_equipo": total, "cursor_previo": desde, "cursor_nuevo": ultimo,
            "revisados": len(nuevos), "emitidos": len(eventos),
            "excluidos_sin_lector": 0 if self.incluir_no_atribuibles else conteo["sin_lector"],
            "excluidos_fallidos": 0 if self.incluir_no_atribuibles else conteo["fallido"],
        }
        return {"eventos": eventos, "cursor": str(ultimo),
                "hay_mas": ultimo < total, "resumen": self.ultimo_resumen}

    def salud(self) -> dict:
        """Estado del equipo. El desfase de reloj es lo crítico:
        un reloj corrido no da error en ninguna parte, solo horas mal."""
        info: dict = {"en_linea": False, "ultimo_evento_at": None,
                      "desfase_reloj_seg": None}
        try:
            cuerpo = self._get("global.cgi?action=getCurrentTime", timeout=20)
            info["en_linea"] = True
            if "=" in cuerpo:
                # El equipo responde su hora de PARED (zona Bogota configurada),
                # no el epoch UTC de los registros. Se compara contra la hora
                # local de este servidor.
                equipo = datetime.strptime(cuerpo.split("=", 1)[1].strip(),
                                           "%Y-%m-%d %H:%M:%S")
                info["hora_equipo"] = equipo.isoformat()
                info["desfase_reloj_seg"] = round(
                    (datetime.now() - equipo).total_seconds())
        except Exception as e:
            info["error"] = f"{type(e).__name__}: {str(e)[:120]}"
            return info

        try:
            total = self._total()
            info["total_registros"] = total
            ult = self._pagina(max(0, total - 1), 1)
            if ult:
                ev = self._traducir(ult[-1])
                if ev:
                    info["ultimo_evento_at"] = ev["event_timestamp"]
        except Exception as e:
            info["error_registros"] = f"{type(e).__name__}: {str(e)[:120]}"
        return info
