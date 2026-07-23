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

# OJO ARQUITECTURA: el backend corre con VARIOS workers Uvicorn y solo el
# LÍDER ejecuta los schedulers; además los contadores en memoria son POR
# WORKER. Por eso los chequeos se basan en HUELLAS EN LA BASE (sent_at de
# messages, calculated_at de advisor_rankings) — verdad compartida entre
# workers — y la memoria solo complementa.

def _check_mensajeria() -> dict:
    """Kommo + Meta escriben en `messages` — el sent_at más reciente es la
    prueba worker-agnóstica de que los webhooks están vivos."""
    candidatos = []
    try:
        from backend.services.produccion import _sb
        sb = _sb()
        r = (sb.table("messages").select("sent_at")
               .order("sent_at", desc=True).limit(1).execute()).data
        if r:
            candidatos.append(_hace_seg(r[0].get("sent_at")))
    except Exception:
        pass
    try:
        from backend.api import revenue as _rev
        candidatos.append(_hace_seg(_rev._webhook_stats.get("ultimo_en")))
    except Exception:
        pass
    try:
        from backend.api import meta as _meta
        candidatos.append(_hace_seg(_meta._stats.get("ultimo_en")))
    except Exception:
        pass
    validos = [c for c in candidatos if c is not None]
    seg = min(validos) if validos else None
    if seg is None:
        return _chk("mensajeria", "Mensajería (Kommo + Meta)", "alerta",
                    "Sin mensajes registrados — ¿webhooks configurados?")
    if seg < 3600:
        return _chk("mensajeria", "Mensajería (Kommo + Meta)", "ok", f"Último mensaje {_fmt_hace(seg)}")
    if _horario_comercial() and seg > 10800:
        return _chk("mensajeria", "Mensajería (Kommo + Meta)", "critico",
                    f"SIN mensajes {_fmt_hace(seg)} en horario comercial — revisar webhooks en Kommo y Meta")
    return _chk("mensajeria", "Mensajería (Kommo + Meta)", "alerta", f"Último mensaje {_fmt_hace(seg)}")


def _check_cron_nocturno() -> dict:
    """La huella real del cron de las 3 AM: calculated_at en advisor_rankings
    (el estado del hilo solo lo conoce el worker líder — no sirve aquí)."""
    try:
        from backend.services.produccion import _sb
        sb = _sb()
        # La tabla no tiene calculated_at (se filtra en el upsert) — la huella
        # que sí existe es updated_at/created_at de la última fila tocada.
        r = (sb.table("advisor_rankings").select("updated_at,created_at")
               .order("updated_at", desc=True).limit(1).execute()).data
        seg = _hace_seg((r[0].get("updated_at") or r[0].get("created_at"))) if r else None
    except Exception as e:
        return _chk("cron_nocturno", "Cron nocturno (rankings 3 AM)", "alerta",
                    f"No se pudo leer rankings: {str(e)[:100]}")
    if seg is None:
        return _chk("cron_nocturno", "Cron nocturno (rankings 3 AM)", "alerta",
                    "Sin corridas registradas aún")
    if seg > 30 * 3600:
        return _chk("cron_nocturno", "Cron nocturno (rankings 3 AM)", "critico",
                    f"No corre {_fmt_hace(seg)} — rankings viejos; revisar backend/Railway")
    return _chk("cron_nocturno", "Cron nocturno (rankings 3 AM)", "ok", f"Corrió {_fmt_hace(seg)}")


def _check_poll_notas() -> dict:
    habilitado = os.environ.get("NOTES_POLL_ENABLED", "false").lower() in ("true", "1", "yes")
    if not habilitado:
        return _chk("poll_notas", "Sondeo de notas Kommo", "ok",
                    "Apagado a propósito (los mensajes llegan por Meta directo)")
    from backend.core import revenue_scheduler as _sch
    st = _sch.get_notes_poll_state()
    seg = _hace_seg(st.get("last_run_at"))
    if seg is not None and seg < 600:
        return _chk("poll_notas", "Sondeo de notas Kommo", "ok", f"Última pasada {_fmt_hace(seg)}")
    return _chk("poll_notas", "Sondeo de notas Kommo", "alerta",
                f"Última pasada {_fmt_hace(seg)} (dato del worker líder — puede ser visión parcial)")


def _check_impresion() -> dict:
    from backend.services import produccion as _prod
    e = _prod.estado_impresion()
    hace_s = e.get("agente_hace_s")
    if hace_s is None:
        return _chk("impresion", "Agente de impresión", "alerta",
                    "Sin reportes desde el último reinicio del backend")
    # Umbral holgado: los polls del agente se reparten entre los workers,
    # así que ESTE worker puede llevar varios minutos sin ver uno.
    if hace_s > 900:
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
            from backend.services.clientes import _shopify_graphql
            r = _shopify_graphql("query { shop { name } }")
            if (r or {}).get("data", {}).get("shop", {}).get("name"):
                return _chk("shopify", "Shopify Admin", "ok", "API respondiendo")
            return _chk("shopify", "Shopify Admin", "alerta",
                        f"Respuesta inesperada: {str(r)[:100]}")
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
    _check_mensajeria,
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
