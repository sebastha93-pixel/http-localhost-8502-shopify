"""
backend.api.revenue — Endpoints del módulo Revenue Intelligence.

F1: sync con Kommo + stats. F2 agregará endpoints de IA. F3+ los del
dashboard.
"""
from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, HTTPException, Query

from backend.core.security import CurrentUser, require_role
from backend.services import kommo as kommo_svc
from backend.services import revenue_db as db


log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/revenue", tags=["revenue"])


# ── Health ────────────────────────────────────────────────────────────────────
@router.get("/health")
def health(_: CurrentUser = Depends(require_role("admin", "operador"))) -> dict:
    """
    Valida la conexión con Kommo y devuelve info de la cuenta.
    Útil para confirmar que las env vars KOMMO_SUBDOMAIN/KOMMO_API_TOKEN
    están bien configuradas.
    """
    return kommo_svc.verificar_conexion()


@router.get("/stats")
def stats(_: CurrentUser = Depends(require_role("admin", "operador"))) -> dict:
    """KPIs del módulo: cuántos leads/conv/mensajes/audits."""
    return db.stats_revenue()


# ── Sync ──────────────────────────────────────────────────────────────────────
@router.post("/sync/advisors")
def sync_advisors_endpoint(
    _: CurrentUser = Depends(require_role("admin")),
) -> dict:
    """Trae asesoras de Kommo y las puebla en advisors. Idempotente."""
    return kommo_svc.sync_advisors()


@router.post("/sync/leads")
def sync_leads_endpoint(
    full: bool = Query(False, description="True = full sync (lento). False = solo cambios"),
    limit: int = Query(1000, ge=1, le=5000),
    _: CurrentUser = Depends(require_role("admin")),
) -> dict:
    """
    Sync de leads desde Kommo. Por defecto incremental (solo cambios
    desde el último sync). Con full=True trae todos.
    """
    return kommo_svc.sync_leads(full=full, limit_total=limit)


@router.post("/sync/lead/{lead_id}/messages")
def sync_messages_endpoint(
    lead_id: int,
    _: CurrentUser = Depends(require_role("admin")),
) -> dict:
    """Trae mensajes de un lead específico (por si quieres re-procesar uno)."""
    return kommo_svc.sync_messages_de_lead(lead_id)


@router.post("/sync/completo")
def sync_completo_endpoint(
    full: bool = Query(False),
    lead_limit: int = Query(200, ge=1, le=5000),
    msg_limit: int = Query(50, ge=1, le=500),
    _: CurrentUser = Depends(require_role("admin")),
) -> dict:
    """
    Pasada completa: asesoras + leads + mensajes.
    El cron de revenue_scheduler llama esto cada 15 min.
    """
    return kommo_svc.sync_completo(full=full, lead_limit=lead_limit, msg_limit_por_lead=msg_limit)


# ── Debug / introspección de Kommo (admin only) ──────────────────────────────
@router.get("/debug/pipelines")
def debug_pipelines(_: CurrentUser = Depends(require_role("admin"))) -> dict:
    """Lista pipelines + stages de Kommo. Útil para mapear el catálogo."""
    import sys
    from pathlib import Path
    _SRC = Path(__file__).resolve().parent.parent.parent / "src"
    if str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))
    import kommo_client as kc
    try:
        return {"pipelines": kc.listar_pipelines()}
    except Exception as e:
        raise HTTPException(503, f"Error: {str(e)[:200]}")


@router.get("/debug/lead/{lead_id}")
def debug_lead(lead_id: int, _: CurrentUser = Depends(require_role("admin"))) -> dict:
    """Detalle crudo de un lead de Kommo. Para inspeccionar campos."""
    import sys
    from pathlib import Path
    _SRC = Path(__file__).resolve().parent.parent.parent / "src"
    if str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))
    import kommo_client as kc
    try:
        return {"lead": kc.obtener_lead(lead_id)}
    except Exception as e:
        raise HTTPException(503, f"Error: {str(e)[:200]}")


@router.get("/debug/lead/{lead_id}/notes")
def debug_lead_notes(
    lead_id: int,
    _: CurrentUser = Depends(require_role("admin")),
) -> dict:
    """
    Todas las notes de un lead, SIN filtro de note_type, para descubrir
    qué tipos usa esta cuenta de Kommo para los mensajes de WhatsApp.
    """
    import sys
    from pathlib import Path
    _SRC = Path(__file__).resolve().parent.parent.parent / "src"
    if str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))
    import kommo_client as kc
    try:
        notes = list(kc.listar_notes_de_lead(lead_id))
        # Cuenta por note_type para ver la distribución
        from collections import Counter
        types = Counter(str(n.get("note_type")) for n in notes)
        return {
            "lead_id":          lead_id,
            "total_notes":      len(notes),
            "tipos_distintos":  dict(types),
            "muestras":         notes[:5],   # primeros 5 con su payload completo
        }
    except Exception as e:
        raise HTTPException(503, f"Error: {str(e)[:200]}")


@router.get("/debug/explorar-chats")
def debug_explorar_chats(_: CurrentUser = Depends(require_role("admin"))) -> dict:
    """
    Explora varios endpoints de Kommo para encontrar dónde están los
    mensajes de WhatsApp en esta cuenta.
    """
    import os, requests, urllib.parse
    subdomain = os.environ.get("KOMMO_SUBDOMAIN", "")
    token = os.environ.get("KOMMO_API_TOKEN", "")
    if not subdomain or not token:
        return {"error": "creds no configuradas"}

    base = f"https://{subdomain}.kommo.com/api/v4"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    # Sacar primer lead_id que tengamos
    from backend.services import revenue_db as db
    sb = db._sb()
    lead_id = None
    if sb:
        r = sb.table("kommo_leads").select("lead_id").order("created_at", desc=True).limit(1).execute()
        if r.data:
            lead_id = r.data[0]["lead_id"]

    paths = [
        # Talks (sabemos que funciona)
        "talks?limit=3",
        # Detalle de un talk específico — tomar el primero
        "_TALK_DETAIL_",
        "_TALK_WITH_MESSAGES_",
        # Filtro talks correcto
        f"talks?filter[entity_type]=lead&filter[entity_id]={lead_id}" if lead_id else None,
        # Messages global
        "messages?limit=5",
        # Customer-facing: contacts → contact tiene chats
        "contacts?limit=2&with=chats",
        # Account info para ver amojo_id
        "account?with=amojo_id",
    ]

    # Primer talk_id que aparezca (para usar en _TALK_DETAIL_ etc.)
    primer_talk_id = None
    try:
        r0 = requests.get(f"{base}/talks?limit=1", headers=headers, timeout=15)
        if r0.ok:
            talks = ((r0.json().get("_embedded") or {}).get("talks") or [])
            if talks:
                primer_talk_id = talks[0].get("talk_id")
    except Exception:
        pass

    resolved_paths = []
    for p in paths:
        if not p:
            continue
        if p == "_TALK_DETAIL_" and primer_talk_id:
            resolved_paths.append(f"talks/{primer_talk_id}")
        elif p == "_TALK_WITH_MESSAGES_" and primer_talk_id:
            resolved_paths.append(f"talks/{primer_talk_id}?with=messages")
        elif p.startswith("_"):
            continue
        else:
            resolved_paths.append(p)

    resultados = []
    for p in resolved_paths:
        url = f"{base}/{p}"
        try:
            r = requests.get(url, headers=headers, timeout=15)
            body = r.text[:600] if r.status_code == 200 else r.text[:300]
            top_keys = []
            try:
                j = r.json()
                if isinstance(j, dict):
                    top_keys = list(j.keys())
                    if "_embedded" in j:
                        emb = j["_embedded"]
                        emb_keys = list(emb.keys()) if isinstance(emb, dict) else []
                        top_keys = top_keys + [f"_embedded.{k}" for k in emb_keys]
            except Exception:
                pass
            resultados.append({"path": p, "status": r.status_code, "top": top_keys, "body": body})
        except Exception as e:
            resultados.append({"path": p, "error": str(e)[:120]})

    return {"lead_id_usado": lead_id, "primer_talk_id": primer_talk_id, "resultados": resultados}
def debug_lead_con_chat(_: CurrentUser = Depends(require_role("admin"))) -> dict:
    """
    Busca el primer lead con MUCHAS notes (probablemente chat largo de
    WhatsApp) entre los recién sincronizados. Devuelve su id y conteos
    por note_type para que sepamos qué filtrar.
    """
    from backend.services import revenue_db as db
    sb = db._sb()
    if sb is None:
        raise HTTPException(503, "Supabase no configurado")
    r = sb.table("kommo_leads").select("lead_id").order("synced_at", desc=True).limit(50).execute()
    lead_ids = [row["lead_id"] for row in (r.data or [])]

    import sys
    from pathlib import Path
    _SRC = Path(__file__).resolve().parent.parent.parent / "src"
    if str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))
    import kommo_client as kc
    from collections import Counter

    mejor = None
    for lid in lead_ids:
        notes = list(kc.listar_notes_de_lead(lid))
        if len(notes) > (mejor["total"] if mejor else 0):
            mejor = {
                "lead_id":  lid,
                "total":    len(notes),
                "tipos":    dict(Counter(str(n.get("note_type")) for n in notes)),
                "muestras": notes[:3],
            }
            if len(notes) >= 10:  # encontramos uno bueno, parar
                break
    return mejor or {"error": "ningún lead reciente tiene notes"}
