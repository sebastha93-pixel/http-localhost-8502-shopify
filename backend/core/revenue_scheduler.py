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


def start() -> threading.Thread | None:
    """Arranca el scheduler si REVENUE_CRON_ENABLED=true (default true en prod)."""
    global _thread
    if os.environ.get("REVENUE_CRON_ENABLED", "true").lower() not in ("true", "1", "yes"):
        log.info("revenue_scheduler deshabilitado por REVENUE_CRON_ENABLED")
        return None
    if _thread is not None and _thread.is_alive():
        return _thread
    _stop_event.clear()
    _thread = threading.Thread(target=_loop, daemon=True, name="revenue_scheduler")
    _thread.start()
    return _thread


def stop():
    _stop_event.set()
    if _thread is not None:
        _thread.join(timeout=5)
