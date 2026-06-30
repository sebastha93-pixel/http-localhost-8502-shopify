"""
backend.api.cod_acciones — Workflow obligatorio antes de autorizar despacho COD.

Flujo:
1. Asesor toca botón Llamar o WhatsApp → POST /contacto (auto-tracked)
2. Asesor marca la respuesta del cliente:
   - "aprobacion" → habilita Autorizar Despacho
   - "no_contesta" → registra que el cliente no contestó (no autoriza)
3. Cada cambio queda con timestamp + usuario para auditoría.

Tabla en Supabase:
    CREATE TABLE IF NOT EXISTS cod_acciones (
        orden_melonn      TEXT PRIMARY KEY,
        orden_tienda      TEXT,
        contacto_via      TEXT,                       -- 'llamada' | 'mensaje'
        contacto_at       TIMESTAMPTZ,
        contacto_por      TEXT,                       -- email del usuario
        respuesta         TEXT,                       -- 'aprobacion' | 'no_contesta'
        respuesta_at      TIMESTAMPTZ,
        respuesta_por     TEXT,
        created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.core.security import CurrentUser, require_role, require_permission
from backend.services import revenue_db as db

router = APIRouter(prefix="/api/cod-acciones", tags=["cod-acciones"])


class ContactoIn(BaseModel):
    via: str  # 'llamada' | 'mensaje'


class RespuestaIn(BaseModel):
    valor: str  # 'aprobacion' | 'no_contesta'


VALID_CONTACTO = {"llamada", "mensaje"}
VALID_RESPUESTA = {"aprobacion", "no_contesta", "rechazo"}


def _resolver_otro_id(orden: str) -> str | None:
    """Dado un identificador (orden_tienda O orden_melonn), busca el OTRO
    en el caché de Melonn para guardar ambos en cod_acciones. Esto permite
    que el gate de autorizar-despacho funcione sin importar cuál se pase.
    """
    if not orden:
        return None
    try:
        import sys as _sys
        from pathlib import Path as _Path
        _SRC = _Path(__file__).resolve().parent.parent.parent / "src"
        if str(_SRC) not in _sys.path:
            _sys.path.insert(0, str(_SRC))
        import melonn_client as _mc
        cache = _mc._cache_leer(ignorar_ttl=True)
        if not cache:
            return None
        pedidos = cache[0]
        for p in pedidos:
            ot = str(p.get("orden_tienda") or "")
            om = str(p.get("orden_melonn") or "")
            if ot == orden:
                return om or None
            if om == orden:
                return ot or None
    except Exception:
        pass
    return None


@router.get("/{orden_melonn}")
def get_accion(
    orden_melonn: str,
    _: CurrentUser = Depends(require_permission("operaciones", "ver")),
) -> dict:
    """Devuelve el estado actual de acciones para un pedido."""
    sb = db._sb()
    if sb is None:
        raise HTTPException(503, "supabase_no_configurado")
    try:
        r = (sb.table("cod_acciones")
               .select("*")
               .eq("orden_melonn", orden_melonn)
               .limit(1)
               .execute())
        if not r.data:
            return {"ok": True, "orden_melonn": orden_melonn, "existe": False}
        return {"ok": True, "existe": True, **r.data[0]}
    except Exception as e:
        # Si la tabla no existe, devolver shape válido para que el front muestre estado vacío.
        err = str(e)
        if "does not exist" in err or "42P01" in err:
            return {
                "ok": False,
                "error": "tabla_no_existe",
                "hint": "Crear tabla cod_acciones en Supabase (ver docstring del módulo).",
            }
        raise HTTPException(500, f"query: {err[:200]}")


@router.post("/{orden_melonn}/contacto")
def registrar_contacto(
    orden_melonn: str,
    body: ContactoIn,
    user: CurrentUser = Depends(require_permission("operaciones", "modificar")),
) -> dict:
    """Registra que un asesor contactó al cliente vía llamada o mensaje."""
    if body.via not in VALID_CONTACTO:
        raise HTTPException(400, f"via_invalida: debe ser uno de {VALID_CONTACTO}")
    sb = db._sb()
    if sb is None:
        raise HTTPException(503, "supabase_no_configurado")
    now_iso = datetime.now(tz=timezone.utc).isoformat()
    # Resolver el otro identificador del pedido para guardar AMBOS
    # (el path puede ser orden_melonn o orden_tienda; queremos almacenar
    # los dos para que el gate de autorizar-despacho encuentre la fila).
    orden_tienda_resuelto = _resolver_otro_id(orden_melonn)
    try:
        payload = {
            "orden_melonn": orden_melonn,
            "contacto_via": body.via,
            "contacto_at": now_iso,
            "contacto_por": getattr(user, "email", None) or "",
            "updated_at": now_iso,
        }
        if orden_tienda_resuelto:
            payload["orden_tienda"] = orden_tienda_resuelto
        sb.table("cod_acciones").upsert(payload, on_conflict="orden_melonn").execute()
        return {"ok": True, "contacto_via": body.via, "contacto_at": now_iso}
    except Exception as e:
        raise HTTPException(500, f"upsert: {str(e)[:200]}")


@router.post("/{orden_melonn}/respuesta")
def registrar_respuesta(
    orden_melonn: str,
    body: RespuestaIn,
    user: CurrentUser = Depends(require_permission("operaciones", "modificar")),
) -> dict:
    """Registra la respuesta del cliente al contacto previo.

    'aprobacion' habilita autorizar despacho.
    'no_contesta' bloquea autorizar (cliente no respondió).
    """
    if body.valor not in VALID_RESPUESTA:
        raise HTTPException(400, f"valor_invalido: debe ser uno de {VALID_RESPUESTA}")
    sb = db._sb()
    if sb is None:
        raise HTTPException(503, "supabase_no_configurado")
    now_iso = datetime.now(tz=timezone.utc).isoformat()
    otro_id = _resolver_otro_id(orden_melonn)
    try:
        # Pre-check: debe existir un contacto previo antes de marcar respuesta.
        # Buscar por ambos identificadores conocidos.
        candidatos = [orden_melonn] + ([otro_id] if otro_id else [])
        existing = None
        for cid in candidatos:
            r = (sb.table("cod_acciones")
                   .select("orden_melonn,contacto_at")
                   .or_(f"orden_melonn.eq.{cid},orden_tienda.eq.{cid}")
                   .limit(1)
                   .execute())
            if r.data and (r.data[0] or {}).get("contacto_at"):
                existing = r.data[0]
                break
        if not existing:
            raise HTTPException(409, "contacto_previo_requerido")

        # Usar la PK que existe en DB (orden_melonn de la fila encontrada)
        pk = existing["orden_melonn"]
        payload = {
            "orden_melonn": pk,
            "respuesta": body.valor,
            "respuesta_at": now_iso,
            "respuesta_por": getattr(user, "email", None) or "",
            "updated_at": now_iso,
        }
        if otro_id:
            payload["orden_tienda"] = otro_id
        sb.table("cod_acciones").upsert(payload, on_conflict="orden_melonn").execute()
        return {"ok": True, "respuesta": body.valor, "respuesta_at": now_iso}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"upsert: {str(e)[:200]}")
