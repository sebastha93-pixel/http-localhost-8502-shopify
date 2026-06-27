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

from backend.core.security import CurrentUser, require_role
from backend.services import revenue_db as db

router = APIRouter(prefix="/api/cod-acciones", tags=["cod-acciones"])


class ContactoIn(BaseModel):
    via: str  # 'llamada' | 'mensaje'


class RespuestaIn(BaseModel):
    valor: str  # 'aprobacion' | 'no_contesta'


VALID_CONTACTO = {"llamada", "mensaje"}
VALID_RESPUESTA = {"aprobacion", "no_contesta"}


@router.get("/{orden_melonn}")
def get_accion(
    orden_melonn: str,
    _: CurrentUser = Depends(require_role("admin", "operador")),
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
    user: CurrentUser = Depends(require_role("admin", "operador")),
) -> dict:
    """Registra que un asesor contactó al cliente vía llamada o mensaje."""
    if body.via not in VALID_CONTACTO:
        raise HTTPException(400, f"via_invalida: debe ser uno de {VALID_CONTACTO}")
    sb = db._sb()
    if sb is None:
        raise HTTPException(503, "supabase_no_configurado")
    now_iso = datetime.now(tz=timezone.utc).isoformat()
    try:
        sb.table("cod_acciones").upsert({
            "orden_melonn": orden_melonn,
            "contacto_via": body.via,
            "contacto_at": now_iso,
            "contacto_por": getattr(user, "email", None) or "",
            "updated_at": now_iso,
        }, on_conflict="orden_melonn").execute()
        return {"ok": True, "contacto_via": body.via, "contacto_at": now_iso}
    except Exception as e:
        raise HTTPException(500, f"upsert: {str(e)[:200]}")


@router.post("/{orden_melonn}/respuesta")
def registrar_respuesta(
    orden_melonn: str,
    body: RespuestaIn,
    user: CurrentUser = Depends(require_role("admin", "operador")),
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
    try:
        # Pre-check: debe existir un contacto previo antes de poder marcar respuesta
        r = (sb.table("cod_acciones")
               .select("contacto_at")
               .eq("orden_melonn", orden_melonn)
               .limit(1)
               .execute())
        if not r.data or not (r.data[0] or {}).get("contacto_at"):
            raise HTTPException(409, "contacto_previo_requerido")

        sb.table("cod_acciones").upsert({
            "orden_melonn": orden_melonn,
            "respuesta": body.valor,
            "respuesta_at": now_iso,
            "respuesta_por": getattr(user, "email", None) or "",
            "updated_at": now_iso,
        }, on_conflict="orden_melonn").execute()
        return {"ok": True, "respuesta": body.valor, "respuesta_at": now_iso}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"upsert: {str(e)[:200]}")
