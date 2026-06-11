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
    if req.forzar_pedidos:
        return req.forzar_pedidos[: req.max_pedidos]

    # Solo pedidos activos (no entregados) sin carrier_real aún
    try:
        data = melonn_svc.obtener_pedidos(forzar_refresh=False)
    except Exception:
        return []

    overrides = overrides_svc.cargar_map()
    seleccion: list[str] = []
    for p in data.get("pedidos", []):
        if p.get("sub_estado_logistico") == "entregado":
            continue  # ya entregados, no urgentes
        orden = p.get("orden_tienda") or ""
        if not orden:
            continue
        ov = overrides.get(orden) or overrides.get(p.get("orden_melonn", ""))
        ya_tiene_carrier = ov and ov.get("carrier_real")
        if req.solo_sin_guia and ya_tiene_carrier:
            continue
        seleccion.append(orden)
        if len(seleccion) >= req.max_pedidos:
            break
    return seleccion


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

    try:
        # Ejecuta el scraping completo (login + batch)
        # NOTA: el scrape_batch interno no expone progreso paso a paso;
        # para v1 esperamos a que termine completo. Si quieres progreso
        # en vivo, lo refactorizamos para iteración.
        res = scrape_batch(ordenes, delay_seconds=4.0)

        with _lock:
            _bot_state["processed"] = res.get("total_procesados", 0)
            _bot_state["exitos"] = res.get("exitos", 0)
            _bot_state["fallidos"] = res.get("fallidos", 0)

            if not res.get("ok"):
                _bot_state["error"] = res.get("error")
                if res.get("requires_2fa"):
                    _bot_state["error"] += " · La cuenta tiene 2FA — desactívalo o configura sesión persistente."
                _bot_state["log"].append(f"✗ {_bot_state['error']}")
            else:
                _bot_state["log"].append(
                    f"✓ Procesados: {res['total_procesados']} · "
                    f"Éxitos: {res['exitos']} · Fallidos: {res['fallidos']}"
                )

        # Persistir resultados en Supabase vía overrides
        fallos_nov = 0
        for r in res.get("resultados", []):
            orden = r.get("orden_tienda")
            if not orden:
                continue
            try:
                # Si trajo carrier/guia, guardarlos
                if r.get("carrier") or r.get("guia"):
                    overrides_svc.upsert(
                        orden,
                        autor=f"Bot ({autor})",
                        carrier_real=r.get("carrier") or "",
                        guia_real=r.get("guia") or "",
                    )

                # Si tiene incidencias sin gestionar → marcar como novedad
                incidencias = r.get("incidencias") or []
                pendientes = [
                    i for i in incidencias
                    if (i.get("estado") or "").lower().startswith("sin")
                ]
                if pendientes:
                    motivo = "Bot Melonn detectó: " + "; ".join(
                        f"{i['numero']} {i['descripcion'][:60]}" for i in pendientes[:3]
                    )
                    overrides_svc.upsert(
                        orden,
                        autor=f"Bot ({autor})",
                        novedad_manual=True,
                        motivo_novedad=motivo[:300],
                    )
                    fallos_nov += 1
            except Exception as e:
                with _lock:
                    _bot_state["log"].append(f"⚠ {orden}: error guardando — {e}")

        with _lock:
            _bot_state["fallos_con_novedad"] = fallos_nov
            if fallos_nov:
                _bot_state["log"].append(f"⚠ {fallos_nov} pedidos marcados con novedad por incidencias detectadas")
    except Exception as e:
        with _lock:
            _bot_state["error"] = str(e)
            _bot_state["log"].append(f"✗ Excepción: {e}")
    finally:
        with _lock:
            _bot_state["running"] = False
            _bot_state["finished_at"] = time.time()


@router.post("/scrape", response_model=ScrapeResponse)
def scrape(
    body: ScrapeRequest,
    user: CurrentUser = Depends(require_role("admin")),
) -> ScrapeResponse:
    """Dispara el bot scraper. Solo admin. Un run a la vez."""
    with _lock:
        if _bot_state["running"]:
            raise HTTPException(409, "El bot ya está corriendo. Espera a que termine.")

    ordenes = _seleccionar_pedidos(body)
    if not ordenes:
        raise HTTPException(400, "No hay pedidos pendientes que cumplan los criterios.")

    task_id = uuid.uuid4().hex[:8]
    threading.Thread(
        target=_run_bot, args=(task_id, ordenes, user.nombre), daemon=True
    ).start()

    return ScrapeResponse(
        task_id=task_id,
        total=len(ordenes),
        message=f"Bot iniciado · procesando {len(ordenes)} pedidos. Consulta /api/bot/status.",
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

                    # Si logueó, navegar a un pedido y capturar el texto real
                    if login_res.get("ok"):
                        from backend.scrapers.melonn_bot import ADMIN_URL as _A
                        for u in [
                            f"{_A}/seller/d2c/sell-orders/58902",
                            f"{_A}/d2c/sell-orders/58902",
                            f"{_A}/sell-orders/58902",
                        ]:
                            page.goto(u, wait_until="domcontentloaded", timeout=20_000)
                            _t.sleep(3)
                            c = page.content()
                            if "58902" in c:
                                info["order_url_ok"] = u
                                break
                        info["order_url_final"] = page.url
                        # Click tab Transporte
                        try:
                            bot._click_tab("Transporte")
                            _t.sleep(2)
                        except Exception as e:
                            info["click_transporte_error"] = str(e)[:200]
                        info["transporte_text"] = page.inner_text("body")[:2500]
                        # Inventario de tabs visibles
                        try:
                            tabs = page.eval_on_selector_all(
                                "[role=tab], button, a",
                                "els => els.map(e=>(e.innerText||'').trim()).filter(t=>/transporte|incidencia/i.test(t)).slice(0,8)",
                            )
                            info["tabs_detectados"] = tabs
                        except Exception:
                            pass
                except Exception as e:
                    info["login_intento_error"] = str(e)[:400]
        finally:
            bot.close()
    except Exception as e:
        info["error"] = str(e)[:500]

    return info
