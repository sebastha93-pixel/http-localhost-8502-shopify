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
    tracking_url: Optional[str] = None
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

    # Flags obligatorios para correr Chromium en contenedores Linux (Railway)
    _LAUNCH_ARGS = [
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-dev-shm-usage",      # evita crash por /dev/shm pequeño
        "--disable-gpu",
        "--single-process",             # más estable en contenedores con poca RAM
        "--no-zygote",
    ]

    def start(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()

        def _launch():
            return self._pw.chromium.launch(
                headless=self.headless,
                args=self._LAUNCH_ARGS,
            )

        try:
            self._browser = _launch()
        except Exception as e:
            msg = str(e)
            # Chromium no instalado → instalar on-the-fly
            if "Executable doesn" in msg or "playwright install" in msg:
                log.warning("Chromium no encontrado — instalando on-the-fly...")
                import subprocess, sys
                subprocess.run(
                    [sys.executable, "-m", "playwright", "install", "chromium"],
                    check=False, timeout=300,
                )
                self._browser = _launch()
            else:
                raise
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

        try:
            # ── 1. Tab TRANSPORTE: carrier + guía ──
            # La info de transporte está en un tab separado. Click primero.
            self._click_tab("Transporte")
            time.sleep(1.2)
            text_transporte = self._page.inner_text("body")

            # Layout real del admin (label en una línea, valor en la siguiente):
            #   Transportadora
            #   Coordinadora Mercantil
            #   Guía
            #   16143081998
            #
            # inner_text separa con \n, así que el valor viene después del label.

            # Carrier: "Transportadora" seguido del nombre en la línea siguiente
            for pat in [
                r"Transportadora\s*\n+\s*([A-Za-zÀ-ſ][^\n\r]{2,45})",
                r"Transportadora:?\s*([A-Za-zÀ-ſ][^\n\r]{2,45})",
                r"Entregada a:?\s*([A-Za-zÀ-ſ][^\n\r]{2,45})",
            ]:
                m = re.search(pat, text_transporte)
                if m:
                    carrier_raw = re.split(
                        r"\s+(?:Gu[ií]a|Documento|Ver|Rastrear|Seguimiento|Intento)\b",
                        m.group(1).strip(),
                    )[0].strip()
                    if carrier_raw and len(carrier_raw) > 2:
                        result.carrier = carrier_raw
                        break

            # Guía: "Guía" seguido del número (puede estar en línea siguiente)
            for pat in [
                r"Gu[ií]a\s*\n+\s*([A-Z0-9][A-Z0-9-]{4,40})",
                r"Gu[ií]a:?\s*([A-Z0-9][A-Z0-9-]{4,40})",
            ]:
                m2 = re.search(pat, text_transporte)
                if m2:
                    result.guia = m2.group(1).strip()
                    break

            # Link directo "Seguimiento transportadora" (href del botón)
            try:
                btn = self._page.get_by_text(re.compile(r"Seguimiento transportadora", re.I)).first
                href = btn.get_attribute("href", timeout=1500)
                if not href:
                    # puede ser un <a> padre o tener onclick; buscar href cercano
                    href = self._page.eval_on_selector(
                        "a:has-text('Seguimiento transportadora')",
                        "el => el.href",
                    )
                if href and href.startswith("http"):
                    result.tracking_url = href
            except Exception:
                pass

            # ── 2. Tab INCIDENCIAS ──
            self._click_tab("Incidencias")
            time.sleep(1.2)
            text_inc = self._page.inner_text("body")
            self._extract_incidencias(text_inc, result)

            # ── 3. Estado de la orden (header, visible en ambos tabs) ──
            m3 = re.search(r"El estado de tu orden es:?\s*([A-Za-zÀ-ſ ]{3,30})", text_transporte)
            if m3:
                result.estado = m3.group(1).strip()

            result.ok = bool(result.carrier or result.guia or result.incidencias)
            if not result.ok:
                # Guardar HTML para diagnóstico
                try:
                    snap = Path(f"/tmp/melonn_{orden_tienda}.txt")
                    snap.write_text(text_transporte[:5000], encoding="utf-8")
                    self._page.screenshot(path=f"/tmp/melonn_{orden_tienda}.png")
                except Exception:
                    pass
                result.error = "Página cargó pero no encontré carrier/guía/incidencias. Revisa /tmp para diagnóstico."
            return result
        except Exception as e:
            log.exception(f"Error extrayendo {orden_tienda}")
            result.error = str(e)
            return result

    def _click_tab(self, nombre: str):
        """Click en un tab (Transporte / Incidencias) si existe."""
        try:
            tab = self._page.get_by_role("tab", name=re.compile(nombre, re.I)).first
            if tab.is_visible(timeout=2_000):
                tab.click()
                return
        except Exception:
            pass
        # Fallback: buscar por texto
        try:
            self._page.get_by_text(re.compile(rf"^{nombre}", re.I)).first.click(timeout=2_000)
        except Exception:
            pass

    def _extract_incidencias(self, text: str, result: ExtractedOrder):
        """Parser de la tabla de incidencias (OV-XXX + estado + descripción)."""
        try:
            _dummy = re.search(r"Gu[ií]a:?\s*([A-Z0-9-]{5,40})", "")  # noop para mantener bloque
        except Exception:
            pass
        # Patrón: OV-XXXXXXX seguido (en cualquier orden) de estado y descripción
        # Buscamos las líneas que tienen OV-XXX
        for m in re.finditer(r"(OV-\d+)", text):
            num = m.group(1)
            # Tomar ~200 chars alrededor para extraer estado + descripción
            start = m.start()
            ventana = text[start:start + 250]
            estado_m = re.search(r"(Sin gestionar|Resuelta|En gesti[oó]n)", ventana)
            estado = estado_m.group(1) if estado_m else "?"
            # Descripción: texto después del estado
            desc = ""
            if estado_m:
                resto = ventana[estado_m.end():].strip()
                desc = re.split(r"\s{2,}|\d{4}/\w+\.", resto)[0].strip()[:120]
            if not any(i["numero"] == num for i in result.incidencias):
                result.incidencias.append({
                    "numero": num,
                    "estado": estado,
                    "descripcion": desc,
                })

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
