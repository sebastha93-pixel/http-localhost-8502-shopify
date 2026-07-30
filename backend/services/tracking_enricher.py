"""
tracking_enricher.py — Rellena transportadora + guía real, automáticamente.

REEMPLAZA al bot de Playwright para este dato. El bot sigue existiendo porque
también detecta novedades, pero para transportadora/guía esta vía es 13× más
rápida (0,6 s vs ~8 s por pedido), no abre navegador y no gasta cuota de la
Sellers API — usa otro host. Ver `src/melonn_tracking.py` para el porqué y la
evidencia.

CÓMO ELIGE: pedidos del caché que NO tengan `carrier_real` en `pedido_overrides`.
Se escribe en overrides y no en el blob del caché porque el blob se reescribe en
cada sync (el 27-jul quedó en blanco una vez), y `overrides.aplicar_a_pedido` lo
pinta encima al leer.

REGLA DE ESCRITURA: `guia_real` solo se manda si LLEGÓ. Las entregas del área
metropolitana de Medellín las hace mensajería local (Rapiboy, EASYWAY, Cabify,
CORDIANDINA) que no emite guía; ahí se guarda solo la transportadora. Mandar la
guía vacía la borraría — y `overrides.upsert` trata "" como "bórralo a propósito".
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

# `src/` no está en el path por defecto en todos los entry points.
_SRC = Path(__file__).resolve().parent.parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

log = logging.getLogger(__name__)

PAUSA_SEG = 0.6          # cortesía con su portal (~1,6 req/s)
TOPE_POR_PASADA = 250    # suficiente para vaciar el atraso en 2-3 pasadas


def _candidatos(limite: int) -> list[tuple[str, str]]:
    """[(orden_tienda, M-id)] de pedidos sin transportadora. Los despachados
    primero: son los que pueden tener guía y los que alguien va a consultar."""
    from backend.services import melonn as melonn_svc
    from backend.services import overrides as overrides_svc

    data = melonn_svc.obtener_pedidos(forzar_refresh=False)
    pedidos = data.get("pedidos", []) or []
    ov = overrides_svc.cargar_map()

    prio = {"en_transito": 0, "novedad": 1, "entregado": 2}
    cands: list[tuple[int, str, str]] = []
    for p in pedidos:
        ot = str(p.get("orden_tienda") or "").strip()
        mid = str(p.get("orden_melonn") or "").strip()
        if not ot or not mid:
            continue
        o = ov.get(ot) or ov.get(mid)
        if o and str(o.get("carrier_real") or "").strip():
            continue          # ya lo tiene: no se vuelve a preguntar
        est = p.get("sub_estado_logistico") or ""
        cands.append((prio.get(est, 3), ot, mid))

    cands.sort(key=lambda c: c[0])
    return [(ot, mid) for _, ot, mid in cands[:limite]]


def pasada(limite: int = TOPE_POR_PASADA) -> dict:
    """Una pasada del enriquecedor. Devuelve el resumen para los logs."""
    from backend.services import overrides as overrides_svc
    import melonn_tracking as mt

    cands = _candidatos(limite)
    if not cands:
        return {"candidatos": 0, "con_guia": 0, "solo_carrier": 0,
                "sin_dato": 0, "error": 0}

    con_guia = solo_carrier = sin_dato = err = 0
    for ot, mid in cands:
        try:
            r = mt.consultar(mid)
        except Exception as e:
            err += 1
            log.debug(f"tracking {ot}: {e}")
            time.sleep(PAUSA_SEG)
            continue
        if not r or not r.get("carrier"):
            # Sin transportadora todavía (aún no sale de bodega). NO se marca
            # nada, así se vuelve a intentar en la próxima pasada.
            sin_dato += 1
            time.sleep(PAUSA_SEG)
            continue
        try:
            overrides_svc.upsert(
                ot,
                autor="tracking-auto",
                carrier_real=r["carrier"],
                # None = "no toques este campo". Ver REGLA DE ESCRITURA arriba.
                guia_real=r["guia"] or None,
            )
            if r["guia"]:
                con_guia += 1
            else:
                solo_carrier += 1
        except Exception as e:
            err += 1
            log.warning(f"tracking upsert {ot}: {e}")
        time.sleep(PAUSA_SEG)

    res = {"candidatos": len(cands), "con_guia": con_guia,
           "solo_carrier": solo_carrier, "sin_dato": sin_dato, "error": err}
    log.info(f"Tracking enricher: {res}")
    return res
