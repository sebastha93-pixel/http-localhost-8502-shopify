"""
memoria.py — Capa de persistencia con Supabase
Snapshots históricos · Historia de pedidos · Notas · Acciones
"""

import os
import json
import pandas as pd
from datetime import datetime, timezone
from functools import lru_cache
from typing import Optional

# ── Cliente ────────────────────────────────────────────────────────────────────
@lru_cache(maxsize=1)
def _client():
    try:
        from supabase import create_client
        url = os.environ.get("SUPABASE_URL", "")
        key = os.environ.get("SUPABASE_KEY", "")
        if not url or not key:
            return None
        return create_client(url, key)
    except Exception:
        return None


def disponible() -> bool:
    """True si Supabase está configurado y accesible."""
    return _client() is not None


# ── Snapshots ──────────────────────────────────────────────────────────────────
def guardar_snapshot(df: pd.DataFrame, nombre_csv: str, omitidos: int = 0) -> Optional[int]:
    """
    Guarda un snapshot completo del CSV cargado.
    Retorna el snapshot_id o None si falla.
    """
    sb = _client()
    if sb is None:
        return None
    try:
        from shared import _parse_cod  # importación tardía para evitar circular
        criticos  = int((df["Nivel"] == "CRITICO").sum())
        en_riesgo = int((df["Nivel"] == "RIESGO").sum())
        normales  = int((df["Nivel"] == "NORMAL").sum())
        total     = len(df)

        df_cod_risk = df[(df["COD"] == "SÍ") & (df["Nivel"].isin(["CRITICO","RIESGO"]))]
        valor_cod = float(df_cod_risk["Valor COD"].apply(_parse_cod).sum())

        datos_json = json.loads(
            df[["Orden","Nivel","Score","Días","Zona","COD","Transportadora","Novedad"]]
            .to_json(orient="records", force_ascii=False)
        )

        res = (sb.table("snapshots")
               .insert({
                   "nombre_csv":       nombre_csv,
                   "total":            total,
                   "criticos":         criticos,
                   "en_riesgo":        en_riesgo,
                   "normales":         normales,
                   "valor_cod_riesgo": valor_cod,
                   "datos_json":       datos_json,
               })
               .execute())

        snap_id = res.data[0]["id"]

        # Guardar historia por pedido
        rows = [
            {
                "snapshot_id":   snap_id,
                "orden":         str(r["Orden"]),
                "nivel":         str(r["Nivel"]),
                "score":         float(r.get("Score", 0) or 0),
                "dias":          float(r.get("Días", 0) or 0),
                "novedad":       str(r.get("Novedad", "")),
            }
            for _, r in df.iterrows()
        ]
        # Insertar en lotes de 500
        for i in range(0, len(rows), 500):
            sb.table("pedido_historia").insert(rows[i:i+500]).execute()

        return snap_id

    except Exception as e:
        print(f"[memoria] Error guardar_snapshot: {e}")
        return None


def cargar_snapshots(limite: int = 30) -> pd.DataFrame:
    """Retorna los últimos N snapshots como DataFrame."""
    sb = _client()
    if sb is None:
        return pd.DataFrame()
    try:
        res = (sb.table("snapshots")
               .select("id,cargado_en,nombre_csv,total,criticos,en_riesgo,normales,valor_cod_riesgo")
               .order("cargado_en", desc=True)
               .limit(limite)
               .execute())
        df = pd.DataFrame(res.data)
        if not df.empty:
            df["cargado_en"] = pd.to_datetime(df["cargado_en"])
        return df
    except Exception as e:
        print(f"[memoria] Error cargar_snapshots: {e}")
        return pd.DataFrame()


# ── Historia de un pedido ──────────────────────────────────────────────────────
def historial_pedido(orden: str) -> pd.DataFrame:
    """Retorna todos los registros históricos de una orden específica."""
    sb = _client()
    if sb is None:
        return pd.DataFrame()
    try:
        res = (sb.table("pedido_historia")
               .select("nivel,score,dias,novedad,registrado_en,snapshots(nombre_csv,cargado_en)")
               .eq("orden", orden)
               .order("registrado_en", desc=False)
               .execute())
        rows = []
        for r in res.data:
            snap = r.get("snapshots") or {}
            rows.append({
                "Fecha":     snap.get("cargado_en", r["registrado_en"]),
                "CSV":       snap.get("nombre_csv", "—"),
                "Nivel":     r["nivel"],
                "Score":     r["score"],
                "Días":      r["dias"],
                "Novedad":   r["novedad"],
            })
        df = pd.DataFrame(rows)
        if not df.empty:
            df["Fecha"] = pd.to_datetime(df["Fecha"])
        return df
    except Exception as e:
        print(f"[memoria] Error historial_pedido: {e}")
        return pd.DataFrame()


# ── Notas ──────────────────────────────────────────────────────────────────────
def cargar_notas(orden: str) -> pd.DataFrame:
    sb = _client()
    if sb is None:
        return pd.DataFrame()
    try:
        res = (sb.table("notas")
               .select("autor,nota,creada_en")
               .eq("orden", orden)
               .order("creada_en", desc=False)
               .execute())
        df = pd.DataFrame(res.data)
        if not df.empty:
            df["creada_en"] = pd.to_datetime(df["creada_en"])
        return df
    except Exception as e:
        print(f"[memoria] Error cargar_notas: {e}")
        return pd.DataFrame()


def agregar_nota(orden: str, autor: str, nota: str) -> tuple[bool, str]:
    """Retorna (True, '') en éxito o (False, mensaje_error)."""
    sb = _client()
    if sb is None:
        return False, "Supabase no está conectado"
    try:
        sb.table("notas").insert({
            "orden": orden,
            "autor": autor.strip() or "Equipo",
            "nota":  nota.strip(),
        }).execute()
        return True, ""
    except Exception as e:
        print(f"[memoria] Error agregar_nota: {e}")
        return False, str(e)


# ── Acciones ───────────────────────────────────────────────────────────────────
TIPOS_ACCION = ["llamada", "escalado", "visita", "acuerdo_cliente",
                "gestion_transportadora", "resuelto", "devolucion", "otro"]

def cargar_acciones(orden: str) -> pd.DataFrame:
    sb = _client()
    if sb is None:
        return pd.DataFrame()
    try:
        res = (sb.table("acciones")
               .select("tipo,descripcion,autor,creada_en")
               .eq("orden", orden)
               .order("creada_en", desc=False)
               .execute())
        df = pd.DataFrame(res.data)
        if not df.empty:
            df["creada_en"] = pd.to_datetime(df["creada_en"])
        return df
    except Exception as e:
        print(f"[memoria] Error cargar_acciones: {e}")
        return pd.DataFrame()


def agregar_accion(orden: str, tipo: str, descripcion: str, autor: str) -> tuple[bool, str]:
    """Retorna (True, '') en éxito o (False, mensaje_error)."""
    sb = _client()
    if sb is None:
        return False, "Supabase no está conectado"
    try:
        sb.table("acciones").insert({
            "orden":       orden,
            "tipo":        tipo,
            "descripcion": descripcion.strip(),
            "autor":       autor.strip() or "Equipo",
        }).execute()
        return True, ""
    except Exception as e:
        print(f"[memoria] Error agregar_accion: {e}")
        return False, str(e)
