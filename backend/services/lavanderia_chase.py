"""
backend.services.lavanderia_chase — Persecución de la remisión de lavandería.

EL PROBLEMA QUE RESUELVE (pedido de Sebastián, 2026-08-18)
Cuando el diseñador dice en el grupo de WhatsApp «ya salió el 2608-0003 para
lavandería», hoy no pasa nada: el mensaje llega al espejo y ahí muere. La
remisión de lavandería es el documento que permite que el lote siga avanzando
y, además, **sin remisión no se activa el pago de la semana** de esa lavandería.
Nadie la persigue, así que a veces aparece tarde y a veces no aparece.

POR QUÉ SON DOS RELOJES Y NO UNO
«Sale para lavandería» lo dice el diseñador, y NO significa que la lavandería
tenga el lote — a veces se demoran en recoger. Si pedimos la remisión de algo
que no han recogido, el mensaje es ruido y encima tapa el problema real (el
lote está quieto esperando el camión). Entonces:

  RELOJ 'recogida'  ¿ya lo recogiste?   se cierra con  lav_recibido_at
  RELOJ 'remision'  ¿y la foto?         se cierra con  remision_lavanderia_url
                    (arranca solo cuando el de recogida se cerró)

LO QUE ESTE MÓDULO NO HACE, A PROPÓSITO
No mueve la etapa del lote. Leer un chat es una suposición: la etapa la firma
quien tiene el lote en la mano, desde su propio enlace. Acá solo se pide y se
escala.

ENV
  LAVANDERIA_GRACIA_MIN        minutos antes del PRIMER mensaje (default 30).
                               Ventana para anular si la detección se equivocó.
  LAVANDERIA_INTERVALO_HORAS   entre avisos del mismo pendiente (default 24)
  LAVANDERIA_RECOGIDA_ESCALA   días sin recoger → escala (default 3)
  LAVANDERIA_REMISION_GRACIA_H horas tras recibir antes de pedir foto (default 24)
  LAVANDERIA_REMISION_ESCALA   días sin remisión → escala (default 3)
  LAVANDERIA_ESCALA_EMAILS     a quién se escala (default sebastian.hurtado@…)
  LAVANDERIA_PLANTILLA_RECOGER / _REMISION   nombres de plantilla en Meta
  LAVANDERIA_CHASE_ACTIVO      "0" apaga el envío y deja todo en simulación
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

log = logging.getLogger(__name__)

TABLA = "pendientes_lavanderia"
BOGOTA = timezone(timedelta(hours=-5))

APP_URL = os.environ.get("APP_PUBLIC_URL", "https://app.maledenim.com").rstrip("/")


def _cfg_int(nombre: str, default: int) -> int:
    try:
        return int(os.environ.get(nombre, "").strip() or default)
    except ValueError:
        return default


def GRACIA_MIN() -> int:          return _cfg_int("LAVANDERIA_GRACIA_MIN", 30)
def INTERVALO_HORAS() -> int:     return _cfg_int("LAVANDERIA_INTERVALO_HORAS", 24)
def RECOGIDA_ESCALA_DIAS() -> int: return _cfg_int("LAVANDERIA_RECOGIDA_ESCALA", 3)
def REMISION_GRACIA_HORAS() -> int: return _cfg_int("LAVANDERIA_REMISION_GRACIA_H", 24)
def REMISION_ESCALA_DIAS() -> int: return _cfg_int("LAVANDERIA_REMISION_ESCALA", 3)


def activo() -> bool:
    """Con LAVANDERIA_CHASE_ACTIVO=0 el motor calcula y registra pero NO envía.
    Sirve para verlo funcionar un día antes de que le escriba a un proveedor."""
    return (os.environ.get("LAVANDERIA_CHASE_ACTIVO", "1").strip() or "1") != "0"


def _escala_emails() -> list[str]:
    raw = os.environ.get("LAVANDERIA_ESCALA_EMAILS",
                         "sebastian.hurtado@maledenim.com")
    return [e.strip().lower() for e in raw.split(",") if e.strip()]


def _sb():
    from backend.services import produccion as prod
    return prod._sb()


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _ts(valor) -> Optional[datetime]:
    """Parsea un timestamp de Postgres tolerando lo que Python 3.10 no aguanta.

    Railway corre Python 3.10 (Dockerfile jammy), y ahí `fromisoformat` es
    estricto de dos maneras que Postgres viola:

      1. La FRACCIÓN de segundo tiene que ser de 3 o 6 dígitos. Postgres
         recorta los ceros y manda los que le queden ('...46.99+00').
      2. El DESFASE tiene que ser '+HH:MM'. Postgres manda '+00', de dos
         dígitos — y eso revienta con ValueError.

    Las dos ya rompieron el módulo de logística en producción. Local corre 3.12,
    que acepta todo, así que este bug no se ve probando en el Mac: hay que
    normalizar a mano.
    """
    if not valor:
        return None
    if isinstance(valor, datetime):
        return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)
    s = normalizar_ts(str(valor))
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        log.warning(f"[lavanderia-chase] timestamp ilegible: {str(valor)[:40]}")
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def normalizar_ts(s: str) -> str:
    """Deja el texto en la forma exacta que Python 3.10 acepta. Separada de
    `_ts` para poder verificarla contra la regla de 3.10 desde un test, ya que
    en local corre 3.12 y ahí cualquier cosa pasa."""
    s = (s or "").strip().replace(" ", "T")
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    # Fracción de segundo → exactamente 6 dígitos.
    m = re.match(r"^(.*?\.)(\d+)(.*)$", s)
    if m:
        s = f"{m.group(1)}{(m.group(2) + '000000')[:6]}{m.group(3)}"
    # Desfase → siempre ±HH:MM. Cubre '+00' y '+0000'.
    m = re.match(r"^(.*?)([+-])(\d{2})(?::?(\d{2}))?$", s)
    if m:
        s = f"{m.group(1)}{m.group(2)}{m.group(3)}:{m.group(4) or '00'}"
    return s


def _horas_desde(valor) -> Optional[float]:
    dt = _ts(valor)
    return None if dt is None else (_ahora() - dt).total_seconds() / 3600.0


# ═══════════════════════════════════════════════════════════════════════
# DETECCIÓN · leer el grupo sin creerle demasiado
# ═══════════════════════════════════════════════════════════════════════

# Código de lote tal como lo escribe la gente. Cubre DOS cosas a propósito:
#   · consecutivo de orden de corte  → 2608-0007  (AAMM-NNNN)
#   · código de referencia           → 96616-1, 26620-1
#
# COMPROBADO CON EL GRUPO REAL (2026-08-19): el diseñador NO escribe el
# consecutivo, escribe la referencia — «Sale lote de lavandería / Ref 45610-1 /
# Terminacion Francy». La primera versión de esto exigía consecutivo y por eso
# habría detectado CERO de los tres mensajes reales de ese día.
#
# No se intenta distinguir por la forma: se saca el código y **la base decide**
# si es un consecutivo, una referencia, o nada. Es la única validación honesta.
_RE_CODIGO = re.compile(r"\b(\d{3,6})\s*-\s*(\d{1,5})\b")

_RE_LAVANDERIA = re.compile(r"lavander[íi]a|lavanderia|lavando|lavada", re.I)

# Señal de salida. Sin esto, un «la lavandería llamó» abriría persecución.
# `recogid|recodig` incluye el typo real que escribieron en el grupo
# («Revisión recodiga de lote lavandería»).
_RE_SALIDA = re.compile(
    r"\b(sale|salen|sali[óo]|salieron|va|van|despach|enviad|envi[éeo]|"
    r"mand[éoa]|para\s+lavander|a\s+lavander|listo\s+para\s+lavar|"
    r"recoger|recogid|recodig)",
    re.I)

# Si el mensaje niega o corrige, no se abre nada. Es más barato perder una
# detección que escribirle a un proveedor por un lote que no salió.
_RE_NEGACION = re.compile(
    r"\b(no\s+(sali|sale|va|despach|entreg)|a[úu]n\s+no|todav[íi]a\s+no|"
    r"cancel|anul|era\s+broma|me\s+equivoqu|falso|olv[íi]d)", re.I)


def detectar_salida_lavanderia(texto: str) -> dict:
    """¿Este mensaje dice que un lote sale a lavandería? ¿Cuál lote?

    Devuelve {'es_salida': bool, 'codigos': [...], 'motivo': str}.
    Deliberadamente conservador: exige mención de lavandería + señal de salida
    + ausencia de negación. Un falso negativo lo arregla una persona; un falso
    positivo le escribe a un proveedor.
    """
    t = (texto or "").strip()
    if not t:
        return {"es_salida": False, "codigos": [], "motivo": "vacio"}
    if not _RE_LAVANDERIA.search(t):
        return {"es_salida": False, "codigos": [], "motivo": "sin_mencion_lavanderia"}
    if _RE_NEGACION.search(t):
        return {"es_salida": False, "codigos": [], "motivo": "negacion"}
    if not _RE_SALIDA.search(t):
        return {"es_salida": False, "codigos": [], "motivo": "sin_senal_de_salida"}
    # dedup conservando orden de aparición
    vistos, unicos = set(), []
    for a, b in _RE_CODIGO.findall(t):
        c = f"{a}-{b}"
        if c not in vistos:
            vistos.add(c)
            unicos.append(c)
    return {"es_salida": True, "codigos": unicos,
            "motivo": "ok" if unicos else "sin_codigo"}


# ═══════════════════════════════════════════════════════════════════════
# ABRIR Y CERRAR PENDIENTES
# ═══════════════════════════════════════════════════════════════════════

def _ruta_por_consecutivo(consecutivo: str) -> Optional[dict]:
    """La hoja de ruta del lote, buscando por el consecutivo de orden de corte."""
    from backend.services import produccion as prod
    sb = _sb()
    if sb is None:
        return None
    oc = (sb.table("ordenes_corte").select("id,consecutivo")
            .eq("consecutivo", consecutivo).limit(1).execute()).data
    if not oc:
        return None
    return prod.obtener_ruta_por_corte(oc[0]["id"])


def resolver_lote(codigo: str) -> dict:
    """Del código que dijo el grupo al lote concreto.

    Devuelve {'ruta': dict|None, 'via': 'consecutivo'|'referencia'|None,
              'ambiguo': [consecutivos]}.

    POR QUÉ NO ES UN SIMPLE SELECT. Un consecutivo apunta a un lote y ya. Pero
    una REFERENCIA puede tener varias órdenes de corte (la misma prenda cortada
    en tandas distintas), y el grupo dice «Ref 96616-1» sin decir cuál tanda. En
    ese caso:

      · un solo candidato perseguible  → ese es
      · varios                          → NO se adivina. Se devuelve `ambiguo` y
                                          un humano lo enlaza desde el OS.

    «Perseguible» = tiene hoja de ruta y todavía no tiene remisión de lavandería.
    Un lote que ya entregó su remisión no vuelve a la cola por un mensaje nuevo.
    """
    from backend.services import produccion as prod
    codigo = (codigo or "").strip()
    vacio = {"ruta": None, "via": None, "ambiguo": []}
    sb = _sb()
    if sb is None or not codigo:
        return vacio

    # 1) ¿Es un consecutivo de orden de corte?
    ruta = _ruta_por_consecutivo(codigo)
    if ruta:
        return {"ruta": ruta, "via": "consecutivo", "ambiguo": []}

    # 2) ¿Es un código de referencia del precosteo?
    try:
        ref = (sb.table("referencias_precosteo").select("id,codigo_referencia")
                 .eq("codigo_referencia", codigo).limit(1).execute()).data
    except Exception as e:
        log.warning(f"[lavanderia-chase] busqueda de referencia falló: {str(e)[:160]}")
        return vacio
    if not ref:
        return vacio

    ordenes = (sb.table("ordenes_corte").select("id,consecutivo,created_at")
                 .eq("referencia_id", ref[0]["id"])
                 .order("created_at", desc=True).limit(50).execute()).data or []

    candidatos = []
    for oc in ordenes:
        r = prod.obtener_ruta_por_corte(oc["id"])
        if r and not r.get("remision_lavanderia_url"):
            candidatos.append(r)

    if len(candidatos) == 1:
        return {"ruta": candidatos[0], "via": "referencia", "ambiguo": []}
    if len(candidatos) > 1:
        return {"ruta": None, "via": "referencia",
                "ambiguo": [(c.get("orden_corte") or {}).get("consecutivo") or c["id"]
                            for c in candidatos]}
    return vacio


def abrir_pendiente(*, ruta: dict, reloj: str, origen: str = "grupo",
                    wa_message_id: str = "", detectado_texto: str = "",
                    creado_por: str = "", gracia_min: Optional[int] = None) -> dict:
    """Abre la persecución. Idempotente por el índice único parcial: si ya hay
    uno abierto para ese lote y reloj, no crea otro y lo dice."""
    sb = _sb()
    if sb is None:
        return {"abierto": False, "motivo": "sin_supabase"}
    if reloj not in ("recogida", "remision"):
        raise ValueError("reloj_invalido")

    espera = GRACIA_MIN() if gracia_min is None else int(gracia_min)
    oc = ruta.get("orden_corte") or {}
    fila = {
        "hoja_ruta_id":    ruta["id"],
        "orden_corte_id":  ruta["orden_corte_id"],
        "consecutivo":     oc.get("consecutivo"),
        "lavanderia_id":   ruta.get("lavanderia_id"),
        "reloj":           reloj,
        "estado":          "abierto",
        "no_avisar_antes": _iso(_ahora() + timedelta(minutes=espera)),
        "origen":          origen,
        "wa_message_id":   (wa_message_id or "")[:200] or None,
        "detectado_texto": (detectado_texto or "")[:1000] or None,
        "creado_por":      (creado_por or "")[:200] or None,
    }
    try:
        r = sb.table(TABLA).insert(fila).execute()
    except Exception as e:
        # 23505 = viola el índice único parcial → ya había uno abierto. No es
        # un error: es exactamente lo que el índice tiene que evitar.
        if "23505" in str(e) or "duplicate key" in str(e).lower():
            return {"abierto": False, "motivo": "ya_existia",
                    "consecutivo": oc.get("consecutivo")}
        log.warning(f"[lavanderia-chase] insert pendiente falló: {str(e)[:200]}")
        return {"abierto": False, "motivo": f"error:{str(e)[:120]}"}

    p = (r.data or [fila])[0]
    log.info(f"[lavanderia-chase] pendiente {reloj} abierto · "
             f"lote {oc.get('consecutivo')} · lavanderia={ruta.get('lavanderia_id')}")
    _nota(ruta["id"], f"El OS abrió seguimiento de {'recogida' if reloj == 'recogida' else 'remisión'} "
                      f"de lavandería" + (f" (leído del grupo: «{detectado_texto[:120]}»)"
                                          if detectado_texto else ""))
    if not ruta.get("lavanderia_id"):
        _avisar_os(
            titulo=f"Lote {oc.get('consecutivo') or '?'} sale a lavandería sin lavandería asignada",
            mensaje=("Se abrió el seguimiento pero no hay a quién escribirle. "
                     "Asigna la lavandería en la hoja de ruta para que el OS "
                     "pueda pedir la remisión."),
            enlace=f"/produccion/tablero",
        )
    return {"abierto": True, "pendiente": p, "consecutivo": oc.get("consecutivo")}


def al_confirmar_recogida(ruta_id: str) -> dict:
    """La lavandería confirmó que recogió el lote (desde su enlace público).

    Cierra el reloj 1 y arranca el reloj 2 en el mismo movimiento. Se llama en
    línea para que la transición sea inmediata; el barrido periódico hace lo
    mismo por si esta llamada se pierde, así que llamarla dos veces no duplica
    nada (el índice único parcial lo impide).
    """
    out = {"cerrado_recogida": cerrar_pendientes(ruta_id, reloj="recogida",
                                                 motivo="confirmo_recogida"),
           "abrio_remision": False}
    ruta = _ruta_por_id(ruta_id)
    if not ruta:
        return out
    if ruta.get("remision_lavanderia_url"):
        return out  # ya subió la remisión en el mismo paso: nada que perseguir
    r = abrir_pendiente(ruta=ruta, reloj="remision", origen="os",
                        gracia_min=REMISION_GRACIA_HORAS() * 60)
    out["abrio_remision"] = bool(r.get("abierto"))
    return out


def cerrar_pendientes(hoja_ruta_id: str, *, reloj: str, motivo: str) -> int:
    """Cierra los pendientes abiertos de ese lote y reloj. Devuelve cuántos."""
    sb = _sb()
    if sb is None:
        return 0
    try:
        r = (sb.table(TABLA)
               .update({"estado": "cerrado", "cerrado_at": _iso(_ahora()),
                        "motivo_cierre": motivo,
                        "actualizado_en": _iso(_ahora())})
               .eq("hoja_ruta_id", hoja_ruta_id).eq("reloj", reloj)
               .eq("estado", "abierto").execute())
        n = len(r.data or [])
        if n:
            log.info(f"[lavanderia-chase] cerrado {reloj} de {hoja_ruta_id} · {motivo}")
        return n
    except Exception as e:
        log.warning(f"[lavanderia-chase] cerrar {reloj} falló: {str(e)[:200]}")
        return 0


def anular_pendiente(pendiente_id: str, *, motivo: str, por: str = "") -> bool:
    """Un humano dice que la detección se equivocó. Se anula, no se cierra:
    cerrado significa 'se cumplió', anulado significa 'no debió existir'."""
    sb = _sb()
    if sb is None:
        return False
    try:
        r = (sb.table(TABLA)
               .update({"estado": "anulado", "cerrado_at": _iso(_ahora()),
                        "motivo_cierre": f"{motivo} ({por})"[:300],
                        "actualizado_en": _iso(_ahora())})
               .eq("id", pendiente_id).eq("estado", "abierto").execute())
        return bool(r.data)
    except Exception as e:
        log.warning(f"[lavanderia-chase] anular falló: {str(e)[:200]}")
        return False


# ═══════════════════════════════════════════════════════════════════════
# ENTRADA DESDE EL ESPEJO DEL GRUPO
# ═══════════════════════════════════════════════════════════════════════

_RE_REMISION = re.compile(r"remisi[óo]n|remision", re.I)


def al_llegar_media(wa_message_id: str) -> dict:
    """Llegó una foto del grupo. ¿Es la remisión de un lote?

    POR QUÉ ESTO EXISTE ASÍ (2026-08-19). El diseño anterior guardaba la foto y
    esperaba a que una persona dijera de qué lote era. Sebastián probó y dijo lo
    obvio: «la remisión llegó, el lote sí está en el OS, y no hubo cambio en el
    estado». Tenía razón — capturar la foto sin que mueva nada no es trazabilidad,
    es un archivo bonito.

    La regla para no adivinar: se adjunta sola SOLO cuando alguien nombró el lote.
    Dos caminos, los dos con una afirmación humana detrás:

      · el pie de foto dice «remisión» y trae un código que resuelve a UN lote
      · el pie trae un código de un lote que YA tiene abierto el reloj de la
        remisión, o sea que el OS estaba pidiendo justamente eso

    Sin pie de foto no se adjunta nada: una foto muda no dice a qué lote
    pertenece, y adivinarlo movería producción con una suposición.
    """
    from backend.services import produccion as prod
    out = {"adjuntada": False, "motivo": "", "consecutivo": None}
    sb = _sb()
    if sb is None:
        out["motivo"] = "sin_supabase"
        return out
    fila = (sb.table("mensajes_grupo_produccion")
              .select("wa_message_id,texto,media_url,tipo")
              .eq("wa_message_id", (wa_message_id or "").strip())
              .limit(1).execute()).data
    if not fila:
        out["motivo"] = "mensaje_no_encontrado"
        return out
    pie = (fila[0].get("texto") or "").strip()
    if not fila[0].get("media_url"):
        out["motivo"] = "sin_archivo"
        return out
    if not pie:
        out["motivo"] = "sin_pie_de_foto"
        return out

    codigos = [f"{a}-{b}" for a, b in _RE_CODIGO.findall(pie)]
    if not codigos:
        out["motivo"] = "el_pie_no_trae_codigo"
        return out

    dice_remision = bool(_RE_REMISION.search(pie))
    for cod in codigos:
        hallado = resolver_lote(cod)
        ruta = hallado.get("ruta")
        if not ruta:
            continue
        # Si el pie no dice «remisión», solo se acepta cuando el OS ya estaba
        # pidiendo la remisión de ese lote. Así una foto cualquiera con un
        # número no se convierte en documento por accidente.
        if not dice_remision and not _tiene_pendiente_remision(ruta["id"]):
            out["motivo"] = "el_pie_no_dice_remision_y_no_habia_pendiente"
            continue
        if ruta.get("remision_lavanderia_url"):
            out["motivo"] = "el_lote_ya_tenia_remision"
            continue
        try:
            prod.usar_media_grupo_como_remision(
                wa_message_id=wa_message_id, ruta_id=ruta["id"],
                usuario="OS · leído del grupo")
        except Exception as e:
            log.warning(f"[lavanderia-chase] adjuntar remisión falló: {str(e)[:200]}")
            out["motivo"] = f"error:{str(e)[:100]}"
            return out
        cons = (ruta.get("orden_corte") or {}).get("consecutivo") or cod
        out.update({"adjuntada": True, "motivo": "ok", "consecutivo": cons})
        log.info(f"[lavanderia-chase] remisión adjuntada al lote {cons} desde el grupo")
        _avisar_os(
            titulo=f"Remisión de lavandería del lote {cons} cargada desde el grupo",
            mensaje=(f"Llegó una foto al grupo con el pie «{pie[:120]}» y el OS la "
                     f"guardó como remisión de ese lote. La etapa avanzó a "
                     f"lavandería. Si es un error, se puede reemplazar desde la "
                     f"hoja de ruta."),
            enlace="/produccion/tablero",
            dedup_wa_id=wa_message_id,
        )
        return out
    if not out["motivo"]:
        out["motivo"] = "ningun_codigo_del_pie_existe_en_el_os"
    return out


def _tiene_pendiente_remision(ruta_id: str) -> bool:
    sb = _sb()
    if sb is None:
        return False
    try:
        r = (sb.table(TABLA).select("id")
               .eq("hoja_ruta_id", ruta_id).eq("reloj", "remision")
               .eq("estado", "abierto").limit(1).execute()).data
        return bool(r)
    except Exception:
        return False


def reprocesar_espejo(*, limite: int = 200, desde: str = "") -> dict:
    """Vuelve a leer mensajes YA guardados con la detección de hoy.

    Hace falta porque la detección cambia: los mensajes del 19-ago que decían
    «Sale lote de lavandería / Ref 96616-1» entraron cuando el código solo
    entendía consecutivos, así que no abrieron nada. El espejo guarda el
    original justamente para poder volver sobre él.

    Es seguro repetirlo: `_ya_procesado` impide abrir dos veces por el mismo
    mensaje, y los códigos que no existen en el OS se ignoran.
    """
    sb = _sb()
    if sb is None:
        return {"ok": False, "error": "sin_supabase"}
    q = (sb.table("mensajes_grupo_produccion")
           .select("wa_message_id,texto,autor_nombre,enviado_en")
           .order("enviado_en", desc=True).limit(min(int(limite), 500)))
    if desde:
        q = q.gte("enviado_en", desde)
    filas = (q.execute()).data or []
    res = procesar_mensajes(filas)
    return {"ok": True, "mensajes_leidos": len(filas), **res}


def _ya_procesado(wa_message_id: str) -> bool:
    """¿Este mensaje del grupo ya abrió un pendiente alguna vez?

    Importa porque el espejo es idempotente pero re-envía: el oyente puede
    subir el mismo `wa_message_id` otra vez. Si alguien ANULÓ el pendiente
    porque la detección se equivocó, volver a leer el mensaje lo resucitaría y
    el proveedor recibiría el aviso que justamente se canceló. Se mira en
    CUALQUIER estado, no solo abiertos.
    """
    if not wa_message_id:
        return False
    sb = _sb()
    if sb is None:
        return False
    try:
        r = (sb.table(TABLA).select("id")
               .eq("wa_message_id", wa_message_id).limit(1).execute()).data
        return bool(r)
    except Exception:
        return False


def procesar_mensajes(mensajes: list[dict]) -> dict:
    """Corre la detección sobre los mensajes que acaban de entrar al espejo.

    Se llama después de guardar, nunca antes: si esto falla, el espejo ya está
    a salvo. Nunca lanza — el oyente no puede quedarse sin poder subir mensajes
    porque la detección tenga un problema.
    """
    # `ignorados` = se habló de lavandería pero el lote no es del OS. No es un
    # error ni un pendiente: es tráfico que no nos toca.
    res = {"revisados": 0, "detectados": 0, "abiertos": 0,
           "sin_lote": 0, "ignorados": 0, "ya_existian": 0}
    for m in (mensajes or []):
        try:
            texto = (m.get("texto") or "").strip()
            if not texto:
                continue
            if _ya_procesado(m.get("wa_message_id") or ""):
                continue
            res["revisados"] += 1
            d = detectar_salida_lavanderia(texto)
            if not d["es_salida"]:
                continue
            res["detectados"] += 1

            if not d["codigos"]:
                # SILENCIO A PROPÓSITO (instrucción de Sebastián, 2026-08-19):
                # «las referencias que envíen por ahí y no existan en el OS no
                # las tengas en cuenta». En el grupo se habla de lotes que el
                # OS no conoce — el primer día ya pasó con 45610-1 y 86509-2.
                # Avisar de cada uno convertiría la campanita en ruido, y una
                # campanita que repite es una campanita que se ignora.
                res["ignorados"] += 1
                log.info(f"[lavanderia-chase] salida sin código identificable — ignorado")
                continue

            for cod in d["codigos"]:
                hallado = resolver_lote(cod)
                ruta = hallado["ruta"]
                if not ruta:
                    if not hallado["ambiguo"]:
                        # El código no existe en el OS. Se ignora en silencio:
                        # no es un problema que alguien tenga que resolver, es
                        # un lote que sencillamente no se lleva por acá.
                        res["ignorados"] += 1
                        log.info(f"[lavanderia-chase] {cod} no existe en el OS — ignorado")
                        continue
                    # Acá solo llega lo AMBIGUO: la referencia sí existe en el
                    # OS pero tiene varias tandas cortadas y el grupo no dice
                    # cuál. Eso sí se avisa, porque es un lote nuestro y hay algo
                    # concreto que una persona puede resolver.
                    res["sin_lote"] += 1
                    _avisar_os(
                        titulo=f"«{cod}» sale a lavandería, pero hay varios lotes de esa referencia",
                        mensaje=("No sé cuál es: " + ", ".join(hallado["ambiguo"][:6]) +
                                 f". Texto del grupo: «{texto[:150]}». "
                                 f"Ábrele el seguimiento al lote correcto desde el OS."),
                        enlace="/produccion/lavanderia",
                        dedup_wa_id=m.get("wa_message_id") or "",
                    )
                    log.info(f"[lavanderia-chase] {cod} ambiguo: {hallado['ambiguo']}")
                    continue
                log.info(f"[lavanderia-chase] {cod} resuelto por {hallado['via']}")
                r = abrir_pendiente(ruta=ruta, reloj="recogida", origen="grupo",
                                    wa_message_id=m.get("wa_message_id") or "",
                                    detectado_texto=texto,
                                    creado_por=m.get("autor_nombre") or "grupo")
                if r.get("abierto"):
                    res["abiertos"] += 1
                elif r.get("motivo") == "ya_existia":
                    res["ya_existian"] += 1
        except Exception as e:
            log.warning(f"[lavanderia-chase] mensaje falló: {str(e)[:200]}")
    if res["detectados"]:
        log.info(f"[lavanderia-chase] {res}")
    return res


# ═══════════════════════════════════════════════════════════════════════
# EL BARRIDO · los dos relojes corriendo
# ═══════════════════════════════════════════════════════════════════════

def barrer() -> dict:
    """Un tick de los dos relojes. Corre solo en el worker líder.

    Orden importante: primero CIERRA lo que ya se cumplió (por si el cierre en
    línea se perdió) y ABRE el reloj 2 de los que ya confirmaron recogida.
    Solo después molesta a alguien. Así nunca se pide algo que ya llegó.
    """
    sb = _sb()
    if sb is None:
        return {"ok": False, "error": "sin_supabase"}

    resumen = {"revisados": 0, "cerrados": 0, "remision_abiertos": 0,
               "avisos": 0, "escalados": 0, "sin_destinatario": 0,
               "simulados": 0, "fallos": 0}
    try:
        abiertos = (sb.table(TABLA).select("*")
                      .eq("estado", "abierto")
                      .order("abierto_at").limit(500).execute()).data or []
    except Exception as e:
        log.warning(f"[lavanderia-chase] no pude leer pendientes: {str(e)[:200]}")
        return {"ok": False, "error": str(e)[:200]}

    for p in abiertos:
        resumen["revisados"] += 1
        try:
            ruta = _ruta_por_id(p["hoja_ruta_id"])
            if not ruta:
                continue

            # ── 1. ¿ya se cumplió?
            if p["reloj"] == "recogida" and ruta.get("lav_recibido_at"):
                cerrar_pendientes(p["hoja_ruta_id"], reloj="recogida",
                                  motivo="confirmo_recogida")
                resumen["cerrados"] += 1
                # Recogió → arranca el reloj de la remisión, con su gracia.
                if not ruta.get("remision_lavanderia_url"):
                    r = abrir_pendiente(ruta=ruta, reloj="remision", origen="os",
                                        gracia_min=REMISION_GRACIA_HORAS() * 60)
                    if r.get("abierto"):
                        resumen["remision_abiertos"] += 1
                continue

            if p["reloj"] == "remision" and ruta.get("remision_lavanderia_url"):
                cerrar_pendientes(p["hoja_ruta_id"], reloj="remision",
                                  motivo="remision_cargada")
                resumen["cerrados"] += 1
                continue

            # ── 2. ¿toca escalar?
            dias = (_horas_desde(p["abierto_at"]) or 0) / 24.0
            limite = (RECOGIDA_ESCALA_DIAS() if p["reloj"] == "recogida"
                      else REMISION_ESCALA_DIAS())
            if dias >= limite:
                if _escalar(p, ruta, dias):
                    resumen["escalados"] += 1
                continue

            # ── 3. ¿toca avisar?
            if (_ts(p["no_avisar_antes"]) or _ahora()) > _ahora():
                continue
            ult = _horas_desde(p.get("ultimo_aviso_at"))
            if ult is not None and ult < INTERVALO_HORAS():
                continue

            lav = ruta.get("lavanderia") or {}
            tel = (lav.get("telefono") or "").strip()
            if not (ruta.get("lavanderia_id") and tel):
                resumen["sin_destinatario"] += 1
                continue

            if not activo():
                resumen["simulados"] += 1
                log.info(f"[lavanderia-chase] SIMULADO aviso {p['reloj']} "
                         f"lote {p.get('consecutivo')} → {lav.get('nombre')}")
                continue

            if _avisar_lavanderia(p, ruta):
                resumen["avisos"] += 1
            else:
                resumen["fallos"] += 1
        except Exception as e:
            resumen["fallos"] += 1
            log.warning(f"[lavanderia-chase] pendiente {p.get('id')} falló: {str(e)[:200]}")

    if any(resumen[k] for k in ("avisos", "escalados", "cerrados", "remision_abiertos")):
        log.info(f"[lavanderia-chase] barrido: {resumen}")
    return {"ok": True, **resumen}


def _ruta_por_id(ruta_id: str) -> Optional[dict]:
    sb = _sb()
    if sb is None:
        return None
    r = (sb.table("hoja_ruta_lote")
           .select("*,lavanderia:lavanderia_id(nombre,telefono),"
                   "orden_corte:orden_corte_id(consecutivo)")
           .eq("id", ruta_id).limit(1).execute()).data
    return r[0] if r else None


def _claim(p: dict) -> bool:
    """Toma el turno de aviso ANTES de enviar, con compare-and-set sobre el
    contador. Si otro proceso ya lo tomó, el contador cambió y este update no
    afecta filas → no se manda nada dos veces. Es un mensaje a un proveedor:
    preferimos perder un aviso que mandarlo doble.
    """
    sb = _sb()
    if sb is None:
        return False
    try:
        r = (sb.table(TABLA)
               .update({"avisos": (p.get("avisos") or 0) + 1,
                        "ultimo_aviso_at": _iso(_ahora()),
                        "actualizado_en": _iso(_ahora())})
               .eq("id", p["id"]).eq("avisos", p.get("avisos") or 0)
               .eq("estado", "abierto").execute())
        return bool(r.data)
    except Exception as e:
        log.warning(f"[lavanderia-chase] claim falló: {str(e)[:200]}")
        return False


def _soltar_claim(p: dict) -> None:
    """El envío falló: devolver el turno para que el próximo tick reintente.
    Sin esto, un fallo de red costaría 24 horas de silencio."""
    sb = _sb()
    if sb is None:
        return
    try:
        (sb.table(TABLA)
           .update({"avisos": p.get("avisos") or 0,
                    "ultimo_aviso_at": p.get("ultimo_aviso_at"),
                    "actualizado_en": _iso(_ahora())})
           .eq("id", p["id"]).execute())
    except Exception:
        pass


def _avisar_lavanderia(p: dict, ruta: dict) -> bool:
    """Mensaje a la lavandería por la Cloud API. Plantilla aprobada primero
    (inicia conversación aunque nunca nos haya escrito); si la plantilla no
    sale, texto libre por si estamos dentro de la ventana de 24 h."""
    from backend.services import whatsapp_cloud as wa

    lav = ruta.get("lavanderia") or {}
    nombre = (lav.get("nombre") or "equipo").strip()
    tel = (lav.get("telefono") or "").strip()
    cons = p.get("consecutivo") or (ruta.get("orden_corte") or {}).get("consecutivo") or "—"
    token = ruta.get("token_publico_lavanderia") or ""
    enlace = f"{APP_URL}/lavanderia/{token}" if token else f"{APP_URL}"

    if p["reloj"] == "recogida":
        plantilla = os.environ.get("LAVANDERIA_PLANTILLA_RECOGER",
                                   "lavanderia_recoger").strip()
        texto = (f"Hola {nombre}, MALE'DENIM tiene el lote *{cons}* listo para "
                 f"que lo recojas. Cuando lo tengas, confírmalo acá para que "
                 f"quede registrado:\n\n{enlace}")
    else:
        plantilla = os.environ.get("LAVANDERIA_PLANTILLA_REMISION",
                                   "lavanderia_remision").strip()
        texto = (f"Hola {nombre}, nos falta la remisión del lote *{cons}*. "
                 f"Súbele la foto acá — sin la remisión el lote no entra al "
                 f"pago de esta semana:\n\n{enlace}")

    envio = wa.enviar_plantilla(tel, plantilla, variables=[nombre, cons],
                                boton_url_suffix=token or None)
    if not envio.get("enviado"):
        log.info(f"[lavanderia-chase] plantilla {plantilla} no salió "
                 f"({envio.get('detalle') or envio.get('motivo')}); intento texto libre")
        envio = wa.enviar_texto(tel, texto)

    if not envio.get("enviado"):
        _soltar_claim(p)
        log.warning(f"[lavanderia-chase] aviso {p['reloj']} lote {cons} NO salió: "
                    f"{envio.get('detalle') or envio.get('motivo')}")
        return False

    _nota(ruta["id"],
          f"El OS le escribió a {nombre} por WhatsApp: "
          f"{'¿ya recogiste el lote?' if p['reloj'] == 'recogida' else 'falta la remisión'} "
          f"(aviso #{(p.get('avisos') or 0) + 1})")
    return True


def _escalar(p: dict, ruta: dict, dias: float) -> bool:
    """Se cumplió el plazo. Escala por campanita y por correo, y marca el
    pendiente como escalado para no repetir el escalamiento todos los días."""
    sb = _sb()
    cons = p.get("consecutivo") or "?"
    lav = (ruta.get("lavanderia") or {}).get("nombre") or "sin lavandería asignada"
    d = int(dias)

    if p["reloj"] == "recogida":
        titulo = f"Lavandería no ha recogido el lote {cons} ({d} días)"
        cuerpo = (f"El lote {cons} salió para lavandería hace {d} días y "
                  f"{lav} todavía no confirma que lo recogió. El cuello de "
                  f"botella es la RECOGIDA, no la remisión.")
    else:
        titulo = f"Falta la remisión de lavandería del lote {cons} ({d} días)"
        cuerpo = (f"{lav} recibió el lote {cons} y no ha subido la remisión "
                  f"después de {d} días. Sin remisión el lote no avanza y no "
                  f"se activa el pago de esta semana.")

    if sb is not None:
        try:
            (sb.table(TABLA)
               .update({"estado": "escalado", "escalado_at": _iso(_ahora()),
                        "motivo_cierre": f"escalado_{d}_dias",
                        "actualizado_en": _iso(_ahora())})
               .eq("id", p["id"]).eq("estado", "abierto").execute())
        except Exception as e:
            log.warning(f"[lavanderia-chase] marcar escalado falló: {str(e)[:200]}")

    _avisar_os(titulo=titulo, mensaje=cuerpo,
               enlace=f"/produccion/lavanderia", solo=_escala_emails())
    _correo_escalamiento(titulo, cuerpo)
    _nota(ruta["id"], f"Escalado a dirección: {titulo}")
    log.info(f"[lavanderia-chase] ESCALADO · {titulo}")
    return True


# ═══════════════════════════════════════════════════════════════════════
# CANALES DE AVISO INTERNO
# ═══════════════════════════════════════════════════════════════════════

def _avisar_os(*, titulo: str, mensaje: str, enlace: str = "",
               solo: Optional[list[str]] = None,
               dedup_wa_id: str = "") -> None:
    """Campanita del OS. `solo` = lista de correos; si no, va al módulo.

    `dedup_wa_id`: para los avisos que NO dejan pendiente en la tabla (el caso
    «dijeron lavandería pero no pude identificar el lote») no hay índice único
    que los frene. Si el oyente reintenta el mismo mensaje, la campanita
    repetiría — y una campanita que repite es una campanita que se ignora.
    """
    try:
        from backend.services import notificaciones as notif
        if dedup_wa_id:
            sb = _sb()
            if sb is not None:
                try:
                    ya = (sb.table("notificaciones").select("id")
                            .eq("tipo", "lavanderia_pendiente")
                            .eq("meta->>wa_message_id", dedup_wa_id)
                            .limit(1).execute()).data
                    if ya:
                        return
                except Exception:
                    pass  # si el dedup falla, mejor avisar de más que callar
        meta = {"wa_message_id": dedup_wa_id} if dedup_wa_id else None
        if solo:
            for email in solo:
                notif.crear(destinatario_email=email, tipo="lavanderia_pendiente",
                            titulo=titulo, mensaje=mensaje, enlace=enlace,
                            meta=meta, creado_por="sistema")
        else:
            notif.crear_para_modulo(modulo="produccion_cortador",
                                    tipo="lavanderia_pendiente", titulo=titulo,
                                    mensaje=mensaje, enlace=enlace,
                                    meta=meta, creado_por="sistema")
    except Exception as e:
        log.warning(f"[lavanderia-chase] campanita falló: {str(e)[:160]}")


def _correo_escalamiento(titulo: str, cuerpo: str) -> None:
    try:
        from backend.services import correo
        if not correo.disponible():
            return
        for email in _escala_emails():
            correo.enviar(para=email, asunto=f"🧵 {titulo}",
                          html=f"<p>{cuerpo}</p>"
                               f"<p><a href=\"{APP_URL}/produccion/lavanderia\">"
                               f"Ver pendientes de lavandería</a></p>",
                          texto=f"{cuerpo}\n\n{APP_URL}/produccion/lavanderia")
    except Exception as e:
        log.warning(f"[lavanderia-chase] correo falló: {str(e)[:160]}")


def _nota(ruta_id: str, mensaje: str) -> None:
    """Todo lo que hace el motor queda en el timeline del lote. Si mañana
    alguien pregunta «¿le avisamos a la lavandería?», la respuesta está ahí."""
    try:
        from backend.services import produccion as prod
        prod.crear_nota_ruta(ruta_id=ruta_id, actor="admin", mensaje=mensaje,
                             autor="OS · seguimiento lavandería")
    except Exception as e:
        log.warning(f"[lavanderia-chase] nota falló: {str(e)[:160]}")


# ═══════════════════════════════════════════════════════════════════════
# LECTURA PARA EL OS
# ═══════════════════════════════════════════════════════════════════════

def listar(*, estado: str = "abierto", limite: int = 200) -> list[dict]:
    sb = _sb()
    if sb is None:
        return []
    q = (sb.table(TABLA)
           .select("*,lavanderia:lavanderia_id(nombre,telefono)")
           .order("abierto_at", desc=True).limit(min(int(limite), 500)))
    if estado and estado != "todos":
        q = q.eq("estado", estado)
    filas = (q.execute()).data or []
    for f in filas:
        h = _horas_desde(f.get("abierto_at"))
        f["dias_abierto"] = round((h or 0) / 24.0, 1)
    return filas


def resumen() -> dict:
    """Contadores para el tablero: cuántos esperan recogida, cuántos remisión,
    cuántos ya se escalaron."""
    filas = listar(estado="todos", limite=500)
    out = {"abiertos_recogida": 0, "abiertos_remision": 0, "escalados": 0,
           "sin_destinatario": 0, "cerrados": 0}
    for f in filas:
        if f["estado"] == "abierto":
            out["abiertos_recogida" if f["reloj"] == "recogida"
                else "abiertos_remision"] += 1
            if not f.get("lavanderia_id"):
                out["sin_destinatario"] += 1
        elif f["estado"] == "escalado":
            out["escalados"] += 1
        elif f["estado"] == "cerrado":
            out["cerrados"] += 1
    return out
