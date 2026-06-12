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
TRACKING_URL = "https://tracking.melonn.com"   # página pública, sin login
SESSION_PATH = Path("/tmp/melonn_session.json")

# Selectores y patrones a iterar según el HTML real de Melonn admin
# (ajustables sin tocar el resto del código)
# Selectores confirmados vía /api/bot/diagnostico contra admin.melonn.com
SELECTORS = {
    "email_input":    'input#email, input[name="email"]',
    "password_input": 'input#password, input[name="password"]',
    "submit_button":  'button:has-text("Iniciar sesión"), button[type="submit"]',
    "post_login_nav": "text=Órdenes D2C",  # algo que solo se ve logueado
    "2fa_indicator":  "text=/(c[óo]digo de verificaci|two.?factor)/i",
}


@dataclass
class ExtractedOrder:
    orden_tienda: str
    carrier: Optional[str] = None
    guia: Optional[str] = None
    tracking_url: Optional[str] = None
    incidencias: list[dict] = field(default_factory=list)  # [{tipo, estado, descripcion, fecha}]
    eventos: list[str] = field(default_factory=list)        # historial del tracking
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
        # Si todavía vemos el form de login (input email visible) → no logueado
        try:
            if self._page.locator('input#email, input[name="email"]').first.is_visible(timeout=1_500):
                return False
        except Exception:
            pass
        # Si la URL ya no es de login y no hay form → asumimos logueado
        if "login" in url.lower() or "signin" in url.lower():
            return False
        return True

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

            # Esperar redirect post-login (la URL debe cambiar de la de login)
            try:
                self._page.wait_for_url(lambda u: "login" not in u.lower(), timeout=12_000)
            except Exception:
                pass
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

    def extract_order(self, orden_tienda: str, melonn_id: str = "") -> ExtractedOrder:
        """
        Extrae carrier + guía desde la página PÚBLICA de tracking de Melonn.

        URL: https://tracking.melonn.com/{internal_order_number}
        Ej: melonn_id=M1781196774156456 → tracking.melonn.com/M1781196774156456

        Ventaja: pública (sin login), muestra transportadora + guía + historial.
        El layout: "En tránsito / Tu pedido está en camino... / ENVÍA / Guía: 034057310824"
        """
        result = ExtractedOrder(orden_tienda=orden_tienda)

        mid = (melonn_id or "").strip()
        if not mid:
            result.error = "Falta melonn_id (internal_order_number)"
            return result
        if not mid.upper().startswith("M"):
            mid = "M" + mid.lstrip("Mm")

        url = f"{TRACKING_URL}/{mid}"
        loaded = False
        for intento in range(3):
            try:
                self._page.goto(url, wait_until="domcontentloaded", timeout=25_000)
                time.sleep(3)  # SPA render
                # La página de tracking muestra "Seguimiento" o "Tu pedido"
                txt = self._page.inner_text("body")
                if "seguimiento" in txt.lower() or "tu pedido" in txt.lower() or orden_tienda in txt:
                    loaded = True
                    break
                head = self._page.content()[:300].lower()
                if "nosuchkey" in head or "404" in head:
                    time.sleep(3)
                    self._page.reload(wait_until="domcontentloaded", timeout=25_000)
                    time.sleep(3)
            except Exception as e:
                log.debug(f"tracking goto {url} intento {intento+1}: {e}")
            time.sleep(2)

        if not loaded:
            result.error = f"No cargó tracking ({url})"
            return result

        try:
            # Abrir el historial de seguimiento si hay botón (ahí está la guía)
            for label in ["Ver historial de seguimiento", "Ver historial", "historial"]:
                try:
                    btn = self._page.get_by_text(re.compile(label, re.I)).first
                    if btn.is_visible(timeout=2000):
                        btn.click()
                        time.sleep(1.5)
                        break
                except Exception:
                    continue

            text = self._page.inner_text("body")

            # Estado actual (ej. "Tu pedido está en camino" / "No pudimos entregar")
            for pat in [
                r"(Tu pedido está en camino)",
                r"(No pudimos entregar[^\n.]*)",
                r"(Entregado[^\n.]*)",
                r"(En tránsito)",
            ]:
                m = re.search(pat, text, re.I)
                if m:
                    result.estado = m.group(1).strip()
                    break

            # Guía: "Guía: 034057310824"
            mg = re.search(r"Gu[ií]a:?\s*([A-Z0-9][A-Z0-9-]{4,40})", text)
            if mg:
                result.guia = mg.group(1).strip()

            # Transportadora: nombre en MAYÚSCULAS o capitalizado justo ANTES de "Guía:"
            # Layout: "ENVÍA\nGuía: 034057310824"  o  "Coordinadora\nGuía: ..."
            mc = re.search(r"\n([A-ZÁÉÍÓÚÑ][A-Za-zÀ-ſ .]{1,38})\s*\n\s*Gu[ií]a:", text)
            if mc:
                result.carrier = mc.group(1).strip()
            else:
                # Fallback: buscar nombres de carriers conocidos en el texto
                for c in ["Coordinadora", "Servientrega", "Interrapidísimo",
                          "Interrapidisimo", "TCC", "Envía", "Envia", "Mercado Libre"]:
                    if re.search(rf"\b{re.escape(c)}\b", text, re.I):
                        result.carrier = c
                        break

            # ── Novedades / incidencias del tracking público ──
            # Cada patrón mapea a un motivo legible. El tracking muestra
            # mensajes como "No pudimos entregar tu pedido y será retornado".
            NOVEDADES = [
                (r"no pudimos entregar",            "Entrega fallida — varios intentos"),
                (r"ser[áa] retornado a bodega",     "Será retornado a bodega"),
                (r"devoluci[óo]n|devuel",           "En devolución"),
                (r"direcci[óo]n (errada|incompleta|incorrecta)", "Dirección errada/incompleta"),
                (r"cliente (no |)(se )?(encontr|ubic|localiz)",  "Cliente no localizado"),
                (r"cliente rechaz",                 "Cliente rechazó el pedido"),
                (r"no (contesta|responde|contactar)", "Cliente no contesta"),
                (r"reprogramad|reagendad",          "Entrega reprogramada"),
                (r"zona de dif[íi]cil acceso",      "Zona de difícil acceso"),
                (r"novedad",                        "Novedad reportada por transportadora"),
            ]
            for pat, motivo in NOVEDADES:
                if re.search(pat, text, re.I):
                    result.incidencias.append({
                        "numero": "TRACKING",
                        "estado": "Sin gestionar",
                        "descripcion": motivo,
                    })
                    break  # un motivo principal basta

            # ── Historial de eventos (timeline del tracking) ──
            # Capturamos las líneas del historial para guardar contexto.
            eventos = []
            for m in re.finditer(
                r"(Tu pedido[^\n]{5,120}|En el centro de distribuci[óo]n[^\n]{0,80}|"
                r"sali[óo] de la bodega[^\n]{0,80}|en reparto[^\n]{0,80})",
                text, re.I,
            ):
                ev = m.group(1).strip()
                if ev and ev not in eventos:
                    eventos.append(ev)
            if eventos:
                result.eventos = eventos[:6]

            result.ok = bool(result.guia or result.carrier)
            if not result.ok:
                try:
                    Path(f"/tmp/track_{orden_tienda}.txt").write_text(text[:4000], encoding="utf-8")
                except Exception:
                    pass
                result.error = "Tracking cargó pero sin guía/carrier visible"
            return result
        except Exception as e:
            log.exception(f"Error extrayendo tracking {orden_tienda}")
            result.error = str(e)
            return result

    def _click_tab(self, nombre: str):
        """
        Click en un tab del detalle (Transporte / Incidencias).
        IMPORTANTE: evitar el item del menú lateral con el mismo nombre.
        """
        # 1. role=tab es lo más específico (el menú lateral usa role=link/menuitem)
        try:
            tab = self._page.get_by_role("tab", name=re.compile(nombre, re.I)).first
            if tab.is_visible(timeout=2_500):
                tab.click()
                return
        except Exception:
            pass
        # 2. Buscar el tab por su ícono+texto dentro del área de detalle.
        #    El menú lateral es un <nav>/<aside>; excluimos esa zona buscando
        #    elementos cuyo texto sea EXACTO al nombre y no estén en el sidebar.
        try:
            # Los tabs del detalle suelen ser <button> o <div role=tab>.
            loc = self._page.locator(
                f"button:has-text('{nombre}'), [role=tab]:has-text('{nombre}')"
            )
            count = loc.count()
            for i in range(count):
                el = loc.nth(i)
                try:
                    if el.is_visible(timeout=800):
                        el.click(timeout=2000)
                        return
                except Exception:
                    continue
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

def scrape_batch(ordenes: list, delay_seconds: float = 2.0, on_result=None) -> dict:
    """
    Loguea y procesa una lista de pedidos. Retorna resultados agregados.

    `ordenes` puede ser:
      - lista de strings (orden_tienda) — sin melonn_id, no funcionará la URL
      - lista de tuplas/dicts {orden_tienda, melonn_id} — recomendado

    `on_result(dict)`: callback opcional invocado por CADA pedido apenas se
    extrae (guardado incremental — no se pierde lo ya conseguido si el bot
    se cae a mitad).
    """
    # El tracking público NO requiere credenciales. Solo se usan como
    # fallback opcional si algún día volvemos al admin.
    email = os.environ.get("MELONN_BOT_EMAIL", "").strip() or "publico"
    pwd   = os.environ.get("MELONN_BOT_PASSWORD", "").strip() or "publico"

    # Normalizar a lista de (orden_tienda, melonn_id)
    pares: list[tuple[str, str]] = []
    for o in ordenes:
        if isinstance(o, dict):
            pares.append((str(o.get("orden_tienda") or ""), str(o.get("melonn_id") or o.get("orden_melonn") or "")))
        elif isinstance(o, (list, tuple)):
            pares.append((str(o[0]), str(o[1]) if len(o) > 1 else ""))
        else:
            pares.append((str(o), ""))

    extracted: list[ExtractedOrder] = []
    try:
        with MelonnBot(email, pwd, headless=True) as bot:
            # Tracking público: NO necesita login. Saltamos ensure_logged_in.
            for i, (orden, mid) in enumerate(pares):
                if i > 0:
                    time.sleep(delay_seconds)  # delay entre pedidos
                r = bot.extract_order(orden, melonn_id=mid)
                extracted.append(r)
                log.info(f"[{i+1}/{len(ordenes)}] {orden}: ok={r.ok} carrier={r.carrier} guia={r.guia} incidencias={len(r.incidencias)}")
                # Guardado incremental: persistir este pedido YA
                if on_result is not None:
                    try:
                        on_result(asdict(r), i + 1, len(pares))
                    except Exception as e:
                        log.warning(f"on_result callback error en {orden}: {e}")
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
