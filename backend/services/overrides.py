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


# PostgREST corta en 1.000 filas por defecto (max-rows). Sin paginar, un
# select("*") sobre esta tabla devolvía 1.000 de 2.875 filas y el 65% de los
# overrides se DESCARTABA EN SILENCIO en cada lectura: guías, transportadoras,
# y también nombre, teléfono, ciudad y novedades manuales. El síntoma visible
# el 2026-07-30 fue "no veo las guías reales" — había 678 guías reales para
# pedidos activos y en pantalla se veían 25.
_PAGINA = 1000
_TOPE_PAGINAS = 100      # 100k filas; si se pasa de ahí, algo más está mal


def cargar_map() -> dict[str, dict]:
    """Retorna {orden: {todos los campos de override}}, TODAS las filas."""
    sb = _sb()
    if sb is None:
        return {}
    out: dict[str, dict] = {}
    desde = 0
    try:
        for _ in range(_TOPE_PAGINAS):
            # Select * para que tolere columnas nuevas sin redeploy.
            # .range() es inclusivo en ambos extremos.
            res = (sb.table("pedido_overrides").select("*")
                     .range(desde, desde + _PAGINA - 1).execute())
            filas = res.data or []
            for r in filas:
                out[r["orden"]] = r
            if len(filas) < _PAGINA:
                return out
            desde += _PAGINA
        print(f"[overrides] cargar_map: corté en {_TOPE_PAGINAS} páginas "
              f"({len(out)} filas) — revisar por qué hay tantas")
        return out
    except Exception as e:
        print(f"[overrides] Error cargar_map: {e}")
        # Devolver lo que se alcanzó a leer es mejor que perderlo todo, pero
        # que quede dicho en el log que va incompleto.
        return out


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
    nombre: Optional[str] = None,
    telefono: Optional[str] = None,
    ciudad: Optional[str] = None,
    autor: str,
    novedad_manual: Optional[bool] = None,
    motivo_novedad: str = "",
    carrier_real: Optional[str] = None,
    guia_real: Optional[str] = None,
) -> dict:
    """Crea/actualiza el override de un pedido.

    OJO — REGLA DE ORO: solo se escriben los campos que el llamador PASA.
    Antes nombre/telefono/ciudad tenían default "" y se mandaban SIEMPRE, así
    que `"".strip() or None` los ponía en NULL: marcar una novedad o guardar
    una guía BORRABA el nombre, el teléfono y la ciudad del pedido. Con el bot
    corriendo en cron eso arrasó con los datos de contacto de cientos de
    pedidos (2026-07-27). Ahora:
      - no pasar el campo  -> no se toca
      - pasar "" (vacío)   -> se borra a propósito (edición manual)
    """
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase no configurado")
    data: dict = {
        "orden":          orden,
        "autor":          autor,
        "actualizado_en": datetime.now(timezone.utc).isoformat(),
    }
    if nombre is not None:
        data["nombre_comprador"] = nombre.strip() or None
    if telefono is not None:
        data["telefono_comprador"] = telefono.strip() or None
    if ciudad is not None:
        data["ciudad_destino"] = ciudad.upper().strip() or None
    if novedad_manual is not None:
        data["novedad_manual"] = novedad_manual
        data["motivo_novedad"] = motivo_novedad.strip() or None
    if carrier_real is not None:
        data["carrier_real"] = carrier_real.strip() or None
    if guia_real is not None:
        data["guia_real"] = guia_real.strip() or None
    res = sb.table("pedido_overrides").upsert(data, on_conflict="orden").execute()
    return res.data[0] if res.data else data


# Un M-id (M1785269442459430) es el número INTERNO de Melonn, no una guía de
# transportadora. El caché lo trae en `guia_real` porque el enriquecedor de
# Shopify lo guardaba como respaldo, y en pantalla quedaba presentado como si
# fuera la guía — peor aún, junto a la transportadora correcta ("EASYWAY
# M1783632128570331"), que invita a rastrearlo en una web donde no existe.
# Medido el 2026-07-30: 661 pedidos activos así.
import re as _re

_RE_MID = _re.compile(r"^[Mm]\d{10,}$")


def es_mid_melonn(v) -> bool:
    return bool(_RE_MID.match(str(v or "").strip()))


def _limpiar_mid(p: dict) -> dict:
    """Borra del pedido lo que NO es una guía real de transportadora.

    Va ANTES de aplicar el override, y a propósito no depende de que exista
    override: si el caché trae basura, un override vacío no podía limpiarla
    (solo se pisaban los campos que el override TENÍA con valor). Así los
    pedidos de mensajería local quedan con su transportadora y sin guía —
    que es la verdad — en vez de mostrar el número interno de Melonn.
    """
    mid = es_mid_melonn(p.get("guia_real"))
    carrier_melonn = str(p.get("carrier_real") or "").strip().lower() == "melonn"
    if not mid and not carrier_melonn:
        return p
    p = dict(p)
    if mid:
        p["guia_real"] = None
    if carrier_melonn:
        # "Melonn" es el operador logístico, no quien lleva el paquete.
        p["carrier_real"] = None
    return p


def aplicar_a_pedido(p: dict, overrides_map: dict[str, dict]) -> dict:
    """
    Aplica el override que matche por orden_melonn o orden_tienda.
    Devuelve una nueva copia del pedido (no muta el original).
    """
    p = _limpiar_mid(p)
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
    if o.get("carrier_real"):
        p["carrier_real"] = o["carrier_real"]
    if o.get("guia_real"):
        p["guia_real"] = o["guia_real"]
    p["_override_autor"]         = o.get("autor")
    p["_override_actualizado_en"] = o.get("actualizado_en")
    return p
