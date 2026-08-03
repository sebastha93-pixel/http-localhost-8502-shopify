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
# El barrido completo del listado corre cada 2 h (_CACHE_TTL en melonn_client) y
# el scheduler tiene tick horario. Con eso, 3 h sin barrer ya significa que un
# barrido se saltó, y 6 h que llevan varios fallando seguidos.
#
# OJO si se cambia _CACHE_TTL: estos dos números tienen que moverse con él, o el
# semáforo empieza a mentir. Un centinela mal calibrado es peor que ninguno,
# porque da verde sobre un tablero viejo.
FETCH_AMARILLO_MIN = 180
FETCH_ROJO_MIN     = 360
# Cuánto puede caer el total entre dos chequeos sin que sea sospechoso.
CAIDA_SOSPECHOSA   = 0.25
# A partir de esta hora de Bogotá ya debería haber pedidos del día.
HORA_ESPERA_PEDIDOS = 11
# Cuánto tiene que pesar un problema de datos sobre los pedidos ABIERTOS para que
# mueva el semáforo. Un puñado es normal (un pedido recién despachado no tiene
# fecha medida hasta la siguiente tanda del enriquecedor); lo que importa es que
# no se vuelva costumbre. Cualquiera de los dos criterios lo activa.
UMBRAL_ABIERTOS_PCT = 5.0
UMBRAL_ABIERTOS_MIN = 10
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


def _revisar_fetch(mc, marcar, medidas: dict) -> None:
    """¿El último fetch quedó completo? ¿Se bloqueó algún guardado?

    Aparte de chequear() y no dentro, porque hay que llamarlo DESPUÉS de leer el
    tablero (leer puede disparar un refresh) y también en el camino de error.
    """
    try:
        uf = mc.ultimo_fetch()
        medidas["ultimo_fetch"] = uf
        if uf.get("motivo_fin") == "nunca_corrio":
            pass   # este worker no ha corrido un fetch; no es un hallazgo
        elif not uf.get("completo"):
            # El motivo trae la causa real detrás del fallo (cuota agotada,
            # ráfaga, timeout, 5xx) — sin eso hay que adivinar, y adivinar es lo
            # que salió mal hoy. Ver `_fallo` en melonn_client.
            marcar("rojo", "fetch_incompleto",
                   f"El último fetch se cortó por '{uf.get('motivo_fin')}': "
                   f"falta parte del listado. El tablero conservó los datos "
                   f"anteriores en vez de guardar una lista mutilada.",
                   motivo=uf.get("motivo_fin"))
        try:
            medidas["ultimo_fallo_get"] = mc.ultimo_fallo_get()
        except Exception:
            pass
    except Exception as e:
        log.info(f"[salud] sin radiografía del fetch: {str(e)[:120]}")

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

    # ── 2. El tablero mismo ──────────────────────────────────────────────────
    # Va ANTES de revisar la radiografía del fetch, y no después, porque leer el
    # tablero puede DISPARAR un refresh (si el caché está vencido, lanza uno en
    # segundo plano). Al revés, un fetch que falla durante este mismo chequeo no
    # se vería hasta la vuelta siguiente. Lo comprobé sin querer: corriendo esto
    # sin llave de Melonn, el fetch dio 401 y el chequeo igual dijo verde.
    pedidos: list = []
    try:
        pedidos, _om, meta = mc.obtener_pedidos_activos()
        medidas["fuente"] = meta.get("fuente")
        medidas["stale"] = bool(meta.get("stale"))
    except Exception as e:
        marcar("rojo", "tablero_ilegible",
               f"No pude leer el tablero: {str(e)[:150]}")
        _revisar_fetch(mc, marcar, medidas)
        return _cerrar(hallazgos, medidas, avisar)

    _revisar_fetch(mc, marcar, medidas)

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
    #
    # ESTE CHEQUEO NUNCA CORRIÓ hasta el 2026-08-02: se llamaba `reporte()` sin
    # argumentos y la firma real es `reporte(pedidos)`. El TypeError caía en el
    # `except` de abajo, se registraba en log.info y `medidas["auditoria"]`
    # quedaba en null. O sea: 37 chequeos en verde con una de sus preguntas sin
    # hacer. Es exactamente el pecado que este módulo existe para cazar —
    # silencio que se lee como "todo bien" — y lo tenía adentro.
    #
    # Por eso el `except` ya no calla: si un sub-chequeo no puede correr, ESO es
    # un hallazgo. Un chequeo roto no puede volver a esconderse detrás de un
    # semáforo verde.
    # Y OJO CON QUÉ LISTA se audita. Hay que medir lo que VE EL USUARIO, no el
    # caché crudo: el teléfono y la guía viven en `pedido_overrides` y se pintan
    # encima al leer, y `dias_origen` lo pone `clasificar()`. Auditando el caché
    # pelado salía "NO AUDITABLE, 0% medido" y 341 contraentregas sin teléfono —
    # todo falso, porque los overrides no se habían aplicado todavía.
    # Es el mismo error que dejó pasar el bug de las guías (678 en base, 25 en
    # pantalla) y está advertido en el endpoint /auditoria-datos. Lo repetí igual.
    try:
        from backend.services import auditoria_datos
        from backend.services import metricas as metricas_svc
        from backend.services import overrides as overrides_svc
        _ov = overrides_svc.cargar_map()
        vista = [metricas_svc.clasificar(overrides_svc.aplicar_a_pedido(p, _ov))
                 for p in pedidos]
        aud = auditoria_datos.reporte(vista)

        # DOS auditorías, y el semáforo solo lo mueve la segunda.
        #
        # Sobre el tablero completo hay 331 contraentregas sin teléfono y 9 pares
        # de fechas imposibles — y las 340 están en pedidos YA ENTREGADOS. Nadie
        # va a llamar a un pedido entregado en mayo. Poner eso en ámbar cada hora
        # sería el ruido contra el que existe la regla de no repetir avisos: se
        # aprende a ignorar el semáforo y el día que salga algo de verdad, no se
        # mira. Se mide sobre los ABIERTOS, que son los que se pueden trabajar.
        abiertos = [p for p in vista
                    if (p.get("sub_estado_logistico") or "") != "entregado"]
        aud_abiertos = auditoria_datos.reporte(abiertos) if abiertos else {}

        medidas["auditoria"] = {
            "veredicto": aud.get("veredicto"),
            "problemas": aud.get("problemas"),
            "dias": aud.get("dias"),
            # Lo mismo pero solo sobre lo accionable.
            "abiertos": {
                "total": len(abiertos),
                "veredicto": aud_abiertos.get("veredicto"),
                "problemas": aud_abiertos.get("problemas"),
            },
        }
        # Y con umbral, porque un puñado es NORMAL, no un defecto: un pedido
        # recién despachado no tiene fecha medida hasta que el enriquecedor la
        # traiga en su próxima tanda. Sin umbral esto quedaría en ámbar
        # permanente por 1 pedido de 380 — y un ámbar permanente no es una
        # alerta, es un adorno que enseña a no mirar el semáforo.
        probs = [p for p in (aud_abiertos.get("problemas") or [])
                 if isinstance(p, dict)]
        n_ab = max(len(abiertos), 1)
        graves = [p for p in probs
                  if int(p.get("n") or 0) >= UMBRAL_ABIERTOS_MIN
                  or (int(p.get("n") or 0) / n_ab * 100) >= UMBRAL_ABIERTOS_PCT]
        medidas["auditoria"]["abiertos"]["bajo_umbral"] = [
            {"clave": p.get("clave"), "n": p.get("n")}
            for p in probs if p not in graves
        ]
        if graves:
            detalle = ", ".join(f"{p.get('clave')} ({p.get('n')})" for p in graves[:4])
            marcar("amarillo", "datos_incompletos_en_abiertos",
                   f"Hay pedidos ABIERTOS con datos que impiden trabajarlos: "
                   f"{detalle}. Sobre {len(abiertos)} pedidos abiertos.",
                   ejemplos=graves[:5])
    except Exception as e:
        log.warning(f"[salud] la auditoría de datos no pudo correr: {str(e)[:150]}")
        marcar("amarillo", "chequeo_no_corrio",
               f"La auditoría de fechas no pudo correr ({type(e).__name__}: "
               f"{str(e)[:100]}). El semáforo está incompleto: esta pregunta "
               f"quedó sin hacer.")

    return _cerrar(hallazgos, medidas, avisar)


def _cerrar(hallazgos: list, medidas: dict, avisar: bool) -> dict:
    rojos = [h for h in hallazgos if h["nivel"] == "rojo"]
    amarillos = [h for h in hallazgos if h["nivel"] == "amarillo"]
    semaforo = "rojo" if rojos else ("amarillo" if amarillos else "verde")

    # El chequeo anterior se lee ANTES de guardar el nuevo — se necesita para
    # decidir si este aviso ya se mandó.
    previo = None
    try:
        previo = _ultimo_chequeo()
    except Exception:
        pass

    avisado_en = ((previo or {}).get("medidas") or {}).get("avisado_en")
    mandar = bool(avisar and rojos and _debe_avisar(rojos, previo))
    if mandar:
        avisado_en = datetime.now(timezone.utc).isoformat(timespec="seconds")
    # Se arrastra en cada fila: así una sola lectura de la fila anterior siempre
    # dice cuándo fue el último aviso, sin recorrer el histórico.
    if avisado_en:
        medidas["avisado_en"] = avisado_en

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
    if mandar:
        _notificar(rojos, medidas)
    elif avisar and rojos:
        log.info(f"[salud] {len(rojos)} en rojo, ya avisado — no repito el aviso")
    return reporte


# Cada cuánto se vuelve a avisar de un problema que sigue igual.
RECORDAR_CADA_H = 6


def _debe_avisar(rojos: list, previo: Optional[dict]) -> bool:
    """¿Mandar aviso, o este problema ya se avisó?

    El scheduler chequea cada hora. Sin este filtro, un problema que dure el día
    manda ~10 avisos idénticos — y una campanita que repite es una campanita que
    se deja de leer, que es justo lo contrario de para qué existe esto.

    Se avisa cuando: es un problema nuevo o distinto, o cuando el mismo problema
    sigue vivo y ya pasaron RECORDAR_CADA_H horas del último aviso.
    """
    if not previo:
        return True
    claves_ahora = sorted({h["clave"] for h in rojos})
    claves_antes = sorted({h.get("clave") for h in (previo.get("hallazgos") or [])
                           if h.get("nivel") == "rojo"})
    if claves_ahora != claves_antes:
        return True   # cambió el problema: hay que contarlo

    avisado_en = (previo.get("medidas") or {}).get("avisado_en")
    if not avisado_en:
        return True   # mismo problema pero nunca se avisó
    try:
        cuando = datetime.fromisoformat(str(avisado_en))
        if cuando.tzinfo is None:
            cuando = cuando.replace(tzinfo=timezone.utc)
        horas = (datetime.now(timezone.utc) - cuando).total_seconds() / 3600
        return horas >= RECORDAR_CADA_H
    except Exception:
        return True   # si no se entiende la fecha, mejor avisar que callarse


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
