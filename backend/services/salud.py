"""
backend.services.salud — CENTRO DE SALUD del sistema.

Un semáforo por circuito: webhooks, crons, integraciones, impresión,
flujo de producción e integridad de datos. La regla de la casa: cada
proceso debe AVISAR solo cuando se atasca, no esperar a que alguien lo
descubra con datos viejos.

Estados: ok | alerta | critico. Cada chequeo corre defensivo (un chequeo
roto se reporta a sí mismo como crítico, nunca tumba el panel). Los
chequeos que pegan a APIs EXTERNAS (Siigo, WhatsApp, Shopify) se cachean
5 minutos para no castigar esas APIs con cada refresco del tablero.
"""
from __future__ import annotations

import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

TZ_BOG = timezone(timedelta(hours=-5))
_TTL_EXTERNOS = 300  # 5 min de caché para chequeos contra APIs de terceros
_cache: dict[str, tuple[float, dict]] = {}


# ── helpers ──────────────────────────────────────────────────────────────

def _hace_seg(iso: Optional[str]) -> Optional[int]:
    """Segundos desde un timestamp ISO. Py 3.10: fromisoformat revienta con
    fracciones de segundo recortadas por Postgres → se limpian primero."""
    if not iso:
        return None
    try:
        limpio = re.sub(r"\.\d+", "", str(iso)).replace("Z", "+00:00")
        t = datetime.fromisoformat(limpio)
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return max(0, int((datetime.now(timezone.utc) - t).total_seconds()))
    except Exception:
        return None


def _fmt_hace(seg: Optional[int]) -> str:
    if seg is None:
        return "nunca"
    if seg < 90:
        return f"hace {seg} s"
    if seg < 5400:
        return f"hace {seg // 60} min"
    if seg < 172800:
        return f"hace {seg // 3600} h"
    return f"hace {seg // 86400} días"


def _horario_comercial() -> bool:
    return 7 <= datetime.now(TZ_BOG).hour <= 20


def _chk(clave: str, nombre: str, estado: str, detalle: str) -> dict:
    return {"clave": clave, "nombre": nombre, "estado": estado, "detalle": detalle}


def _cacheado(clave: str, fn) -> dict:
    ahora = time.time()
    hit = _cache.get(clave)
    if hit and ahora - hit[0] < _TTL_EXTERNOS:
        return hit[1]
    out = fn()
    _cache[clave] = (ahora, out)
    return out


# ── chequeos ─────────────────────────────────────────────────────────────

def _check_webhook_kommo() -> dict:
    from backend.api import revenue as _rev
    seg = _hace_seg(_rev._webhook_stats.get("ultimo_en"))
    if seg is None:
        # El contador vive en memoria (se borra al redesplegar) → mirar la
        # base: el último mensaje guardado sobrevive reinicios.
        try:
            from backend.services import revenue_db as _rdb
            sb = _rdb._sb()
            r = (sb.table("messages").select("created_at")
                   .order("created_at", desc=True).limit(1).execute()).data
            seg = _hace_seg(r[0]["created_at"]) if r else None
        except Exception:
            seg = None
    if seg is None:
        return _chk("webhook_kommo", "Webhook Kommo", "alerta",
                    "Sin eventos registrados aún (¿reinicio reciente?)")
    if seg < 1800:
        return _chk("webhook_kommo", "Webhook Kommo", "ok", f"Último evento {_fmt_hace(seg)}")
    if _horario_comercial() and seg > 7200:
        return _chk("webhook_kommo", "Webhook Kommo", "critico",
                    f"SIN eventos {_fmt_hace(seg)} en horario comercial — ¿webhook apagado en Kommo?")
    return _chk("webhook_kommo", "Webhook Kommo", "alerta", f"Último evento {_fmt_hace(seg)}")


def _check_webhook_meta() -> dict:
    from backend.api import meta as _meta
    seg = _hace_seg(_meta._stats.get("ultimo_en"))
    if seg is None:
        return _chk("webhook_meta", "Webhook Meta (WA/IG/FB)", "alerta",
                    "Sin eventos registrados aún (¿reinicio reciente?)")
    if seg < 3600:
        return _chk("webhook_meta", "Webhook Meta (WA/IG/FB)", "ok", f"Último evento {_fmt_hace(seg)}")
    if _horario_comercial() and seg > 14400:
        return _chk("webhook_meta", "Webhook Meta (WA/IG/FB)", "critico",
                    f"SIN eventos {_fmt_hace(seg)} — revisar suscripción del webhook en Meta")
    return _chk("webhook_meta", "Webhook Meta (WA/IG/FB)", "alerta", f"Último evento {_fmt_hace(seg)}")


def _check_cron_nocturno() -> dict:
    from backend.core import revenue_scheduler as _sch
    st = _sch.get_state()
    if not st.get("running"):
        return _chk("cron_nocturno", "Cron nocturno (rankings 3 AM)", "critico",
                    "El hilo del scheduler está CAÍDO — reiniciar el backend")
    seg = _hace_seg(st.get("last_run_at"))
    if seg is None:
        return _chk("cron_nocturno", "Cron nocturno (rankings 3 AM)", "ok",
                    "Aún no corre desde el último reinicio (programado 3 AM Bogotá)")
    if seg > 26 * 3600:
        return _chk("cron_nocturno", "Cron nocturno (rankings 3 AM)", "critico",
                    f"No corre {_fmt_hace(seg)} — los rankings están viejos")
    return _chk("cron_nocturno", "Cron nocturno (rankings 3 AM)", "ok", f"Corrió {_fmt_hace(seg)}")


def _check_poll_notas() -> dict:
    from backend.core import revenue_scheduler as _sch
    st = _sch.get_notes_poll_state()
    seg = _hace_seg(st.get("last_run_at"))
    if seg is None:
        return _chk("poll_notas", "Sondeo de notas Kommo", "alerta",
                    "Sin corridas registradas (¿reinicio reciente?)")
    if seg < 300:
        return _chk("poll_notas", "Sondeo de notas Kommo", "ok", f"Última pasada {_fmt_hace(seg)}")
    if seg > 1800:
        return _chk("poll_notas", "Sondeo de notas Kommo", "critico",
                    f"Detenido {_fmt_hace(seg)} — mensajes salientes sin capturar")
    return _chk("poll_notas", "Sondeo de notas Kommo", "alerta", f"Última pasada {_fmt_hace(seg)}")


def _check_impresion() -> dict:
    from backend.services import produccion as _prod
    e = _prod.estado_impresion()
    hace_s = e.get("agente_hace_s")
    if hace_s is None:
        return _chk("impresion", "Agente de impresión", "alerta",
                    "Sin reportes desde el último reinicio del backend")
    if hace_s > 300:
        return _chk("impresion", "Agente de impresión", "critico",
                    f"SIN CONEXIÓN {_fmt_hace(hace_s)} — ¿el Mac del agente está dormido/apagado?")
    if e.get("pendientes", 0) > 0 and e.get("mas_viejo_min", 0) >= 10:
        return _chk("impresion", "Agente de impresión", "alerta",
                    f"{e['pendientes']} trabajo(s) represados hace {e['mas_viejo_min']} min — ¿impresora apagada o sin cinta?")
    return _chk("impresion", "Agente de impresión", "ok", f"En línea ({_fmt_hace(hace_s)})")


def _check_siigo() -> dict:
    def _run():
        try:
            from backend.services import siigo as _sii
            if not _sii.siigo_configurado():
                return _chk("siigo", "Siigo (facturación)", "alerta", "Sin credenciales configuradas")
            _sii._get_token()
            return _chk("siigo", "Siigo (facturación)", "ok", "Token válido")
        except Exception as e:
            return _chk("siigo", "Siigo (facturación)", "critico", f"Autenticación falló: {str(e)[:120]}")
    return _cacheado("siigo", _run)


def _check_whatsapp() -> dict:
    def _run():
        token = (os.environ.get("WHATSAPP_TOKEN") or "").strip()
        num_id = (os.environ.get("WHATSAPP_PHONE_NUMBER_ID") or "").strip()
        if not token or not num_id:
            return _chk("whatsapp", "WhatsApp Cloud API", "alerta", "Sin credenciales configuradas")
        try:
            import requests
            r = requests.get(
                f"https://graph.facebook.com/v20.0/{num_id}",
                params={"fields": "display_phone_number"},
                headers={"Authorization": f"Bearer {token}"}, timeout=8)
            if r.status_code == 200:
                return _chk("whatsapp", "WhatsApp Cloud API", "ok",
                            f"Token válido · {r.json().get('display_phone_number', '')}")
            return _chk("whatsapp", "WhatsApp Cloud API", "critico",
                        f"HTTP {r.status_code}: {r.text[:100]} — ¿token vencido?")
        except Exception as e:
            return _chk("whatsapp", "WhatsApp Cloud API", "alerta", f"No se pudo verificar: {str(e)[:100]}")
    return _cacheado("whatsapp", _run)


def _check_shopify() -> dict:
    def _run():
        try:
            from backend.services.clientes import _shopify_get
            _shopify_get("shop.json")
            return _chk("shopify", "Shopify Admin", "ok", "API respondiendo")
        except Exception as e:
            # Alerta (no crítico): el fallo puede ser del propio chequeo.
            return _chk("shopify", "Shopify Admin", "alerta", f"No respondió: {str(e)[:120]}")
    return _cacheado("shopify", _run)


def _check_lotes_estancados() -> dict:
    from backend.services.produccion import _sb
    sb = _sb()
    if sb is None:
        return _chk("lotes", "Lotes en ruta", "alerta", "Sin conexión a la base")
    corte = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    rows = (sb.table("hoja_ruta_lote")
              .select("id,etapa,updated_at,orden_corte:orden_corte_id(consecutivo)")
              .neq("etapa", "despachado")
              .lt("updated_at", corte)
              .limit(20).execute()).data or []
    if not rows:
        return _chk("lotes", "Lotes en ruta", "ok", "Ningún lote lleva más de 7 días quieto")
    det = " · ".join(
        f"{(r.get('orden_corte') or {}).get('consecutivo') or '¿?'} ({r.get('etapa')})"
        for r in rows[:4])
    extra = f" y {len(rows) - 4} más" if len(rows) > 4 else ""
    return _chk("lotes", "Lotes en ruta", "alerta",
                f"{len(rows)} lote(s) sin moverse hace más de 7 días: {det}{extra}")


def _check_datos_corte() -> dict:
    from backend.services.produccion import _sb
    sb = _sb()
    if sb is None:
        return _chk("datos_corte", "Integridad de corte", "alerta", "Sin conexión a la base")
    rows = (sb.table("ordenes_corte")
              .select("consecutivo,unidades_cortadas")
              .eq("estado", "cortada").limit(300).execute()).data or []
    vacias = [r.get("consecutivo") for r in rows
              if not r.get("unidades_cortadas")
              or sum(int(v or 0) for v in (r.get("unidades_cortadas") or {}).values()) <= 0]
    if not vacias:
        return _chk("datos_corte", "Integridad de corte", "ok",
                    f"{len(rows)} órdenes cerradas, todas con unidades")
    return _chk("datos_corte", "Integridad de corte", "alerta",
                f"{len(vacias)} orden(es) cerradas SIN unidades: {' · '.join(vacias[:5])} — usar Corregir unidades")


# ── panel ────────────────────────────────────────────────────────────────

_CHEQUEOS = (
    _check_webhook_kommo,
    _check_webhook_meta,
    _check_cron_nocturno,
    _check_poll_notas,
    _check_impresion,
    _check_siigo,
    _check_whatsapp,
    _check_shopify,
    _check_lotes_estancados,
    _check_datos_corte,
)


def resumen() -> dict:
    checks = []
    for fn in _CHEQUEOS:
        try:
            checks.append(fn())
        except Exception as e:
            checks.append(_chk(fn.__name__, fn.__name__.replace("_check_", ""),
                               "critico", f"El chequeo falló: {str(e)[:120]}"))
    orden = {"critico": 0, "alerta": 1, "ok": 2}
    checks.sort(key=lambda c: orden.get(c["estado"], 3))
    peor = checks[0]["estado"] if checks else "ok"
    return {
        "estado_general": peor,
        "criticos": sum(1 for c in checks if c["estado"] == "critico"),
        "alertas": sum(1 for c in checks if c["estado"] == "alerta"),
        "checks": checks,
        "generado_en": datetime.now(timezone.utc).isoformat(),
    }
