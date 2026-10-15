"""
backend.services.caja_menor — Caja menor (fondo fijo) con soporte fotográfico.

Modelo de fondo fijo:
  · La caja tiene una BASE (efectivo con que debe quedar llena).
  · Cada GASTO exige descripción y foto del recibo, y descuenta del disponible.
  · saldo_disponible = base − Σ(gastos abiertos, sin anular).
  · REPONER cierra el periodo (marca los gastos como saldados) y devuelve el
    saldo a la base, registrando un movimiento 'reembolso' por lo gastado.

La foto vive en Supabase Storage (bucket 'caja-menor-fotos', público de lectura),
mismo patrón que las fotos de precosteo. Ver services/produccion.subir_foto_precosteo.
"""
from __future__ import annotations

import os
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

from supabase import Client, create_client

log = logging.getLogger("maledenim.caja_menor")

_BUCKET = "caja-menor-fotos"
_EXT_OK = ("jpg", "jpeg", "png", "webp", "gif", "heic")
_CATEGORIAS_SUGERIDAS = [
    "Transporte", "Papelería", "Aseo", "Alimentación",
    "Mensajería", "Mantenimiento", "Servicios", "Otros",
]

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
    except Exception as e:  # pragma: no cover
        log.warning(f"[caja_menor] Supabase client failed: {e}")
        return None


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _sb_or_raise() -> Client:
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase no configurado")
    return sb


# ── Storage ──────────────────────────────────────────────────────────

def _asegurar_bucket(sb: Client) -> None:
    """Crea el bucket público si aún no existe. Idempotente."""
    try:
        sb.storage.get_bucket(_BUCKET)
        return
    except Exception:
        pass
    try:
        sb.storage.create_bucket(_BUCKET, options={"public": True})
        log.info(f"[caja_menor] bucket '{_BUCKET}' creado (público de lectura)")
    except Exception as e:
        msg = str(e).lower()
        if "already exists" in msg or "duplicate" in msg or "resource_already" in msg:
            return
        raise RuntimeError(
            f"no se pudo crear el bucket '{_BUCKET}' en Supabase Storage: {str(e)[:160]}"
        )


def _subir_foto(sb: Client, *, mov_id: str, file_bytes: bytes,
                filename: str, content_type: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in (filename or "") else "jpg"
    if ext not in _EXT_OK:
        raise ValueError("formato_imagen_no_soportado")
    path = f"{mov_id}.{ext}"
    _asegurar_bucket(sb)
    try:
        try:
            sb.storage.from_(_BUCKET).remove([path])
        except Exception:
            pass
        sb.storage.from_(_BUCKET).upload(
            path, file_bytes,
            {"content-type": content_type or f"image/{ext}", "upsert": "true"},
        )
    except Exception as e:
        raise RuntimeError(f"subir_foto: {str(e)[:200]}")
    return sb.storage.from_(_BUCKET).get_public_url(path)


# ── Caja ─────────────────────────────────────────────────────────────

def obtener_o_crear_caja() -> dict:
    """La caja por defecto (una sola en la UI). La crea si aún no existe."""
    sb = _sb_or_raise()
    filas = (sb.table("caja_menor")
               .select("*").eq("activa", True)
               .order("creada_at").limit(1).execute()).data or []
    if filas:
        return filas[0]
    nueva = (sb.table("caja_menor")
               .insert({"nombre": "Caja menor", "base": 0})
               .execute()).data
    return nueva[0]


def _gastos_abiertos(sb: Client, caja_id: str) -> list[dict]:
    """Gastos del periodo abierto, sin anular. Paginado: entre reposiciones son
    pocos, pero PostgREST corta en 1.000 y una suma de plata no puede capar."""
    filas: list[dict] = []
    inicio = 0
    while True:
        chunk = (sb.table("caja_menor_movimiento")
                   .select("id,monto,descripcion,categoria,foto_url,fecha,"
                           "usuario_nombre,creado_at")
                   .eq("caja_id", caja_id).eq("tipo", "gasto")
                   .eq("periodo_cerrado", False).eq("anulado", False)
                   .order("fecha", desc=True).order("creado_at", desc=True)
                   .range(inicio, inicio + 999).execute()).data or []
        filas.extend(chunk)
        if len(chunk) < 1000:
            break
        inicio += 1000
    return filas


def resumen() -> dict:
    """Estado de la caja: base, saldo disponible y lo gastado en el periodo."""
    sb = _sb_or_raise()
    caja = obtener_o_crear_caja()
    abiertos = _gastos_abiertos(sb, caja["id"])
    gastado = round(sum(float(g.get("monto") or 0) for g in abiertos), 2)
    base = float(caja.get("base") or 0)
    return {
        "caja": {
            "id": caja["id"],
            "nombre": caja.get("nombre") or "Caja menor",
            "base": base,
            "base_actualizada_por": caja.get("base_actualizada_por"),
            "base_actualizada_at": caja.get("base_actualizada_at"),
        },
        "saldo_disponible": round(base - gastado, 2),
        "gastado_periodo": gastado,
        "n_gastos_periodo": len(abiertos),
        "categorias_sugeridas": _CATEGORIAS_SUGERIDAS,
    }


def set_base(monto: float, *, usuario_id: str = "", usuario_nombre: str = "") -> dict:
    """Fija/ajusta la base (fondo fijo) de la caja."""
    if monto is None or float(monto) < 0:
        raise ValueError("base_invalida")
    sb = _sb_or_raise()
    caja = obtener_o_crear_caja()
    (sb.table("caja_menor").update({
        "base": round(float(monto), 2),
        "base_actualizada_por": usuario_nombre or usuario_id,
        "base_actualizada_at": _now_iso(),
        "actualizada_at": _now_iso(),
    }).eq("id", caja["id"]).execute())
    return resumen()


# ── Movimientos ──────────────────────────────────────────────────────

def listar_movimientos(*, incluir_cerrados: bool = False, limit: int = 200) -> dict:
    """Los gastos del periodo abierto (default) o el histórico completo."""
    sb = _sb_or_raise()
    caja = obtener_o_crear_caja()
    q = (sb.table("caja_menor_movimiento")
           .select("id,tipo,monto,descripcion,categoria,foto_url,fecha,"
                   "periodo_cerrado,reembolso_id,anulado,anulado_por,"
                   "motivo_anulacion,usuario_nombre,creado_at")
           .eq("caja_id", caja["id"]))
    if not incluir_cerrados:
        # El periodo abierto: gastos vivos + su naturaleza. Los reembolsos y los
        # gastos ya saldados quedan para la vista de histórico.
        q = q.eq("periodo_cerrado", False)
    filas = (q.order("creado_at", desc=True)
               .limit(max(1, min(int(limit or 200), 2000))).execute()).data or []
    return {"movimientos": filas, "total": len(filas)}


def registrar_gasto(*, monto: float, descripcion: str, categoria: Optional[str],
                    fecha: Optional[str], file_bytes: bytes, filename: str,
                    content_type: str, usuario_id: str = "",
                    usuario_nombre: str = "") -> dict:
    """Registra un gasto. Exige monto>0, descripción y foto del soporte.

    Sube la foto ANTES de insertar la fila: si el storage falla no queda un
    gasto sin su recibo (que es justo lo que da la trazabilidad)."""
    try:
        monto_f = round(float(monto), 2)
    except (TypeError, ValueError):
        raise ValueError("monto_invalido")
    if monto_f <= 0:
        raise ValueError("monto_invalido")
    desc = (descripcion or "").strip()
    if not desc:
        raise ValueError("descripcion_requerida")
    if not file_bytes:
        raise ValueError("foto_requerida")

    sb = _sb_or_raise()
    caja = obtener_o_crear_caja()

    mov_id = str(uuid.uuid4())
    foto_url = _subir_foto(sb, mov_id=mov_id, file_bytes=file_bytes,
                           filename=filename, content_type=content_type)

    fila = {
        "id": mov_id,
        "caja_id": caja["id"],
        "tipo": "gasto",
        "monto": monto_f,
        "descripcion": desc[:500],
        "categoria": (categoria or "").strip()[:80] or None,
        "foto_url": foto_url,
        "usuario_id": usuario_id or None,
        "usuario_nombre": usuario_nombre or None,
    }
    if fecha:
        fila["fecha"] = fecha[:10]  # YYYY-MM-DD
    (sb.table("caja_menor_movimiento").insert(fila).execute())
    return {"ok": True, "id": mov_id, "foto_url": foto_url, **resumen()}


def anular_gasto(mov_id: str, *, motivo: str = "", usuario_id: str = "",
                 usuario_nombre: str = "") -> dict:
    """Anula un gasto ABIERTO (corregir una mala carga). No borra el rastro."""
    sb = _sb_or_raise()
    fila = (sb.table("caja_menor_movimiento")
              .select("id,tipo,periodo_cerrado,anulado")
              .eq("id", mov_id).limit(1).execute()).data or []
    if not fila:
        raise ValueError("no_encontrado")
    m = fila[0]
    if m.get("tipo") != "gasto":
        raise ValueError("solo_gastos")
    if m.get("periodo_cerrado"):
        raise ValueError("periodo_cerrado")  # ya fue repuesto: no se puede anular
    if m.get("anulado"):
        return resumen()  # idempotente
    (sb.table("caja_menor_movimiento").update({
        "anulado": True,
        "anulado_por": usuario_nombre or usuario_id,
        "anulado_at": _now_iso(),
        "motivo_anulacion": (motivo or "").strip()[:300] or None,
    }).eq("id", mov_id).execute())
    return resumen()


def reponer_caja(*, usuario_id: str = "", usuario_nombre: str = "") -> dict:
    """Repone el fondo: suma lo gastado en el periodo, cierra esos gastos y
    devuelve el saldo a la base. El monto lo calcula el servidor (los gastos
    abiertos), nunca el cliente, para que reembolso y gastos siempre cuadren."""
    sb = _sb_or_raise()
    caja = obtener_o_crear_caja()
    abiertos = _gastos_abiertos(sb, caja["id"])
    if not abiertos:
        raise ValueError("nada_por_reponer")
    total = round(sum(float(g.get("monto") or 0) for g in abiertos), 2)

    reembolso_id = str(uuid.uuid4())
    (sb.table("caja_menor_movimiento").insert({
        "id": reembolso_id,
        "caja_id": caja["id"],
        "tipo": "reembolso",
        "monto": total,
        "descripcion": f"Reposición de {len(abiertos)} gasto(s)",
        "periodo_cerrado": True,   # el reembolso nace cerrado: no es saldo vivo
        "usuario_id": usuario_id or None,
        "usuario_nombre": usuario_nombre or None,
    }).execute())

    # Cerrar exactamente los gastos que se contaron (por id, no por filtro: si
    # entró un gasto nuevo entre la lectura y aquí, no lo arrastramos).
    ids = [g["id"] for g in abiertos]
    for i in range(0, len(ids), 100):
        lote = ids[i:i + 100]
        (sb.table("caja_menor_movimiento").update({
            "periodo_cerrado": True,
            "reembolso_id": reembolso_id,
        }).in_("id", lote).execute())

    out = resumen()
    out.update({"ok": True, "reembolso_id": reembolso_id,
                "repuesto": total, "n_gastos": len(ids)})
    return out
