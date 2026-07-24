"""
backend.services.drive_sheet — vuelca los precosteos a una Google Sheet
consultable (una fila por referencia), para que el equipo pueda mirar la info
de los lotes también en Drive.

Config por variables de entorno (Railway):
  · GOOGLE_SERVICE_ACCOUNT_JSON — el JSON completo de una cuenta de servicio
    de Google con la Sheets API habilitada.
  · PRECOSTEO_SHEET_ID — el ID de la Google Sheet (de la URL) compartida como
    EDITOR con el email de la cuenta de servicio.

TODO es tolerante a fallos: si no está configurado, si falta la librería o si
la hoja no se puede abrir, es un no-op silencioso — NUNCA tumba el guardado del
precosteo. Los imports de google van adentro de las funciones a propósito.

Columnas: Referencia · Descripción · Costo sin IVA · Costo con IVA ·
           Precio venta sin IVA · Precio venta con IVA · Margen % · Actualizado
"""
from __future__ import annotations

import json
import logging
import os
import threading
from typing import Optional

log = logging.getLogger(__name__)

ENCABEZADO = [
    "Referencia", "Descripción", "Costo sin IVA", "Costo con IVA",
    "Precio venta sin IVA", "Precio venta con IVA", "Margen %", "Actualizado",
]


def configurado() -> bool:
    return bool(os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
                and os.environ.get("PRECOSTEO_SHEET_ID", "").strip())


def _hoja():
    """Abre la primera pestaña de la Sheet. Devuelve None si no se puede."""
    if not configurado():
        return None
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except Exception as e:
        log.warning(f"[drive] librería gspread/google-auth no disponible: {e}")
        return None
    try:
        info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
        creds = Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/spreadsheets"])
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(os.environ["PRECOSTEO_SHEET_ID"].strip())
        ws = sh.sheet1
        try:
            if not ws.row_values(1):
                ws.update("A1", [ENCABEZADO], value_input_option="USER_ENTERED")
        except Exception:
            pass
        return ws
    except Exception as e:
        log.warning(f"[drive] no se pudo abrir la Sheet: {e}")
        return None


def _fila(p: dict) -> list:
    """Fila de la hoja a partir de un precosteo (dict de referencias_precosteo)."""
    iva = float(p.get("iva_pct") or 19)
    costo_sin = float(p.get("costo_total_sin_iva") or 0)
    costo_con = float(p.get("costo_total_con_iva") or 0)
    pvp = float(p.get("precio_venta_final") or 0)
    precio_sin = pvp / (1 + iva / 100) if pvp > 0 else 0
    margen = ((precio_sin - costo_sin) / precio_sin * 100) if precio_sin > 0 else 0
    from datetime import datetime, timezone
    ahora = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    return [
        p.get("codigo_referencia") or "",
        p.get("nombre") or "",
        round(costo_sin),
        round(costo_con),
        round(precio_sin) if pvp > 0 else "",
        round(pvp) if pvp > 0 else "",
        f"{margen:.1f}%" if pvp > 0 else "",
        ahora,
    ]


def upsert(p: dict) -> None:
    """Inserta o actualiza la fila de UNA referencia (match por código en col A)."""
    ws = _hoja()
    if ws is None:
        return
    try:
        cod = (p.get("codigo_referencia") or "").strip()
        if not cod:
            return
        fila = _fila(p)
        col = ws.col_values(1)  # incluye encabezado
        idx = None
        for i, v in enumerate(col):
            if i == 0:
                continue
            if (v or "").strip() == cod:
                idx = i + 1
                break
        if idx:
            ws.update(f"A{idx}:H{idx}", [fila], value_input_option="USER_ENTERED")
        else:
            ws.append_row(fila, value_input_option="USER_ENTERED")
    except Exception as e:
        log.warning(f"[drive] upsert {p.get('codigo_referencia')} falló: {e}")


def upsert_async(p: dict) -> None:
    """Fire-and-forget: no frena el guardado del precosteo (corre en un hilo)."""
    if not configurado():
        return
    try:
        threading.Thread(target=upsert, args=(dict(p),), daemon=True).start()
    except Exception:
        pass


def sync_todos(precosteos: list[dict]) -> dict:
    """Reescribe TODA la hoja de una (encabezado + una fila por referencia).
    Para el llenado inicial o un refresco manual."""
    ws = _hoja()
    if ws is None:
        return {"ok": False, "motivo": "drive_no_configurado_o_sin_acceso"}
    filas = [ENCABEZADO] + [
        _fila(p) for p in precosteos if (p.get("codigo_referencia") or "").strip()
    ]
    try:
        ws.clear()
        ws.update("A1", filas, value_input_option="USER_ENTERED")
        return {"ok": True, "sincronizados": len(filas) - 1}
    except Exception as e:
        log.warning(f"[drive] sync_todos falló: {e}")
        return {"ok": False, "motivo": str(e)[:200]}
