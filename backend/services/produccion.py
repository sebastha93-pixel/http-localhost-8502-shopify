"""
backend.services.produccion — Lógica de negocio del módulo Producción.

Patrón: espeja backend/services/clientes.py y revenue_db.
Toda persistencia va contra Supabase.
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timezone
from typing import Any, Optional

from supabase import Client, create_client

log = logging.getLogger(__name__)

_client: Optional[Client] = None


def _sb() -> Optional[Client]:
    global _client
    if _client is not None:
        return _client
    url = (os.environ.get("SUPABASE_URL") or "").strip()
    key = (os.environ.get("SUPABASE_KEY") or "").strip()
    if not url or not key:
        return None
    try:
        _client = create_client(url, key)
        return _client
    except Exception as e:
        log.warning(f"[produccion] Supabase client failed: {e}")
        return None


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


# ═══════════════════════════════════════════════════════════════════════
# Consecutivos (ING-2026-0001, ROLLO-2026-000001, OC-2026-0001, ...)
# ═══════════════════════════════════════════════════════════════════════

def next_consecutivo(prefijo: str, anio: Optional[int] = None, width: int = 4) -> str:
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase no configurado")
    anio = anio or datetime.now(tz=timezone.utc).year
    r = (sb.table("produccion_consecutivos")
           .select("ultimo")
           .eq("prefijo", prefijo)
           .eq("anio", anio)
           .limit(1)
           .execute())
    ultimo = ((r.data or [None])[0] or {}).get("ultimo") or 0
    nuevo = ultimo + 1
    sb.table("produccion_consecutivos").upsert(
        {"prefijo": prefijo, "anio": anio, "ultimo": nuevo, "updated_at": _now_iso()},
        on_conflict="prefijo,anio",
    ).execute()
    return f"{prefijo}-{anio}-{str(nuevo).zfill(width)}"


# ═══════════════════════════════════════════════════════════════════════
# Health
# ═══════════════════════════════════════════════════════════════════════

TABLAS_ESPERADAS = [
    "ordenes_ingreso", "rollos_tela", "movimientos_inventario",
    "referencias_precosteo", "precosteo_items",
    "ordenes_corte", "orden_corte_rollos",
    "confeccionistas", "remisiones", "remision_items",
    "insumos", "remisiones_insumos", "remision_insumo_items",
]


def health_check() -> dict:
    sb = _sb()
    if sb is None:
        return {"ok": False, "error": "supabase_no_configurado"}
    tablas_ok: list[str] = []
    tablas_faltantes: list[str] = []
    for t in TABLAS_ESPERADAS:
        try:
            sb.table(t).select("id").limit(0).execute()
            tablas_ok.append(t)
        except Exception as e:
            err = str(e)
            if "does not exist" in err or "42P01" in err:
                tablas_faltantes.append(t)
            else:
                tablas_faltantes.append(f"{t}({err[:60]})")
    return {
        "ok": not tablas_faltantes,
        "tablas_encontradas": len(tablas_ok),
        "tablas_esperadas": len(TABLAS_ESPERADAS),
        "tablas_faltantes": tablas_faltantes,
        "hint": "Corre SUPABASE_PRODUCCION.sql en Supabase SQL Editor." if tablas_faltantes else None,
    }


# ═══════════════════════════════════════════════════════════════════════
# INGRESO + INVENTARIO
# ═══════════════════════════════════════════════════════════════════════

def crear_ingreso(*, textilera: str, nit_textilera: Optional[str], numero_documento: str,
                  tipo_documento: str, fecha: str, orden_compra: Optional[str],
                  observaciones: Optional[str], rollos: list[dict],
                  created_by: str) -> dict:
    """Crea una orden de ingreso con N rollos en una sola transacción lógica.

    Cada rollo genera su codigo_interno/barcode + registra movimiento +metros.
    Retorna la orden completa con sus rollos hidratados.
    """
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase no configurado")
    if not rollos:
        raise ValueError("Debes agregar al menos 1 rollo")

    numero_ingreso = next_consecutivo("ING", width=4)
    total_metros = round(sum(float(r.get("metros_inicial") or 0) for r in rollos), 2)

    # 1. Cabecera
    ingreso_row = {
        "numero_ingreso": numero_ingreso,
        "textilera": textilera.strip(),
        "nit_textilera": (nit_textilera or "").strip() or None,
        "numero_documento": numero_documento.strip(),
        "tipo_documento": tipo_documento,
        "fecha": fecha,
        "orden_compra": (orden_compra or "").strip() or None,
        "total_rollos": len(rollos),
        "total_metros": total_metros,
        "estado": "recibida_completa",
        "observaciones": (observaciones or "").strip() or None,
        "created_by": created_by,
    }
    ing_res = sb.table("ordenes_ingreso").insert(ingreso_row).execute()
    if not ing_res.data:
        raise RuntimeError("No se pudo crear la orden de ingreso")
    ingreso = ing_res.data[0]
    ingreso_id = ingreso["id"]

    # 2. Rollos + movimientos
    rollos_creados: list[dict] = []
    for r in rollos:
        try:
            metros_inicial = float(r.get("metros_inicial") or 0)
        except Exception:
            metros_inicial = 0
        if metros_inicial <= 0:
            continue

        codigo = next_consecutivo("ROLLO", width=6)
        rollo_row = {
            "codigo_interno": codigo,
            "barcode": codigo,  # mismo valor, se lee con Code128
            "orden_ingreso_id": ingreso_id,
            "numero_rollo": (r.get("numero_rollo") or "").strip() or None,
            "serial": (r.get("serial") or "").strip() or None,
            "lote_fabrica": (r.get("lote_fabrica") or "").strip() or None,
            "tono": (r.get("tono") or "").strip() or None,
            "referencia_tela": (r.get("referencia_tela") or "").strip() or None,
            "descripcion_tela": (r.get("descripcion_tela") or "").strip(),
            "ancho": r.get("ancho") or None,
            "costo_metro": r.get("costo_metro") or None,
            "metros_inicial": metros_inicial,
            "metros_disponible": metros_inicial,
            "fecha_ingreso": fecha,
            "estado": "disponible",
        }
        if not rollo_row["descripcion_tela"]:
            continue  # skip rollos sin descripción

        r_res = sb.table("rollos_tela").insert(rollo_row).execute()
        if not r_res.data:
            continue
        rollo = r_res.data[0]
        rollos_creados.append(rollo)

        # Movimiento +metros por ingreso
        sb.table("movimientos_inventario").insert({
            "rollo_id": rollo["id"],
            "tipo": "ingreso",
            "metros": metros_inicial,
            "doc_ref": numero_ingreso,
            "usuario": created_by,
            "nota": f"Ingreso desde {textilera}",
        }).execute()

    return {"ingreso": ingreso, "rollos": rollos_creados}


def listar_ingresos(*, limit: int = 100, textilera: Optional[str] = None,
                    estado: Optional[str] = None) -> list[dict]:
    sb = _sb()
    if sb is None:
        return []
    q = sb.table("ordenes_ingreso").select("*").order("fecha", desc=True).limit(limit)
    if textilera:
        q = q.eq("textilera", textilera)
    if estado:
        q = q.eq("estado", estado)
    return (q.execute().data or [])


def obtener_ingreso(ingreso_id: str) -> Optional[dict]:
    sb = _sb()
    if sb is None:
        return None
    ing = (sb.table("ordenes_ingreso").select("*").eq("id", ingreso_id).limit(1).execute()).data
    if not ing:
        return None
    rollos = (sb.table("rollos_tela").select("*")
                .eq("orden_ingreso_id", ingreso_id)
                .order("codigo_interno").execute()).data or []
    return {**ing[0], "rollos": rollos}


def listar_rollos(*, tela: Optional[str] = None, estado: Optional[str] = None,
                  tono: Optional[str] = None, limit: int = 500) -> list[dict]:
    sb = _sb()
    if sb is None:
        return []
    q = sb.table("rollos_tela").select("*").order("codigo_interno", desc=True).limit(limit)
    if tela:
        q = q.ilike("descripcion_tela", f"%{tela}%")
    if estado:
        q = q.eq("estado", estado)
    if tono:
        q = q.eq("tono", tono)
    return (q.execute().data or [])


def obtener_rollo(rollo_id: str) -> Optional[dict]:
    sb = _sb()
    if sb is None:
        return None
    r = (sb.table("rollos_tela").select("*").eq("id", rollo_id).limit(1).execute()).data
    return r[0] if r else None


def obtener_rollo_por_barcode(barcode: str) -> Optional[dict]:
    sb = _sb()
    if sb is None:
        return None
    r = (sb.table("rollos_tela").select("*").eq("barcode", barcode).limit(1).execute()).data
    return r[0] if r else None


def inventario_resumen() -> list[dict]:
    """Agrupa por descripcion_tela + tono con conteo rollos y metros.

    Retorna: [
      { descripcion_tela, tono, num_rollos, metros_disponible, metros_inicial, valor_estimado }
    ]
    """
    sb = _sb()
    if sb is None:
        return []
    # Traer todos los rollos disponibles y agrupar en Python.
    # Simple pero eficiente hasta ~10k rollos; después migramos a SQL agg.
    rollos = (sb.table("rollos_tela")
                .select("descripcion_tela,tono,metros_inicial,metros_disponible,costo_metro,estado")
                .neq("estado", "agotado")
                .limit(20000)
                .execute()).data or []

    agrupado: dict[tuple[str, str], dict] = {}
    for r in rollos:
        desc = (r.get("descripcion_tela") or "SIN DESCRIPCIÓN").strip().upper()
        tono = (r.get("tono") or "").strip() or "—"
        key = (desc, tono)
        row = agrupado.setdefault(key, {
            "descripcion_tela": desc,
            "tono": tono,
            "num_rollos": 0,
            "metros_disponible": 0.0,
            "metros_inicial": 0.0,
            "valor_estimado": 0.0,
        })
        row["num_rollos"] += 1
        md = float(r.get("metros_disponible") or 0)
        mi = float(r.get("metros_inicial") or 0)
        cm = float(r.get("costo_metro") or 0)
        row["metros_disponible"] += md
        row["metros_inicial"] += mi
        row["valor_estimado"] += md * cm

    # Ordenar por descripcion + tono
    out = list(agrupado.values())
    for row in out:
        row["metros_disponible"] = round(row["metros_disponible"], 2)
        row["metros_inicial"] = round(row["metros_inicial"], 2)
        row["valor_estimado"] = round(row["valor_estimado"], 0)
    out.sort(key=lambda x: (x["descripcion_tela"], x["tono"]))
    return out


def ajustar_stock(*, rollo_id: str, metros_delta: float, nota: str,
                  usuario: str) -> dict:
    """Ajuste manual de stock de un rollo (admin). Registra movimiento."""
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase no configurado")
    rollo = obtener_rollo(rollo_id)
    if not rollo:
        raise ValueError("Rollo no encontrado")
    nuevo = round(float(rollo["metros_disponible"]) + float(metros_delta), 2)
    if nuevo < 0:
        raise ValueError(f"Metros negativos ({nuevo}). Actual: {rollo['metros_disponible']}, delta: {metros_delta}")
    estado_nuevo = "agotado" if nuevo <= 0 else ("disponible" if rollo.get("estado") in ("agotado",) else rollo.get("estado"))
    sb.table("rollos_tela").update({
        "metros_disponible": nuevo,
        "estado": estado_nuevo,
        "updated_at": _now_iso(),
    }).eq("id", rollo_id).execute()
    sb.table("movimientos_inventario").insert({
        "rollo_id": rollo_id,
        "tipo": "ajuste",
        "metros": float(metros_delta),
        "doc_ref": "ajuste_manual",
        "usuario": usuario,
        "nota": nota or None,
    }).execute()
    return {"ok": True, "metros_disponible": nuevo, "estado": estado_nuevo}
