"""
backend.scrapers.melonn_bot — Bot que extrae transportadora, guía e
incidencias del admin web de Melonn (datos que NO expone su API REST).

Usa Playwright para login con credenciales reales y navegación headless.

Estado persistente: storage_state se guarda en /tmp/melonn_session.json
tras login exitoso. Próximos runs lo reutilizan (saltan login y 2FA).
"""
from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional


log = logging.getLogger(__name__)

ADMIN_URL = "https://admin.melonn.com"
SESSION_PATH = Path("/tmp/melonn_session.json")

# Selectores y patrones a iterar según el HTML real de Melonn admin
# (ajustables sin tocar el resto del código)
SELECTORS = {
    "email_input":    'input[type="email"], input[name="email"]',
    "password_input": 'input[type="password"], input[name="password"]',
    "submit_button":  'button[type="submit"]',
    "post_login_nav": "text=Órdenes D2C",  # algo que solo se ve logueado
    "2fa_indicator":  "text=/(c[óo]digo|verifi|2FA|two.?factor)/i",
}


@dataclass
class ExtractedOrder:
    orden_tienda: str
    carrier: Optional[str] = None
    guia: Optional[str] = None
    incidencias: list[dict] = field(default_factory=list)  # [{tipo, estado, descripcion, fecha}]
    estado: Optional[str] = None
    ok: bool = False
    error: Optional[str] = None


class MelonnBot:
    """Bot Playwright con sesión persistente."""

    def __init__(self, email: str, password: str, headless: bool = True):
        self.email = email
        self.password = password
        self.headless = headless
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None

    # ── Lifecycle ────────────────────────────────────────────────────

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.close()

    def start(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)
        # Reutilizar sesión si existe
        if SESSION_PATH.exists():
            self._context = self._browser.new_context(storage_state=str(SESSION_PATH))
            log.info("Sesión Melonn reutilizada desde disco")
        else:
            self._context = self._browser.new_context()
        self._page = self._context.new_page()
        self._page.set_default_timeout(15_000)

    def close(self):
        try:
            if self._browser:
                self._browser.close()
        except Exception:
            pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass

    # ── Login ────────────────────────────────────────────────────────

    def ensure_logged_in(self) -> dict:
        """
        Verifica si la sesión existente sigue activa; si no, hace login.

        Retorna {ok, requires_2fa, error}.
        """
        # Probar primero si la sesión persistida ya funciona
        try:
            self._page.goto(f"{ADMIN_URL}/", wait_until="domcontentloaded", timeout=15_000)
            # Si ya está logueado, debería redirigir a dashboard
            time.sleep(2)
            if self._is_logged_in():
                log.info("Sesión activa — sin re-login")
                return {"ok": True, "requires_2fa": False}
        except Exception as e:
            log.warning(f"Pre-check sesión falló: {e}")

        # No hay sesión: intentar login
        return self._do_login()

    def _is_logged_in(self) -> bool:
        url = self._page.url
        if "login" in url.lower() or "signin" in url.lower():
            return False
        # Buscar algo que solo aparezca logueado
        try:
            self._page.locator(SELECTORS["post_login_nav"]).first.wait_for(state="visible", timeout=3_000)
            return True
        except Exception:
            return False

    def _do_login(self) -> dict:
        try:
            self._page.goto(f"{ADMIN_URL}/", wait_until="domcontentloaded", timeout=20_000)

            # Buscar campo email
            email_field = self._page.locator(SELECTORS["email_input"]).first
            email_field.wait_for(state="visible", timeout=10_000)
            email_field.fill(self.email)

            pw_field = self._page.locator(SELECTORS["password_input"]).first
            pw_field.fill(self.password)

            submit = self._page.locator(SELECTORS["submit_button"]).first
            submit.click()

            # Esperar redirect post-login
            time.sleep(3)

            # Detectar 2FA
            try:
                indicator = self._page.locator(SELECTORS["2fa_indicator"]).first
                if indicator.is_visible(timeout=2_000):
                    log.warning("2FA detectado — el bot no puede continuar sin código")
                    # Guardar screenshot para debug
                    try:
                        self._page.screenshot(path="/tmp/melonn_2fa.png")
                    except Exception:
                        pass
                    return {
                        "ok": False,
                        "requires_2fa": True,
                        "error": "Tu cuenta Melonn tiene 2FA activado. El bot no puede continuar sin código de verificación. Opciones: desactivar 2FA en esta cuenta, o configurar sesión persistente manualmente.",
                    }
            except Exception:
                pass

            # Validar que el login fue exitoso
            if self._is_logged_in():
                # Guardar sesión para próximos runs
                try:
                    self._context.storage_state(path=str(SESSION_PATH))
                    log.info(f"Sesión guardada en {SESSION_PATH}")
                except Exception as e:
                    log.warning(f"No se pudo guardar sesión: {e}")
                return {"ok": True, "requires_2fa": False}

            # Login falló por otra razón
            return {
                "ok": False,
                "requires_2fa": False,
                "error": "Login falló — verifica credenciales o el formulario de Melonn cambió.",
            }
        except Exception as e:
            log.exception("Error durante login")
            return {"ok": False, "requires_2fa": False, "error": str(e)}

    # ── Extracción ───────────────────────────────────────────────────

    def extract_order(self, orden_tienda: str) -> ExtractedOrder:
        """
        Navega a la página del pedido y extrae carrier + guía + incidencias.

        La URL del admin para una orden tiene patrón:
        admin.melonn.com/seller/d2c/sell-orders/{external_id}
        (ajustable si descubrimos otro patrón al inspeccionar)
        """
        result = ExtractedOrder(orden_tienda=orden_tienda)

        urls_to_try = [
            f"{ADMIN_URL}/seller/d2c/sell-orders/{orden_tienda}",
            f"{ADMIN_URL}/d2c/sell-orders/{orden_tienda}",
            f"{ADMIN_URL}/sell-orders/{orden_tienda}",
        ]

        loaded = False
        for url in urls_to_try:
            try:
                self._page.goto(url, wait_until="domcontentloaded", timeout=15_000)
                time.sleep(2)  # esperar JS render
                # Si el contenido tiene el número de orden + "Información del envío" → cargó OK
                content = self._page.content()
                if orden_tienda in content and ("envío" in content.lower() or "envio" in content.lower()):
                    loaded = True
                    break
            except Exception as e:
                log.debug(f"Falló URL {url}: {e}")

        if not loaded:
            result.error = "No se pudo cargar la página del pedido"
            return result

        # ── Extraer carrier ──
        # Patrones esperados en el HTML/texto:
        #   "Entregada a: Coordinadora Mercantil"
        #   "Entregada a: Servientrega"
        try:
            html = self._page.content()
            text = self._page.inner_text("body")

            m = re.search(r"Entregada a:?\s*([A-Za-zÀ-ſ][^\n\r\|]{2,40})", text)
            if m:
                carrier_raw = m.group(1).strip()
                # Cortar antes de palabras que típicamente siguen (Guía, +, etc)
                carrier_raw = re.split(r"\s+(?:Gu[ií]a|Documento|Ver)\b", carrier_raw)[0].strip()
                result.carrier = carrier_raw

            # ── Extraer guía ──
            m2 = re.search(r"Gu[ií]a:?\s*([A-Z0-9-]{5,40})", text)
            if m2:
                result.guia = m2.group(1).strip()

            # ── Estado de la orden ──
            m3 = re.search(r"El estado de tu orden es:?\s*([A-Za-zÀ-ſ ]{3,30})", text)
            if m3:
                result.estado = m3.group(1).strip()

            # ── Incidencias ──
            # Buscar bloques con "Incidencias" o "Sin gestionar" / "Resuelta"
            incidencias = []
            # Patrón simple: filas en una tabla con OV-XXX + Sin gestionar/Resuelta + descripción
            for m in re.finditer(
                r"(OV-\d+).*?(Sin gestionar|Resuelta|En gesti[oó]n|Gestionable)[\s\S]{0,500}?([\wÀ-ſ][^\n\r]{5,200})",
                text,
            ):
                incidencias.append({
                    "numero": m.group(1),
                    "estado": m.group(2),
                    "descripcion": m.group(3).strip()[:200],
                })
            # Dedupe por número
            seen = set()
            for inc in incidencias:
                if inc["numero"] not in seen:
                    seen.add(inc["numero"])
                    result.incidencias.append(inc)

            result.ok = bool(result.carrier or result.guia or result.incidencias)
            if not result.ok:
                result.error = "Página cargó pero no encontré carrier/guía/incidencias. ¿HTML cambió?"
        except Exception as e:
            log.exception(f"Error extrayendo {orden_tienda}")
            result.error = str(e)

        return result


# ── API funcional para el endpoint ────────────────────────────────────

def scrape_batch(ordenes: list[str], delay_seconds: float = 4.0) -> dict:
    """
    Loguea y procesa una lista de pedidos. Retorna resultados agregados.
    """
    email = os.environ.get("MELONN_BOT_EMAIL", "").strip()
    pwd   = os.environ.get("MELONN_BOT_PASSWORD", "").strip()
    if not email or not pwd:
        return {
            "ok": False,
            "error": "Faltan credenciales: configura MELONN_BOT_EMAIL y MELONN_BOT_PASSWORD en Railway.",
            "resultados": [],
        }

    extracted: list[ExtractedOrder] = []
    try:
        with MelonnBot(email, pwd, headless=True) as bot:
            login_res = bot.ensure_logged_in()
            if not login_res.get("ok"):
                return {
                    "ok": False,
                    "error": login_res.get("error"),
                    "requires_2fa": login_res.get("requires_2fa", False),
                    "resultados": [],
                }

            for i, orden in enumerate(ordenes):
                if i > 0:
                    time.sleep(delay_seconds)  # delay entre pedidos
                r = bot.extract_order(orden)
                extracted.append(r)
                log.info(f"[{i+1}/{len(ordenes)}] {orden}: ok={r.ok} carrier={r.carrier} guia={r.guia} incidencias={len(r.incidencias)}")
    except Exception as e:
        log.exception("Error en scrape_batch")
        return {"ok": False, "error": str(e), "resultados": [asdict(r) for r in extracted]}

    exitos = sum(1 for r in extracted if r.ok)
    return {
        "ok": True,
        "total_procesados": len(extracted),
        "exitos": exitos,
        "fallidos": len(extracted) - exitos,
        "resultados": [asdict(r) for r in extracted],
    }
