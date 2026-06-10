"""
backend.services.overrides — Datos manuales de cliente que sobre-escriben
o complementan los provenientes de Shopify para pedidos sin enriquecer.

Schema (Supabase):
    create table pedido_overrides (
      orden text primary key,
      nombre_comprador text,
      telefono_comprador text,
      ciudad_destino text,
      autor text not null,
      creado_en timestamptz default now(),
      actualizado_en timestamptz default now()
    );
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

from supabase import create_client, Client


_client: Optional[Client] = None


def _sb() -> Optional[Client]:
    global _client
    if _client is not None:
        return _client
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_KEY", "").strip()
    if not url or not key:
        return None
    try:
        _client = create_client(url, key)
        return _client
    except Exception as e:
        print(f"[overrides] Error creando cliente Supabase: {e}")
        return None


def cargar_map() -> dict[str, dict]:
    """Retorna {orden: {nombre, telefono, ciudad, novedad_manual, autor, actualizado_en}}."""
    sb = _sb()
    if sb is None:
        return {}
    try:
        # Intentar con la columna novedad_manual; si la columna no existe,
        # fallback al select original.
        try:
            res = (sb.table("pedido_overrides")
                   .select("orden,nombre_comprador,telefono_comprador,ciudad_destino,novedad_manual,motivo_novedad,autor,actualizado_en")
                   .execute())
        except Exception:
            res = (sb.table("pedido_overrides")
                   .select("orden,nombre_comprador,telefono_comprador,ciudad_destino,autor,actualizado_en")
                   .execute())
        return {r["orden"]: r for r in (res.data or [])}
    except Exception as e:
        print(f"[overrides] Error cargar_map: {e}")
        return {}


def obtener(orden: str) -> Optional[dict]:
    sb = _sb()
    if sb is None:
        return None
    try:
        res = (sb.table("pedido_overrides")
               .select("*")
               .eq("orden", orden)
               .limit(1)
               .execute())
        return (res.data or [None])[0]
    except Exception as e:
        print(f"[overrides] Error obtener: {e}")
        return None


def upsert(
    orden: str,
    *,
    nombre: str = "",
    telefono: str = "",
    ciudad: str = "",
    autor: str,
    novedad_manual: Optional[bool] = None,
    motivo_novedad: str = "",
) -> dict:
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase no configurado")
    data: dict = {
        "orden":              orden,
        "nombre_comprador":   nombre.strip() or None,
        "telefono_comprador": telefono.strip() or None,
        "ciudad_destino":     (ciudad or "").upper().strip() or None,
        "autor":              autor,
        "actualizado_en":     datetime.now(timezone.utc).isoformat(),
    }
    if novedad_manual is not None:
        data["novedad_manual"] = novedad_manual
        data["motivo_novedad"] = motivo_novedad.strip() or None
    res = sb.table("pedido_overrides").upsert(data, on_conflict="orden").execute()
    return res.data[0] if res.data else data


def aplicar_a_pedido(p: dict, overrides_map: dict[str, dict]) -> dict:
    """
    Aplica el override que matche por orden_melonn o orden_tienda.
    Devuelve una nueva copia del pedido (no muta el original).
    """
    if not overrides_map:
        return p
    o = (overrides_map.get(p.get("orden_melonn", ""))
         or overrides_map.get(p.get("orden_tienda", "")))
    if not o:
        return p
    p = dict(p)
    if o.get("nombre_comprador"):
        p["nombre_comprador"] = o["nombre_comprador"]
    if o.get("telefono_comprador"):
        p["telefono_comprador"] = o["telefono_comprador"]
    if o.get("ciudad_destino"):
        p["ciudad_destino"] = o["ciudad_destino"]
    if o.get("novedad_manual"):
        p["novedad_manual"] = True
        if o.get("motivo_novedad"):
            p["motivo_novedad_manual"] = o["motivo_novedad"]
    p["_override_autor"]         = o.get("autor")
    p["_override_actualizado_en"] = o.get("actualizado_en")
    return p
