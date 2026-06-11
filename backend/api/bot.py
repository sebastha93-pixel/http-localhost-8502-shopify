"""
backend.api.bot — Endpoint para disparar el bot scraper de Melonn admin.

Procesa en background: el frontend dispara, recibe task_id, y consulta
el progreso vía /status. Resultado se persiste vía overrides_svc.
"""
from __future__ import annotations

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

    # Prioridad: novedad (1) > en_transito (2) > pendiente_despacho (3).
    # Entregados se EXCLUYEN (ya no necesitan guía).
    prioridad = {"novedad": 1, "en_transito": 2, "pendiente_despacho": 3}
    candidatos: list[tuple[int, dict]] = []
    for p in pedidos:
        sub = p.get("sub_estado_logistico")
        if sub == "entregado":
            continue  # nunca procesar entregados
        if sub not in prioridad:
            continue  # solo activos conocidos
        orden = p.get("orden_tienda") or ""
        if not orden:
            continue
        ov = overrides.get(orden) or overrides.get(p.get("orden_melonn", ""))
        if req.solo_sin_guia and ov and ov.get("carrier_real"):
            continue  # ya tiene guía guardada → saltar (incremental)
        candidatos.append((
            prioridad[sub],
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
            if r.get("carrier") or r.get("guia"):
                overrides_svc.upsert(
                    orden,
                    autor=f"Bot ({autor})",
                    carrier_real=r.get("carrier") or "",
                    guia_real=r.get("guia") or "",
                )
                counters["guardados"] += 1
            incidencias = r.get("incidencias") or []
            pendientes = [i for i in incidencias if (i.get("estado") or "").lower().startswith("sin")]
            if pendientes:
                motivo = "Bot Melonn detectó: " + "; ".join(
                    f"{i['numero']} {i['descripcion'][:60]}" for i in pendientes[:3]
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
        res = scrape_batch(ordenes, delay_seconds=2.0, on_result=_persistir)

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


@router.get("/diagnostico")
def diagnostico(_: CurrentUser = Depends(require_role("admin"))) -> dict:
    """
    Abre la página de login de Melonn y reporta qué encuentra:
    inputs, botones, URL, título. Para ajustar selectores sin adivinar.
    """
    import os
    email = os.environ.get("MELONN_BOT_EMAIL", "")
    pwd = os.environ.get("MELONN_BOT_PASSWORD", "")

    info: dict = {
        "creds_email_present": bool(email),
        "creds_password_present": bool(pwd),
        "email_masked": (email[:3] + "***" + email[-8:]) if len(email) > 11 else ("***" if email else ""),
    }

    try:
        from backend.scrapers.melonn_bot import MelonnBot, ADMIN_URL
        bot = MelonnBot(email or "x", pwd or "x", headless=True)
        bot.start()
        try:
            page = bot._page
            page.goto(f"{ADMIN_URL}/", wait_until="domcontentloaded", timeout=25_000)
            import time as _t
            _t.sleep(3)
            info["url_final"] = page.url
            info["title"] = page.title()
            # Inventario de inputs
            inputs = page.eval_on_selector_all(
                "input",
                "els => els.map(e => ({type: e.type, name: e.name, id: e.id, placeholder: e.placeholder}))",
            )
            info["inputs"] = inputs
            # Botones
            botones = page.eval_on_selector_all(
                "button",
                "els => els.slice(0,10).map(e => (e.innerText||'').trim()).filter(Boolean)",
            )
            info["botones"] = botones
            # ¿Hay texto de 2FA / código?
            body_text = page.inner_text("body")[:2000]
            info["menciona_2fa"] = bool(
                __import__("re").search(r"c[óo]digo|verifi|2fa|two.?factor|autenticaci", body_text, __import__("re").I)
            )
            info["body_preview"] = body_text[:600]

            # Ejecutar el login REAL (mismo path que usa el bot) y reportar
            if email and pwd:
                import time as _t
                try:
                    login_res = bot._do_login()
                    info["login_resultado"] = login_res
                    _t.sleep(2)
                    info["url_post_login"] = page.url
                    post_text = page.inner_text("body")[:1500]
                    info["post_login_preview"] = post_text
                    try:
                        info["form_sigue_visible"] = page.locator(
                            'input#email, input[name="email"]'
                        ).first.is_visible(timeout=2000)
                    except Exception:
                        info["form_sigue_visible"] = False
                    info["is_logged_in_check"] = bot._is_logged_in()

                    # Si logueó, ir a Órdenes D2C y descubrir la URL real del detalle
                    if login_res.get("ok"):
                        from backend.scrapers.melonn_bot import ADMIN_URL as _A
                        # 1. Ir al listado de órdenes D2C
                        for u in [
                            f"{_A}/sell-orders",
                            f"{_A}/orders",
                            f"{_A}/d2c",
                        ]:
                            try:
                                page.goto(u, wait_until="networkidle", timeout=25_000)
                                _t.sleep(4)
                                if page.locator("text=58902").first.is_visible(timeout=2000):
                                    info["listado_url"] = u
                                    break
                            except Exception:
                                continue
                        info["listado_final"] = page.url

                        # 2. Buscar todos los hrefs que contengan números de orden
                        try:
                            hrefs = page.eval_on_selector_all(
                                "a[href]",
                                "els => els.map(e=>e.getAttribute('href')).filter(h=>h && /order|sell|58|59/i.test(h)).slice(0,15)",
                            )
                            info["hrefs_orden"] = hrefs
                        except Exception as e:
                            info["hrefs_error"] = str(e)[:200]

                        # 3. Intentar click en el texto 58902 para ver a dónde lleva
                        try:
                            page.locator("text=58902").first.click(timeout=4000)
                            _t.sleep(4)
                            info["click_resultado_url"] = page.url
                            bot._click_tab("Transporte")
                            _t.sleep(2)
                            info["transporte_text"] = page.inner_text("body")[:2500]
                        except Exception as e:
                            info["click_error"] = str(e)[:200]
                            info["transporte_text"] = page.inner_text("body")[:1500]
                except Exception as e:
                    info["login_intento_error"] = str(e)[:400]
        finally:
            bot.close()
    except Exception as e:
        info["error"] = str(e)[:500]

    return info
