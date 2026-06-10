"""
backend.api.pedidos — Acciones, notas e historial por pedido (Supabase).
Reusa src/memoria.py, mismo schema que Streamlit.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.core.security import CurrentUser, get_current_user, require_role

_SRC = Path(__file__).resolve().parent.parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import memoria  # noqa: E402

from backend.services import overrides as overrides_svc

router = APIRouter(prefix="/api/pedidos", tags=["pedidos"])


# ── Tipos de acción permitidos (alineados con memoria.TIPOS_ACCION) ──
TIPOS_ACCION = [
    "llamada", "whatsapp", "despacho_autorizado", "acuerdo_cliente",
    "gestion_transportadora", "escalado", "visita", "resuelto",
    "devolucion", "nota", "otro",
]


# ── Modelos ───────────────────────────────────────────────────────────

class Accion(BaseModel):
    tipo: str
    descripcion: str
    autor: str
    creada_en: Optional[str] = None


class NuevaAccion(BaseModel):
    tipo: str = Field(..., description="Uno de TIPOS_ACCION")
    descripcion: str = Field(default="")


class Nota(BaseModel):
    autor: str
    nota: str
    creada_en: Optional[str] = None


class NuevaNota(BaseModel):
    nota: str = Field(..., min_length=1)


class HistorialItem(BaseModel):
    fecha: Optional[str] = None
    csv: Optional[str] = None
    nivel: Optional[str] = None
    score: Optional[int] = None
    dias: Optional[int] = None
    novedad: Optional[str] = None


# ── Helpers ───────────────────────────────────────────────────────────

def _df_to_records(df) -> list[dict]:
    """Convierte DataFrame de pandas a list[dict] con datetimes ISO UTC (Z)."""
    from datetime import timezone
    if df is None or df.empty:
        return []
    out = []
    for _, r in df.iterrows():
        d = {}
        for k, v in r.items():
            if hasattr(v, "isoformat"):
                # Asegurar UTC con sufijo Z
                try:
                    if v.tzinfo is None:
                        v = v.tz_localize("UTC") if hasattr(v, "tz_localize") else v.replace(tzinfo=timezone.utc)
                    iso = v.isoformat() if not hasattr(v, "tz_convert") else v.tz_convert("UTC").isoformat()
                except Exception:
                    iso = v.isoformat()
                d[k] = iso.replace("+00:00", "Z") if "+00:00" in iso else (iso if iso.endswith("Z") else iso + "Z")
            else:
                d[k] = v
        out.append(d)
    return out


# ── Acciones ──────────────────────────────────────────────────────────

@router.get("/{orden}/acciones", response_model=list[Accion])
def get_acciones(orden: str, _: CurrentUser = Depends(get_current_user)) -> list[Accion]:
    df = memoria.cargar_acciones(orden)
    return [Accion(**r) for r in _df_to_records(df)]


@router.post("/{orden}/acciones", response_model=Accion)
def post_accion(
    orden: str,
    body: NuevaAccion,
    user: CurrentUser = Depends(require_role("admin", "operador")),
) -> Accion:
    if body.tipo not in TIPOS_ACCION:
        raise HTTPException(status_code=400, detail=f"Tipo inválido. Permitidos: {TIPOS_ACCION}")
    ok, err = memoria.agregar_accion(orden, body.tipo, body.descripcion, user.nombre)
    if not ok:
        raise HTTPException(status_code=500, detail=err or "Error al guardar acción")
    return Accion(
        tipo=body.tipo,
        descripcion=body.descripcion,
        autor=user.nombre,
        creada_en=datetime.utcnow().isoformat() + "Z",
    )


# ── Notas ─────────────────────────────────────────────────────────────

@router.get("/{orden}/notas", response_model=list[Nota])
def get_notas(orden: str, _: CurrentUser = Depends(get_current_user)) -> list[Nota]:
    df = memoria.cargar_notas(orden)
    return [Nota(**r) for r in _df_to_records(df)]


@router.post("/{orden}/notas", response_model=Nota)
def post_nota(
    orden: str,
    body: NuevaNota,
    user: CurrentUser = Depends(require_role("admin", "operador")),
) -> Nota:
    ok, err = memoria.agregar_nota(orden, user.nombre, body.nota)
    if not ok:
        raise HTTPException(status_code=500, detail=err or "Error al guardar nota")
    return Nota(
        autor=user.nombre,
        nota=body.nota,
        creada_en=datetime.utcnow().isoformat() + "Z",
    )


# ── Historial de estados (snapshots) ──────────────────────────────────

# ── Overrides manuales de cliente ────────────────────────────────────

class Override(BaseModel):
    orden: str
    nombre_comprador: Optional[str] = None
    telefono_comprador: Optional[str] = None
    ciudad_destino: Optional[str] = None
    autor: Optional[str] = None
    actualizado_en: Optional[str] = None


class NuevoOverride(BaseModel):
    nombre: str = ""
    telefono: str = ""
    ciudad: str = ""


@router.get("/{orden}/override", response_model=Optional[Override])
def get_override(orden: str, _: CurrentUser = Depends(get_current_user)) -> Optional[Override]:
    o = overrides_svc.obtener(orden)
    return Override(**o) if o else None


@router.post("/{orden}/override", response_model=Override)
def post_override(
    orden: str,
    body: NuevoOverride,
    user: CurrentUser = Depends(require_role("admin", "operador")),
) -> Override:
    try:
        o = overrides_svc.upsert(
            orden,
            nombre=body.nombre,
            telefono=body.telefono,
            ciudad=body.ciudad,
            autor=user.nombre,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return Override(**o)


# ── Historial de estados (snapshots) ──────────────────────────────────

@router.get("/{orden}/historial", response_model=list[HistorialItem])
def get_historial(orden: str, _: CurrentUser = Depends(get_current_user)) -> list[HistorialItem]:
    df = memoria.historial_pedido(orden)
    return [
        HistorialItem(
            fecha=r.get("Fecha"),
            csv=r.get("CSV"),
            nivel=r.get("Nivel"),
            score=r.get("Score"),
            dias=r.get("Días"),
            novedad=r.get("Novedad"),
        )
        for r in _df_to_records(df)
    ]
