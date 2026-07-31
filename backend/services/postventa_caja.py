"""
backend.services.postventa_caja — Cierre diario de postventa por punto de venta.

EL PROBLEMA QUE RESUELVE: el excedente de un cambio lo paga la clienta en el
datáfono o la caja física de la tienda, pero la factura sale por FV-5 desde
Siigo Nube. El POS de la tienda nunca se entera. Al cerrar el día la cajera
tiene MÁS plata de la que su cierre dice, y no sabe de dónde salió.

No hay forma de escribirle al POS (Siigo POS no tiene API), así que el módulo
entrega el dato al revés: esto es lo que la cajera SUMA a su arqueo.

REGLA CENTRAL: aquí solo va plata que ENTRÓ A LA CAJA. El anticipo no es
plata — es el crédito que dejó la nota crédito. Contarlo inflaría el arqueo
con dinero que nunca pasó por ahí.

Solo lectura.
"""
from __future__ import annotations

import logging
from typing import Optional

from backend.services import fiscal_logic as F
from backend.services import tiendas

log = logging.getLogger("postventa_caja")


def _nombre_medio(clave_tienda: str, pago_id: int) -> str:
    for m in (tiendas.obtener(clave_tienda) or {}).get("formas_pago") or []:
        if int(m["id"]) == int(pago_id):
            return str(m.get("nombre") or pago_id)
    return str(pago_id)


def _cobrado(payload: dict) -> list[dict]:
    """Pagos que representan plata real en la caja.

    Se excluye el ANTICIPO: lo aplica el sistema al consumir el crédito de la
    nota crédito, no la clienta en el datáfono.
    """
    salida = []
    for p in ((payload or {}).get("payments") or []):
        pid = p.get("id")
        if not pid or int(pid) == F.ANTICIPO_CLIENTES_ID:
            continue
        val = round(float(p.get("value") or 0), 2)
        if val > 0:
            salida.append({"id": int(pid), "value": val})
    return salida


def cierre_del_dia(documentos: list[dict], *, tienda: str,
                   fecha: str) -> dict:
    """Lo que la cajera de ESE punto suma a su arqueo de ESE día.

    `documentos` son filas de postventa_fiscal con su caso adjunto. Se filtra
    aquí y no en la consulta para poder probarlo sin base de datos.
    """
    clave = (tienda or "").strip().lower()
    dia = str(fecha or "")[:10]

    por_medio: dict[int, float] = {}
    casos: list[dict] = []
    nc_cantidad = 0
    nc_total = 0.0

    for d in documentos:
        if not isinstance(d, dict):
            continue
        caso = d.get("caso") or {}
        if (caso.get("tienda") or "").strip().lower() != clave:
            continue
        if str(d.get("created_at") or "")[:10] != dia:
            continue
        # Un preview que nunca se emitió no cobró nada.
        if d.get("status") != "emitido":
            continue

        if d.get("doc_kind") == "nota_credito":
            # No es plata: la clienta no pagó nada. Se reporta aparte porque
            # sí explica por qué entraron prendas al inventario del punto.
            nc_cantidad += 1
            nc_total += round(float(d.get("amount") or 0), 2)
            continue

        pagos = _cobrado(d.get("payload_snapshot") or {})
        if not pagos:
            continue
        total_caso = round(sum(p["value"] for p in pagos), 2)
        for p in pagos:
            por_medio[p["id"]] = round(por_medio.get(p["id"], 0.0) + p["value"], 2)
        casos.append({
            "caso": caso.get("case_number"),
            "factura": d.get("siigo_document_number"),
            "cobrado": total_caso,
            "medios": [{"id": p["id"], "nombre": _nombre_medio(clave, p["id"]),
                        "total": p["value"]} for p in pagos],
        })

    t = tiendas.obtener(clave) or {}
    return {
        "tienda": clave,
        "nombre": t.get("nombre"),
        "fecha": dia,
        "total_cobrado": round(sum(por_medio.values()), 2),
        "por_medio": [{"id": k, "nombre": _nombre_medio(clave, k), "total": v}
                      for k, v in sorted(por_medio.items())],
        "casos": casos,
        # Informativo: no entra al arqueo, pero explica el movimiento de
        # inventario del día en ese punto.
        "notas_credito": {"cantidad": nc_cantidad, "total": round(nc_total, 2)},
    }


def documentos_del_dia(fecha: str) -> list[dict]:
    """Documentos fiscales del día con el caso adjunto.

    Trae los de TODAS las tiendas de una sola consulta; `cierre_del_dia`
    filtra. Así el panel puede mostrar los tres puntos sin pegarle tres veces
    a la base.
    """
    from backend.services import postventa as pv
    sb = pv._sb()
    if sb is None:
        return []
    dia = str(fecha or "")[:10]
    r = (sb.table("postventa_fiscal")
           .select("doc_kind,status,created_at,siigo_document_number,"
                   "siigo_document_id,amount,payload_snapshot,"
                   "postventa_cases(tienda,case_number)")
           .eq("brand_id", pv._brand_id())
           .eq("status", "emitido")
           .gte("created_at", f"{dia}T00:00:00")
           .lte("created_at", f"{dia}T23:59:59.999")
           .execute())
    filas = []
    for f in (r.data or []):
        f["caso"] = f.pop("postventa_cases", None) or {}
        filas.append(f)
    return filas


def _factura_de_siigo(documento_id: Optional[str]) -> Optional[dict]:
    if not documento_id:
        return None
    try:
        from backend.services import siigo
        return siigo.siigo_get(f"/invoices/{documento_id}")
    except Exception as e:  # noqa: BLE001
        log.warning("[caja] no se pudo leer la factura %s: %s", documento_id, e)
        return None


def verificar(cierre: dict, documentos: list[dict]) -> dict:
    """Confirma cada cobro contra la factura guardada en Siigo.

    Se hace por caso y no en bloque para poder decir CUÁL no coincide: un
    total que no cuadra sin saber dónde no le sirve a quien cierra la caja.
    """
    por_caso = {d.get("caso", {}).get("case_number"): d for d in documentos
                if d.get("doc_kind") == "factura"}
    confirmados = 0
    revisar = []
    for c in cierre.get("casos", []):
        d = por_caso.get(c.get("caso")) or {}
        enviado = _cobrado(d.get("payload_snapshot") or {})
        fac = _factura_de_siigo(d.get("siigo_document_id"))
        v = comparar_pagos(enviado=enviado, factura=fac)
        c["confirmado"] = v["coincide"]
        c["en_siigo"] = v.get("en_siigo")
        if v["coincide"] is True:
            confirmados += 1
        else:
            revisar.append({"caso": c.get("caso"), "factura": c.get("factura"),
                            "cobrado": c.get("cobrado"),
                            "en_siigo": v.get("en_siigo"),
                            "motivo": v.get("motivo") or
                                      "La factura en Siigo no tiene el mismo cobro."})
    cierre["confirmados"] = confirmados
    cierre["revisar"] = revisar
    return cierre


def cierre_de_todos(fecha: str) -> list[dict]:
    """Un cierre por punto de venta. Lo que se imprime al cerrar el día."""
    docs = documentos_del_dia(fecha)
    return [verificar(cierre_del_dia(docs, tienda=p["clave"], fecha=fecha), docs)
            for p in tiendas.listar()]


# ── Confirmación contra Siigo ─────────────────────────────────────────
# El cierre sumaba `payload_snapshot`: lo que le MANDAMOS a Siigo. Nunca
# volvía a leer la factura. Siigo descarta en silencio lo que no le gusta
# —pasó con `warehouse`— así que el cierre podía mandar a la cajera a buscar
# plata que la contabilidad no tiene.

def comparar_pagos(*, enviado: list, factura: Optional[dict]) -> dict:
    """Lo que cobramos según nosotros vs. lo que quedó en la factura.

    `coincide` es None cuando no se pudo leer la factura: sin dato no se
    afirma que esté bien. Un cierre sin cobros no necesita verificación.
    """
    nuestro = round(sum(p["value"] for p in _sin_anticipo(enviado)), 2)
    if nuestro <= 0:
        return {"coincide": True, "enviado": 0.0, "en_siigo": 0.0}
    if not factura:
        return {"coincide": None, "enviado": nuestro, "en_siigo": None,
                "motivo": "No se pudo leer la factura en Siigo."}
    suyo = round(sum(p["value"] for p in
                     _sin_anticipo(factura.get("payments") or [])), 2)
    return {"coincide": abs(nuestro - suyo) <= 1.0,
            "enviado": nuestro, "en_siigo": suyo}


def _sin_anticipo(pagos) -> list[dict]:
    salida = []
    for p in (pagos or []):
        pid = p.get("id")
        if not pid or int(pid) == F.ANTICIPO_CLIENTES_ID:
            continue
        try:
            v = round(float(p.get("value") or 0), 2)
        except (TypeError, ValueError):
            continue
        if v > 0:
            salida.append({"id": int(pid), "value": v})
    return salida
