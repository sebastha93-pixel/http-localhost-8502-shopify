"""
backend.core.revenue_scheduler — Cron nocturno para el módulo Revenue.

Cada noche a las 3:00 AM Bogotá (UTC-5) ejecuta:
  - rankings_calcular(days_back=30) → persiste snapshot en advisor_rankings

Sigue el patrón de threading + Event del scheduler principal (no apscheduler).
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)

_thread: threading.Thread | None = None
_stop_event = threading.Event()

# Cron de alertas Slack
_alertas_thread: threading.Thread | None = None
_alertas_stop = threading.Event()
ALERTAS_INTERVAL_MIN = int(os.environ.get("REVENUE_ALERTAS_INTERVAL_MIN", "5"))
ALERTAS_UMBRAL_MIN = int(os.environ.get("REVENUE_ALERTAS_UMBRAL_MIN", "30"))

# Cron hora Bogotá (UTC-5). 3am Bogotá = 8am UTC
HORA_OBJETIVO_BOG = int(os.environ.get("REVENUE_CRON_HOUR_BOG", "3"))
TZ_BOG = timezone(timedelta(hours=-5))

_last_run_at: str | None = None
_last_result: dict | None = None


def get_state() -> dict:
    """Estado del scheduler para diagnóstico."""
    next_run = _calcular_proxima_corrida()
    return {
        "running":      _thread is not None and _thread.is_alive(),
        "hora_objetivo_bog": HORA_OBJETIVO_BOG,
        "proxima_corrida_utc": next_run.isoformat(),
        "last_run_at":  _last_run_at,
        "last_result":  _last_result,
    }


def _calcular_proxima_corrida() -> datetime:
    """Próxima ejecución a HORA_OBJETIVO_BOG hora Bogotá."""
    ahora_bog = datetime.now(tz=TZ_BOG)
    objetivo = ahora_bog.replace(hour=HORA_OBJETIVO_BOG, minute=0, second=0, microsecond=0)
    if objetivo <= ahora_bog:
        objetivo = objetivo + timedelta(days=1)
    return objetivo.astimezone(timezone.utc)


def _correr_jobs():
    """Ejecuta los jobs nocturnos. Captura excepciones por job."""
    global _last_run_at, _last_result
    _last_run_at = datetime.now(tz=timezone.utc).isoformat()
    resultado: dict = {}
    try:
        # Importes locales para evitar circular imports al boot
        from backend.services import revenue_db as _db
        from datetime import timedelta as _td

        sb = _db._sb()
        if sb is None:
            resultado["error"] = "supabase_no_configurado"
            _last_result = resultado
            return

        # Calcular rankings 30 días
        from backend.api.revenue import rankings_calcular as _rc  # noqa
        # rankings_calcular es un endpoint que requiere CurrentUser. Hacemos la lógica inline.
        # En vez de llamarlo, replicamos el core: usamos requests al propio backend.
        # Más simple: ejecutamos la lógica directamente:
        try:
            from datetime import datetime as _dt, timezone as _tz
            desde_dt = _dt.now(tz=_tz.utc) - _td(days=30)
            desde = desde_dt.isoformat()
            period_key = f"{desde_dt.date().isoformat()}_to_{_dt.now(tz=_tz.utc).date().isoformat()}"

            advisors = sb.table("advisors").select("advisor_id,name,active").eq("active", True).execute().data or []
            convs = sb.table("conversations").select("conversation_id,advisor_id,lead_id,last_message_at").gte("last_message_at", desde).execute().data or []
            lead_ids = list({c["lead_id"] for c in convs if c.get("lead_id")})
            leads_map: dict = {}
            if lead_ids:
                for ib in range(0, len(lead_ids), 200):
                    batch = lead_ids[ib:ib + 200]
                    r = sb.table("kommo_leads").select("lead_id,status,lead_value").in_("lead_id", batch).execute().data or []
                    for ld in r:
                        leads_map[ld["lead_id"]] = ld

            audits_map: dict = {}
            audits = sb.table("chat_audits").select("advisor_id,overall_score,response_time_score,attention_score,follow_up_score,closing_score,economic_impact_estimate").gte("audit_date", desde).execute().data or []
            for a in audits:
                adv = a.get("advisor_id")
                if not adv:
                    continue
                r = audits_map.setdefault(adv, {"count": 0, "overall": [], "response": [], "attention": [], "follow_up": [], "closing": [], "impact_perdido": 0})
                r["count"] += 1
                for k_src, k_dst in [("overall_score","overall"),("response_time_score","response"),("attention_score","attention"),("follow_up_score","follow_up"),("closing_score","closing")]:
                    v = a.get(k_src)
                    if v is not None:
                        r[k_dst].append(float(v))
                r["impact_perdido"] += float(a.get("economic_impact_estimate") or 0)

            def avg(lst): return round(sum(lst) / len(lst), 2) if lst else None
            persistidos = 0
            for adv in advisors:
                adv_id = adv["advisor_id"]
                convs_adv = [c for c in convs if c.get("advisor_id") == adv_id]
                won = sum(1 for c in convs_adv if (leads_map.get(c.get("lead_id")) or {}).get("status") == "won")
                lost = sum(1 for c in convs_adv if (leads_map.get(c.get("lead_id")) or {}).get("status") == "lost")
                revenue = sum(float((leads_map.get(c.get("lead_id")) or {}).get("lead_value") or 0) for c in convs_adv if (leads_map.get(c.get("lead_id")) or {}).get("status") == "won")
                cerradas = won + lost
                conv_rate = round(100 * won / cerradas, 2) if cerradas else None
                a = audits_map.get(adv_id, {})
                row = {
                    "advisor_id":       adv_id,
                    "period_key":       period_key,
                    "period_days":      30,
                    "calculated_at":    _dt.now(tz=_tz.utc).isoformat(),
                    "conversations":    len(convs_adv),
                    "won":              won,
                    "lost":             lost,
                    "conversion_rate":  conv_rate,
                    "revenue_generated": revenue,
                    "audits_count":     a.get("count", 0),
                    "avg_overall_score": avg(a.get("overall", [])),
                    "avg_response_score": avg(a.get("response", [])),
                    "avg_attention_score": avg(a.get("attention", [])),
                    "avg_follow_up_score": avg(a.get("follow_up", [])),
                    "avg_closing_score": avg(a.get("closing", [])),
                    "impact_perdido":   a.get("impact_perdido", 0),
                }
                clean = {k: v for k, v in row.items() if v is not None}
                try:
                    sb.table("advisor_rankings").upsert(clean, on_conflict="advisor_id,period_key").execute()
                    persistidos += 1
                except Exception:
                    pass
            resultado["rankings"] = {"persistidos": persistidos, "total_advisors": len(advisors), "period_key": period_key}
        except Exception as e:
            resultado["rankings_error"] = str(e)[:300]
    except Exception as e:
        resultado["error"] = str(e)[:300]
    _last_result = resultado
    log.info(f"revenue_scheduler corrida completa: {resultado}")


def _loop():
    """Loop principal del scheduler. Calcula tiempo hasta próxima 3am y duerme."""
    while not _stop_event.is_set():
        proxima = _calcular_proxima_corrida()
        ahora = datetime.now(tz=timezone.utc)
        segundos = (proxima - ahora).total_seconds()
        log.info(f"revenue_scheduler: próxima corrida en {int(segundos/60)} min ({proxima.isoformat()})")
        # Dormir en bloques de 60s para responder a stop_event rápido
        while segundos > 0 and not _stop_event.is_set():
            tick = min(60.0, segundos)
            if _stop_event.wait(timeout=tick):
                return
            segundos -= tick
        if _stop_event.is_set():
            return
        try:
            _correr_jobs()
        except Exception as e:
            log.exception(f"revenue_scheduler error: {e}")
        # Pequeña pausa para evitar doble-trigger si el reloj rebota
        _stop_event.wait(timeout=120)


def _detectar_alertas_y_notificar() -> dict:
    """Detecta conversations donde el cliente está esperando > N min y notifica a Slack."""
    from backend.services import slack_notifier as sn
    from backend.services import revenue_db as _db
    sb = _db._sb()
    if sb is None:
        return {"error": "supabase_no_configurado"}
    if not sn._webhook_url():
        return {"skip": "slack_webhook_no_configurado"}

    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    cutoff = _dt.now(tz=_tz.utc) - _td(minutes=ALERTAS_UMBRAL_MIN)
    desde_amplio = (_dt.now(tz=_tz.utc) - _td(days=2)).isoformat()
    convs = (sb.table("conversations")
               .select("conversation_id,lead_id,advisor_id,channel,last_message_at,status")
               .eq("status", "in_work")
               .gte("last_message_at", desde_amplio)
               .lte("last_message_at", cutoff.isoformat())
               .order("last_message_at", desc=True)
               .limit(50).execute().data) or []
    if not convs:
        return {"alertas": 0, "enviadas": 0}

    # Para cada conv, último mensaje
    alertas = []
    lead_ids = list({c["lead_id"] for c in convs if c.get("lead_id")})
    advisor_ids = list({c["advisor_id"] for c in convs if c.get("advisor_id")})
    leads_map = {}
    advisors_map = {}
    if lead_ids:
        for l in (sb.table("kommo_leads").select("lead_id,customer_name,customer_phone").in_("lead_id", lead_ids).execute().data or []):
            leads_map[l["lead_id"]] = l
    if advisor_ids:
        for a in (sb.table("advisors").select("advisor_id,name").in_("advisor_id", advisor_ids).execute().data or []):
            advisors_map[a["advisor_id"]] = a

    ahora = _dt.now(tz=_tz.utc)
    for c in convs:
        cid = c["conversation_id"]
        m = (sb.table("messages").select("sender_type,message_text,sent_at")
               .eq("conversation_id", cid)
               .order("sent_at", desc=True)
               .limit(1).execute().data) or []
        if not m or m[0].get("sender_type") != "customer":
            continue
        try:
            last_dt = _dt.fromisoformat(m[0]["sent_at"].replace("Z", "+00:00"))
            mins = int((ahora - last_dt).total_seconds() / 60)
        except Exception:
            mins = None
        lead = leads_map.get(c.get("lead_id"), {})
        advisor = advisors_map.get(c.get("advisor_id"), {})
        alertas.append({
            "conversation_id":      cid,
            "customer_name":        lead.get("customer_name"),
            "customer_phone":       lead.get("customer_phone"),
            "advisor_name":         advisor.get("name"),
            "channel":              c.get("channel"),
            "ultimo_mensaje":       (m[0].get("message_text") or "")[:300],
            "minutos_sin_respuesta": mins,
        })
    res = sn.notificar_lote_alertas(alertas)
    return {"alertas_detectadas": len(alertas), **res}


def _loop_alertas():
    """Loop del cron de alertas: cada N min revisa y notifica."""
    while not _alertas_stop.is_set():
        try:
            res = _detectar_alertas_y_notificar()
            log.info(f"alertas_loop: {res}")
        except Exception as e:
            log.exception(f"alertas_loop error: {e}")
        # Dormir N min en bloques de 60s
        seg_total = ALERTAS_INTERVAL_MIN * 60
        while seg_total > 0 and not _alertas_stop.is_set():
            tick = min(60.0, seg_total)
            if _alertas_stop.wait(timeout=tick):
                return
            seg_total -= tick


def start() -> threading.Thread | None:
    """Arranca ambos schedulers (rankings nocturno + alertas Slack)."""
    global _thread, _alertas_thread
    enabled = os.environ.get("REVENUE_CRON_ENABLED", "true").lower() in ("true", "1", "yes")
    if not enabled:
        log.info("revenue_scheduler deshabilitado por REVENUE_CRON_ENABLED")
        return None
    if _thread is None or not _thread.is_alive():
        _stop_event.clear()
        _thread = threading.Thread(target=_loop, daemon=True, name="revenue_scheduler")
        _thread.start()
    if _alertas_thread is None or not _alertas_thread.is_alive():
        _alertas_stop.clear()
        _alertas_thread = threading.Thread(target=_loop_alertas, daemon=True, name="revenue_alertas")
        _alertas_thread.start()
    return _thread


def stop():
    _stop_event.set()
    _alertas_stop.set()
    if _thread is not None:
        _thread.join(timeout=5)
    if _alertas_thread is not None:
        _alertas_thread.join(timeout=5)
