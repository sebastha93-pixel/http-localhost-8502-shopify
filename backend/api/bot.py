"""
backend.api.bot — Endpoint para disparar el bot scraper de Melonn admin.

Procesa en background: el frontend dispara, recibe task_id, y consulta
el progreso vía /status. Resultado se persiste vía overrides_svc.
"""
from __future__ import annotations

import os
import threading
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.core.security import CurrentUser, require_role
from backend.services import melonn as melonn_svc
from backend.services import metricas as metricas_svc
from backend.services import overrides as overrides_svc


router = APIRouter(prefix="/api/bot", tags=["bot"])

# Estado en memoria del bot — un solo run a la vez
_bot_state: dict = {
    "running": False,
    "task_id": None,
    "started_at": None,
    "finished_at": None,
    "total": 0,
    "processed": 0,
    "exitos": 0,
    "fallidos": 0,
    "fallos_con_novedad": 0,
    "error": None,
    "log": [],   # últimas líneas de log para mostrar progreso
}
_lock = threading.Lock()


class ScrapeRequest(BaseModel):
    max_pedidos: int = 30          # cuántos procesar por run (límite seguro)
    solo_sin_guia: bool = True     # solo los que no tienen carrier_real aún
    forzar_pedidos: list[str] = []  # IDs específicos opcionales


class ScrapeResponse(BaseModel):
    task_id: str
    total: int
    message: str


def _seleccionar_pedidos(req: ScrapeRequest) -> list[str]:
    """Decide qué pedidos procesar."""
    # Mapear orden_tienda → melonn_id desde el caché de pedidos
    try:
        data = melonn_svc.obtener_pedidos(forzar_refresh=False)
    except Exception:
        return []
    pedidos = data.get("pedidos", [])
    id_por_orden = {
        str(p.get("orden_tienda")): str(p.get("orden_melonn") or "")
        for p in pedidos if p.get("orden_tienda")
    }

    if req.forzar_pedidos:
        return [
            {"orden_tienda": o, "melonn_id": id_por_orden.get(o, "")}
            for o in req.forzar_pedidos[: req.max_pedidos]
        ]

    overrides = overrides_svc.cargar_map()

    # Solo procesar pedidos que REALMENTE pueden tener guía en Melonn:
    # estados de despacho/tránsito (5=Packed, 7=Shipped, 8=Delivered, 24=Prepared,
    # 28=Ready for packing). Excluimos:
    #   - entregados (no necesitan)
    #   - code 26/29 (hold, sin transportadora asignada aún)
    #   - code 1/2 (prepago en alistamiento, sin despachar)
    CODES_CON_GUIA = {5, 7, 8, 24, 28}
    # Prioridad: novedad visible (1) > en_transito (2)
    candidatos: list[tuple[int, dict]] = []
    for p in pedidos:
        sub = p.get("sub_estado_logistico")
        if sub == "entregado":
            continue  # nunca procesar entregados
        code = int(p.get("estado_melonn_code") or 0)
        es_novedad = bool(p.get("es_novedad_visible"))
        # Procesar si: está en estado con guía O es novedad visible
        if code not in CODES_CON_GUIA and not es_novedad:
            continue
        orden = p.get("orden_tienda") or ""
        if not orden:
            continue
        ov = overrides.get(orden) or overrides.get(p.get("orden_melonn", ""))
        ya_procesado = ov and ov.get("carrier_real")
        zona = (p.get("zona") or "").upper()
        es_medellin = "MEDELLIN" in zona or "MEDELLÍN" in zona

        # Medellín local: aunque ya tenga carrier="Mensajería local", lo
        # seguimos revisando para detectar novedades (lo que importa ahí).
        # El resto: si ya tiene guía, saltar (incremental).
        if req.solo_sin_guia and ya_procesado and not es_medellin:
            continue
        # Medellín ya procesado pero SIN novedad → saltar también
        # (solo re-revisamos los de Medellín que aún no se han chequeado
        #  o que están en estado activo de tránsito)
        if req.solo_sin_guia and ya_procesado and es_medellin and not es_novedad:
            # Re-chequear solo si está en tránsito (puede surgir novedad)
            if p.get("sub_estado_logistico") != "en_transito":
                continue
        prio = 1 if es_novedad else (2 if es_medellin else 3)
        candidatos.append((
            prio,
            {"orden_tienda": orden, "melonn_id": str(p.get("orden_melonn") or "")},
        ))

    # Ordenar por prioridad y tomar el lote
    candidatos.sort(key=lambda c: c[0])
    return [c[1] for c in candidatos[: req.max_pedidos]]


def _run_bot(task_id: str, ordenes: list[str], autor: str):
    """Worker thread: corre el scraper y guarda resultados."""
    from backend.scrapers.melonn_bot import scrape_batch

    with _lock:
        _bot_state.update({
            "running": True,
            "task_id": task_id,
            "started_at": time.time(),
            "finished_at": None,
            "total": len(ordenes),
            "processed": 0,
            "exitos": 0,
            "fallidos": 0,
            "fallos_con_novedad": 0,
            "error": None,
            "log": [f"Iniciando bot · {len(ordenes)} pedidos a procesar"],
        })

    # Contador de novedades detectadas (mutado por el callback)
    counters = {"novedad": 0, "guardados": 0}

    def _persistir(r: dict, idx: int, total: int):
        """Callback: guarda CADA pedido apenas se extrae (incremental)."""
        orden = r.get("orden_tienda")
        # Actualizar progreso en vivo
        with _lock:
            _bot_state["processed"] = idx
            if r.get("ok"):
                _bot_state["exitos"] = _bot_state.get("exitos", 0) + 1
            else:
                _bot_state["fallidos"] = _bot_state.get("fallidos", 0) + 1
        if not orden:
            return
        try:
            # Guardar carrier/guía si los hay. Para envíos locales (Medellín
            # con mensajería) no hay guía → guardamos "Mensajería local" como
            # carrier para que NO se reprocese indefinidamente.
            carrier = r.get("carrier") or ""
            guia = r.get("guia") or ""
            if carrier or guia:
                overrides_svc.upsert(
                    orden,
                    autor=f"Bot ({autor})",
                    carrier_real=carrier,
                    guia_real=guia,
                )
                counters["guardados"] += 1
            incidencias = r.get("incidencias") or []
            pendientes = [i for i in incidencias if (i.get("estado") or "").lower().startswith("sin")]
            if pendientes:
                motivo = "Tracking Melonn: " + "; ".join(
                    i["descripcion"][:80] for i in pendientes[:2]
                )
                overrides_svc.upsert(
                    orden, autor=f"Bot ({autor})",
                    novedad_manual=True, motivo_novedad=motivo[:300],
                )
                counters["novedad"] += 1
            with _lock:
                _bot_state["fallos_con_novedad"] = counters["novedad"]
        except Exception as e:
            with _lock:
                _bot_state["log"].append(f"⚠ {orden}: error guardando — {str(e)[:120]}")

    try:
        # Delay entre pedidos configurable (modo lento evita bloqueo Melonn)
        _delay = float(os.environ.get("BOT_DELAY_SEC", "3"))
        res = scrape_batch(ordenes, delay_seconds=_delay, on_result=_persistir)

        with _lock:
            if not res.get("ok"):
                _bot_state["error"] = res.get("error")
                if res.get("requires_2fa"):
                    _bot_state["error"] += " · La cuenta tiene 2FA — desactívalo o configura sesión persistente."
                _bot_state["log"].append(f"✗ {_bot_state['error']}")
            else:
                _bot_state["log"].append(
                    f"✓ Procesados: {res.get('total_procesados',0)} · "
                    f"Guías guardadas: {counters['guardados']} · "
                    f"Novedades: {counters['novedad']}"
                )
    except Exception as e:
        with _lock:
            _bot_state["error"] = str(e)
            _bot_state["log"].append(f"✗ Excepción: {e}")
    finally:
        with _lock:
            _bot_state["running"] = False
            _bot_state["finished_at"] = time.time()


def iniciar_run(max_pedidos: int, autor: str, solo_sin_guia: bool = True) -> dict:
    """
    Inicia un run del bot (reutilizable por el endpoint manual y el cron).
    Retorna {ok, total, message} o {ok: False, error}.
    """
    with _lock:
        if _bot_state["running"]:
            return {"ok": False, "error": "Bot ya corriendo"}

    body = ScrapeRequest(max_pedidos=max_pedidos, solo_sin_guia=solo_sin_guia)
    ordenes = _seleccionar_pedidos(body)
    if not ordenes:
        return {"ok": False, "error": "Sin pedidos pendientes", "total": 0}

    task_id = uuid.uuid4().hex[:8]
    threading.Thread(target=_run_bot, args=(task_id, ordenes, autor), daemon=True).start()
    return {"ok": True, "task_id": task_id, "total": len(ordenes)}


@router.get("/pendientes")
def pendientes(_: CurrentUser = Depends(require_role("admin", "operador"))) -> dict:
    """Cuántos pedidos activos faltan por extraer guía."""
    body = ScrapeRequest(max_pedidos=10_000, solo_sin_guia=True)
    faltantes = _seleccionar_pedidos(body)
    return {"pendientes": len(faltantes)}


@router.post("/scrape", response_model=ScrapeResponse)
def scrape(
    body: ScrapeRequest,
    user: CurrentUser = Depends(require_role("admin")),
) -> ScrapeResponse:
    """Dispara el bot scraper. Solo admin. Un run a la vez."""
    r = iniciar_run(body.max_pedidos, user.nombre, body.solo_sin_guia)
    if not r.get("ok"):
        if r.get("error") == "Bot ya corriendo":
            raise HTTPException(409, "El bot ya está corriendo. Espera a que termine.")
        raise HTTPException(400, r.get("error") or "No hay pedidos pendientes.")
    return ScrapeResponse(
        task_id=r["task_id"],
        total=r["total"],
        message=f"Bot iniciado · procesando {r['total']} pedidos. Consulta /api/bot/status.",
    )


@router.get("/status")
def status(_: CurrentUser = Depends(require_role("admin", "operador"))) -> dict:
    """Estado actual del bot scraper."""
    with _lock:
        return dict(_bot_state)


@router.post("/stop")
def stop(_: CurrentUser = Depends(require_role("admin"))) -> dict:
    """Marca el run como detenido (libera el lock para un nuevo run)."""
    with _lock:
        _bot_state["running"] = False
        _bot_state["finished_at"] = time.time()
        _bot_state["error"] = "Detenido manualmente"
        _bot_state["log"].append("⏹ Detenido manualmente por admin")
    return {"ok": True, "message": "Estado liberado. El thread previo terminará solo."}


@router.get("/diagnostico")
def diagnostico(_: CurrentUser = Depends(require_role("admin"))) -> dict:
    """
    Diagnóstico del path REAL: ensure_logged_in + extract_order de un
    pedido pendiente real. Reporta el ExtractedOrder + el texto capturado.
    """
    import os
    from dataclasses import asdict
    email = os.environ.get("MELONN_BOT_EMAIL", "")
    pwd = os.environ.get("MELONN_BOT_PASSWORD", "")
    info: dict = {"creds_present": bool(email and pwd)}

    # Tomar el primer pedido pendiente real (orden + melonn_id)
    sel = _seleccionar_pedidos(ScrapeRequest(max_pedidos=1, solo_sin_guia=True))
    if not sel:
        info["aviso"] = "No hay pedidos pendientes para diagnosticar"
        return info
    info["pedido_prueba"] = sel[0]

    try:
        from backend.scrapers.melonn_bot import MelonnBot, ADMIN_URL
        bot = MelonnBot(email or "x", pwd or "x", headless=True)
        bot.start()
        try:
            # Path REAL: ensure_logged_in (detecta sesión o re-loguea)
            login = bot.ensure_logged_in()
            info["login"] = login
            if login.get("ok"):
                orden = sel[0]["orden_tienda"]
                mid = sel[0]["melonn_id"]
                internal = mid.lstrip("Mm")
                info["url_detalle"] = f"{ADMIN_URL}/sell-orders/{internal}"
                r = bot.extract_order(orden, melonn_id=mid)
                info["extract_resultado"] = asdict(r)
                # Capturar el texto crudo de la página para ver qué hay
                try:
                    info["texto_pagina"] = bot._page.inner_text("body")[:2000]
                except Exception:
                    pass
        finally:
            bot.close()
    except Exception as e:
        info["error"] = str(e)[:500]

    return info
