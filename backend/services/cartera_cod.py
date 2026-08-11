"""
CARTERA CONTRAENTREGA — lo que Melonn nos debe DE VERDAD.
═══════════════════════════════════════════════════════════════════════════

EL PROBLEMA (2026-08-10, pedido de Sebastián): el tablero mostraba
$168.388.033 de "COD entregado". Ese número es la suma de TODO lo entregado en
la ventana de 90 días y solo crece, porque nunca descuenta lo que Melonn ya
consignó. Medido contra producción ese mismo día:

    tablero              $168.388.033   (936 pedidos entregados)
    deuda real            $36.552.345   (210 facturas con saldo abierto)
    ya cobrado           $124.064.381   (689 facturas en saldo 0)

Inflado 4,6 veces. Con un número así no se puede reclamar nada ni proyectar
caja: no se sabe qué parte ya entró.

LA SOLUCIÓN: no calcularlo, LEERLO. Cada factura de venta en Siigo trae

    observations = "Orden Nº: 62098 - Medio de Pago: CASH ON DELIVERY (COD)"

y trae su `balance`. Ese saldo ES la cartera viva: si está en 0, el dinero
llegó; si no, Melonn lo tiene. La contadora ya hace ese registro, así que la
app no tiene que interpretar nada — solo cruzar el número de orden.

DOS COSAS QUE APARECIERON AL CRUZAR y que el tablero tapaba:

  · 44 pedidos ENTREGADOS ($8.391.900) sin factura de venta en Siigo.
    Mercancía que salió, el cliente pagó, y no hay factura. Ese hueco es más
    grave que el número inflado, y antes era invisible.
  · Saldos de mayo y junio todavía abiertos (FV-1-60544, orden entregada el
    23 de mayo). Plata para reclamar, no para esperar.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from datetime import date, datetime, timedelta, timezone
from typing import Optional

log = logging.getLogger("maledenim.cartera_cod")

# El medio de pago con el que la contadora marca las facturas de contraentrega.
# Se compara normalizado; si algún día cambia el texto, `MEDIOS_COD` es el único
# sitio que hay que tocar.
MEDIOS_COD = ("CASH ON DELIVERY (COD)", "CONTRAENTREGA", "COD")

# "Orden Nº: 62098 - Medio de Pago: CASH ON DELIVERY (COD)"
# El Nº tolera º, o, ° y la falta de dos puntos: son datos digitados a mano.
_RE_OBS = re.compile(
    r"Orden\s*N[ºo°]?\s*:?\s*(\d+)\s*-\s*Medio\s+de\s+Pago\s*:\s*(.+)$",
    re.IGNORECASE)

# Estados Melonn que significan ENTREGADO (el cliente ya pagó).
_CODES_ENTREGADO = (6, 8)

# Cuántos días atrás pedir facturas. El tablero de Melonn solo trae 90 días de
# pedidos, así que una factura más vieja que eso no puede cruzar con ningún
# entregado: pedir más es pagar páginas de Siigo para nada. 120 da margen.
DIAS_VENTANA = 120

# Cache: el fetch son ~80 páginas de Siigo. Sin cache, cada carga del tablero
# reventaría el rate limit. Stale-while-revalidate: se sirve el dato viejo y se
# refresca atrás, para que la pantalla nunca espere 80 llamadas.
# 2 h: son ~90 páginas de Siigo por refresco y una cartera no cambia por minuto.
_TTL = 7200
_cache: dict = {}
_refresh_en_curso: set = set()
_lock = threading.Lock()


def _norm(s: Optional[str]) -> str:
    return (s or "").strip().upper()


def _es_cod(medio: str) -> bool:
    m = _norm(medio)
    return any(k in m for k in MEDIOS_COD)


def _numeros_orden(valor) -> list[str]:
    """'60822#60821' → ['60822','60821'].  '#61966' → ['61966'].

    Los pedidos combinados existen: dos órdenes de Shopify que se despachan
    juntas quedan con el número pegado. Sin partirlos, esos pedidos nunca
    cruzaban y se contaban como 'entregado sin facturar' siendo mentira.
    """
    return re.findall(r"\d{4,}", str(valor or ""))


# ═══════════════════════════════════════════════════════════════════════
# Facturas COD de Siigo
# ═══════════════════════════════════════════════════════════════════════

def _fetch_facturas_cod(desde: str) -> dict[str, list[dict]]:
    """{numero_de_orden: [factura, …]} solo de las facturas de contraentrega."""
    from backend.services import siigo

    por_orden: dict[str, list[dict]] = {}
    total = con_patron = cod = 0
    page = 1
    while page <= 200:
        data = siigo.siigo_get("/invoices", {"created_start": desde,
                                             "page": page, "page_size": 100})
        res = data.get("results") or []
        if not res:
            break
        for f in res:
            total += 1
            m = _RE_OBS.search((f.get("observations") or "").strip())
            if not m:
                continue
            con_patron += 1
            if not _es_cod(m.group(2)):
                continue
            cod += 1
            por_orden.setdefault(m.group(1), []).append({
                "factura":  f.get("name"),
                "fecha":    (f.get("date") or "")[:10],
                "total":    float(f.get("total") or 0),
                "saldo":    float(f.get("balance") or 0),
                "cliente":  (f.get("customer") or {}).get("identification"),
                "url":      f.get("public_url"),
            })
        if len(res) < 100:
            break
        page += 1
    log.info(f"[cartera_cod] {total} facturas desde {desde}; {con_patron} con "
             f"'Orden Nº'; {cod} de contraentrega en {len(por_orden)} órdenes")
    return por_orden


def _refrescar_atras(desde: str) -> None:
    with _lock:
        if desde in _refresh_en_curso:
            return
        _refresh_en_curso.add(desde)

    def _run():
        try:
            _cache[desde] = (time.time(), _fetch_facturas_cod(desde))
            log.info(f"[cartera_cod] cache refrescado ({desde})")
        except Exception as e:
            log.warning(f"[cartera_cod] refresh atrás falló: {str(e)[:140]}")
        finally:
            with _lock:
                _refresh_en_curso.discard(desde)

    threading.Thread(target=_run, daemon=True).start()


def facturas_cod(*, desde: Optional[str] = None, force: bool = False) -> dict:
    desde = desde or (date.today() - timedelta(days=DIAS_VENTANA)).isoformat()
    hit = _cache.get(desde)
    if hit and not force:
        if time.time() - hit[0] >= _TTL:
            _refrescar_atras(desde)
        return hit[1]
    datos = _fetch_facturas_cod(desde)
    _cache[desde] = (time.time(), datos)
    return datos


# ═══════════════════════════════════════════════════════════════════════
# El cruce
# ═══════════════════════════════════════════════════════════════════════

def cruzar(pedidos: list[dict], *, desde: Optional[str] = None) -> dict:
    """Cruza los COD ENTREGADOS contra sus facturas de Siigo.

    `pedidos` son los del tablero, ya pasados por `metricas.clasificar`
    (necesita `tipo_recaudo`, `estado_melonn_code`, `orden_tienda`, `valor_num`).

    Devuelve, y esto es lo importante, CUATRO cifras que antes eran una sola:

      melonn_debe      lo que falta por consignar  (saldo abierto en Siigo)
      ya_cobrado       lo que ya entró             (saldo en 0)
      sin_facturar     entregado y NO facturado    (hueco de facturación)
      en_transito      facturado con saldo, aún no entregado

    Si Siigo no responde, `disponible` sale en False y NO se inventa un
    número: un tablero de plata que muestra un cero se lee como "no nos deben
    nada", que es la peor mentira posible.
    """
    try:
        fv = facturas_cod(desde=desde)
    except Exception as e:
        log.error(f"[cartera_cod] Siigo no respondió: {str(e)[:160]}")
        return {"disponible": False,
                "motivo": f"Siigo no respondió: {str(e)[:120]}"}

    entregados: dict[str, dict] = {}
    for p in pedidos:
        if _norm(p.get("tipo_recaudo")) != "CONTRAENTREGA":
            continue
        try:
            code = int(p.get("estado_melonn_code") or 0)
        except (TypeError, ValueError):
            code = 0
        if code not in _CODES_ENTREGADO:
            continue
        for n in _numeros_orden(p.get("orden_tienda")):
            entregados.setdefault(n, p)

    hoy = datetime.now(timezone.utc).date()
    abiertas: list[dict] = []
    cobrado = 0.0
    n_cobrado = 0
    vistas: set = set()

    for n, p in entregados.items():
        for f in fv.get(n, []):
            if f["factura"] in vistas:
                continue          # una factura puede cubrir dos órdenes
            vistas.add(f["factura"])
            if f["saldo"] > 0:
                try:
                    dias = (hoy - date.fromisoformat(f["fecha"])).days
                except (TypeError, ValueError):
                    dias = None
                abiertas.append({**f, "orden": n, "dias": dias,
                                 "entrega": (p.get("fecha_entrega") or "")[:10],
                                 "ciudad": p.get("ciudad_destino"),
                                 "valor_melonn": p.get("valor_num")})
            else:
                cobrado += f["total"]
                n_cobrado += 1

    sin_facturar = [{"orden": n,
                     "valor": p.get("valor_num") or 0,
                     "entrega": (p.get("fecha_entrega") or "")[:10],
                     "ciudad": p.get("ciudad_destino")}
                    for n, p in entregados.items() if n not in fv]

    # Facturado con saldo pero el pedido no está entregado: es cartera futura,
    # no deuda exigible. Se muestra aparte para que no se confunda con lo uno.
    en_transito = 0.0
    n_transito = 0
    for n, fs in fv.items():
        if n in entregados:
            continue
        for f in fs:
            if f["saldo"] > 0:
                en_transito += f["saldo"]
                n_transito += 1

    abiertas.sort(key=lambda x: (x["dias"] is None, -(x["dias"] or 0)))
    deuda = round(sum(f["saldo"] for f in abiertas), 2)

    # Antigüedad: una deuda de 90 días no se cobra igual que una de 5.
    tramos = {"0-15": 0.0, "16-30": 0.0, "31-60": 0.0, "60+": 0.0, "sin_fecha": 0.0}
    for f in abiertas:
        d = f["dias"]
        k = ("sin_fecha" if d is None else
             "0-15" if d <= 15 else "16-30" if d <= 30 else
             "31-60" if d <= 60 else "60+")
        tramos[k] = round(tramos[k] + f["saldo"], 2)

    return {
        "disponible":        True,
        "melonn_debe":       deuda,
        "n_melonn_debe":     len(abiertas),
        "ya_cobrado":        round(cobrado, 2),
        "n_ya_cobrado":      n_cobrado,
        "sin_facturar":      round(sum(x["valor"] for x in sin_facturar), 2),
        "n_sin_facturar":    len(sin_facturar),
        "en_transito":       round(en_transito, 2),
        "n_en_transito":     n_transito,
        "entregados_total":  len(entregados),
        "antiguedad":        tramos,
        "abiertas":          abiertas[:300],
        "sin_factura":       sorted(sin_facturar, key=lambda x: x["entrega"])[:300],
    }


# ═══════════════════════════════════════════════════════════════════════
# ALERTA POR ANTIGÜEDAD
# ═══════════════════════════════════════════════════════════════════════
#
# POR QUÉ (2026-08-10): al cruzar por primera vez aparecieron saldos de MAYO
# todavía abiertos — la FV-1-60544 con 88 días, de un pedido entregado el 23 de
# mayo. Nadie lo sabía porque el tablero mostraba un solo número gigante que
# crecía. El ciclo normal de Melonn es de días: pasados 30, eso no es demora, es
# plata perdida de vista.
#
# UMBRAL EN 30 DÍAS y no en 15: el 86% de la cartera vive en la franja 0-15, que
# es el ciclo sano. Avisar a los 15 sería avisar por lo normal, y una alerta que
# suena por lo normal enseña a ignorarla.

UMBRAL_DIAS_VENCIDA = 30
UMBRAL_DIAS_SIN_FACTURAR = 15
RECORDAR_CADA_H = 24          # un recordatorio al día, no uno por tick


def _ultimo_aviso(tipo: str) -> Optional[dict]:
    """La última notificación de ese tipo. La tabla de avisos ES la memoria:
    así no hace falta una tabla nueva ni estado en el proceso —que con 4 workers
    y reinicios no serviría de nada—."""
    try:
        from backend.services import notificaciones
        sb = notificaciones._sb()
        if sb is None:
            return None
        r = (sb.table("notificaciones").select("creado_en,meta")
               .eq("tipo", tipo).order("creado_en", desc=True)
               .limit(1).execute()).data
        return r[0] if r else None
    except Exception as e:
        log.warning(f"[cartera_cod] no pude leer el último aviso: {str(e)[:120]}")
        return None


def _debe_avisar(tipo: str, claves: list[str]) -> bool:
    """Avisar si el problema CAMBIÓ, o si ya pasaron las horas del recordatorio.

    'Cambió' significa que apareció algo nuevo, no que desapareció: si una
    factura se cobró, la lista se achica y eso no merece una alerta.
    """
    prev = _ultimo_aviso(tipo)
    if not prev:
        return True
    antes = set((prev.get("meta") or {}).get("claves") or [])
    if set(claves) - antes:
        return True               # hay algo nuevo vencido
    try:
        cuando = datetime.fromisoformat(str(prev.get("creado_en")).replace("Z", "+00:00"))
        if cuando.tzinfo is None:
            cuando = cuando.replace(tzinfo=timezone.utc)
        horas = (datetime.now(timezone.utc) - cuando).total_seconds() / 3600
        return horas >= RECORDAR_CADA_H
    except (TypeError, ValueError):
        return True               # fecha ilegible: mejor avisar que callarse


def revisar_y_avisar(pedidos: list[dict]) -> dict:
    """Revisa la cartera y avisa a la campanita de finanzas si hay plata vieja.

    Manda hasta DOS avisos, con tipos distintos a propósito: uno se le reclama a
    Melonn y el otro lo cierra contabilidad. Mezclarlos en un solo mensaje haría
    que nadie sepa a quién le toca.
    """
    res = cruzar(pedidos)
    if not res.get("disponible"):
        return {"ok": False, "motivo": res.get("motivo")}

    from backend.services import notificaciones
    salida = {"ok": True, "avisos": []}

    # ── 1. Facturas entregadas con saldo viejo → se le reclama a Melonn ──
    vencidas = [f for f in (res.get("abiertas") or [])
                if (f.get("dias") or 0) > UMBRAL_DIAS_VENCIDA]
    if vencidas:
        claves = sorted(f["factura"] for f in vencidas)
        monto = sum(f["saldo"] for f in vencidas)
        if _debe_avisar("cartera_cod_vencida", claves):
            vieja = max(vencidas, key=lambda f: f.get("dias") or 0)
            n = notificaciones.crear_para_modulo(
                modulo="finanzas",
                tipo="cartera_cod_vencida",
                titulo=(f"Contraentrega: {len(vencidas)} factura(s) con más de "
                        f"{UMBRAL_DIAS_VENCIDA} días sin consignar"),
                mensaje=(f"${monto:,.0f} sin consignar. La más vieja es la "
                         f"{vieja['factura']} con {vieja['dias']} días "
                         f"(pedido #{vieja['orden']}, entregado {vieja['entrega']}). "
                         f"El ciclo normal de Melonn es de días."),
                enlace="/finanzas",
                meta={"claves": claves, "monto": round(monto, 2),
                      "umbral_dias": UMBRAL_DIAS_VENCIDA},
                creado_por="centinela",
            )
            log.warning(f"[cartera_cod] {len(vencidas)} facturas vencidas "
                        f"(${monto:,.0f}); avisé a {n} persona(s)")
            salida["avisos"].append({"tipo": "cartera_cod_vencida",
                                     "facturas": len(vencidas),
                                     "monto": round(monto, 2), "destinatarios": n})

    # ── 2. Entregado y sin factura → lo cierra contabilidad ──────────────
    hoy = datetime.now(timezone.utc).date()
    def _dias_entrega(s):
        try:
            return (hoy - date.fromisoformat(s)).days
        except (TypeError, ValueError):
            return None
    sin_fac = [s for s in (res.get("sin_factura") or [])
               if (_dias_entrega(s.get("entrega")) or 0) > UMBRAL_DIAS_SIN_FACTURAR]
    if sin_fac:
        claves = sorted(str(s["orden"]) for s in sin_fac)
        monto = sum(s["valor"] for s in sin_fac)
        if _debe_avisar("cod_sin_facturar", claves):
            n = notificaciones.crear_para_modulo(
                modulo="finanzas",
                tipo="cod_sin_facturar",
                titulo=f"{len(sin_fac)} pedido(s) entregados sin factura de venta",
                mensaje=(f"${monto:,.0f} en pedidos de contraentrega entregados hace "
                         f"más de {UMBRAL_DIAS_SIN_FACTURAR} días que no tienen "
                         f"factura en Siigo. Salió mercancía y el cliente pagó. "
                         f"Esto no lo debe Melonn: lo cierra contabilidad."),
                enlace="/finanzas",
                meta={"claves": claves, "monto": round(monto, 2)},
                creado_por="centinela",
            )
            log.warning(f"[cartera_cod] {len(sin_fac)} entregados sin factura "
                        f"(${monto:,.0f}); avisé a {n} persona(s)")
            salida["avisos"].append({"tipo": "cod_sin_facturar",
                                     "pedidos": len(sin_fac),
                                     "monto": round(monto, 2), "destinatarios": n})

    salida["vencidas"] = len(vencidas)
    salida["sin_facturar_viejos"] = len(sin_fac)
    return salida
