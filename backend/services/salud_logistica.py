"""salud_logistica.py — ¿el tablero logístico se puede creer HOY?

POR QUÉ EXISTE (2026-08-01): en un solo día el tablero falló de cuatro formas
distintas y NINGUNA dio un error. Se encontraron porque Sebastián contó pedidos a
mano y le pareció raro el número:

  1. El listado de Melonn se dejó de pedir durante horas (dos relojes del caché
     confundidos) y los estados quedaron congelados.
  2. Un pedido en código 23 ("Packed - on hold") no estaba en ninguna categoría:
     desapareció del tablero y estuvo dos días invisible.
  3. Un webhook reescribió el caché entero con UN pedido: 1.208 → 3, y la página
     de Envíos apareció en cero.
  4. La ventana de 90 días no cortaba entregados, y el tablero se llenó con toda
     la historia: 2.126 pedidos, 1.709 de ellos ya entregados.

Los tres primeros son "el dato es falso pero la pantalla se ve normal". Contra eso
no sirve un try/except: sirve alguien que cuente y compare. Eso es este módulo.

CORRE SOLO, en el scheduler, después de cada refresh. Si algo está en rojo manda
aviso a la campanita de quien tenga el módulo de operaciones. La regla es que
Sebastián NO se tenga que enterar contando pedidos.

No arregla nada y no toca datos: mide y avisa.
"""
from __future__ import annotations

import logging
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# ── Umbrales ─────────────────────────────────────────────────────────────────
# El scheduler pide el listado cada hora y el TTL del caché son 30 min. Con eso,
# 90 min sin hablar con Melonn ya es raro y 4 horas es que algo está roto.
FETCH_AMARILLO_MIN = 90
FETCH_ROJO_MIN     = 240
# Cuánto puede caer el total entre dos chequeos sin que sea sospechoso.
CAIDA_SOSPECHOSA   = 0.25
# A partir de esta hora de Bogotá ya debería haber pedidos del día.
HORA_ESPERA_PEDIDOS = 11
_TZ_BOGOTA = timezone(timedelta(hours=-5))
_TABLA = "logistica_salud"


def _mc():
    """El cliente de Melonn vive en src/, fuera del paquete backend."""
    raiz = Path(__file__).resolve().parent.parent.parent / "src"
    if str(raiz) not in sys.path:
        sys.path.insert(0, str(raiz))
    import melonn_client as mc
    return mc


def _sb():
    try:
        from supabase import create_client
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")
        if not url or not key:
            return None
        return create_client(url, key)
    except Exception:
        return None


def _ultimo_chequeo() -> Optional[dict]:
    """El chequeo anterior, para poder comparar totales entre corridas."""
    sb = _sb()
    if sb is None:
        return None
    try:
        rows = (sb.table(_TABLA).select("*")
                  .order("creado_en", desc=True).limit(1).execute()).data
        return rows[0] if rows else None
    except Exception as e:
        log.info(f"[salud] sin histórico todavía: {str(e)[:120]}")
        return None


def _guardar(reporte: dict) -> None:
    sb = _sb()
    if sb is None:
        return
    try:
        sb.table(_TABLA).insert({
            "creado_en":   datetime.now(timezone.utc).isoformat(),
            "semaforo":    reporte["semaforo"],
            "total":       reporte["medidas"].get("total_tablero", 0),
            "hallazgos":   reporte["hallazgos"],
            "medidas":     reporte["medidas"],
        }).execute()
    except Exception as e:
        log.warning(f"[salud] no pude guardar el chequeo: {str(e)[:150]}")


def chequear(*, avisar: bool = False) -> dict:
    """Mide el tablero y devuelve un semáforo con los hallazgos.

    avisar=True manda notificación a la campanita cuando hay algo en rojo. Se
    deja apagado por defecto para poder mirar el chequeo desde un endpoint sin
    generar avisos cada vez que alguien abre la pantalla.
    """
    mc = _mc()
    hallazgos: list[dict] = []
    medidas: dict = {}

    def marcar(nivel: str, clave: str, mensaje: str, **datos) -> None:
        hallazgos.append({"nivel": nivel, "clave": clave,
                          "mensaje": mensaje, **datos})

    # ── 1. ¿Hace cuánto le hablamos a Melonn? ────────────────────────────────
    # La pregunta NO es cuándo se escribió el caché: un webhook lo reescribe cada
    # rato. Es cuándo pedimos el listado. Confundir las dos fue el bug de fondo.
    edad_seg = None
    try:
        edad_seg = mc._edad_fetch_api()
    except Exception as e:
        marcar("rojo", "reloj_ilegible",
               f"No pude leer cuándo fue el último fetch: {str(e)[:120]}")
    medidas["minutos_desde_fetch"] = (
        round(edad_seg / 60, 1) if edad_seg is not None else None)
    if edad_seg is None:
        marcar("rojo", "sin_fetch_registrado",
               "No hay registro de un fetch al listado de Melonn. El tablero "
               "puede estar viviendo solo de webhooks, que no traen los pedidos "
               "que no cambian.")
    elif edad_seg < -60:
        # Edad negativa = "sincronizado en el futuro". Es desalineación de relojes
        # (marca en UTC, resta en hora local) y es peligrosa en silencio: haría
        # ver el caché fresco para siempre y el listado no se pediría nunca más.
        marcar("rojo", "reloj_desalineado",
               f"El último fetch aparece {abs(edad_seg) / 60:.0f} minutos en el "
               f"FUTURO. Los relojes no concuerdan, así que no se puede saber si "
               f"el tablero está al día. Revisar la zona horaria del servidor.",
               segundos=round(edad_seg))
    else:
        mins = edad_seg / 60
        if mins > FETCH_ROJO_MIN:
            marcar("rojo", "fetch_viejo",
                   f"Llevamos {mins:.0f} minutos sin pedirle el listado a "
                   f"Melonn. Los estados del tablero pueden estar viejos.",
                   minutos=round(mins, 1))
        elif mins > FETCH_AMARILLO_MIN:
            marcar("amarillo", "fetch_viejo",
                   f"{mins:.0f} minutos sin pedirle el listado a Melonn.",
                   minutos=round(mins, 1))

    # ── 2. ¿El último fetch quedó completo? ──────────────────────────────────
    try:
        uf = mc.ultimo_fetch()
        medidas["ultimo_fetch"] = uf
        if uf.get("motivo_fin") == "nunca_corrio":
            pass   # este worker no ha corrido un fetch; no es un hallazgo
        elif not uf.get("completo"):
            marcar("rojo", "fetch_incompleto",
                   f"El último fetch se cortó por '{uf.get('motivo_fin')}': "
                   f"falta parte del listado. El tablero conservó los datos "
                   f"anteriores en vez de guardar una lista mutilada.",
                   motivo=uf.get("motivo_fin"))
    except Exception as e:
        log.info(f"[salud] sin radiografía del fetch: {str(e)[:120]}")

    # ── 3. ¿Alguien intentó vaciar el caché? ─────────────────────────────────
    try:
        bloq = mc.ultimo_guardado_bloqueado()
        if bloq.get("ts"):
            medidas["guardado_bloqueado"] = bloq
            marcar("rojo", "guardado_bloqueado",
                   f"Se bloqueó un guardado que dejaba el caché en "
                   f"{bloq.get('intento')} pedidos (tenía {bloq.get('antes')}), "
                   f"fuente '{bloq.get('fuente')}'. El candado hizo su trabajo, "
                   f"pero hay que ver por qué llegó una lista tan corta.")
    except Exception:
        pass

    # ── 4. El tablero mismo ──────────────────────────────────────────────────
    pedidos: list = []
    try:
        pedidos, _om, meta = mc.obtener_pedidos_activos()
        medidas["fuente"] = meta.get("fuente")
        medidas["stale"] = bool(meta.get("stale"))
    except Exception as e:
        marcar("rojo", "tablero_ilegible",
               f"No pude leer el tablero: {str(e)[:150]}")
        return _cerrar(hallazgos, medidas, avisar)

    medidas["total_tablero"] = len(pedidos)
    if not pedidos:
        marcar("rojo", "tablero_vacio",
               "El tablero está en CERO pedidos. Es el síntoma que vio "
               "Sebastián cuando un webhook reescribió el caché.")
        return _cerrar(hallazgos, medidas, avisar)

    # Caída de volumen contra el chequeo anterior.
    prev = _ultimo_chequeo()
    if prev and (prev.get("total") or 0) > 100:
        antes = int(prev["total"])
        if len(pedidos) < antes * (1 - CAIDA_SOSPECHOSA):
            marcar("rojo", "caida_de_volumen",
                   f"El tablero pasó de {antes} a {len(pedidos)} pedidos desde "
                   f"el chequeo anterior. Una caída así no es movimiento normal.",
                   antes=antes, ahora=len(pedidos))

    # ── 5. Estados que no sabemos clasificar → pedidos invisibles ────────────
    try:
        desconocidos = sorted(mc._ESTADOS_DESCONOCIDOS)
        if desconocidos:
            medidas["estados_desconocidos"] = desconocidos
            marcar("rojo", "estados_desconocidos",
                   f"Melonn está usando {len(desconocidos)} estado(s) que la app "
                   f"no sabe clasificar: {', '.join(desconocidos[:5])}. Los "
                   f"pedidos en ese estado NO aparecen en ninguna pestaña.",
                   estados=desconocidos[:20])
    except Exception:
        pass

    # Pedidos sin código de estado: pasan por nombre y son frágiles.
    sin_codigo = [p for p in pedidos if not (p.get("estado_melonn_code") or 0)]
    medidas["sin_codigo_estado"] = len(sin_codigo)
    if sin_codigo:
        marcar("amarillo", "sin_codigo_estado",
               f"{len(sin_codigo)} pedido(s) sin código de estado — se clasifican "
               f"por el NOMBRE, que Melonn puede cambiar sin avisar.",
               ordenes=[p.get("orden_tienda") for p in sin_codigo[:10]])

    # ── 6. ¿Están entrando los pedidos del día? ──────────────────────────────
    hoy = datetime.now(_TZ_BOGOTA)
    hoy_str = hoy.date().isoformat()
    de_hoy = [p for p in pedidos if str(p.get("fecha_creacion") or "")[:10] == hoy_str]
    medidas["pedidos_de_hoy"] = len(de_hoy)
    medidas["hora_bogota"] = hoy.strftime("%H:%M")
    if hoy.hour >= HORA_ESPERA_PEDIDOS and not de_hoy:
        marcar("rojo", "sin_pedidos_de_hoy",
               f"Son las {hoy.strftime('%H:%M')} de Bogotá y el tablero no tiene "
               f"ni un pedido creado hoy. O no está entrando nada, o el tablero "
               f"no está viendo lo nuevo.")

    # ── 7. Contraentrega, desglosada como para comparar con Melonn ───────────
    cod = [p for p in pedidos if p.get("es_contraentrega")]
    sin_despachar = [p for p in cod
                     if (p.get("estado_melonn_code") or 0) not in (6, 7, 8)]
    por_pestana = Counter(p.get("sub_estado_logistico") for p in sin_despachar)
    medidas["contraentrega"] = {
        "total": len(cod),
        "sin_despachar_total": len(sin_despachar),
        "por_pestana": dict(por_pestana),
    }
    medidas["por_codigo"] = dict(sorted(
        Counter(p.get("estado_melonn_code") for p in pedidos).items(),
        key=lambda x: x[0] or 0))

    # ── 8. Fechas imposibles (entrega antes del despacho) ────────────────────
    try:
        from backend.services import auditoria_datos
        aud = auditoria_datos.reporte()
        medidas["auditoria"] = {
            "veredicto": aud.get("veredicto"),
            "problemas": aud.get("problemas"),
        }
        probs = aud.get("problemas") or []
        if isinstance(probs, list) and probs:
            marcar("amarillo", "fechas_imposibles",
                   f"La auditoría de datos encontró {len(probs)} problema(s) de "
                   f"fechas o procedencia.")
    except Exception as e:
        log.info(f"[salud] auditoría no disponible: {str(e)[:120]}")

    return _cerrar(hallazgos, medidas, avisar)


def _cerrar(hallazgos: list, medidas: dict, avisar: bool) -> dict:
    rojos = [h for h in hallazgos if h["nivel"] == "rojo"]
    amarillos = [h for h in hallazgos if h["nivel"] == "amarillo"]
    semaforo = "rojo" if rojos else ("amarillo" if amarillos else "verde")
    reporte = {
        "semaforo":  semaforo,
        "ok":        semaforo == "verde",
        "revisado":  datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rojos":     len(rojos),
        "amarillos": len(amarillos),
        "hallazgos": hallazgos,
        "medidas":   medidas,
    }
    try:
        _guardar(reporte)
    except Exception:
        pass
    if avisar and rojos:
        _notificar(rojos, medidas)
    return reporte


def _notificar(rojos: list, medidas: dict) -> None:
    """Aviso a la campanita. Solo rojos: un amarillo cada hora es ruido, y el
    ruido es lo que hace que nadie mire los avisos."""
    try:
        from backend.services import notificaciones
        titulo = ("Tablero logístico: 1 problema" if len(rojos) == 1
                  else f"Tablero logístico: {len(rojos)} problemas")
        cuerpo = " · ".join(h["mensaje"] for h in rojos[:3])
        n = notificaciones.crear_para_modulo(
            modulo="operaciones",
            tipo="salud_logistica",
            titulo=titulo,
            mensaje=cuerpo[:600],
            enlace="/logistica",
            meta={"claves": [h["clave"] for h in rojos],
                  "total_tablero": medidas.get("total_tablero"),
                  "minutos_desde_fetch": medidas.get("minutos_desde_fetch")},
            creado_por="centinela",
        )
        log.warning(f"[salud] {len(rojos)} hallazgo(s) en rojo, avisé a {n} persona(s)")
    except Exception as e:
        log.warning(f"[salud] no pude notificar: {str(e)[:150]}")
