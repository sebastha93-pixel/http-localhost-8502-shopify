"""
MercadoPago Client — Male Denim OS
Fetches approved payments, matches to pedidos, persists in DB.

Matching strategy (orden de prioridad):
  Nivel 1 → email_cliente + precio_venta exacto
  Nivel 2 → precio_venta + fecha ±3 días (cuando no hay email)
  Sin match → inserta en pagos_plataforma sin pedido_id (para revisión manual)
"""

import requests
import streamlit as st
from datetime import datetime, timedelta
from typing import Optional
from src.db import get_conn

MP_BASE = "https://api.mercadopago.com"


def _token() -> str:
    return st.secrets["MP_ACCESS_TOKEN"]


def _headers() -> dict:
    return {"Authorization": f"Bearer {_token()}"}


# ── Fetch payments ─────────────────────────────────────────────────────────────

def obtener_pagos(
    fecha_desde: Optional[str] = None,
    fecha_hasta: Optional[str] = None,
    limit_total: int = 5000,
) -> list:
    """
    Trae pagos aprobados de MercadoPago con paginación automática.
    fecha_desde / fecha_hasta: ISO format 'YYYY-MM-DD' (por defecto últimos 90 días)
    Retorna lista de dicts con los campos relevantes normalizados.
    """
    if fecha_desde is None:
        fecha_desde = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%dT00:00:00.000-05:00")
    else:
        fecha_desde = f"{fecha_desde}T00:00:00.000-05:00"

    if fecha_hasta is None:
        fecha_hasta = datetime.now().strftime("%Y-%m-%dT23:59:59.000-05:00")
    else:
        fecha_hasta = f"{fecha_hasta}T23:59:59.000-05:00"

    pagos = []
    offset = 0
    page_size = 100

    while len(pagos) < limit_total:
        params = {
            "sort": "date_approved",
            "criteria": "desc",
            "range": "date_approved",
            "begin_date": fecha_desde,
            "end_date": fecha_hasta,
            "status": "approved",
            "limit": page_size,
            "offset": offset,
        }
        try:
            r = requests.get(
                f"{MP_BASE}/v1/payments/search",
                headers=_headers(),
                params=params,
                timeout=30,
            )
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            raise RuntimeError(f"Error consultando MercadoPago: {e}")

        resultados = data.get("results", [])
        if not resultados:
            break

        for p in resultados:
            comision = sum(
                f.get("amount", 0)
                for f in p.get("fee_details", [])
                if f.get("type") == "mercadopago_fee"
            )
            pagos.append({
                "mp_id": str(p.get("id")),
                "valor_bruto": p.get("transaction_amount", 0),
                "comision": comision,
                "valor_neto": p.get("transaction_amount", 0) - comision,
                "email": (p.get("payer") or {}).get("email", ""),
                "nombre_pagador": _nombre_pagador(p),
                "fecha_aprobado": p.get("date_approved", "")[:10],
                "estado": p.get("status", ""),
                "descripcion": str(p.get("description", "")),
                "external_reference": p.get("external_reference", ""),
            })

        paging = data.get("paging", {})
        total = paging.get("total", 0)
        offset += page_size
        if offset >= total or offset >= limit_total:
            break

    return pagos


def _nombre_pagador(p: dict) -> str:
    payer = p.get("payer") or {}
    nombre = f"{payer.get('first_name', '')} {payer.get('last_name', '')}".strip()
    return nombre


# ── Matching ───────────────────────────────────────────────────────────────────

def _cargar_pedidos_para_matching() -> list:
    """Carga pedidos con email/precio para matching en memoria."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT id, orden_shopify, nombre_cliente, email_cliente,
                   precio_venta, fecha_pedido
            FROM pedidos
            WHERE metodo_pago != 'cod' OR metodo_pago IS NULL
        """).fetchall()
    return [dict(r) for r in rows]


def _match_pedido(pago: dict, pedidos: list) -> Optional[dict]:
    """
    Intenta asociar un pago MP a un pedido.
    Retorna el pedido matcheado o None.
    """
    email = (pago.get("email") or "").lower().strip()
    monto = pago["valor_bruto"]
    fecha_pago = pago["fecha_aprobado"]  # 'YYYY-MM-DD'

    # Nivel 1: email + monto exacto
    if email:
        candidatos = [
            p for p in pedidos
            if (p.get("email_cliente") or "").lower().strip() == email
            and abs((p.get("precio_venta") or 0) - monto) < 1
        ]
        if len(candidatos) == 1:
            return candidatos[0]
        # Si hay varios al mismo email+monto, desambiguar por fecha
        if len(candidatos) > 1 and fecha_pago:
            try:
                fp = datetime.strptime(fecha_pago, "%Y-%m-%d")
                scored = []
                for c in candidatos:
                    if c.get("fecha_pedido"):
                        try:
                            fd = datetime.strptime(str(c["fecha_pedido"])[:10], "%Y-%m-%d")
                            scored.append((abs((fp - fd).days), c))
                        except Exception:
                            scored.append((999, c))
                    else:
                        scored.append((999, c))
                scored.sort(key=lambda x: x[0])
                if scored[0][0] <= 7:
                    return scored[0][1]
            except Exception:
                pass

    # Nivel 2: monto exacto + fecha ±3 días (sin email)
    if fecha_pago:
        try:
            fp = datetime.strptime(fecha_pago, "%Y-%m-%d")
            candidatos2 = []
            for p in pedidos:
                if abs((p.get("precio_venta") or 0) - monto) < 1 and p.get("fecha_pedido"):
                    try:
                        fd = datetime.strptime(str(p["fecha_pedido"])[:10], "%Y-%m-%d")
                        delta = abs((fp - fd).days)
                        if delta <= 3:
                            candidatos2.append((delta, p))
                    except Exception:
                        pass
            if len(candidatos2) == 1:
                return candidatos2[0][1]
        except Exception:
            pass

    return None


# ── Persistencia ───────────────────────────────────────────────────────────────

def sincronizar_pagos_mp(
    fecha_desde: Optional[str] = None,
    fecha_hasta: Optional[str] = None,
) -> dict:
    """
    Flujo completo:
    1. Descarga pagos aprobados de MP
    2. Hace matching contra pedidos
    3. Inserta/actualiza pagos_plataforma
    4. Actualiza pedidos matcheados
    Retorna resumen con conteos.
    """
    pagos = obtener_pagos(fecha_desde=fecha_desde, fecha_hasta=fecha_hasta)
    pedidos = _cargar_pedidos_para_matching()

    nuevos = 0
    ya_existian = 0
    matcheados = 0
    sin_match = 0
    errores = 0

    for pago in pagos:
        try:
            # Verificar si ya existe en DB
            with get_conn() as conn:
                existe = conn.execute(
                    "SELECT id FROM pagos_plataforma WHERE referencia_plataforma = ?",
                    (pago["mp_id"],),
                ).fetchone()

            if existe:
                ya_existian += 1
                continue

            # Matching
            pedido = _match_pedido(pago, pedidos)
            pedido_id = pedido["id"] if pedido else None
            orden_shopify = pedido["orden_shopify"] if pedido else None

            # Insertar en pagos_plataforma
            with get_conn() as conn:
                conn.execute("""
                    INSERT INTO pagos_plataforma
                        (plataforma, referencia_plataforma, pedido_id, orden_shopify,
                         valor_bruto, comision, valor_neto, estado,
                         fecha_transaccion, conciliado)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    "mercadopago",
                    pago["mp_id"],
                    pedido_id,
                    orden_shopify,
                    pago["valor_bruto"],
                    pago["comision"],
                    pago["valor_neto"],
                    pago["estado"],
                    pago["fecha_aprobado"],
                    1 if pedido_id else 0,
                ))

            nuevos += 1
            if pedido_id:
                matcheados += 1
                # Actualizar pedido
                with get_conn() as conn:
                    conn.execute("""
                        UPDATE pedidos SET
                            estado_pago      = 'pagado',
                            plataforma_pago  = 'mercadopago',
                            valor_pagado     = ?,
                            fecha_pago       = ?,
                            conciliado       = 1,
                            estado_conciliacion = 'ok',
                            actualizado_en   = CURRENT_TIMESTAMP
                        WHERE id = ?
                    """, (pago["valor_bruto"], pago["fecha_aprobado"], pedido_id))
            else:
                sin_match += 1

        except Exception as e:
            errores += 1
            print(f"[mp_client] Error procesando pago {pago.get('mp_id')}: {e}")

    return {
        "total_mp": len(pagos),
        "nuevos": nuevos,
        "ya_existian": ya_existian,
        "matcheados": matcheados,
        "sin_match": sin_match,
        "errores": errores,
        "tasa_match": round(matcheados / nuevos * 100, 1) if nuevos > 0 else 0,
    }


# ── Stats ──────────────────────────────────────────────────────────────────────

def stats_mp() -> dict:
    """Resumen rápido del estado de pagos MP en DB."""
    with get_conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM pagos_plataforma WHERE plataforma='mercadopago'"
        ).fetchone()[0]
        matcheados = conn.execute(
            "SELECT COUNT(*) FROM pagos_plataforma WHERE plataforma='mercadopago' AND pedido_id IS NOT NULL"
        ).fetchone()[0]
        sin_match = conn.execute(
            "SELECT COUNT(*) FROM pagos_plataforma WHERE plataforma='mercadopago' AND pedido_id IS NULL"
        ).fetchone()[0]
        valor_total = conn.execute(
            "SELECT COALESCE(SUM(valor_bruto),0) FROM pagos_plataforma WHERE plataforma='mercadopago'"
        ).fetchone()[0]
        ultima = conn.execute(
            "SELECT MAX(fecha_transaccion) FROM pagos_plataforma WHERE plataforma='mercadopago'"
        ).fetchone()[0]
    return {
        "total": total,
        "matcheados": matcheados,
        "sin_match": sin_match,
        "valor_total": valor_total,
        "ultima_transaccion": ultima,
        "tasa_match": round(matcheados / total * 100, 1) if total > 0 else 0,
    }


def pagos_sin_match() -> list:
    """Pagos MP sin pedido asociado — para revisión manual."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT referencia_plataforma, valor_bruto, fecha_transaccion
            FROM pagos_plataforma
            WHERE plataforma='mercadopago' AND pedido_id IS NULL
            ORDER BY fecha_transaccion DESC
        """).fetchall()
    return [dict(r) for r in rows]
