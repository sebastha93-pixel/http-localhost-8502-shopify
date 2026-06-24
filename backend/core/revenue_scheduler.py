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

# Prewarmer del módulo comercial (Shopify)
_warmup_thread: threading.Thread | None = None
_warmup_stop = threading.Event()
WARMUP_INTERVAL_MIN = int(os.environ.get("WARMUP_INTERVAL_MIN", "3"))

# Polling de notas (mensajes salientes de asesoras vía Kommo notes)
_notes_thread: threading.Thread | None = None
_notes_stop = threading.Event()
NOTES_POLL_INTERVAL_SEC = int(os.environ.get("NOTES_POLL_INTERVAL_SEC", "15"))
NOTES_POLL_WINDOW_MIN = int(os.environ.get("NOTES_POLL_WINDOW_MIN", "5"))
_notes_state: dict = {"running": False, "last_run_at": None, "last_result": None}

# Ciclo de enrichment Meta↔Kommo cada N horas
_enrich_thread: threading.Thread | None = None
_enrich_stop = threading.Event()
ENRICH_CYCLE_HOURS = int(os.environ.get("ENRICH_CYCLE_HOURS", "6"))
_enrich_state: dict = {"running": False, "last_run_at": None, "last_result": None}


def _correr_cycle_enrichment() -> dict:
    """Wrapper para correr el endpoint de enrichment desde el cron."""
    try:
        from backend.api.meta import cycle_enrichment
        return cycle_enrichment(max_iterations=5)
    except Exception as e:
        return {"error": str(e)[:300]}


def _loop_enrich():
    """Loop del cron de enrichment: cada N horas dispara el ciclo completo."""
    if _enrich_stop.wait(timeout=300):  # esperar 5 min después del boot
        return
    while not _enrich_stop.is_set():
        try:
            _enrich_state["running"] = True
            _enrich_state["last_run_at"] = datetime.now(tz=timezone.utc).isoformat()
            res = _correr_cycle_enrichment()
            _enrich_state["last_result"] = res
            log.info(f"cycle_enrichment: {res.get('convs_total_enriched', 0)} convs enriquecidas")
        except Exception as e:
            log.exception(f"cycle_enrich error: {e}")
        finally:
            _enrich_state["running"] = False
        # Dormir N horas en bloques de 60s
        rem = ENRICH_CYCLE_HOURS * 3600
        while rem > 0 and not _enrich_stop.is_set():
            tick = min(60.0, rem)
            if _enrich_stop.wait(timeout=tick):
                return
            rem -= tick


def _poll_notes_de_conversaciones_activas() -> dict:
    """Para cada conversation actualizada en los últimos N minutos, fetch
    notes del lead y persiste mensajes nuevos (incluye outgoing de asesoras
    que Kommo no expone vía webhook)."""
    from backend.services import revenue_db as _db
    from backend.services import kommo as _kommo_svc
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    sb = _db._sb()
    if sb is None:
        return {"error": "supabase_no_configurado"}
    cutoff = (_dt.now(tz=_tz.utc) - _td(minutes=NOTES_POLL_WINDOW_MIN)).isoformat()
    try:
        convs = (sb.table("conversations")
                   .select("conversation_id,lead_id,last_message_at")
                   .gte("last_message_at", cutoff)
                   .not_.is_("lead_id", "null")
                   .order("last_message_at", desc=True)
                   .limit(30).execute().data) or []
    except Exception as e:
        return {"error": f"query: {str(e)[:200]}"}
    procesadas = 0
    msgs_total = 0
    errores = []
    for c in convs:
        lead_id = c.get("lead_id")
        cid = c.get("conversation_id")
        if not lead_id or not cid:
            continue
        try:
            res = _kommo_svc.sync_messages_de_lead(int(lead_id), conversation_id_override=cid)
            procesadas += 1
            msgs_total += int(res.get("mensajes", 0) or 0)
        except Exception as e:
            if len(errores) < 3:
                errores.append(f"lead={lead_id}: {str(e)[:100]}")
    return {"procesadas": procesadas, "msgs_total": msgs_total, "errores": errores}


def _loop_notes_poll():
    """Loop del poller de notas. Espera tras boot, después cada N seg."""
    if _notes_stop.wait(timeout=20):
        return
    while not _notes_stop.is_set():
        try:
            _notes_state["running"] = True
            _notes_state["last_run_at"] = datetime.now(tz=timezone.utc).isoformat()
            res = _poll_notes_de_conversaciones_activas()
            _notes_state["last_result"] = res
            log.info(f"notes_poll: {res}")
        except Exception as e:
            log.exception(f"notes_poll error: {e}")
        finally:
            _notes_state["running"] = False
        # Sleep en bloques de 10s
        rem = NOTES_POLL_INTERVAL_SEC
        while rem > 0 and not _notes_stop.is_set():
            tick = min(10, rem)
            if _notes_stop.wait(timeout=tick):
                return
            rem -= tick


def get_notes_poll_state() -> dict:
    return dict(_notes_state)

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

        # ── Transcribir audios WhatsApp pendientes ───────────────────────
        # Solo si OPENAI_API_KEY está configurado. Lote hasta 50 por noche
        # para mantener costo controlado (~$0.30 a precio Whisper).
        try:
            from backend.services import transcription as _tx
            tx_res = _tx.process_pending(limit=50)
            resultado["transcripcion"] = {
                "transcritos": tx_res.get("transcritos", 0),
                "procesados":  tx_res.get("procesados", 0),
            }
        except Exception as e:
            resultado["transcripcion_error"] = str(e)[:300]

        # ── Dedupe nocturno de conversations duplicadas ──────────────────
        # Para cada lead_id con >1 conversation: consolida en una sola
        # (preferencia talk-* > meta-* > otros · desempate por last_message_at
        # desc). Reasigna mensajes de las dupes a la canónica y borra dupes.
        # Idempotente: si no hay dupes, no hace nada.
        try:
            page = 0
            todas: list = []
            MAX_CONVS = 50_000  # cap RAM. Si la base crece, este cron procesa lo más reciente.
            truncated = False
            while True:
                r = (sb.table("conversations")
                       .select("conversation_id,lead_id,last_message_at")
                       .not_.is_("lead_id", "null")
                       .order("last_message_at", desc=True)
                       .range(page * 1000, page * 1000 + 999)
                       .execute().data) or []
                if not r:
                    break
                todas.extend(r)
                if len(todas) >= MAX_CONVS:
                    truncated = True
                    log.warning(f"dedupe nocturno: truncado en {MAX_CONVS} convs. Procesa lo más reciente.")
                    break
                if len(r) < 1000:
                    break
                page += 1
                if page > 50:
                    break
            if truncated:
                resultado.setdefault("dedupe_warnings", []).append(f"truncado en {MAX_CONVS}")
            por_lead: dict = {}
            for c in todas:
                por_lead.setdefault(c["lead_id"], []).append(c)
            n_dupes_borradas = 0
            n_msgs_reasignados = 0
            for lid, convs in por_lead.items():
                if len(convs) < 2:
                    continue
                def _prio(c):
                    cid = c["conversation_id"] or ""
                    kind = 2 if cid.startswith("talk-") else (1 if cid.startswith("meta-") else 0)
                    return (kind, c.get("last_message_at") or "")
                ordenadas = sorted(convs, key=_prio, reverse=True)
                canon = ordenadas[0]["conversation_id"]
                for dupe in [c["conversation_id"] for c in ordenadas[1:]]:
                    try:
                        upd = sb.table("messages").update({"conversation_id": canon}).eq("conversation_id", dupe).execute()
                        n_msgs_reasignados += len(upd.data or [])
                        sb.table("conversations").delete().eq("conversation_id", dupe).execute()
                        n_dupes_borradas += 1
                    except Exception:
                        pass
            resultado["dedupe"] = {"borradas": n_dupes_borradas, "msgs_reasignados": n_msgs_reasignados}
        except Exception as e:
            resultado["dedupe_error"] = str(e)[:300]

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


def _prewarm_comercial() -> dict:
    """Precalienta el cache interno de shopify_metrics, melonn y dashboard.
    Mantiene caliente: /comercial, /inventario, /centro-control, /contraentrega."""
    out: dict = {}
    try:
        import sys
        from pathlib import Path
        _SRC = Path(__file__).resolve().parent.parent.parent / "src"
        if str(_SRC) not in sys.path:
            sys.path.insert(0, str(_SRC))
        import shopify_metrics as sm

        # Comercial (Shopify metrics)
        for fname, fn, args in [
            ("ventas_del_dia",    sm.ventas_del_dia,  ()),
            ("delta_vs_ayer",     sm.delta_vs_ayer,   ()),
            ("ventas_serie_12d",  sm.ventas_serie,    (12,)),
            ("top_productos",     sm.top_productos,   ()),
            ("comparativas",      sm.comparativas,    ()),
            ("clientes_90d",      sm.analisis_clientes, (90,)),
            ("desglose_30d",      sm.desglose_ventas, ("30d",)),
        ]:
            try:
                fn(*args)
                out[fname] = "ok"
            except Exception as e:
                out[fname] = f"err: {str(e)[:120]}"

        # Inventario (catálogo Shopify)
        try:
            sm.inventario_shopify()
            out["inventario_shopify"] = "ok"
        except Exception as e:
            out["inventario_shopify"] = f"err: {str(e)[:120]}"
        try:
            sm.listar_productos(status="active", limit=250)
            out["productos_activos"] = "ok"
        except Exception as e:
            out["productos_activos"] = f"err: {str(e)[:120]}"

        # Dashboard centro-control (Melonn pedidos)
        try:
            from backend.services import melonn as melonn_svc
            melonn_svc.obtener_pedidos(forzar_refresh=False)
            out["melonn_pedidos"] = "ok"
        except Exception as e:
            out["melonn_pedidos"] = f"err: {str(e)[:120]}"
    except Exception as e:
        out["_error"] = str(e)[:200]
    return out


def _loop_warmup():
    """Loop del prewarmer: cada N min llama a los endpoints pesados para
    mantener el cache interno caliente."""
    # Espera inicial para que el servidor termine de bootear
    if _warmup_stop.wait(timeout=30):
        return
    while not _warmup_stop.is_set():
        try:
            res = _prewarm_comercial()
            ok_count = sum(1 for v in res.values() if v == "ok")
            log.info(f"warmup comercial: {ok_count}/{len(res)} ok")
        except Exception as e:
            log.exception(f"warmup error: {e}")
        seg_total = WARMUP_INTERVAL_MIN * 60
        while seg_total > 0 and not _warmup_stop.is_set():
            tick = min(60.0, seg_total)
            if _warmup_stop.wait(timeout=tick):
                return
            seg_total -= tick


def start() -> threading.Thread | None:
    """Arranca los schedulers (rankings + alertas Slack + warmup comercial)."""
    global _thread, _alertas_thread, _warmup_thread
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
    warmup_enabled = os.environ.get("WARMUP_ENABLED", "true").lower() in ("true", "1", "yes")
    if warmup_enabled and (_warmup_thread is None or not _warmup_thread.is_alive()):
        _warmup_stop.clear()
        _warmup_thread = threading.Thread(target=_loop_warmup, daemon=True, name="warmup_comercial")
        _warmup_thread.start()
    # En modo híbrido con Meta, ya no necesitamos pollear notas de Kommo.
    # Meta nos da mensajes directamente (incluyendo outgoing via App Review).
    notes_enabled = os.environ.get("NOTES_POLL_ENABLED", "false").lower() in ("true", "1", "yes")
    global _notes_thread
    if notes_enabled and (_notes_thread is None or not _notes_thread.is_alive()):
        _notes_stop.clear()
        _notes_thread = threading.Thread(target=_loop_notes_poll, daemon=True, name="notes_poll")
        _notes_thread.start()

    enrich_enabled = os.environ.get("ENRICH_CYCLE_ENABLED", "true").lower() in ("true", "1", "yes")
    global _enrich_thread
    if enrich_enabled and (_enrich_thread is None or not _enrich_thread.is_alive()):
        _enrich_stop.clear()
        _enrich_thread = threading.Thread(target=_loop_enrich, daemon=True, name="cycle_enrich")
        _enrich_thread.start()

    return _thread


def stop():
    _stop_event.set()
    _alertas_stop.set()
    _warmup_stop.set()
    _notes_stop.set()
    _enrich_stop.set()
    if _thread is not None:
        _thread.join(timeout=5)
    if _alertas_thread is not None:
        _alertas_thread.join(timeout=5)
    if _warmup_thread is not None:
        _warmup_thread.join(timeout=5)
    if _notes_thread is not None:
        _notes_thread.join(timeout=5)
    if _enrich_thread is not None:
        _enrich_thread.join(timeout=5)
