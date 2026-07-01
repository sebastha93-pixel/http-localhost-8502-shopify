"""
backend.services.produccion — Lógica de negocio del módulo Producción.

Patrón: espeja backend/services/clientes.py y revenue_db.
Toda persistencia va contra Supabase.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import date, datetime, timezone
from typing import Any, Optional

from supabase import Client, create_client

log = logging.getLogger(__name__)

# Cache simple en memoria por endpoint (TTL segundos)
# Vive mientras el worker esté vivo. Con 30s es suficiente para navegación fluida
# y aún así refleja cambios recientes en pocos segundos.
_CACHE: dict[str, tuple[float, Any]] = {}


def _cache_get(key: str, ttl_seg: int):
    hit = _CACHE.get(key)
    if not hit:
        return None
    expires_at, val = hit
    if time.time() > expires_at:
        _CACHE.pop(key, None)
        return None
    return val


def _cache_set(key: str, val, ttl_seg: int):
    _CACHE[key] = (time.time() + ttl_seg, val)


def _cache_invalidate_prefix(prefix: str):
    for k in list(_CACHE.keys()):
        if k.startswith(prefix):
            _CACHE.pop(k, None)

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

def next_consecutivo_mensual(prefijo: str, width: int = 4) -> str:
    """Consecutivo mensual — resetea al inicio de cada mes.
    Devuelve `YYMM-NNNN`. Ejemplo: 2607-0001 (julio 2026).

    Los últimos 2 dígitos del año + mes + serial mensual.
    Usa la misma tabla `produccion_consecutivos` con clave sintética
    `prefijo:YYMM` — no choca con los otros consecutivos (ING, ROLLO,
    PC, REM) porque son filas independientes por prefijo/año.
    """
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase no configurado")
    now = datetime.now(tz=timezone.utc)
    yy = f"{now.year % 100:02d}"
    mm = f"{now.month:02d}"
    yymm = f"{yy}{mm}"
    key = f"{prefijo}:{yymm}"
    r = (sb.table("produccion_consecutivos")
           .select("ultimo").eq("prefijo", key).eq("anio", now.year)
           .limit(1).execute())
    ultimo = ((r.data or [None])[0] or {}).get("ultimo") or 0
    nuevo = ultimo + 1
    sb.table("produccion_consecutivos").upsert(
        {"prefijo": key, "anio": now.year, "ultimo": nuevo, "updated_at": _now_iso()},
        on_conflict="prefijo,anio",
    ).execute()
    return f"{yymm}-{str(nuevo).zfill(width)}"


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
    Cache 30s — la mayoría de páginas consultan este endpoint al abrirse.
    """
    cache_key = "inventario_resumen"
    cached = _cache_get(cache_key, ttl_seg=30)
    if cached is not None:
        return cached
    sb = _sb()
    if sb is None:
        return []
    # Traer solo columnas necesarias, no cargar rollos agotados.
    # 5000 es holgado para MALE'DENIM (~cientos activos).
    rollos = (sb.table("rollos_tela")
                .select("descripcion_tela,tono,metros_inicial,metros_disponible,costo_metro")
                .neq("estado", "agotado")
                .limit(5000)
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
    _cache_set(cache_key, out, ttl_seg=30)
    return out


# ═══════════════════════════════════════════════════════════════════════
# PRECOSTEO
# ═══════════════════════════════════════════════════════════════════════

CATEGORIAS_PRECOSTEO = (
    "MATERIA PRIMA",
    "PROCESO EN MATERIA PRIMA",
    "INSUMO CONFECCION",
    "INSUMO TERMINACION",
)


def _calcular_totales_precosteo(items: list[dict], iva_pct: float, margen: float) -> dict:
    """Suma totales de líneas y calcula precio sugerido por margen."""
    total_sin = 0.0
    total_con = 0.0
    for it in items:
        vu = float(it.get("valor_unitario") or 0)
        cant = float(it.get("cantidad") or 0)
        iva = float(it.get("iva") or 0)
        ts = round(vu * cant, 2)
        tc = round(ts + iva, 2)
        it["total_sin_iva"] = ts
        it["total_con_iva"] = tc
        total_sin += ts
        total_con += tc
    total_sin = round(total_sin, 2)
    total_con = round(total_con, 2)
    precio = round(total_con * (1 + (float(margen) or 0) / 100), 0) if margen else None
    return {
        "costo_total_sin_iva": total_sin,
        "costo_total_con_iva": total_con,
        "precio_sugerido_venta": precio,
    }


def crear_precosteo(*, codigo_referencia: str, nombre: str, tela: str, color: str,
                    iva_pct: float, margen: float, items: list[dict],
                    created_by: str, es_muestra_diseno: bool = False) -> dict:
    """Crea un precosteo en estado 'borrador' con sus líneas.

    Si es_muestra_diseno=True, el precosteo puede usarse para generar
    órdenes de corte aunque siga en borrador (no requiere firma).
    """
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase no configurado")
    if not codigo_referencia.strip():
        raise ValueError("codigo_referencia_requerido")
    # Validar categorías
    for it in items:
        cat = (it.get("categoria") or "").upper().strip()
        if cat and cat not in CATEGORIAS_PRECOSTEO:
            raise ValueError(f"categoria_invalida: {cat}")
    totales = _calcular_totales_precosteo(items, iva_pct, margen)
    row = {
        "codigo_referencia": codigo_referencia.strip(),
        "nombre": nombre.strip(),
        "tela": (tela or "").strip() or None,
        "color": (color or "").strip() or None,
        "iva_pct": iva_pct,
        "margen": margen,
        "costo_total_sin_iva": totales["costo_total_sin_iva"],
        "costo_total_con_iva": totales["costo_total_con_iva"],
        "precio_sugerido_venta": totales["precio_sugerido_venta"],
        "estado": "borrador",
        "bloqueada": False,
        "es_muestra_diseno": bool(es_muestra_diseno),
        "created_by": created_by,
    }
    try:
        r = sb.table("referencias_precosteo").insert(row).execute()
    except Exception as e:
        # Compat: si la migración aún no corrió, quita el flag y reintenta
        if "es_muestra_diseno" in str(e):
            row.pop("es_muestra_diseno", None)
            r = sb.table("referencias_precosteo").insert(row).execute()
        else:
            raise
    if not r.data:
        raise RuntimeError("no_se_pudo_crear")
    ref = r.data[0]
    ref_id = ref["id"]

    # Insertar ítems
    if items:
        rows_items = []
        for i, it in enumerate(items):
            rows_items.append({
                "referencia_id": ref_id,
                "categoria": (it.get("categoria") or "").upper().strip(),
                "item": (it.get("item") or "").strip(),
                "valor_unitario": it.get("valor_unitario") or 0,
                "cantidad": it.get("cantidad") or 1,
                "iva": it.get("iva") or 0,
                "total_sin_iva": it.get("total_sin_iva") or 0,
                "total_con_iva": it.get("total_con_iva") or 0,
                "orden": i,
            })
        sb.table("precosteo_items").insert(rows_items).execute()

    return obtener_precosteo(ref_id)


def actualizar_precosteo(precosteo_id: str, *, nombre: Optional[str] = None,
                         tela: Optional[str] = None, color: Optional[str] = None,
                         iva_pct: Optional[float] = None, margen: Optional[float] = None,
                         items: Optional[list[dict]] = None,
                         foto_url: Optional[str] = None,
                         es_muestra_diseno: Optional[bool] = None) -> dict:
    """Actualiza un borrador. Rechaza si el precosteo ya está bloqueado."""
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase no configurado")
    actual = obtener_precosteo(precosteo_id)
    if not actual:
        raise ValueError("no_encontrado")
    if actual.get("bloqueada"):
        raise ValueError("precosteo_bloqueado")

    update: dict = {}
    if nombre is not None:  update["nombre"] = nombre.strip()
    if tela is not None:    update["tela"] = tela.strip() or None
    if color is not None:   update["color"] = color.strip() or None
    if iva_pct is not None: update["iva_pct"] = iva_pct
    if margen is not None:  update["margen"] = margen
    if foto_url is not None: update["foto_url"] = foto_url
    if es_muestra_diseno is not None: update["es_muestra_diseno"] = bool(es_muestra_diseno)

    if items is not None:
        # Reemplazar líneas: borrar y volver a insertar
        sb.table("precosteo_items").delete().eq("referencia_id", precosteo_id).execute()
        totales = _calcular_totales_precosteo(items, iva_pct if iva_pct is not None else float(actual.get("iva_pct") or 19), margen if margen is not None else float(actual.get("margen") or 0))
        update.update(totales)
        rows_items = []
        for i, it in enumerate(items):
            rows_items.append({
                "referencia_id": precosteo_id,
                "categoria": (it.get("categoria") or "").upper().strip(),
                "item": (it.get("item") or "").strip(),
                "valor_unitario": it.get("valor_unitario") or 0,
                "cantidad": it.get("cantidad") or 1,
                "iva": it.get("iva") or 0,
                "total_sin_iva": it.get("total_sin_iva") or 0,
                "total_con_iva": it.get("total_con_iva") or 0,
                "orden": i,
            })
        if rows_items:
            sb.table("precosteo_items").insert(rows_items).execute()

    if update:
        update["updated_at"] = _now_iso()
        sb.table("referencias_precosteo").update(update).eq("id", precosteo_id).execute()

    return obtener_precosteo(precosteo_id)


def firmar_precosteo(precosteo_id: str, *, usuario_id: str) -> dict:
    """Firma un precosteo (autoriza + bloquea). Requiere flag puede_autorizar_precosteo."""
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase no configurado")

    # Validar flag del usuario
    from backend.services import usuarios as _usuarios
    u = _usuarios.obtener_por_id(usuario_id)
    if not u:
        raise ValueError("usuario_no_encontrado")
    if not u.get("puede_autorizar_precosteo"):
        raise ValueError("sin_permiso_autorizar_precosteo")

    actual = obtener_precosteo(precosteo_id)
    if not actual:
        raise ValueError("no_encontrado")
    if actual.get("bloqueada"):
        raise ValueError("ya_bloqueado")

    now = _now_iso()
    sb.table("referencias_precosteo").update({
        "estado": "autorizada",
        "bloqueada": True,
        "autorizada_por": u.get("email") or usuario_id,
        "fecha_autorizacion": now,
        "updated_at": now,
    }).eq("id", precosteo_id).execute()
    return obtener_precosteo(precosteo_id)


def eliminar_precosteo(precosteo_id: str) -> None:
    """Elimina un precosteo (solo borrador). Los ítems caen por CASCADE."""
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase no configurado")
    actual = obtener_precosteo(precosteo_id)
    if not actual:
        raise ValueError("no_encontrado")
    if actual.get("bloqueada"):
        raise ValueError("no_se_puede_eliminar_bloqueado")
    sb.table("referencias_precosteo").delete().eq("id", precosteo_id).execute()


def listar_precosteos(*, estado: Optional[str] = None, tela: Optional[str] = None,
                      limit: int = 200,
                      disponibles_para_corte: bool = False) -> list[dict]:
    """Lista precosteos.
    Si `disponibles_para_corte`, devuelve TODOS los autorizados + los borradores
    marcados como muestra de diseño (que pueden generar corte sin firma).
    Cache 30s.
    """
    cache_key = f"precosteos:{estado}:{tela}:{limit}:{disponibles_para_corte}"
    cached = _cache_get(cache_key, ttl_seg=30)
    if cached is not None:
        return cached
    sb = _sb()
    if sb is None:
        return []
    # Solo columnas necesarias para la lista + selector — foto_url no viaja aquí.
    cols = ("id,codigo_referencia,nombre,tela,color,iva_pct,margen,"
            "costo_total_sin_iva,costo_total_con_iva,precio_sugerido_venta,"
            "estado,bloqueada,es_muestra_diseno,autorizada_por,fecha_autorizacion,"
            "created_at,created_by")
    q = sb.table("referencias_precosteo").select(cols).order("created_at", desc=True).limit(limit)
    if disponibles_para_corte:
        try:
            q = q.or_("bloqueada.eq.true,es_muestra_diseno.eq.true")
        except Exception:
            q = q.eq("bloqueada", True)
    else:
        if estado:
            q = q.eq("estado", estado)
        if tela:
            q = q.ilike("tela", f"%{tela}%")
    out = q.execute().data or []
    _cache_set(cache_key, out, ttl_seg=30)
    return out


def obtener_precosteo(precosteo_id: str) -> Optional[dict]:
    sb = _sb()
    if sb is None:
        return None
    ref = (sb.table("referencias_precosteo").select("*").eq("id", precosteo_id).limit(1).execute()).data
    if not ref:
        return None
    items = (sb.table("precosteo_items").select("*")
               .eq("referencia_id", precosteo_id)
               .order("orden").execute()).data or []
    return {**ref[0], "items": items}


def subir_foto_precosteo(precosteo_id: str, *, file_bytes: bytes, filename: str,
                         content_type: str) -> str:
    """Sube la foto de la referencia a Supabase Storage bucket 'produccion-fotos'
    y devuelve la URL pública. Actualiza foto_url en la tabla.
    """
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase no configurado")
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpg"
    if ext not in ("jpg", "jpeg", "png", "webp", "gif"):
        raise ValueError("formato_imagen_no_soportado")
    path = f"{precosteo_id}/foto.{ext}"
    bucket = "produccion-fotos"
    try:
        # Upsert por si ya existía
        try:
            sb.storage.from_(bucket).remove([path])
        except Exception:
            pass
        sb.storage.from_(bucket).upload(
            path, file_bytes,
            {"content-type": content_type or f"image/{ext}", "upsert": "true"},
        )
    except Exception as e:
        raise RuntimeError(f"subir_foto: {str(e)[:200]}")
    # URL pública (asume bucket con read policy pública)
    url = sb.storage.from_(bucket).get_public_url(path)
    # Guardar en la referencia
    sb.table("referencias_precosteo").update({
        "foto_url": url,
        "updated_at": _now_iso(),
    }).eq("id", precosteo_id).execute()
    return url


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


# ═══════════════════════════════════════════════════════════════════════
# ORDEN DE CORTE (Bloque 4)
# ═══════════════════════════════════════════════════════════════════════

def calcular_capas_desde_curva(curva: dict) -> int:
    """Regla del cortador MALE'DENIM: pares FIJOS de tallas que van juntas
    en el mismo trazo. Talla 4 se corta sola.

    Pares: (6, 12), (8, 10), (14, 16)
    Solos: 4 (y cualquier talla no mapeada)

    Para cada par: capas = max(cantidad_talla_A, cantidad_talla_B).
    (Si difieren, se hace el máximo — el excedente se corta con capas extra
    de esa talla; en el conteo total contamos el peor caso = max.)
    Para tallas solas: capas = cantidad.
    Total = suma de capas de cada bloque.
    """
    if not curva:
        return 0
    PARES = [("6", "12"), ("8", "10"), ("14", "16")]

    # Normalizar claves y valores a int
    curva_n: dict[str, int] = {}
    for k, v in curva.items():
        key = str(k).strip()
        try:
            val = int(v)
        except Exception:
            val = 0
        if val > 0:
            curva_n[key] = val

    total = 0
    consumidas: set[str] = set()
    for a, b in PARES:
        if a in curva_n or b in curva_n:
            total += max(curva_n.get(a, 0), curva_n.get(b, 0))
            consumidas.add(a)
            consumidas.add(b)
    # Tallas restantes se cortan solas
    for k, v in curva_n.items():
        if k not in consumidas:
            total += v
    return total


def crear_orden_corte(*, referencia_id: str,
                       largo_trazo: float,
                       curva_trazo: dict,
                       cantidad_programada: Optional[int] = None,
                       promedio_tecnico: Optional[float] = None,
                       responsable: Optional[str] = None,
                       fecha_envio: Optional[str] = None,
                       indicaciones: Optional[str] = None,
                       destinatarios_correo: Optional[list[str]] = None,
                       trazos_url: Optional[str] = None,
                       created_by: str = "") -> dict:
    """Crea una orden de corte a partir de un precosteo (firmado o muestra).
    - num_capas se auto-calcula desde la curva de tallas.
    - prendas_por_trazo = # tallas distintas con cantidad > 0 (aprox).
    - prendas_estimadas = suma de unidades de la curva.
    """
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase no configurado")
    p = obtener_precosteo(referencia_id)
    if not p:
        raise ValueError("precosteo_no_encontrado")
    if not p.get("bloqueada") and not p.get("es_muestra_diseno"):
        raise ValueError("precosteo_no_firmado")

    curva = curva_trazo or {}
    prendas_curva = sum(int(n or 0) for n in curva.values())
    prendas_est = int(cantidad_programada) if cantidad_programada else prendas_curva
    num_capas = calcular_capas_desde_curva(curva)
    prendas_por_trazo_est = max(1, sum(1 for v in curva.values() if int(v or 0) > 0))
    # Metros teóricos = promedio_tecnico × cantidad_programada.
    # Rendimiento = metros_teoricos / cantidad_programada (equivale al promedio,
    # se guarda por auditoría por si se editan campos por separado).
    prom = float(promedio_tecnico or 0)
    metros_teo = round(prom * prendas_est, 2) if (prom > 0 and prendas_est > 0) else 0
    rendimiento = round(metros_teo / prendas_est, 4) if prendas_est else 0

    codigo = next_consecutivo_mensual("OC", width=4)
    row = {
        "consecutivo": codigo,
        "referencia_id": referencia_id,
        "largo_trazo": float(largo_trazo),
        "prendas_por_trazo": prendas_por_trazo_est,
        "curva_trazo": curva,
        "num_capas": num_capas,
        "cantidad_programada": prendas_est,
        "promedio_tecnico": float(promedio_tecnico) if promedio_tecnico is not None else None,
        "prendas_estimadas": prendas_est,
        "metros_consumidos": metros_teo,
        "rendimiento_teorico": rendimiento,
        "responsable": responsable or None,
        "fecha_envio": fecha_envio or None,
        "fecha_limite": fecha_envio or None,   # retro-compat con la columna vieja
        "indicaciones": indicaciones or None,
        "trazos_url": trazos_url or None,
        "destinatarios_correo": destinatarios_correo or [],
        "estado": "borrador",
        "created_by": created_by,
    }
    try:
        r = sb.table("ordenes_corte").insert(row).execute()
    except Exception as e:
        # Compat si la migración aún no corrió: quita las columnas nuevas
        msg = str(e)
        cols_nuevas = ("cantidad_programada", "promedio_tecnico", "fecha_envio",
                       "trazos_url", "destinatarios_correo")
        if any(c in msg for c in cols_nuevas):
            for c in cols_nuevas:
                row.pop(c, None)
            r = sb.table("ordenes_corte").insert(row).execute()
        else:
            raise
    return r.data[0]


def listar_ordenes_corte(*, estado: Optional[str] = None,
                          limit: int = 200) -> list[dict]:
    """Lista órdenes de corte. Cache 20s."""
    cache_key = f"ordenes_corte_lista:{estado}:{limit}"
    cached = _cache_get(cache_key, ttl_seg=20)
    if cached is not None:
        return cached
    sb = _sb()
    if sb is None:
        return []
    # No traer foto_url en el JOIN — pesa mucho y no se usa en la lista.
    q = (sb.table("ordenes_corte")
           .select("*,referencia:referencia_id(codigo_referencia,nombre,tela,color)")
           .order("created_at", desc=True).limit(limit))
    if estado:
        q = q.eq("estado", estado)
    out = q.execute().data or []
    _cache_set(cache_key, out, ttl_seg=20)
    return out


def obtener_orden_corte(oc_id: str) -> Optional[dict]:
    sb = _sb()
    if sb is None:
        return None
    # Sin foto_url — el detalle nunca la mostraba.
    r = (sb.table("ordenes_corte")
           .select("*,referencia:referencia_id(codigo_referencia,nombre,tela,color)")
           .eq("id", oc_id).limit(1).execute()).data
    if not r:
        return None
    rollos = (sb.table("orden_corte_rollos")
                .select("*,rollo:rollo_id(codigo_interno,barcode,descripcion_tela,tono,metros_disponible,metros_inicial,costo_metro)")
                .eq("orden_corte_id", oc_id).execute()).data or []
    return {**r[0], "rollos": rollos}


def asignar_rollo_a_corte(*, oc_id: str, barcode: str,
                           metros_reservar: float) -> dict:
    """Pistolear un rollo: valida barcode → agrega a la orden con los metros reservados.
    NO descuenta del inventario todavía (eso pasa al cerrar la orden).
    """
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase no configurado")
    oc = obtener_orden_corte(oc_id)
    if not oc:
        raise ValueError("orden_no_encontrada")
    if oc.get("estado") == "cortada":
        raise ValueError("orden_ya_cortada")

    rollo = obtener_rollo_por_barcode(barcode.strip())
    if not rollo:
        raise ValueError("rollo_no_encontrado")
    if rollo.get("estado") == "agotado":
        raise ValueError("rollo_agotado")
    disp = float(rollo.get("metros_disponible") or 0)
    m = float(metros_reservar or 0)
    if m <= 0:
        raise ValueError("metros_reservar_debe_ser_positivo")
    if m > disp:
        raise ValueError(f"metros_insuficientes: rollo tiene {disp}m disponibles")

    # Upsert por (orden_corte_id, rollo_id)
    existing = (sb.table("orden_corte_rollos").select("id")
                 .eq("orden_corte_id", oc_id).eq("rollo_id", rollo["id"])
                 .limit(1).execute()).data
    if existing:
        sb.table("orden_corte_rollos").update({"metros_usados": m}).eq("id", existing[0]["id"]).execute()
    else:
        sb.table("orden_corte_rollos").insert({
            "orden_corte_id": oc_id,
            "rollo_id": rollo["id"],
            "metros_usados": m,
        }).execute()
    return obtener_orden_corte(oc_id)


def auto_asignar_rollos_por_tono(*, oc_id: str,
                                   tono: Optional[str] = None) -> dict:
    """Auto-selecciona rollos disponibles con la MISMA TELA y MISMO TONO
    de la referencia (o el tono indicado si viene) y los agrega al corte
    hasta cubrir los metros teóricos.

    Regla de negocio: no se pueden mezclar tonos en un mismo trazo — el
    color termina saliendo distinto. Este helper reduce el riesgo humano.
    """
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase no configurado")
    oc = obtener_orden_corte(oc_id)
    if not oc:
        raise ValueError("orden_no_encontrada")
    if oc.get("estado") == "cortada":
        raise ValueError("orden_ya_cortada")

    tela = ((oc.get("referencia") or {}).get("tela") or "").strip()
    if not tela:
        raise ValueError("precosteo_sin_tela")

    tono_target = (tono or oc.get("tono") or "").strip()

    # Metros teóricos que necesita el corte
    m_necesarios = float(oc.get("metros_consumidos") or 0)
    if m_necesarios <= 0:
        raise ValueError("orden_sin_metros_teoricos")

    # Rollos ya asignados → no repetir
    ya_asignados = {link.get("rollo_id") for link in (oc.get("rollos") or []) if link.get("rollo_id")}
    m_ya = sum(float(link.get("metros_usados") or 0) for link in (oc.get("rollos") or []))
    m_pendientes = round(m_necesarios - m_ya, 2)
    if m_pendientes <= 0:
        return {"ok": True, "asignados": [], "faltantes": 0,
                "mensaje": "ya_cubierto"}

    q = (sb.table("rollos_tela")
           .select("id,codigo_interno,barcode,descripcion_tela,tono,metros_disponible")
           .eq("estado", "disponible")
           .ilike("descripcion_tela", f"%{tela}%")
           .order("metros_disponible", desc=True)
           .limit(200))
    if tono_target:
        q = q.eq("tono", tono_target)
    rollos = q.execute().data or []

    asignados: list[dict] = []
    for r in rollos:
        if r["id"] in ya_asignados:
            continue
        if m_pendientes <= 0:
            break
        disp = float(r.get("metros_disponible") or 0)
        if disp <= 0:
            continue
        m_usar = round(min(m_pendientes, disp), 2)
        # Insertar link (no descuenta inventario todavía — eso pasa al cerrar)
        sb.table("orden_corte_rollos").insert({
            "orden_corte_id": oc_id,
            "rollo_id":       r["id"],
            "metros_usados":  m_usar,
        }).execute()
        asignados.append({
            "codigo_interno": r["codigo_interno"],
            "tono":           r.get("tono"),
            "metros_usados":  m_usar,
        })
        m_pendientes = round(m_pendientes - m_usar, 2)

    return {
        "ok":         m_pendientes <= 0,
        "asignados":  asignados,
        "faltantes":  m_pendientes if m_pendientes > 0 else 0,
        "tono_usado": tono_target or None,
        "tela":       tela,
    }


def quitar_rollo_de_corte(*, oc_id: str, rollo_id: str) -> dict:
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase no configurado")
    oc = obtener_orden_corte(oc_id)
    if not oc:
        raise ValueError("orden_no_encontrada")
    if oc.get("estado") == "cortada":
        raise ValueError("orden_ya_cortada")
    sb.table("orden_corte_rollos").delete().eq("orden_corte_id", oc_id).eq("rollo_id", rollo_id).execute()
    return obtener_orden_corte(oc_id)


def cerrar_orden_corte(*, oc_id: str, consumo_real_cortador: float,
                        merma_tipo: Optional[str] = None,
                        merma_valor: Optional[float] = None,
                        usuario: str,
                        referencia_lote: Optional[str] = None,
                        capas_real: Optional[int] = None,
                        promedio_real: Optional[float] = None,
                        unidades_cortadas: Optional[dict] = None,
                        retazos_cantidad: Optional[int] = None,
                        fecha_entrega: Optional[str] = None,
                        precio_corte: Optional[float] = None) -> dict:
    """Cierra la orden con el INFORME DEL CORTADOR:
    - Descuenta metros del inventario según metros_usados por rollo.
    - Guarda promedio_real, capas_real, unidades cortadas por talla, retazos,
      referencia de lote, fecha de entrega y precio del corte.
    - Calcula la diferencia teórica vs real.
    """
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase no configurado")
    oc = obtener_orden_corte(oc_id)
    if not oc:
        raise ValueError("orden_no_encontrada")
    if oc.get("estado") == "cortada":
        raise ValueError("orden_ya_cortada")
    rollos = oc.get("rollos") or []
    if not rollos:
        raise ValueError("orden_sin_rollos")

    doc_ref = oc["consecutivo"]
    # Descuenta cada rollo por sus metros_usados
    for link in rollos:
        rollo_id = link.get("rollo_id")
        m = float(link.get("metros_usados") or 0)
        if not rollo_id or m <= 0:
            continue
        rollo = obtener_rollo(rollo_id)
        if not rollo:
            continue
        nuevo = round(float(rollo["metros_disponible"]) - m, 2)
        if nuevo < 0:
            raise ValueError(f"metros_negativos_en_rollo_{rollo['codigo_interno']}")
        estado_nuevo = "agotado" if nuevo <= 0 else rollo.get("estado")
        sb.table("rollos_tela").update({
            "metros_disponible": nuevo,
            "estado": estado_nuevo,
            "fecha_ultimo_corte": _now_iso(),
            "updated_at": _now_iso(),
        }).eq("id", rollo_id).execute()
        sb.table("movimientos_inventario").insert({
            "rollo_id": rollo_id,
            "tipo": "corte",
            "metros": -m,
            "doc_ref": doc_ref,
            "usuario": usuario,
            "nota": f"Corte {doc_ref}",
        }).execute()

    # Calcula diferencia teórico vs real
    teorico = float(oc.get("metros_consumidos") or 0)
    real = float(consumo_real_cortador or 0)
    diff = round((real - teorico) / teorico * 100, 2) if teorico > 0 else 0

    update = {
        "consumo_real_cortador": real,
        "diferencia_pct": diff,
        "merma_tipo": merma_tipo,
        "merma_valor": merma_valor,
        "estado": "cortada",
        "updated_at": _now_iso(),
    }
    if referencia_lote is not None:  update["referencia_lote"] = referencia_lote.strip() or None
    if capas_real is not None:       update["capas_real"] = int(capas_real)
    if promedio_real is not None:    update["promedio_real"] = float(promedio_real)
    if unidades_cortadas is not None:update["unidades_cortadas"] = unidades_cortadas or {}
    if retazos_cantidad is not None: update["retazos_cantidad"] = int(retazos_cantidad)
    if fecha_entrega is not None:    update["fecha_entrega"] = fecha_entrega or None
    if precio_corte is not None:     update["precio_corte"] = float(precio_corte)

    try:
        sb.table("ordenes_corte").update(update).eq("id", oc_id).execute()
    except Exception as e:
        # Compat si la migración del informe no corrió
        cols_informe = ("referencia_lote","capas_real","promedio_real",
                         "unidades_cortadas","retazos_cantidad","fecha_entrega","precio_corte")
        if any(c in str(e) for c in cols_informe):
            for c in cols_informe:
                update.pop(c, None)
            sb.table("ordenes_corte").update(update).eq("id", oc_id).execute()
        else:
            raise
    return obtener_orden_corte(oc_id)


def eliminar_orden_corte(oc_id: str) -> None:
    """Elimina orden de corte solo si está en borrador (no ha descontado inventario)."""
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase no configurado")
    oc = obtener_orden_corte(oc_id)
    if not oc:
        raise ValueError("orden_no_encontrada")
    if oc.get("estado") == "cortada":
        raise ValueError("no_se_puede_eliminar_cortada")
    # orden_corte_rollos cae por CASCADE
    sb.table("ordenes_corte").delete().eq("id", oc_id).execute()


# ── Trazos: adjuntar archivo (PDF/imagen) ─────────────────────────────
def subir_trazos_corte(oc_id: str, *, file_bytes: bytes, filename: str,
                       content_type: str) -> str:
    """Sube el archivo de trazos a Storage bucket 'produccion-trazos'
    y guarda la URL en la orden. Devuelve la URL pública.
    """
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase no configurado")
    oc = obtener_orden_corte(oc_id)
    if not oc:
        raise ValueError("orden_no_encontrada")
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "pdf").lower()
    if ext not in ("pdf", "png", "jpg", "jpeg", "webp"):
        raise ValueError("formato_no_soportado")
    bucket = "produccion-trazos"
    path = f"{oc_id}/trazos.{ext}"
    try:
        try:
            sb.storage.from_(bucket).remove([path])
        except Exception:
            pass
        sb.storage.from_(bucket).upload(
            path, file_bytes,
            {"content-type": content_type or "application/octet-stream", "upsert": "true"},
        )
    except Exception as e:
        raise RuntimeError(f"subir_trazos: {str(e)[:200]}")
    url = sb.storage.from_(bucket).get_public_url(path)
    sb.table("ordenes_corte").update({
        "trazos_url": url, "updated_at": _now_iso(),
    }).eq("id", oc_id).execute()
    return url


# ── Autorizar orden de corte y enviar correo ──────────────────────────
def autorizar_orden_corte(oc_id: str, *, destinatarios: Optional[list[str]] = None,
                           mensaje_extra: Optional[str] = None,
                           usuario: str) -> dict:
    """Marca la orden como 'autorizada' y prepara el correo para los destinatarios.

    Estrategia de envío:
    - Si RESEND_API_KEY está seteada → envía vía Resend API.
    - Si no → devuelve `mailto_url` para que el frontend lo abra en el cliente
      de correo del usuario. Los datos quedan igualmente guardados en la orden.
    """
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase no configurado")
    oc = obtener_orden_corte(oc_id)
    if not oc:
        raise ValueError("orden_no_encontrada")
    if oc.get("estado") == "cortada":
        raise ValueError("orden_ya_cortada")

    # Guardar destinatarios si vinieron
    update: dict = {"estado": "autorizada", "autorizada_por": usuario, "updated_at": _now_iso()}
    if destinatarios is not None:
        update["destinatarios_correo"] = destinatarios
    try:
        sb.table("ordenes_corte").update(update).eq("id", oc_id).execute()
    except Exception as e:
        if "destinatarios_correo" in str(e):
            update.pop("destinatarios_correo", None)
            sb.table("ordenes_corte").update(update).eq("id", oc_id).execute()
        else:
            raise

    ref = oc.get("referencia") or {}
    codigo_ref = ref.get("codigo_referencia") or ""
    asunto = f"Orden de corte referencia {codigo_ref}"

    # Cuerpo del correo
    filas_curva = "\n".join(f"  · Talla {t}: {n} und" for t, n in (oc.get("curva_trazo") or {}).items())
    body = (
        f"Orden de corte {oc.get('consecutivo')}\n"
        f"Referencia: {codigo_ref} · {ref.get('nombre','')}\n"
        f"Tela: {ref.get('tela','—')}\n"
        f"Largo trazo: {oc.get('largo_trazo')} m\n"
        f"Número de capas: {oc.get('num_capas')}\n"
        f"Cantidad programada: {oc.get('cantidad_programada') or oc.get('prendas_estimadas') or ''}\n"
        f"Promedio técnico: {oc.get('promedio_tecnico') or '—'}\n"
        f"Cortador responsable: {oc.get('responsable') or '—'}\n"
        f"Fecha envío: {oc.get('fecha_envio') or oc.get('fecha_limite') or '—'}\n"
        f"\nCurva de tallas:\n{filas_curva or '  (sin curva)'}\n"
        f"\nTrazos: {oc.get('trazos_url') or '—'}\n"
    )
    if mensaje_extra:
        body += f"\n{mensaje_extra}\n"
    body += f"\nAutorizada por: {usuario}\n"

    dest = destinatarios if destinatarios is not None else (oc.get("destinatarios_correo") or [])
    resultado = {
        "asunto": asunto,
        "body": body,
        "destinatarios": dest,
        "enviado_por": None,   # 'resend' | 'mailto'
        "mailto_url": None,
    }

    # Envío via Resend si hay API key
    resend_key = os.environ.get("RESEND_API_KEY", "").strip()
    if resend_key and dest:
        try:
            import httpx
            from_email = os.environ.get("RESEND_FROM", "orden-corte@maledenim.com").strip()
            r = httpx.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {resend_key}",
                         "Content-Type": "application/json"},
                json={
                    "from": from_email,
                    "to": dest,
                    "subject": asunto,
                    "text": body,
                },
                timeout=15.0,
            )
            if r.status_code >= 400:
                raise RuntimeError(f"resend_error: {r.status_code} {r.text[:200]}")
            resultado["enviado_por"] = "resend"
        except Exception as e:
            print(f"[corte.autorizar] Resend falló, fallback a mailto: {e}")

    # Fallback mailto
    if resultado["enviado_por"] is None:
        from urllib.parse import quote
        to_str = ",".join(dest) if dest else ""
        resultado["mailto_url"] = (
            f"mailto:{to_str}"
            f"?subject={quote(asunto)}"
            f"&body={quote(body)}"
        )
        resultado["enviado_por"] = "mailto"

    return {**obtener_orden_corte(oc_id), "correo": resultado}


# ═══════════════════════════════════════════════════════════════════════
# BLOQUE 6A — CONFECCIONISTAS
# ═══════════════════════════════════════════════════════════════════════

def crear_confeccionista(*, nombre: str, telefono: Optional[str] = None,
                          direccion: Optional[str] = None) -> dict:
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase no configurado")
    if not nombre.strip():
        raise ValueError("nombre_requerido")
    row = {
        "nombre":    nombre.strip(),
        "telefono":  (telefono or "").strip() or None,
        "direccion": (direccion or "").strip() or None,
        "activo":    True,
    }
    r = sb.table("confeccionistas").insert(row).execute()
    return r.data[0]


def listar_confeccionistas(*, incluir_inactivos: bool = False,
                            limit: int = 200) -> list[dict]:
    sb = _sb()
    if sb is None:
        return []
    q = sb.table("confeccionistas").select("*").order("nombre").limit(limit)
    if not incluir_inactivos:
        q = q.eq("activo", True)
    return q.execute().data or []


def actualizar_confeccionista(cid: str, **campos) -> dict:
    permitidos = {"nombre", "telefono", "direccion", "activo"}
    update = {k: v for k, v in campos.items() if k in permitidos and v is not None}
    if not update:
        raise ValueError("nada_que_actualizar")
    if "nombre" in update:
        update["nombre"] = str(update["nombre"]).strip()
    update["updated_at"] = _now_iso()
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase no configurado")
    r = sb.table("confeccionistas").update(update).eq("id", cid).execute()
    if not r.data:
        raise ValueError("no_encontrado")
    return r.data[0]


# ═══════════════════════════════════════════════════════════════════════
# BLOQUE 6A — REMISIONES A CONFECCIONISTA
# ═══════════════════════════════════════════════════════════════════════

def crear_remision(*, confeccionista_id: str, fecha_recogida: str,
                    orden_corte_ids: list[str], created_by: str) -> dict:
    """Crea una remisión: entrega de N órdenes de corte cortadas a un confeccionista.
    - Valida que las órdenes existan y estén 'cortada' (no borrador ni autorizada).
    - Genera consecutivo `REM-YYYY-NNNN`.
    """
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase no configurado")
    if not orden_corte_ids:
        raise ValueError("sin_ordenes")

    # Validar confeccionista
    c = (sb.table("confeccionistas").select("id,nombre,activo")
           .eq("id", confeccionista_id).limit(1).execute()).data
    if not c:
        raise ValueError("confeccionista_no_encontrado")
    if not c[0].get("activo"):
        raise ValueError("confeccionista_inactivo")

    # Validar órdenes de corte
    for oc_id in orden_corte_ids:
        oc = (sb.table("ordenes_corte").select("id,estado,consecutivo")
                .eq("id", oc_id).limit(1).execute()).data
        if not oc:
            raise ValueError(f"orden_corte_no_encontrada:{oc_id}")
        if oc[0].get("estado") != "cortada":
            raise ValueError(f"orden_no_cortada:{oc[0].get('consecutivo')}")

    codigo = next_consecutivo("REM", width=4)
    row = {
        "consecutivo":       codigo,
        "confeccionista_id": confeccionista_id,
        "fecha_recogida":    fecha_recogida,
        "estado":            "generada",
        "created_by":        created_by,
    }
    r = sb.table("remisiones").insert(row).execute()
    if not r.data:
        raise RuntimeError("no_se_pudo_crear_remision")
    rem = r.data[0]

    # Items
    items_rows = [
        {"remision_id": rem["id"], "orden_corte_id": oc_id}
        for oc_id in orden_corte_ids
    ]
    sb.table("remision_items").insert(items_rows).execute()

    return obtener_remision(rem["id"])


def listar_remisiones(*, estado: Optional[str] = None,
                       confeccionista_id: Optional[str] = None,
                       limit: int = 200) -> list[dict]:
    sb = _sb()
    if sb is None:
        return []
    q = (sb.table("remisiones")
           .select("*,confeccionista:confeccionista_id(nombre)")
           .order("created_at", desc=True).limit(limit))
    if estado:
        q = q.eq("estado", estado)
    if confeccionista_id:
        q = q.eq("confeccionista_id", confeccionista_id)
    return q.execute().data or []


def obtener_remision(rem_id: str) -> Optional[dict]:
    sb = _sb()
    if sb is None:
        return None
    r = (sb.table("remisiones")
           .select("*,confeccionista:confeccionista_id(nombre,telefono,direccion)")
           .eq("id", rem_id).limit(1).execute()).data
    if not r:
        return None
    items = (sb.table("remision_items")
               .select("*,orden_corte:orden_corte_id("
                       "consecutivo,referencia_lote,cantidad_programada,"
                       "unidades_cortadas,fecha_entrega,"
                       "referencia:referencia_id(codigo_referencia,nombre,tela))")
               .eq("remision_id", rem_id).execute()).data or []
    return {**r[0], "items": items}


def marcar_remision_recogida(rem_id: str) -> dict:
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase no configurado")
    r = (sb.table("remisiones").update({
        "estado": "recogida",
        "updated_at": _now_iso(),
    }).eq("id", rem_id).execute()).data
    if not r:
        raise ValueError("no_encontrado")
    return obtener_remision(rem_id)
