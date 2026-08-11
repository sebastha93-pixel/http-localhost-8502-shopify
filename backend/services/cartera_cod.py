"""
CARTERA CONTRAENTREGA — qué está facturado y qué falta por recaudar.
═══════════════════════════════════════════════════════════════════════════

CORRECCIÓN IMPORTANTE (2026-08-11). La primera versión de este módulo usaba el
`balance` de la factura como señal de "Melonn ya pagó". ESO ESTÁ MAL, y Sebastián
lo cazó: "hay muchos que están facturados y ya marcados como pagados en Siigo".

Lo que se midió después, contra producción:

  · 1.328 de las 1.329 facturas de contraentrega registran su pago contra la
    cuenta "CONTRA ENTREGA CREDITO 10 DIAS" (13050501), NO contra un banco.
    O sea que `balance = 0` significa "venta a crédito registrada", no "la plata
    llegó". La consignación de Melonn es un movimiento contable APARTE, que no
    se ve en la factura.
  · De 44 pedidos que reporté como "entregados sin facturar", 41 SÍ tenían
    factura — con otro medio de pago: 31 MANUAL, 6 ADDI PAYMENT, y unos pocos
    BANCOLOMBIA / EFECTIVO / MERCADO PAGO. El medio de ENVÍO (contraentrega) y
    el medio de PAGO de la factura no son lo mismo: un envío COD puede acabar
    cobrado por transferencia. Solo 3 no tenían ninguna factura.

POR ESO ESTE MÓDULO YA NO DICE "MELONN NOS DEBE". Desde Siigo solo se puede
saber qué se facturó y contra qué cuenta; cuánto consignó Melonn se mide en el
módulo de conciliación, que tiene los recaudos pedido por pedido (tabla
`recon.gateway_transactions`, gateway `melonn_cod`). El backend del OS todavía no
puede leer eso —llega a `recon` solo por HTTP y ese servicio no expone el detalle
por pedido—, así que acá se muestra lo que SÍ se puede probar y se dice
explícitamente lo que falta. Medido a mano el 2026-08-11: de 943 entregados, 750
con recaudo reportado por Melonn y 193 sin reporte ($34,9 M).

Preferir un dato incompleto y rotulado antes que un número redondo y falso: el
número falso se usa para tomar decisiones.
"""
from __future__ import annotations

import logging
import re
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

# Ya NO hay caché en proceso. Lo hubo, y fue un error: el backend corre con
# cuatro workers de Uvicorn, así que un caché en memoria significaba cuatro
# recorridos de 112 páginas contra una API que aguanta ~1 req/s. Ahora el espejo
# vive en la tabla `siigo_facturas_cod`, que los cuatro comparten, y solo el
# scheduler la sincroniza.


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

def _sb():
    from backend.services import notificaciones
    return notificaciones._sb()


PAUSA_PAGINA = 1.1     # Siigo aguanta ~1 req/s; sin esto son 429 garantizados


def _pedir_a_siigo(desde: str) -> list[dict]:
    """Recorre /invoices desde una fecha y devuelve las filas a guardar.

    LA PAUSA ENTRE PÁGINAS NO ES OPCIONAL. Siigo aguanta cerca de una petición
    por segundo y el backoff de `siigo_get` se rinde a los ~23 s. Sin pausa, el
    recorrido moría en «429 intento 5» y el tablero mostraba el aviso de que no
    se pudo consultar.
    """
    from backend.services import siigo

    filas, page, leidas = [], 1, 0
    while page <= 200:
        data = siigo.siigo_get("/invoices", {"created_start": desde,
                                             "page": page, "page_size": 100})
        res = data.get("results") or []
        if not res:
            break
        leidas += len(res)
        for f in res:
            m = _RE_OBS.search((f.get("observations") or "").strip())
            if not m:
                continue          # sin número de orden no sirve para cruzar
            cuentas = [(pg.get("name") or "").strip().upper()
                       for pg in (f.get("payments") or [])]
            filas.append({
                "factura":   f.get("name"),
                "orden":     m.group(1),
                "fecha":     (f.get("date") or "")[:10] or None,
                "total":     float(f.get("total") or 0),
                "saldo":     float(f.get("balance") or 0),
                "medio":     m.group(2).strip().upper()[:80],
                "a_credito": any("CONTRA ENTREGA" in c for c in cuentas),
                "cuentas":   cuentas,
            })
        if len(res) < 100:
            break
        page += 1
        time.sleep(PAUSA_PAGINA)
    log.info(f"[cartera_cod] Siigo: {leidas} facturas leídas desde {desde}, "
             f"{len(filas)} con número de orden ({page} páginas)")
    return filas


def sincronizar(*, completa: bool = False) -> dict:
    """Trae de Siigo lo que falte y lo guarda en la tabla espejo.

    Incremental por defecto: arranca desde la fecha más nueva que ya está
    guardada, menos dos días de traslape (una factura puede entrar con fecha
    atrasada). En régimen son 2 o 3 páginas en vez de 112.

    `completa=True` rehace la ventana entera. Se usa la primera vez y si hay
    sospecha de huecos.
    """
    sb = _sb()
    if sb is None:
        return {"ok": False, "motivo": "Supabase no configurado"}

    piso = (date.today() - timedelta(days=DIAS_VENTANA)).isoformat()
    desde = piso
    if not completa:
        try:
            r = (sb.table("siigo_facturas_cod").select("fecha")
                   .order("fecha", desc=True).limit(1).execute()).data
            if r and r[0].get("fecha"):
                ultima = date.fromisoformat(str(r[0]["fecha"])[:10])
                desde = max(piso, (ultima - timedelta(days=2)).isoformat())
        except Exception as e:
            log.warning(f"[cartera_cod] no pude leer la última fecha: {str(e)[:120]}")

    filas = _pedir_a_siigo(desde)
    if not filas:
        return {"ok": True, "guardadas": 0, "desde": desde}

    guardadas = 0
    for i in range(0, len(filas), 300):
        lote = filas[i:i + 300]
        try:
            sb.table("siigo_facturas_cod").upsert(
                lote, on_conflict="factura").execute()
            guardadas += len(lote)
        except Exception as e:
            log.error(f"[cartera_cod] fallo guardando lote: {str(e)[:160]}")
            break
    log.info(f"[cartera_cod] sincronizadas {guardadas} facturas desde {desde}")
    return {"ok": True, "guardadas": guardadas, "desde": desde,
            "completa": completa}


def facturas_cod(*, desde: Optional[str] = None, force: bool = False) -> dict:
    """{numero_de_orden: [factura, …]} leído de la tabla espejo.

    NO llama a Siigo: eso lo hace `sincronizar()` desde el scheduler. Si la
    tabla está vacía —primer arranque o migración recién corrida— sí dispara una
    sincronización, porque servir un mapa vacío haría ver todos los pedidos como
    «sin factura», que es exactamente la mentira que este módulo vino a corregir.
    """
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase no configurado")

    piso = desde or (date.today() - timedelta(days=DIAS_VENTANA)).isoformat()
    def _leer() -> list[dict]:
        out, inicio = [], 0
        while inicio < 20000:            # tope de seguridad
            r = (sb.table("siigo_facturas_cod")
                   .select("factura,orden,fecha,total,saldo,medio,a_credito,cuentas")
                   .gte("fecha", piso)
                   .range(inicio, inicio + 999).execute()).data or []
            out += r
            if len(r) < 1000:
                break
            inicio += 1000
        return out

    filas = _leer()
    if not filas or force:
        log.warning("[cartera_cod] tabla espejo vacía; sincronizando contra Siigo")
        sincronizar(completa=not filas)
        filas = _leer()
    if not filas:
        raise RuntimeError("no hay facturas en la tabla espejo y Siigo no respondió")

    por_orden: dict[str, list[dict]] = {}
    for f in filas:
        por_orden.setdefault(str(f["orden"]), []).append({
            "factura":   f["factura"],
            "fecha":     str(f.get("fecha") or "")[:10],
            "total":     float(f.get("total") or 0),
            "saldo":     float(f.get("saldo") or 0),
            "medio":     f.get("medio"),
            "es_cod":    _es_cod(f.get("medio") or ""),
            "a_credito": bool(f.get("a_credito")),
            "cuentas":   f.get("cuentas") or [],
        })
    return por_orden


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
    a_credito: list[dict] = []      # facturado contra "CONTRA ENTREGA CREDITO 10 DIAS"
    cobrado_directo = 0.0           # facturado y pagado por otro medio (banco, ADDI…)
    n_directo = 0
    vistas: set = set()

    for n, p in entregados.items():
        for f in fv.get(n, []):
            if f["factura"] in vistas:
                continue          # una factura puede cubrir dos órdenes
            vistas.add(f["factura"])
            if f["a_credito"]:
                try:
                    dias = (hoy - date.fromisoformat(f["fecha"])).days
                except (TypeError, ValueError):
                    dias = None
                a_credito.append({**f, "orden": n, "dias": dias,
                                  "entrega": (p.get("fecha_entrega") or "")[:10],
                                  "ciudad": p.get("ciudad_destino"),
                                  "valor_melonn": p.get("valor_num")})
            else:
                cobrado_directo += f["total"]
                n_directo += 1

    sin_facturar = [{"orden": n,
                     "valor": p.get("valor_num") or 0,
                     "entrega": (p.get("fecha_entrega") or "")[:10],
                     "ciudad": p.get("ciudad_destino")}
                    for n, p in entregados.items() if n not in fv]

    a_credito.sort(key=lambda x: (x["dias"] is None, -(x["dias"] or 0)))
    total_credito = round(sum(f["total"] for f in a_credito), 2)

    # Antigüedad contra el plazo pactado: la cuenta se llama "CRÉDITO 10 DÍAS",
    # así que a los 30 ya no es demora normal. Sirva o no como deuda exigible
    # —eso lo confirma la conciliación—, una factura a crédito de 88 días hay
    # que mirarla.
    tramos = {"0-15": 0.0, "16-30": 0.0, "31-60": 0.0, "60+": 0.0, "sin_fecha": 0.0}
    for f in a_credito:
        d = f["dias"]
        k = ("sin_fecha" if d is None else
             "0-15" if d <= 15 else "16-30" if d <= 30 else
             "31-60" if d <= 60 else "60+")
        tramos[k] = round(tramos[k] + f["total"], 2)

    return {
        "disponible":         True,
        # Lo que Siigo SÍ puede probar
        "facturado_credito":  total_credito,
        "n_facturado_credito": len(a_credito),
        "cobrado_directo":    round(cobrado_directo, 2),
        "n_cobrado_directo":  n_directo,
        "sin_facturar":       round(sum(x["valor"] for x in sin_facturar), 2),
        "n_sin_facturar":     len(sin_facturar),
        "entregados_total":   len(entregados),
        "antiguedad":         tramos,
        "abiertas":           a_credito[:300],
        "sin_factura":        sorted(sin_facturar, key=lambda x: x["entrega"])[:300],
        # Lo que NO se puede saber desde Siigo, dicho explícitamente para que la
        # pantalla no invente: cuánto de `facturado_credito` ya consignó Melonn
        # vive en el módulo de conciliación (recon.gateway_transactions).
        "recaudo_medible":    False,
        "nota_recaudo": ("Siigo no dice cuánto consignó Melonn: las facturas de "
                         "contraentrega se cierran contra la cuenta de crédito a "
                         "10 días, no contra un banco. El recaudo real se mide en "
                         "la conciliación bancaria."),
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

    # ── 1. Facturado a crédito contraentrega y ya viejo ─────────────────
    # NO dice "Melonn no ha consignado": eso no se sabe desde Siigo. Dice que la
    # factura lleva N días abierta contra una cuenta cuyo plazo pactado es 10.
    # Quien lo revise cruza con la conciliación y decide si reclamar.
    vencidas = [f for f in (res.get("abiertas") or [])
                if (f.get("dias") or 0) > UMBRAL_DIAS_VENCIDA]
    if vencidas:
        claves = sorted(f["factura"] for f in vencidas)
        monto = sum(f["total"] for f in vencidas)
        if _debe_avisar("cartera_cod_vencida", claves):
            vieja = max(vencidas, key=lambda f: f.get("dias") or 0)
            n = notificaciones.crear_para_modulo(
                modulo="finanzas",
                tipo="cartera_cod_vencida",
                titulo=(f"Contraentrega: {len(vencidas)} factura(s) a crédito con "
                        f"más de {UMBRAL_DIAS_VENCIDA} días"),
                mensaje=(f"${monto:,.0f} facturados contra la cuenta de "
                         f"contraentrega a 10 días que llevan más de "
                         f"{UMBRAL_DIAS_VENCIDA}. La más vieja es la "
                         f"{vieja['factura']} con {vieja['dias']} días "
                         f"(pedido #{vieja['orden']}, entregado {vieja['entrega']}). "
                         f"Verifica en la conciliación si Melonn ya consignó."),
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
                mensaje=(f"${monto:,.0f} en pedidos entregados hace más de "
                         f"{UMBRAL_DIAS_SIN_FACTURAR} días sin NINGUNA factura en "
                         f"Siigo —se buscó con cualquier medio de pago, no solo "
                         f"contraentrega—. Salió mercancía y el cliente pagó. "
                         f"Esto lo cierra contabilidad."),
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
