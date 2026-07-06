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

def _incrementar_consecutivo(*, prefijo_key: str, anio: int) -> int:
    """Incrementa atómicamente el contador para (prefijo_key, anio) y devuelve
    el número nuevo. Motor compartido para todos los formatos de consecutivo.
    """
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase no configurado")
    # Camino atómico: RPC en Postgres (INSERT ... ON CONFLICT ... RETURNING).
    # Dos requests concurrentes NUNCA reciben el mismo número.
    try:
        r = sb.rpc("next_consecutivo_atomico",
                   {"p_prefijo": prefijo_key, "p_anio": anio}).execute()
        if isinstance(r.data, int):
            return r.data
        if isinstance(r.data, list) and r.data:
            return int(r.data[0] if isinstance(r.data[0], int) else r.data[0]["ultimo"])
    except Exception as e:
        log.debug(f"[consecutivo] RPC no disponible, fallback read-upsert: {e}")
    # Fallback (pre-migración): read → upsert. NO es atómico — el UNIQUE del
    # documento en DB atrapa la colisión con un error en vez de duplicar.
    r = (sb.table("produccion_consecutivos")
           .select("ultimo")
           .eq("prefijo", prefijo_key)
           .eq("anio", anio)
           .limit(1).execute())
    ultimo = ((r.data or [None])[0] or {}).get("ultimo") or 0
    nuevo = ultimo + 1
    sb.table("produccion_consecutivos").upsert(
        {"prefijo": prefijo_key, "anio": anio, "ultimo": nuevo, "updated_at": _now_iso()},
        on_conflict="prefijo,anio",
    ).execute()
    return nuevo


def next_consecutivo(prefijo: str, anio: Optional[int] = None, width: int = 4,
                     formato: str = "anual") -> str:
    """Consecutivo secuencial. `formato` decide el layout:
      - "anual"   → `PREFIJO-YYYY-NNNN` (ej. ING-2026-0001)
      - "mensual" → `YYMM-NNNN`         (ej. 2607-0001, resetea cada mes)
    """
    now = datetime.now(tz=timezone.utc)
    anio_ef = anio or now.year
    if formato == "mensual":
        yymm = f"{now.year % 100:02d}{now.month:02d}"
        prefijo_key = f"{prefijo}:{yymm}"
        nuevo = _incrementar_consecutivo(prefijo_key=prefijo_key, anio=now.year)
        return f"{yymm}-{str(nuevo).zfill(width)}"
    nuevo = _incrementar_consecutivo(prefijo_key=prefijo, anio=anio_ef)
    return f"{prefijo}-{anio_ef}-{str(nuevo).zfill(width)}"


def next_consecutivo_mensual(prefijo: str, width: int = 4) -> str:
    """Alias de compat — usa next_consecutivo(formato='mensual')."""
    return next_consecutivo(prefijo, width=width, formato="mensual")


def peek_consecutivo(prefijo: str) -> dict:
    """Consulta el último consecutivo SIN incrementarlo (para debug/preview).
    El GET del API usaba next_consecutivo y quemaba números con cada refresh.
    """
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase no configurado")
    r = (sb.table("produccion_consecutivos").select("prefijo,anio,ultimo")
           .like("prefijo", f"{prefijo}%")
           .order("updated_at", desc=True).limit(5).execute())
    return {"prefijo": prefijo, "contadores": r.data or []}


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
    if disponibles_para_corte:
        # Excluir precosteos que YA tienen orden de corte — un precosteo
        # genera un solo lote; si se necesita otro lote se hace otro precosteo.
        con_corte = (sb.table("ordenes_corte").select("referencia_id")
                       .limit(2000).execute()).data or []
        usados = {r["referencia_id"] for r in con_corte if r.get("referencia_id")}
        out = [p for p in out if p["id"] not in usados]
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
    # Regla de negocio: un precosteo = un lote. El filtro del selector tiene
    # cache de 30s — esta validación en servidor evita el doble corte por
    # doble click / dos pestañas.
    existente = (sb.table("ordenes_corte").select("id,consecutivo")
                   .eq("referencia_id", referencia_id).limit(1).execute()).data
    if existente:
        raise ValueError(f"precosteo_ya_tiene_corte:{existente[0].get('consecutivo')}")

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
                          limit: int = 200,
                          sin_remision: Optional[str] = None,
                          marcar_remisiones: bool = False) -> list[dict]:
    """Lista órdenes de corte. Cache 20s.
    `sin_remision='confeccion'|'terminacion'` excluye las OCs que YA tienen
    una remisión de ese tipo — un lote no puede remitirse dos veces al
    mismo proceso.
    `marcar_remisiones=True` anota cada OC con tiene_remision_confeccion /
    tiene_remision_terminacion (para mostrarlas marcadas en la UI).
    """
    cache_key = f"ordenes_corte_lista:{estado}:{limit}:{sin_remision}:{marcar_remisiones}"
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
    if sin_remision in ("confeccion", "terminacion"):
        ya = _ocs_con_remision(sin_remision)
        out = [oc for oc in out if oc["id"] not in ya]
    if marcar_remisiones:
        con_conf = _ocs_con_remision("confeccion")
        con_term = _ocs_con_remision("terminacion")
        for oc in out:
            oc["tiene_remision_confeccion"] = oc["id"] in con_conf
            oc["tiene_remision_terminacion"] = oc["id"] in con_term
    _cache_set(cache_key, out, ttl_seg=20)
    return out


def reset_datos_produccion() -> dict:
    """Borra TODO lo transaccional del módulo Producción para arrancar de
    cero (equivalente a SUPABASE_RESET_PRODUCCION.sql). CONSERVA usuarios.
    Solo lo invoca el endpoint admin. IRREVERSIBLE."""
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase no configurado")
    # Orden FK-seguro: hijos primero. (tabla, columna_para_filtro, valor_imposible)
    UUID_CERO = "00000000-0000-0000-0000-000000000000"
    tablas = [
        ("notas_hoja_ruta",        "id",      UUID_CERO),
        ("hoja_ruta_lote",         "id",      UUID_CERO),
        ("remision_items",         "id",      UUID_CERO),
        ("remisiones",             "id",      UUID_CERO),
        ("orden_corte_rollos",     "id",      UUID_CERO),
        ("ordenes_corte",          "id",      UUID_CERO),
        ("precosteo_items",        "id",      UUID_CERO),
        ("referencias_precosteo",  "id",      UUID_CERO),
        ("movimientos_inventario", "id",      UUID_CERO),
        ("rollos_tela",            "id",      UUID_CERO),
        ("ordenes_ingreso",        "id",      UUID_CERO),
        ("insumos_movimientos",    "id",      UUID_CERO),
        ("insumos",                "id",      UUID_CERO),
        ("produccion_consecutivos","prefijo", "___nunca___"),
        ("confeccionistas",        "id",      UUID_CERO),
    ]
    borradas: dict[str, int] = {}
    errores: dict[str, str] = {}
    for tabla, col, imposible in tablas:
        try:
            r = sb.table(tabla).delete().neq(col, imposible).execute()
            borradas[tabla] = len(r.data or [])
        except Exception as e:
            msg = str(e)
            if "does not exist" in msg:
                borradas[tabla] = 0  # tabla aún no migrada — nada que borrar
            else:
                errores[tabla] = msg[:150]
    _cache_invalidate_prefix("")  # limpiar TODO el cache del módulo
    log.warning(f"[reset] produccion reseteada: {borradas} errores={errores}")
    return {"borradas": borradas, "errores": errores, "ok": not errores}


def despachos_por_corte(limit: int = 200) -> list[dict]:
    """Control interno del cortador: por cada corte cerrado, las unidades
    que despachó por talla + el estado de la remisión de confección.
    NO incluye insumos, precios ni datos de proveedores."""
    sb = _sb()
    if sb is None:
        return []
    ocs = listar_ordenes_corte(estado="cortada", limit=limit)
    # Mapa oc_id → remisión de confección (para saber si ya se despachó)
    rem_por_oc: dict[str, dict] = {}
    try:
        rems = (sb.table("remisiones")
                  .select("id,consecutivo,estado,tipo,fecha_recogida,updated_at")
                  .limit(2000).execute()).data or []
        conf = {r["id"]: r for r in rems if (r.get("tipo") or "confeccion") == "confeccion"}
        if conf:
            items = (sb.table("remision_items").select("remision_id,orden_corte_id")
                       .in_("remision_id", list(conf.keys())).limit(5000).execute()).data or []
            for it in items:
                if it.get("orden_corte_id"):
                    rem_por_oc[it["orden_corte_id"]] = conf[it["remision_id"]]
    except Exception as e:
        log.warning(f"[despachos] remisiones no disponibles: {e}")
    out = []
    for oc in ocs:
        unidades = oc.get("unidades_cortadas") or {}
        try:
            total = sum(int(v or 0) for v in unidades.values())
        except Exception:
            total = 0
        rem = rem_por_oc.get(oc["id"])
        out.append({
            "id":            oc["id"],
            "consecutivo":   oc.get("consecutivo"),
            "referencia":    (oc.get("referencia") or {}).get("codigo_referencia"),
            "nombre":        (oc.get("referencia") or {}).get("nombre"),
            "responsable":   oc.get("responsable"),
            "fecha_entrega": oc.get("fecha_entrega"),
            "unidades":      unidades,
            "total":         total,
            "remision": None if not rem else {
                "id":             rem["id"],
                "consecutivo":    rem.get("consecutivo"),
                "despachada":     rem.get("estado") == "recogida",
                "fecha_recogida": rem.get("fecha_recogida"),
            },
        })
    return out


def _ocs_con_remision(tipo: str) -> set:
    """IDs de órdenes de corte que ya tienen una remisión del tipo dado.
    Compat: si la columna `tipo` no existe aún, toda remisión cuenta como
    confección (comportamiento pre-migración).
    """
    sb = _sb()
    if sb is None:
        return set()
    try:
        rems = (sb.table("remisiones").select("id,tipo").limit(2000).execute()).data or []
        rem_ids = [r["id"] for r in rems if (r.get("tipo") or "confeccion") == tipo]
    except Exception:
        if tipo != "confeccion":
            return set()
        rems = (sb.table("remisiones").select("id").limit(2000).execute()).data or []
        rem_ids = [r["id"] for r in rems]
    if not rem_ids:
        return set()
    items = (sb.table("remision_items").select("orden_corte_id")
               .in_("remision_id", rem_ids).limit(5000).execute()).data or []
    return {it["orden_corte_id"] for it in items if it.get("orden_corte_id")}


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

    # Upsert por (orden_corte_id, rollo_id)
    existing = (sb.table("orden_corte_rollos").select("id")
                 .eq("orden_corte_id", oc_id).eq("rollo_id", rollo["id"])
                 .limit(1).execute()).data

    # Un rollo reservado en OTRO corte no se puede volver a tomar
    if rollo.get("estado") == "en_corte" and not existing:
        raise ValueError("rollo_reservado_en_otro_corte")

    disp = float(rollo.get("metros_disponible") or 0)
    m = float(metros_reservar or 0)
    if m <= 0:
        raise ValueError("metros_reservar_debe_ser_positivo")
    if m > disp:
        raise ValueError(f"metros_insuficientes: rollo tiene {disp}m disponibles")

    if existing:
        sb.table("orden_corte_rollos").update({"metros_usados": m}).eq("id", existing[0]["id"]).execute()
    else:
        sb.table("orden_corte_rollos").insert({
            "orden_corte_id": oc_id,
            "rollo_id": rollo["id"],
            "metros_usados": m,
        }).execute()
    # Reserva: el rollo deja de estar disponible para otros cortes
    sb.table("rollos_tela").update({
        "estado": "en_corte", "updated_at": _now_iso(),
    }).eq("id", rollo["id"]).execute()
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
        sb.table("rollos_tela").update({
            "estado": "en_corte", "updated_at": _now_iso(),
        }).eq("id", r["id"]).execute()
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
    # Libera la reserva — solo si no quedó vinculado a otro corte ABIERTO.
    # Los links de órdenes ya cortadas son histórico y no cuentan.
    otros = (sb.table("orden_corte_rollos")
               .select("id,orden_corte:orden_corte_id(estado)")
               .eq("rollo_id", rollo_id).limit(20).execute()).data or []
    abiertos = [o for o in otros
                if (o.get("orden_corte") or {}).get("estado") != "cortada"]
    if not abiertos:
        rollo = obtener_rollo(rollo_id)
        if rollo and rollo.get("estado") == "en_corte":
            sb.table("rollos_tela").update({
                "estado": "disponible", "updated_at": _now_iso(),
            }).eq("id", rollo_id).execute()
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
                        espigas_metros: Optional[dict] = None,
                        retazos_metros: Optional[float] = None,
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

    # Sanitizar unidades_cortadas ANTES de tocar nada — un valor no numérico
    # guardado aquí rompería el tablero y el cruce Siigo para siempre.
    if unidades_cortadas is not None:
        limpio: dict = {}
        for talla, v in (unidades_cortadas or {}).items():
            try:
                limpio[str(talla)] = int(float(v or 0))
            except (TypeError, ValueError):
                raise ValueError(f"unidades_invalidas_talla_{talla}")
        unidades_cortadas = limpio

    # Si el informe viene POR ESPIGAS, el consumo real se recalcula acá
    # (no se confía en el cálculo del cliente):
    #   consumo = Σ (metros_espiga + 0.02) × capas_espiga + retazos_metros
    #   capas_espiga = max(unidades cortadas de las tallas de la espiga)
    ESPIGAS_DEF = (("4",), ("6", "12"), ("8", "10"), ("14", "16"))
    if espigas_metros:
        try:
            unid = {str(k): _int0(v) for k, v in (unidades_cortadas or {}).items()}
            consumo_calc = 0.0
            for esp in ESPIGAS_DEF:
                key = "-".join(esp)
                largo = float(espigas_metros.get(key) or 0)
                capas_e = max([unid.get(t, 0) for t in esp] + [0])
                if largo > 0 and capas_e > 0:
                    consumo_calc += (largo + 0.02) * capas_e
            consumo_calc += float(retazos_metros or 0)
            if consumo_calc > 0:
                consumo_real_cortador = round(consumo_calc, 2)
                total_u = sum(unid.values())
                if total_u > 0 and promedio_real is None:
                    promedio_real = round(consumo_calc / total_u, 4)
        except (TypeError, ValueError):
            raise ValueError("espigas_metros_invalido")

    doc_ref = oc["consecutivo"]

    # PASO 1 — Pre-validar TODOS los rollos antes de descontar ninguno.
    # Si uno no alcanza, se falla aquí sin dejar descuentos a medias.
    descuentos: list[tuple[str, float, float]] = []  # (rollo_id, metros, nuevo_disponible)
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
        descuentos.append((rollo_id, m, nuevo))

    # PASO 2 — Claim atómico: marcar 'cortada' condicionado a que NO lo esté ya.
    # Dos cierres concurrentes → solo uno pasa; el otro recibe orden_ya_cortada.
    claim = (sb.table("ordenes_corte")
               .update({"estado": "cortada", "updated_at": _now_iso()})
               .eq("id", oc_id).neq("estado", "cortada").execute())
    if not claim.data:
        raise ValueError("orden_ya_cortada")

    # PASO 3 — Descontar (ya pre-validado; la reserva 'en_corte' se libera aquí)
    for rollo_id, m, nuevo in descuentos:
        estado_nuevo = "agotado" if nuevo <= 0 else "disponible"
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
    if espigas_metros is not None:  update["espigas_metros"] = espigas_metros
    if retazos_metros is not None:  update["retazos_metros"] = float(retazos_metros)
    if fecha_entrega is not None:    update["fecha_entrega"] = fecha_entrega or None
    if precio_corte is not None:
        update["precio_corte"] = float(precio_corte)
    else:
        # Sin precio digitado → trae el del precosteo (item 'Corte')
        auto = _precio_proceso_precosteo(oc.get("referencia_id"), "corte")
        if auto is not None:
            update["precio_corte"] = auto

    try:
        sb.table("ordenes_corte").update(update).eq("id", oc_id).execute()
    except Exception as e:
        # Compat si la migración del informe no corrió
        cols_informe = ("referencia_lote","capas_real","promedio_real",
                         "unidades_cortadas","retazos_cantidad","fecha_entrega","precio_corte",
                         "espigas_metros","retazos_metros")
        if any(c in str(e) for c in cols_informe):
            log.error(f"[cerrar_corte] {doc_ref}: migración informe faltante — "
                      f"se descartaron columnas del informe del cortador: {e}")
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
    # Liberar la reserva de los rollos asignados ANTES de borrar —
    # si no, quedan en 'en_corte' huérfanos e inutilizables.
    for link in (oc.get("rollos") or []):
        rollo_id = link.get("rollo_id")
        if not rollo_id:
            continue
        rollo = obtener_rollo(rollo_id)
        if rollo and rollo.get("estado") == "en_corte":
            sb.table("rollos_tela").update({
                "estado": "disponible", "updated_at": _now_iso(),
            }).eq("id", rollo_id).execute()
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
                          direccion: Optional[str] = None,
                          tipo: str = "confeccion") -> dict:
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase no configurado")
    if not nombre.strip():
        raise ValueError("nombre_requerido")
    if tipo not in ("confeccion", "terminacion", "lavanderia", "otros"):
        raise ValueError("tipo_invalido")
    row = {
        "nombre":    nombre.strip(),
        "telefono":  (telefono or "").strip() or None,
        "direccion": (direccion or "").strip() or None,
        "tipo":      tipo,
        "activo":    True,
    }
    try:
        r = sb.table("confeccionistas").insert(row).execute()
    except Exception as e:
        # Compat si la columna tipo aún no existe
        if "tipo" in str(e):
            row.pop("tipo", None)
            r = sb.table("confeccionistas").insert(row).execute()
        else:
            raise
    return r.data[0]


def listar_confeccionistas(*, incluir_inactivos: bool = False,
                            tipo: Optional[str] = None,
                            limit: int = 200) -> list[dict]:
    """Lista proveedores. `tipo` opcional: 'confeccion' | 'terminacion'."""
    sb = _sb()
    if sb is None:
        return []
    q = sb.table("confeccionistas").select("*").order("nombre").limit(limit)
    if not incluir_inactivos:
        q = q.eq("activo", True)
    if tipo:
        try:
            q = q.eq("tipo", tipo)
        except Exception:
            pass  # compat si la migración no corrió
    try:
        return q.execute().data or []
    except Exception as e:
        # Compat: si la columna tipo aún no existe y filtramos por ella
        if "tipo" in str(e):
            q2 = sb.table("confeccionistas").select("*").order("nombre").limit(limit)
            if not incluir_inactivos:
                q2 = q2.eq("activo", True)
            return q2.execute().data or []
        raise


def actualizar_confeccionista(cid: str, **campos) -> dict:
    permitidos = {"nombre", "telefono", "direccion", "activo", "tipo"}
    update = {k: v for k, v in campos.items() if k in permitidos and v is not None}
    if not update:
        raise ValueError("nada_que_actualizar")
    if "nombre" in update:
        update["nombre"] = str(update["nombre"]).strip()
    if "tipo" in update and update["tipo"] not in ("confeccion", "terminacion", "lavanderia", "otros"):
        raise ValueError("tipo_invalido")
    update["updated_at"] = _now_iso()
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase no configurado")
    try:
        r = sb.table("confeccionistas").update(update).eq("id", cid).execute()
    except Exception as e:
        # Compat si la columna `tipo` aún no existe en la DB
        if "tipo" in str(e) and "tipo" in update:
            update.pop("tipo", None)
            r = sb.table("confeccionistas").update(update).eq("id", cid).execute()
        else:
            raise
    if not r.data:
        raise ValueError("no_encontrado")
    return r.data[0]


# ═══════════════════════════════════════════════════════════════════════
# BLOQUE 6A — REMISIONES A CONFECCIONISTA
# ═══════════════════════════════════════════════════════════════════════

def crear_remision(*, confeccionista_id: str, fecha_recogida: str,
                    orden_corte_ids: list[str], created_by: str,
                    tipo: str = "confeccion") -> dict:
    """Crea una remisión: entrega de N órdenes de corte cortadas a un proveedor.
    - `tipo`: 'confeccion' o 'terminacion' — define a qué proveedor va y
       qué campo de la hoja de ruta se actualiza (confeccionista_id vs terminacion_id).
    - Genera consecutivo `REM-YYYY-NNNN`.
    """
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase no configurado")
    if not orden_corte_ids:
        raise ValueError("sin_ordenes")
    if tipo not in ("confeccion", "terminacion"):
        raise ValueError("tipo_invalido")

    # Validar proveedor (puede ser confección o terminación — misma tabla)
    c = (sb.table("confeccionistas").select("id,nombre,activo,tipo")
           .eq("id", confeccionista_id).limit(1).execute()).data
    if not c:
        raise ValueError("proveedor_no_encontrado")
    if not c[0].get("activo"):
        raise ValueError("proveedor_inactivo")
    # Coherencia: si tipo=confeccion, el proveedor debe ser de confección (o legacy sin tipo)
    prov_tipo = (c[0].get("tipo") or "confeccion").lower()
    if tipo == "confeccion" and prov_tipo != "confeccion":
        raise ValueError("proveedor_no_es_confeccion")
    if tipo == "terminacion" and prov_tipo != "terminacion":
        raise ValueError("proveedor_no_es_terminacion")

    # Validar órdenes de corte
    ya_remitidas = _ocs_con_remision(tipo)
    for oc_id in orden_corte_ids:
        oc = (sb.table("ordenes_corte").select("id,estado,consecutivo")
                .eq("id", oc_id).limit(1).execute()).data
        if not oc:
            raise ValueError(f"orden_corte_no_encontrada:{oc_id}")
        if oc[0].get("estado") != "cortada":
            raise ValueError(f"orden_no_cortada:{oc[0].get('consecutivo')}")
        # Un lote no puede tener dos remisiones del mismo tipo
        if oc_id in ya_remitidas:
            raise ValueError(f"lote_ya_tiene_remision_{tipo}:{oc[0].get('consecutivo')}")

    codigo = next_consecutivo("REM", width=4)
    row = {
        "consecutivo":       codigo,
        "confeccionista_id": confeccionista_id,   # el "destinatario" de la remisión
        "fecha_recogida":    fecha_recogida,
        "estado":            "generada",
        "tipo":              tipo,
        "created_by":        created_by,
    }
    try:
        r = sb.table("remisiones").insert(row).execute()
    except Exception as e:
        # Compat si la columna tipo aún no existe
        if "tipo" in str(e):
            row.pop("tipo", None)
            r = sb.table("remisiones").insert(row).execute()
        else:
            raise
    if not r.data:
        raise RuntimeError("no_se_pudo_crear_remision")
    rem = r.data[0]

    # Items
    items_rows = [
        {"remision_id": rem["id"], "orden_corte_id": oc_id}
        for oc_id in orden_corte_ids
    ]
    sb.table("remision_items").insert(items_rows).execute()

    # Actualiza hoja de ruta según tipo:
    #   confeccion → auto-crea la ruta con confeccionista_id (comportamiento original)
    #   terminacion → busca la ruta existente y le asigna terminacion_id
    for oc_id in orden_corte_ids:
        try:
            existente = obtener_ruta_por_corte(oc_id)
            if tipo == "confeccion":
                if existente:
                    continue
                crear_ruta_lote(
                    orden_corte_id=oc_id,
                    confeccionista_id=confeccionista_id,
                    remision_id=rem["id"],
                    created_by=created_by,
                )
            else:  # terminacion
                if not existente:
                    # Primero debería existir una remisión de confección para esta OC.
                    # Igual creamos la ruta con un placeholder para que sea usable.
                    log.warning(f"[remision-terminacion] OC {oc_id} sin ruta previa, se salta")
                    continue
                # Precio de terminación: sale del precosteo firmado (bloqueado)
                oc_row = obtener_orden_corte(oc_id) or {}
                precio_term = existente.get("precio_terminacion") or _precio_proceso_precosteo(
                    oc_row.get("referencia_id"), "terminacion")
                actualizar_ruta_lote(existente["id"], terminacion_id=confeccionista_id,
                                     precio_terminacion=precio_term)
        except Exception as e:
            log.warning(f"[remision] no se pudo actualizar ruta {oc_id}: {e}")

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
                       "unidades_cortadas,fecha_entrega,promedio_real,"
                       "consumo_real_cortador,retazos_metros,retazos_cantidad,"
                       "referencia:referencia_id(codigo_referencia,nombre,tela,color))")
               .eq("remision_id", rem_id).execute()).data or []
    return {**r[0], "items": items}


def marcar_remision_recogida(rem_id: str, usuario: str = "sistema") -> dict:
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase no configurado")
    # Update CONDICIONAL: solo si aún no estaba recogida — así el descuento
    # de insumos corre exactamente UNA vez aunque haya doble click.
    r = (sb.table("remisiones").update({
        "estado": "recogida",
        "updated_at": _now_iso(),
    }).eq("id", rem_id).neq("estado", "recogida").execute()).data
    if not r:
        # Ya estaba recogida (o no existe) — devolver estado actual sin re-descontar
        rem = obtener_remision(rem_id)
        if not rem:
            raise ValueError("no_encontrado")
        return rem
    rem = obtener_remision(rem_id)
    # SALIDA automática de insumos del inventario (tolerante a fallos:
    # la remisión queda marcada aunque el descuento falle — se loggea)
    try:
        descontados = descontar_insumos_remision(rem, usuario)
        if descontados:
            log.info(f"[insumos] remisión {rem.get('consecutivo')}: "
                     f"{len(descontados)} insumos descontados")
    except Exception as e:
        log.warning(f"[insumos] descuento remisión {rem_id} falló: {e}")

    # NOTIFICACIÓN al proveedor: mensaje con el link de su ficha para que
    # verifique y acepte. Si la WhatsApp Cloud API está configurada se envía
    # SOLO; si no, el frontend recibe el wa.me armado y lo abre de una.
    try:
        rem["whatsapp"] = _notificar_remision_whatsapp(rem)
    except Exception as e:
        log.warning(f"[wa] notificación remisión {rem_id} falló: {e}")
        rem["whatsapp"] = []
    return rem


def _notificar_remision_whatsapp(rem: dict) -> list[dict]:
    """Arma (y si se puede, ENVÍA) el WhatsApp por cada lote de la remisión."""
    from urllib.parse import quote
    from backend.services import whatsapp_cloud as wa

    es_term = (rem.get("tipo") or "confeccion") == "terminacion"
    prov = rem.get("confeccionista") or {}
    tel = (prov.get("telefono") or "").strip()
    base = os.environ.get("APP_PUBLIC_URL", "https://app.maledenim.com").rstrip("/")
    salidas = []
    for it in (rem.get("items") or []):
        ruta = obtener_ruta_por_corte(it["orden_corte_id"])
        if not ruta:
            continue
        token = ruta.get("token_publico_terminacion") if es_term else ruta.get("token_publico")
        if not token:
            continue
        link = f"{base}/{'terminacion' if es_term else 'lote'}/{token}"
        oc = it.get("orden_corte") or {}
        ref = (oc.get("referencia") or {}).get("codigo_referencia") or oc.get("consecutivo") or ""
        mensaje = (f"Hola {prov.get('nombre') or ''}, MALE'DENIM te despachó el lote "
                   f"referencia *{ref}*. Verifica cantidades e insumos en tu ficha y "
                   f"confirma con \"Aceptar lote\":\n\n{link}")
        envio = wa.enviar_texto(tel, mensaje)
        tel_norm = "".join(c for c in tel if c.isdigit())
        tel_norm = tel_norm if tel_norm.startswith("57") else (f"57{tel_norm}" if tel_norm else "")
        salidas.append({
            "referencia": ref,
            "telefono": tel_norm,
            "enviado": bool(envio.get("enviado")),
            "wa_url": (f"https://wa.me/{tel_norm}?text={quote(mensaje)}"
                       if tel_norm else f"https://wa.me/?text={quote(mensaje)}"),
        })
    return salidas


# ═══════════════════════════════════════════════════════════════════════
# INSUMOS REQUERIDOS POR ORDEN DE CORTE (auto desde precosteo)
# ═══════════════════════════════════════════════════════════════════════

# Qué categorías del precosteo se consideran "insumos que van con el corte"
CATEGORIAS_INSUMOS_CORTE = ("INSUMO CONFECCION", "INSUMO TERMINACION")


def calcular_insumos_requeridos_corte(
    oc_id: str,
    categorias: Optional[tuple[str, ...]] = None,
) -> dict:
    """Dado un corte, calcula los insumos que se necesitan multiplicando la
    cantidad de cada insumo del precosteo por la cantidad de prendas a cortar.

    Si `categorias` viene, restringe a esas categorías (útil para separar la
    remisión de confección de la de terminación).

    Regla:
      total_requerido = item.cantidad (del precosteo, por prenda)
                        × cantidad_a_cortar (de la OC)

    Cantidad base:
      - Si la orden ya está cerrada → usa la suma real cortada por talla.
      - Si sigue en proceso → usa cantidad_programada (o suma de la curva).
    """
    oc = obtener_orden_corte(oc_id)
    if not oc:
        raise ValueError("orden_no_encontrada")

    # Cantidad base para el cálculo
    if oc.get("estado") == "cortada":
        unidades = oc.get("unidades_cortadas") or {}
        cantidad_base = sum(int(v or 0) for v in unidades.values())
        origen = "unidades_cortadas"
    else:
        cantidad_base = int(oc.get("cantidad_programada") or 0)
        if cantidad_base <= 0:
            curva = oc.get("curva_trazo") or {}
            cantidad_base = sum(int(v or 0) for v in curva.values())
            origen = "suma_curva"
        else:
            origen = "cantidad_programada"

    ref = oc.get("referencia") or {}
    ref_id = oc.get("referencia_id")
    if not ref_id or cantidad_base <= 0:
        return {
            "cantidad_base": cantidad_base,
            "origen_cantidad": origen,
            "referencia": ref.get("codigo_referencia"),
            "items": [],
            "total_costo": 0,
        }

    p = obtener_precosteo(ref_id)
    if not p:
        return {
            "cantidad_base": cantidad_base,
            "origen_cantidad": origen,
            "referencia": ref.get("codigo_referencia"),
            "items": [],
            "total_costo": 0,
        }

    cats_filtro = tuple(c.upper() for c in categorias) if categorias else CATEGORIAS_INSUMOS_CORTE
    items = []
    total_costo = 0.0
    for it in (p.get("items") or []):
        cat = (it.get("categoria") or "").upper().strip()
        if cat not in cats_filtro:
            continue
        base_por_prenda = float(it.get("cantidad") or 0)
        if base_por_prenda <= 0:
            continue
        total_req = round(base_por_prenda * cantidad_base, 3)
        vu = float(it.get("valor_unitario") or 0)
        costo = round(vu * total_req, 2)
        total_costo += costo
        items.append({
            "categoria":           cat,
            "item":                it.get("item"),
            "cantidad_por_prenda": base_por_prenda,
            "total_requerido":     total_req,
            "valor_unitario":      vu,
            "costo_total":         costo,
        })

    return {
        "orden_corte":     oc.get("consecutivo"),
        "referencia":      ref.get("codigo_referencia"),
        "nombre":          ref.get("nombre"),
        "cantidad_base":   cantidad_base,
        "origen_cantidad": origen,
        "items":           items,
        "total_costo":     round(total_costo, 2),
    }


# ═══════════════════════════════════════════════════════════════════════
# HOJA DE RUTA · confección → gap lavandería → terminación → despacho
# ═══════════════════════════════════════════════════════════════════════

# Estados válidos ordenados
ETAPAS_RUTA = (
    "asignado",              # link enviado, confeccionista aún no acepta
    "aceptado",              # confeccionista aceptó
    "en_confeccion",         # trabajando (opcional; puede saltar directo a lavandería)
    "lavanderia",            # confeccionista terminó, envió a lavandería
    "terminacion_recibida",  # lavandería entregó a terminación
    "terminacion_terminada", # terminación terminó
    "despachado",            # despacho hecho
)


def _ruta_orden_map():
    return {e: i for i, e in enumerate(ETAPAS_RUTA)}


def obtener_ruta_por_corte(oc_id: str) -> Optional[dict]:
    sb = _sb()
    if sb is None:
        return None
    r = (sb.table("hoja_ruta_lote")
           .select("*,confeccionista:confeccionista_id(nombre,telefono),"
                   "terminacion:terminacion_id(nombre,telefono),"
                   "lavanderia:lavanderia_id(nombre,telefono),"
                   "orden_corte:orden_corte_id(consecutivo,curva_trazo,unidades_cortadas,"
                   "cantidad_programada,referencia_lote,"
                   "referencia:referencia_id(codigo_referencia,nombre,tela,color,foto_url))")
           .eq("orden_corte_id", oc_id).limit(1).execute()).data
    return r[0] if r else None


def obtener_ruta_por_token_terminacion(token: str) -> Optional[dict]:
    sb = _sb()
    if sb is None:
        return None
    try:
        r = (sb.table("hoja_ruta_lote")
               .select("*,terminacion:terminacion_id(nombre),"
                       "orden_corte:orden_corte_id(consecutivo,curva_trazo,unidades_cortadas,"
                       "cantidad_programada,referencia_lote,fecha_entrega,"
                       "referencia:referencia_id(codigo_referencia,nombre,tela,color,foto_url))")
               .eq("token_publico_terminacion", token).limit(1).execute()).data
    except Exception:
        return None
    return r[0] if r else None


def obtener_ruta_por_token(token: str) -> Optional[dict]:
    sb = _sb()
    if sb is None:
        return None
    r = (sb.table("hoja_ruta_lote")
           .select("*,confeccionista:confeccionista_id(nombre),"
                   "orden_corte:orden_corte_id(consecutivo,curva_trazo,unidades_cortadas,"
                   "cantidad_programada,referencia_lote,fecha_entrega,"
                   "referencia:referencia_id(codigo_referencia,nombre,tela,color,foto_url))")
           .eq("token_publico", token).limit(1).execute()).data
    return r[0] if r else None


def _precio_proceso_precosteo(referencia_id: Optional[str], proceso: str) -> Optional[float]:
    """Busca en el precosteo el valor unitario del proceso 'confeccion' o
    'terminacion' (items de PROCESO EN MATERIA PRIMA). El precio del lote
    sale del precosteo firmado — no se digita a mano.
    """
    if not referencia_id:
        return None
    p = obtener_precosteo(referencia_id)
    if not p:
        return None
    import unicodedata
    def _norm(s: str) -> str:
        return unicodedata.normalize("NFD", (s or "")).encode("ascii", "ignore").decode().lower().strip()
    target = _norm(proceso)
    for it in (p.get("items") or []):
        cat = _norm(it.get("categoria") or "")
        if "proceso" not in cat:
            continue
        if target in _norm(it.get("item") or ""):
            vu = float(it.get("valor_unitario") or 0)
            return vu if vu > 0 else None
    return None


def crear_ruta_lote(*, orden_corte_id: str, confeccionista_id: str,
                     precio_confeccion: Optional[float] = None,
                     fecha_entrega_confeccion: Optional[str] = None,
                     remision_id: Optional[str] = None,
                     created_by: str) -> dict:
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase no configurado")
    # Verificar que la OC exista y esté cortada
    oc = obtener_orden_corte(orden_corte_id)
    if not oc:
        raise ValueError("orden_no_encontrada")
    if oc.get("estado") != "cortada":
        raise ValueError("orden_no_cortada")
    # Si ya existe hoja, devolverla (una sola por OC)
    existente = obtener_ruta_por_corte(orden_corte_id)
    if existente:
        return existente
    # Precio de confección: sale del precosteo firmado (bloqueado, no se digita)
    if precio_confeccion is None:
        precio_confeccion = _precio_proceso_precosteo(oc.get("referencia_id"), "confeccion")
    row = {
        "orden_corte_id":           orden_corte_id,
        "confeccionista_id":        confeccionista_id,
        "precio_confeccion":        float(precio_confeccion) if precio_confeccion is not None else None,
        "fecha_entrega_confeccion": fecha_entrega_confeccion or None,
        "remision_id":              remision_id or None,
        "etapa":                    "asignado",
        "created_by":               created_by,
    }
    sb.table("hoja_ruta_lote").insert(row).execute()
    return obtener_ruta_por_corte(orden_corte_id)


def actualizar_ruta_lote(ruta_id: str, **campos) -> dict:
    permitidos = {
        "confeccionista_id", "terminacion_id", "lavanderia_id",
        "precio_confeccion", "precio_terminacion",
        "fecha_entrega_confeccion", "remision_lavanderia_url",
        "notas", "nota_confeccionista", "nota_terminacion",
    }
    update = {k: v for k, v in campos.items() if k in permitidos and v is not None}
    if not update:
        raise ValueError("nada_que_actualizar")
    update["updated_at"] = _now_iso()
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase no configurado")
    # Al asignar terminación sin precio: trae el precio del precosteo (bloqueado)
    if "terminacion_id" in update and "precio_terminacion" not in update:
        try:
            ruta = (sb.table("hoja_ruta_lote").select("orden_corte_id,precio_terminacion")
                      .eq("id", ruta_id).limit(1).execute()).data
            if ruta and not ruta[0].get("precio_terminacion"):
                oc_row = (sb.table("ordenes_corte").select("referencia_id")
                            .eq("id", ruta[0]["orden_corte_id"]).limit(1).execute()).data
                if oc_row:
                    p = _precio_proceso_precosteo(oc_row[0].get("referencia_id"), "terminacion")
                    if p is not None:
                        update["precio_terminacion"] = p
        except Exception as e:
            log.warning(f"[ruta] auto-precio terminacion fallo: {e}")
    try:
        r = sb.table("hoja_ruta_lote").update(update).eq("id", ruta_id).execute()
    except Exception as e:
        # Compat si la migración de notas aún no corrió
        msg = str(e)
        if "nota_confeccionista" in msg or "nota_terminacion" in msg:
            for c in ("nota_confeccionista", "nota_terminacion"):
                if c in update:
                    # Fallback: guarda en notas plana
                    update.setdefault("notas", update.pop(c))
            r = sb.table("hoja_ruta_lote").update(update).eq("id", ruta_id).execute()
        else:
            raise
    if not r.data:
        raise ValueError("no_encontrada")
    # Regla: guardar la remisión de recogida de la lavandería marca la etapa
    # 'lavanderia' de una vez (sin botón aparte).
    if update.get("remision_lavanderia_url"):
        try:
            avanzar_etapa_si_antes(ruta_id, "lavanderia")
        except Exception as e:
            log.warning(f"[ruta] avance a lavanderia (patch) fallo: {e}")
        r2 = (sb.table("hoja_ruta_lote").select("*").eq("id", ruta_id).limit(1).execute()).data
        if r2:
            return r2[0]
    return r.data[0]


def cambiar_etapa_ruta(ruta_id: str, etapa_nueva: str) -> dict:
    """Cambia la etapa y estampa el timestamp correspondiente.
    No permite retroceder (a menos que sea admin — no expuesto por defecto).
    """
    orden = _ruta_orden_map()
    if etapa_nueva not in orden:
        raise ValueError(f"etapa_invalida:{etapa_nueva}")

    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase no configurado")
    r = (sb.table("hoja_ruta_lote").select("etapa").eq("id", ruta_id).limit(1).execute()).data
    if not r:
        raise ValueError("no_encontrada")
    actual = r[0].get("etapa") or "asignado"
    if orden[etapa_nueva] < orden.get(actual, 0):
        raise ValueError(f"no_se_puede_retroceder:{actual}→{etapa_nueva}")

    ts_col_por_etapa = {
        "aceptado":              "aceptado_at",
        "en_confeccion":         "confeccion_iniciada_at",
        "lavanderia":            "lavanderia_at",
        "terminacion_recibida":  "terminacion_recibida_at",
        "terminacion_terminada": "terminacion_terminada_at",
        "despachado":            "despachado_at",
    }
    now = _now_iso()
    update = {"etapa": etapa_nueva, "updated_at": now}
    ts_col = ts_col_por_etapa.get(etapa_nueva)
    if ts_col:
        update[ts_col] = now
    sb.table("hoja_ruta_lote").update(update).eq("id", ruta_id).execute()
    r = (sb.table("hoja_ruta_lote").select("*").eq("id", ruta_id).limit(1).execute()).data
    return r[0] if r else {}


def avanzar_etapa_si_antes(ruta_id: str, etapa_objetivo: str) -> Optional[dict]:
    """Avanza la etapa SOLO si la actual va antes que la objetivo.
    Si ya está en esa etapa o más adelante, no hace nada (idempotente)."""
    orden = _ruta_orden_map()
    if etapa_objetivo not in orden:
        raise ValueError(f"etapa_invalida:{etapa_objetivo}")
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase no configurado")
    r = (sb.table("hoja_ruta_lote").select("etapa").eq("id", ruta_id).limit(1).execute()).data
    if not r:
        raise ValueError("no_encontrada")
    actual = r[0].get("etapa") or "asignado"
    if orden.get(actual, 0) >= orden[etapa_objetivo]:
        return None
    return cambiar_etapa_ruta(ruta_id, etapa_objetivo)


def subir_remision_lavanderia(ruta_id: str, *, file_bytes: bytes, filename: str,
                              content_type: str,
                              lavanderia_id: Optional[str] = None) -> dict:
    """Sube la foto/PDF de la remisión de recogida de la lavandería y marca
    la etapa 'lavanderia' INMEDIATAMENTE (regla de Sebastián: el estado de
    lavandería se marca al subir la remisión de recogida)."""
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase no configurado")
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "pdf").lower()
    if ext not in ("pdf", "png", "jpg", "jpeg", "webp"):
        raise ValueError("formato_no_soportado")
    bucket = "produccion-trazos"
    path = f"rutas/{ruta_id}/remision_lavanderia.{ext}"
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
        raise RuntimeError(f"subir_remision_lavanderia: {str(e)[:200]}")
    url = sb.storage.from_(bucket).get_public_url(path)
    update = {"remision_lavanderia_url": url, "updated_at": _now_iso()}
    if lavanderia_id:
        update["lavanderia_id"] = lavanderia_id
    sb.table("hoja_ruta_lote").update(update).eq("id", ruta_id).execute()
    try:
        avanzar_etapa_si_antes(ruta_id, "lavanderia")
    except Exception as e:
        log.warning(f"[ruta] avance a lavanderia fallo: {e}")
    r = (sb.table("hoja_ruta_lote").select("*").eq("id", ruta_id).limit(1).execute()).data
    return {"url": url, "ruta": r[0] if r else {}}


def listar_rutas(*, etapa: Optional[str] = None,
                  confeccionista_id: Optional[str] = None,
                  limit: int = 200) -> list[dict]:
    sb = _sb()
    if sb is None:
        return []
    q = (sb.table("hoja_ruta_lote")
           .select("*,confeccionista:confeccionista_id(nombre),"
                   "terminacion:terminacion_id(nombre),"
                   "lavanderia:lavanderia_id(nombre),"
                   "orden_corte:orden_corte_id(consecutivo,"
                   "referencia:referencia_id(codigo_referencia,nombre,tela))")
           .order("created_at", desc=True).limit(limit))
    if etapa:
        q = q.eq("etapa", etapa)
    if confeccionista_id:
        q = q.eq("confeccionista_id", confeccionista_id)
    return q.execute().data or []


# ═══════════════════════════════════════════════════════════════════════
# NOTAS · timeline por hoja de ruta
# ═══════════════════════════════════════════════════════════════════════

def crear_nota_ruta(*, ruta_id: str, actor: str, mensaje: str,
                     autor: Optional[str] = None) -> dict:
    """Agrega una nota al histórico de la ruta.
    - actor: 'confeccionista' | 'terminacion' | 'admin'
    - autor: email o identificador (opcional)
    """
    if actor not in ("confeccionista", "terminacion", "admin"):
        raise ValueError("actor_invalido")
    msg = (mensaje or "").strip()
    if not msg:
        raise ValueError("mensaje_vacio")
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase no configurado")
    row = {
        "ruta_id": ruta_id,
        "actor":   actor,
        "autor":   autor or None,
        "mensaje": msg[:5000],
    }
    r = sb.table("notas_hoja_ruta").insert(row).execute()
    if not r.data:
        raise RuntimeError("no_se_pudo_crear_nota")
    return r.data[0]


def listar_notas_ruta(ruta_id: str) -> list[dict]:
    sb = _sb()
    if sb is None:
        return []
    try:
        r = (sb.table("notas_hoja_ruta")
               .select("*")
               .eq("ruta_id", ruta_id)
               .order("created_at", desc=False)
               .limit(500)
               .execute())
        return r.data or []
    except Exception as e:
        # Compat si la migración aún no corrió
        log.warning(f"[notas] tabla notas_hoja_ruta no disponible: {e}")
        return []


# ═══════════════════════════════════════════════════════════════════════
# TABLERO DE PRODUCCIÓN · eficiencia + stock + valor + ruta
# ═══════════════════════════════════════════════════════════════════════


def _int0(v) -> int:
    """int tolerante: valores no numéricos (datos viejos) cuentan como 0."""
    try:
        return int(float(v or 0))
    except (TypeError, ValueError):
        return 0


STOCK_MINIMO_METROS = 50  # tela+tono con menos de esto se marca "baja"


def tablero_produccion() -> dict:
    """KPIs del módulo de producción. Cache 60s.

    - Inventario: metros disponibles, valor, telas bajo stock mínimo.
    - Corte: unidades cortadas del mes, eficiencia teórico vs real.
    - Ruta: lotes por etapa + lotes estancados (>7 días sin ingreso a bodega).
    """
    cache_key = "tablero_produccion"
    cached = _cache_get(cache_key, ttl_seg=60)
    if cached is not None:
        return cached
    sb = _sb()
    if sb is None:
        return {}

    # ── Inventario ────────────────────────────────────────────────
    inv = inventario_resumen()
    metros_disp = round(sum(t["metros_disponible"] for t in inv), 2)
    valor_inv = round(sum(t["valor_estimado"] for t in inv), 0)
    telas_bajas = [t for t in inv if 0 < t["metros_disponible"] < STOCK_MINIMO_METROS]

    # ── Cortes ────────────────────────────────────────────────────
    cortes = listar_ordenes_corte(estado="cortada", limit=200)
    hoy = datetime.now(timezone.utc)
    mes_actual = (hoy.year, hoy.month)

    unidades_mes = 0
    metros_teoricos = 0.0
    metros_reales = 0.0
    ultimos = []
    for oc in cortes:
        try:
            created = datetime.fromisoformat(str(oc.get("created_at", "")).replace("Z", "+00:00"))
        except Exception:
            created = None
        unidades = sum(_int0(v) for v in (oc.get("unidades_cortadas") or {}).values())
        if created and (created.year, created.month) == mes_actual:
            unidades_mes += unidades
        teo = float(oc.get("metros_consumidos") or 0)
        real = float(oc.get("consumo_real_cortador") or 0)
        if teo > 0 and real > 0:
            metros_teoricos += teo
            metros_reales += real
        if len(ultimos) < 10:
            ref = oc.get("referencia") or {}
            ultimos.append({
                "id":             oc["id"],
                "consecutivo":    oc.get("consecutivo"),
                "referencia":     ref.get("codigo_referencia"),
                "nombre":         ref.get("nombre"),
                "unidades":       unidades,
                "metros_teorico": teo,
                "metros_real":    real,
                "diferencia_pct": oc.get("diferencia_pct"),
                "promedio_real":  oc.get("promedio_real"),
            })

    eficiencia_pct = (
        round((metros_reales - metros_teoricos) / metros_teoricos * 100, 2)
        if metros_teoricos > 0 else None
    )

    # ── Ruta (lotes en proceso) ───────────────────────────────────
    rutas = (sb.table("hoja_ruta_lote")
               .select("etapa,asignado_at,despachado_at,"
                       "orden_corte:orden_corte_id(consecutivo)")
               .limit(500).execute()).data or []
    por_etapa: dict[str, int] = {}
    estancados = []
    for r in rutas:
        etapa = r.get("etapa") or "asignado"
        por_etapa[etapa] = por_etapa.get(etapa, 0) + 1
        if etapa != "despachado" and r.get("asignado_at"):
            try:
                asignado = datetime.fromisoformat(str(r["asignado_at"]).replace("Z", "+00:00"))
                dias = (hoy - asignado).days
                if dias > 7:
                    estancados.append({
                        "consecutivo": (r.get("orden_corte") or {}).get("consecutivo"),
                        "etapa": etapa,
                        "dias": dias,
                    })
            except Exception:
                pass
    estancados.sort(key=lambda x: -x["dias"])

    out = {
        "inventario": {
            "metros_disponibles": metros_disp,
            "valor_estimado":     valor_inv,
            "num_telas":          len(inv),
            "telas_bajas":        telas_bajas[:10],
            "stock_minimo":       STOCK_MINIMO_METROS,
        },
        "corte": {
            "ordenes_cortadas":  len(cortes),
            "unidades_mes":      unidades_mes,
            "eficiencia_pct":    eficiencia_pct,  # + = se gastó más tela que lo teórico
            "metros_teoricos":   round(metros_teoricos, 2),
            "metros_reales":     round(metros_reales, 2),
            "ultimos":           ultimos,
        },
        "ruta": {
            "por_etapa":   por_etapa,
            "en_proceso":  sum(v for k, v in por_etapa.items() if k != "despachado"),
            "en_bodega":   por_etapa.get("despachado", 0),
            "estancados":  estancados[:10],
        },
    }
    _cache_set(cache_key, out, ttl_seg=60)
    return out


# ═══════════════════════════════════════════════════════════════════════
# CRUCE SIIGO · costeo real vs precosteo (Bloque 5)
# ═══════════════════════════════════════════════════════════════════════

# Tolerancia: desviaciones de precio/cantidad menores a esto no alertan
TOLERANCIA_PRECIO_PCT = 1.0   # %
TOLERANCIA_CANTIDAD = 0       # unidades exactas


def cruce_costeo_siigo(*, desde: Optional[str] = None) -> dict:
    """Cruza los lotes cortados contra los Documentos Soporte de Siigo.

    Match por REFERENCIA: la auxiliar registra el DS con producto
    "Servicio de Confección REF <codigo_referencia>". Se compara:
      teórico = unidades_cortadas × precio_confeccion (del precosteo)
      real    = cantidad × valor_unitario del DS

    Devuelve lotes cruzados + alertas:
      - sin_ds:            lote asignado a confección sin DS contabilizado
      - precio_distinto:   valor unitario del DS ≠ precio del precosteo
      - cantidad_distinta: cantidad del DS ≠ unidades cortadas
      - ds_sin_lote:       DS con REF que no corresponde a ningún lote
    """
    from backend.services import siigo

    if not siigo.siigo_configurado():
        return {"ok": False, "error": "siigo_no_configurado",
                "mensaje": "Faltan SIIGO_USERNAME / SIIGO_ACCESS_KEY / SIIGO_PARTNER_ID en Railway."}

    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase no configurado")

    # ── Lotes: cortadas con su ruta y referencia ─────────────────
    ocs = listar_ordenes_corte(estado="cortada", limit=500)
    rutas = (sb.table("hoja_ruta_lote")
               .select("orden_corte_id,precio_confeccion,etapa,lavanderia_at,confeccionista:confeccionista_id(nombre)")
               .limit(500).execute()).data or []
    ruta_por_oc = {r["orden_corte_id"]: r for r in rutas if r.get("orden_corte_id")}

    def _norm_ref(s: Optional[str]) -> str:
        return (s or "").upper().replace(" ", "").strip("-")

    lotes = []
    lotes_por_ref: dict[str, dict] = {}
    for oc in ocs:
        d = (oc.get("created_at") or "")[:10]
        if desde and d and d < desde:
            continue
        ref = _norm_ref((oc.get("referencia") or {}).get("codigo_referencia"))
        ruta = ruta_por_oc.get(oc["id"])
        unidades = sum(_int0(v) for v in (oc.get("unidades_cortadas") or {}).values())
        precio = float((ruta or {}).get("precio_confeccion") or 0)
        lote = {
            "orden_corte_id": oc["id"],
            "consecutivo":    oc.get("consecutivo"),
            "referencia":     (oc.get("referencia") or {}).get("codigo_referencia"),
            "confeccionista": ((ruta or {}).get("confeccionista") or {}).get("nombre"),
            # El DS se vuelve exigible cuando el confeccionista ENTREGÓ
            # (lote pasó a lavandería). Antes de eso no se alerta.
            "entregado_at":   (ruta or {}).get("lavanderia_at"),
            "unidades":       unidades,
            "precio_teorico": precio,
            "total_teorico":  round(unidades * precio, 2),
            "tiene_ruta":     bool(ruta),
            "ds":             None,
            "estado":         "sin_ds" if ruta else "sin_asignar",
        }
        lotes.append(lote)
        if ref:
            lotes_por_ref[ref] = lote

    # ── Documentos soporte de Siigo ──────────────────────────────
    # Sin `desde` explícito, solo traer DS desde el primer lote del OS —
    # los DS históricos pre-sistema no cruzan con nada y pedir su detalle
    # uno a uno se comería el rate limit.
    desde_siigo = desde
    if not desde_siigo and ocs:
        fechas = sorted((oc.get("created_at") or "")[:10] for oc in ocs if oc.get("created_at"))
        desde_siigo = fechas[0] if fechas else None
    try:
        docs = siigo.listar_documentos_soporte(desde=desde_siigo)
    except Exception as e:
        return {"ok": False, "error": "siigo_error", "mensaje": str(e)[:300]}

    # PASO 1 — Recolectar TODOS los items que matchean cada lote.
    # Un lote puede pagarse en varios DS (pagos parciales): se ACUMULAN,
    # no se pisan (last-wins subestimaba el total y daba alertas falsas).
    #
    # Matching en 2 niveles:
    #   1. REF extraída por regex ("Servicio de Confección REF 94608-1")
    #   2. Fallback: buscar cada referencia conocida como substring de la
    #      descripción normalizada — cubre digitación sin la palabra REF
    #      (ej. "Confección lote 94608-1"). Solo refs de 4+ caracteres
    #      para no matchear por accidente.
    def _match_fallback(descripcion: str):
        desc_norm = _norm_ref(descripcion)
        for ref_conocida, lote_c in lotes_por_ref.items():
            if len(ref_conocida) >= 4 and ref_conocida in desc_norm:
                return lote_c
        return None

    ds_sin_lote = []
    matches: dict[str, list] = {}   # orden_corte_id → [(doc, item)]
    for doc in docs:
        for it in doc["items"]:
            ref = _norm_ref(it.get("ref"))
            lote = lotes_por_ref.get(ref) if ref else None
            if not lote:
                lote = _match_fallback(it.get("descripcion") or "")
            if not lote:
                ds_sin_lote.append({
                    "ds":         doc["ds"],
                    "fecha":      doc["fecha"],
                    "proveedor":  doc.get("proveedor_nombre") or doc.get("proveedor_id"),
                    "descripcion": it["descripcion"],
                    "total":      it["total_sin_iva"],
                })
                continue
            matches.setdefault(lote["orden_corte_id"], []).append((doc, it))

    # PASO 2 — Evaluar cada lote contra la SUMA de sus DS.
    for lote in lotes:
        pares = matches.get(lote["orden_corte_id"]) or []
        if not pares:
            continue
        cantidad_total = sum(it["cantidad"] for _, it in pares)
        total_real = round(sum(it["total_sin_iva"] for _, it in pares), 2)
        valor_unit = round(total_real / cantidad_total, 2) if cantidad_total > 0 else 0
        lote["ds"] = {
            "ds":              " + ".join(d["ds"] for d, _ in pares),
            "fecha":           max(d["fecha"] for d, _ in pares),
            "proveedor":       (pares[0][0].get("proveedor_nombre")
                                or pares[0][0].get("proveedor_id")),
            "cantidad":        cantidad_total,
            "valor_unitario":  valor_unit,
            "total_real":      total_real,
            "saldo_por_pagar": round(sum(
                d["balance"] for d in {d["ds"]: d for d, _ in pares}.values()), 2),
        }
        dif_precio_pct = (
            abs(valor_unit - lote["precio_teorico"]) / lote["precio_teorico"] * 100
            if lote["precio_teorico"] > 0 else 0
        )
        if lote["precio_teorico"] > 0 and dif_precio_pct > TOLERANCIA_PRECIO_PCT:
            lote["estado"] = "precio_distinto"
        elif lote["unidades"] > 0 and abs(cantidad_total - lote["unidades"]) > TOLERANCIA_CANTIDAD:
            lote["estado"] = "cantidad_distinta"
        else:
            lote["estado"] = "ok"
        lote["desviacion"] = round(total_real - lote["total_teorico"], 2)

    # ── Alertas ──────────────────────────────────────────────────
    alertas = []
    ahora = datetime.now(timezone.utc)
    for l in lotes:
        if l["estado"] == "sin_ds":
            # Solo alerta si el lote ya fue ENTREGADO al siguiente proceso
            # (salió a lavandería) hace más de 1 día y sigue sin DS.
            entregado = l.get("entregado_at")
            if not entregado:
                continue  # el confeccionista aún trabaja — no es exigible
            try:
                ent_dt = datetime.fromisoformat(str(entregado).replace("Z", "+00:00"))
            except (TypeError, ValueError):
                continue
            if (ahora - ent_dt).total_seconds() < 86400:
                continue  # menos de 1 día — gracia para contabilizar
            dias = int((ahora - ent_dt).total_seconds() // 86400)
            alertas.append({
                "tipo": "sin_ds", "severidad": "media",
                "mensaje": f"Lote {l['consecutivo']} (REF {l['referencia']}) — "
                           f"{l['confeccionista'] or 'confección'} entregó hace {dias} día(s) "
                           f"y aún no tiene documento soporte en Siigo.",
            })
        elif l["estado"] == "precio_distinto":
            ds = l["ds"]
            alertas.append({
                "tipo": "precio_distinto", "severidad": "alta",
                "mensaje": f"Lote {l['consecutivo']}: DS {ds['ds']} pagó "
                           f"${ds['valor_unitario']:,.0f}/prenda pero el precosteo dice "
                           f"${l['precio_teorico']:,.0f} (desviación ${l['desviacion']:,.0f}).",
            })
        elif l["estado"] == "cantidad_distinta":
            ds = l["ds"]
            alertas.append({
                "tipo": "cantidad_distinta", "severidad": "alta",
                "mensaje": f"Lote {l['consecutivo']}: DS {ds['ds']} contabilizó "
                           f"{ds['cantidad']:.0f} unidades pero se cortaron {l['unidades']}.",
            })
    for d in ds_sin_lote:
        alertas.append({
            "tipo": "ds_sin_lote", "severidad": "media",
            "mensaje": f"DS {d['ds']} de {d['proveedor']} (\"{d['descripcion'][:60]}\") "
                       f"por ${d['total']:,.0f} no corresponde a ningún lote del OS.",
        })

    total_teorico = round(sum(l["total_teorico"] for l in lotes), 2)
    total_real = round(sum((l.get("ds") or {}).get("total_real", 0) for l in lotes), 2)

    return {
        "ok": True,
        "resumen": {
            "lotes":          len(lotes),
            "con_ds":         sum(1 for l in lotes if l.get("ds")),
            "ok":             sum(1 for l in lotes if l["estado"] == "ok"),
            "con_alerta":     len(alertas),
            "total_teorico":  total_teorico,
            "total_real":     total_real,
            "desviacion":     round(total_real - total_teorico, 2),
        },
        "lotes":       lotes,
        "ds_sin_lote": ds_sin_lote,
        "alertas":     alertas,
    }


# ═══════════════════════════════════════════════════════════════════════
# ALERTAS DE PRODUCCIÓN · agregador (tablero + cruce Siigo)
# ═══════════════════════════════════════════════════════════════════════

def alertas_produccion(*, incluir_costeo: bool = True) -> dict:
    """Junta TODAS las alertas del módulo de producción en una sola lista:
      - stock_bajo:   tela+tono bajo el mínimo (tablero)
      - estancado:    lote >7 días sin llegar a bodega (tablero)
      - costeo:       desviaciones del cruce Siigo (sin_ds, precio, cantidad, ds_sin_lote)
    Se usa en el Centro de Control y en el resumen diario por correo.
    """
    alertas: list[dict] = []

    # ── Tablero (rápido, cache 60s) ──────────────────────────────
    try:
        t = tablero_produccion()
        for tela in (t.get("inventario", {}).get("telas_bajas") or []):
            alertas.append({
                "tipo": "stock_bajo", "severidad": "media", "fuente": "inventario",
                "mensaje": f"Tela {tela['descripcion_tela']} tono {tela['tono']}: quedan "
                           f"{tela['metros_disponible']:.1f} m ({tela['num_rollos']} rollos) — "
                           f"bajo el mínimo de {t['inventario']['stock_minimo']} m.",
            })
        for l in (t.get("ruta", {}).get("estancados") or []):
            alertas.append({
                "tipo": "estancado", "severidad": "alta" if l["dias"] > 14 else "media",
                "fuente": "ruta",
                "mensaje": f"Lote {l['consecutivo'] or '—'} lleva {l['dias']} días en etapa "
                           f"'{l['etapa']}' sin llegar a bodega.",
            })
    except Exception as e:
        log.warning(f"[alertas] tablero fallo: {e}")

    # ── Cruce Siigo (usa cache 10 min del cruce) ─────────────────
    if incluir_costeo:
        try:
            cruce = cruce_costeo_siigo()
            if cruce.get("ok"):
                for a in (cruce.get("alertas") or []):
                    alertas.append({**a, "fuente": "costeo"})
        except Exception as e:
            log.warning(f"[alertas] cruce siigo fallo: {e}")

    orden_sev = {"alta": 0, "media": 1, "baja": 2}
    alertas.sort(key=lambda a: orden_sev.get(a.get("severidad"), 3))
    return {
        "alertas": alertas,
        "total": len(alertas),
        "altas": sum(1 for a in alertas if a.get("severidad") == "alta"),
        "generado_at": _now_iso(),
    }


# ═══════════════════════════════════════════════════════════════════════
# INVENTARIO DE INSUMOS · cierres, botones, marquillas, bolsas…
# Entradas: ingreso manual. Salidas: automáticas al entregar la remisión.
# ═══════════════════════════════════════════════════════════════════════

def _norm_insumo(nombre: str) -> str:
    return (nombre or "").strip().upper()


def listar_insumos() -> list[dict]:
    sb = _sb()
    if sb is None:
        return []
    return (sb.table("insumos").select("*")
              .order("categoria").order("nombre").execute()).data or []


def movimientos_insumos(limit: int = 100) -> list[dict]:
    sb = _sb()
    if sb is None:
        return []
    return (sb.table("insumos_movimientos")
              .select("*,insumo:insumo_id(nombre,unidad)")
              .order("created_at", desc=True).limit(limit).execute()).data or []


def _upsert_insumo(sb, nombre: str, categoria: str, unidad: str = "und") -> dict:
    """Busca el insumo por nombre normalizado; si no existe lo crea en 0."""
    nom = _norm_insumo(nombre)
    r = (sb.table("insumos").select("*").eq("nombre", nom).limit(1).execute()).data
    if r:
        return r[0]
    ins = sb.table("insumos").insert({
        "nombre": nom, "categoria": categoria or "OTRO",
        "unidad": unidad or "und", "cantidad_disponible": 0,
    }).execute()
    return ins.data[0]


def _mover_insumo(sb, insumo: dict, delta: float, tipo: str,
                  doc_ref: Optional[str], usuario: str, nota: str = "") -> None:
    nuevo = round(float(insumo.get("cantidad_disponible") or 0) + delta, 3)
    sb.table("insumos").update({
        "cantidad_disponible": nuevo, "updated_at": _now_iso(),
    }).eq("id", insumo["id"]).execute()
    sb.table("insumos_movimientos").insert({
        "insumo_id": insumo["id"], "tipo": tipo, "cantidad": delta,
        "doc_ref": doc_ref, "nota": nota[:500] if nota else None, "usuario": usuario,
    }).execute()


def ingreso_insumos(*, items: list[dict], doc_ref: Optional[str],
                    usuario: str) -> dict:
    """Registra la ENTRADA de insumos al inventario.
    items: [{nombre, categoria, cantidad, unidad?}]
    """
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase no configurado")
    registrados = []
    for it in items:
        nombre = _norm_insumo(it.get("nombre") or "")
        cantidad = float(it.get("cantidad") or 0)
        if not nombre or cantidad <= 0:
            continue
        insumo = _upsert_insumo(sb, nombre, it.get("categoria") or "OTRO",
                                it.get("unidad") or "und")
        _mover_insumo(sb, insumo, cantidad, "ingreso", doc_ref, usuario,
                      nota="Ingreso de insumos")
        registrados.append({"nombre": nombre, "cantidad": cantidad})
    if not registrados:
        raise ValueError("sin_items_validos")
    return {"ok": True, "registrados": registrados}


def descontar_insumos_remision(rem: dict, usuario: str) -> list[dict]:
    """SALIDA automática: al entregar la remisión (recogida/despachada) se
    descuentan los insumos calculados del precosteo para cada lote.
    El stock PUEDE quedar negativo — mejor visible que bloqueado; el
    inventario de insumos es control, no restricción de la operación.
    """
    sb = _sb()
    if sb is None:
        return []
    tipo_rem = (rem.get("tipo") or "confeccion")
    cats = ("INSUMO TERMINACION",) if tipo_rem == "terminacion" else ("INSUMO CONFECCION",)
    cat_insumo = cats[0]
    doc_ref = rem.get("consecutivo")
    descontados = []
    for it in (rem.get("items") or []):
        try:
            calc = calcular_insumos_requeridos_corte(it["orden_corte_id"], categorias=cats)
        except Exception as e:
            log.warning(f"[insumos] calculo fallo OC {it.get('orden_corte_id')}: {e}")
            continue
        for ins in (calc.get("items") or []):
            nombre = _norm_insumo(ins.get("item") or "")
            req = float(ins.get("total_requerido") or 0)
            if not nombre or req <= 0:
                continue
            try:
                insumo = _upsert_insumo(sb, nombre, cat_insumo)
                _mover_insumo(sb, insumo, -req, "salida", doc_ref, usuario,
                              nota=f"Entrega remisión {doc_ref}")
                descontados.append({"nombre": nombre, "cantidad": req})
            except Exception as e:
                log.warning(f"[insumos] descuento fallo {nombre}: {e}")
    return descontados


# ═══════════════════════════════════════════════════════════════════════
# SEPARACIÓN DE INSUMOS · checklist con responsable (BAY / HENRY HURTADO)
# ═══════════════════════════════════════════════════════════════════════

RESPONSABLES_SEPARACION = ("BAY", "HENRY HURTADO")


def guardar_separacion(ruta_id: str, *, tipo: str, items: dict,
                       responsable: Optional[str] = None,
                       ok: bool = False, usuario: str = "") -> dict:
    """Guarda el checklist de separación de insumos del lote.
    Estructura en hoja_ruta_lote.separacion_insumos:
      { "confeccion": {"items": {"CIERRE": true, ...}, "ok": true,
                        "responsable": "BAY", "completado_at": "...",
                        "guardado_por": "email"} , "terminacion": {...} }
    """
    if tipo not in ("confeccion", "terminacion"):
        raise ValueError("tipo_invalido")
    if ok and (responsable or "").strip().upper() not in RESPONSABLES_SEPARACION:
        raise ValueError("responsable_requerido")
    sb = _sb()
    if sb is None:
        raise RuntimeError("Supabase no configurado")
    r = (sb.table("hoja_ruta_lote").select("id,separacion_insumos")
           .eq("id", ruta_id).limit(1).execute()).data
    if not r:
        raise ValueError("ruta_no_encontrada")
    actual = r[0].get("separacion_insumos") or {}
    entrada = {
        "items":        {str(k): bool(v) for k, v in (items or {}).items()},
        "ok":           bool(ok),
        "responsable":  (responsable or "").strip().upper() or None,
        "guardado_por": usuario,
    }
    entrada["completado_at"] = _now_iso() if ok else None
    actual[tipo] = entrada
    try:
        sb.table("hoja_ruta_lote").update({
            "separacion_insumos": actual, "updated_at": _now_iso(),
        }).eq("id", ruta_id).execute()
    except Exception as e:
        if "separacion_insumos" in str(e):
            raise ValueError("migracion_separacion_pendiente")
        raise
    return entrada
