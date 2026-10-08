"""El manejador que convierte una venta del POS en una factura de Siigo.

Lo llama el drenador del outbox (`emitir_documento_fiscal`), nunca la caja: la
venta ya se cobró y la clienta ya se fue. Esto corre después, y si Siigo está
caído, vuelve a intentarlo solo (ADR-002).

LO QUE ESTE ARCHIVO TIENE QUE GARANTIZAR, por encima de todo: **una venta, una
factura.** Una factura repetida no es un error de software: es un documento de
más ante la DIAN, que se anula con nota crédito y con el contador.

Y Siigo no ayuda: no tiene llave de idempotencia. Si el envío se corta sin
respuesta —timeout, 502, el proceso muere— NO SE SABE si la factura se creó.
Reintentar a ciegas es la forma de emitir dos. Por eso son tres pasos y no uno:

  1. Se deja escrito «voy a enviar» (`documentos_fiscales` en `enviando`) y
     SE CONFIRMA EN LA BASE antes de tocar Siigo.
  2. Se envía, UNA sola vez. Sin reintentos automáticos.
  3. Se anota el resultado.

Si al volver hay un «voy a enviar» sin resultado, lo primero es BUSCAR la
factura en Siigo por su marca (`observations`). Si está, se adopta. Sólo si no
está se vuelve a enviar.

EL MODO manda (`RETAIL_FISCAL_MODO`):
  · `apagado` (por defecto) — no emite; los trabajos esperan sin gastarse.
  · `prueba`  — crea el documento en Siigo SIN estamparlo: no va a la DIAN,
                queda revisable y se puede borrar.
  · `produccion` — estampa. Irreversible.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import text

from backend.modules.retail.application.comandos.drenar_outbox import (
    Aplazar,
    RechazoDefinitivo,
)
from backend.modules.retail.infrastructure.siigo.factura_venta import (
    CONSUMIDOR_FINAL,
    FacturaInvalida,
    construir_factura,
    marca_de,
)

log = logging.getLogger("retail.fiscal")

__all__ = ["TIPO", "emitir_factura", "crear_manejador", "modo", "SiigoIO",
           "RechazoDeSiigo"]

TIPO = "emitir_documento_fiscal"
MODOS = ("apagado", "prueba", "produccion")


def modo() -> str:
    m = os.environ.get("RETAIL_FISCAL_MODO", "apagado").strip().lower()
    return m if m in MODOS else "apagado"


class RechazoDeSiigo(Exception):
    """Siigo respondió 4xx: el documento NO se creó y no se va a crear así."""


# ── La puerta a Siigo ───────────────────────────────────────────────────────

class SiigoIO:
    """Todo lo que este manejador le pide a Siigo. Las pruebas ponen otro.

    Los imports son LOCALES: `backend.services.siigo` es del ERP y el módulo
    retail tiene que poder cargarse sin él.
    """

    async def tipo_documento(self, documento_id: int) -> Optional[dict]:
        def ir():
            from backend.services.siigo import siigo_get
            tipos = siigo_get("/document-types", {"type": "FV"})
            return next((t for t in tipos if int(t.get("id") or 0) == int(documento_id)),
                        None)
        return await asyncio.to_thread(ir)

    async def existe_cliente(self, identificacion: str) -> bool:
        def ir():
            from backend.services.siigo import siigo_get
            r = siigo_get("/customers", {"identification": identificacion})
            filas = r.get("results", []) if isinstance(r, dict) else (r or [])
            # `identification` es de los filtros que Siigo a veces ignora y
            # devuelve la lista entera: se comprueba el dato, no que haya filas.
            return any(str(c.get("identification")) == str(identificacion)
                       for c in filas)
        return await asyncio.to_thread(ir)

    async def buscar_por_marca(self, *, documento_id: int, fecha: str,
                               marca: str) -> Optional[dict]:
        def ir():
            from backend.services.siigo import siigo_get
            for pagina in range(1, 21):
                r = siigo_get("/invoices", {
                    "document_id": documento_id, "date_start": fecha,
                    "date_end": fecha, "page": pagina, "page_size": 100})
                filas = r.get("results", []) if isinstance(r, dict) else []
                for f in filas:
                    if marca in (f.get("observations") or ""):
                        return f
                if len(filas) < 100:
                    return None
            return None
        return await asyncio.to_thread(ir)

    async def crear_factura(self, cuerpo: dict) -> dict:
        """UN intento. `siigo_post` reintenta solo ante un 502, y si la
        factura sí se creó, ese reintento crea la segunda."""
        def ir():
            import httpx
            from backend.services import siigo as s
            r = httpx.post(s.SIIGO_BASE + "/invoices", json=cuerpo, timeout=60,
                           headers={"Authorization": f"Bearer {s._get_token()}",
                                    "Partner-Id": os.getenv("SIIGO_PARTNER_ID", ""),
                                    "Content-Type": "application/json"})
            if r.status_code in (200, 201):
                return r.json()
            if 400 <= r.status_code < 500 and r.status_code != 429:
                raise RechazoDeSiigo(f"HTTP {r.status_code}: {r.text[:400]}")
            raise RuntimeError(f"Siigo HTTP {r.status_code}: {r.text[:200]}")
        return await asyncio.to_thread(ir)


# ── El manejador ────────────────────────────────────────────────────────────

def crear_manejador(io: Optional[SiigoIO] = None):
    io = io or SiigoIO()

    async def manejador(t, payload: dict) -> Optional[str]:
        return await _emitir(t, payload, io)
    return manejador


async def emitir_factura(t, payload: dict) -> Optional[str]:
    """El que se registra en `MANEJADORES`."""
    return await _emitir(t, payload, SiigoIO())


async def _emitir(t, payload: dict, io: SiigoIO) -> Optional[str]:
    en_modo = modo()
    if en_modo == "apagado":
        raise Aplazar("la facturación desde el POS está apagada "
                      "(RETAIL_FISCAL_MODO)")

    venta_id = payload["venta_id"]
    v = (await t.sesion.execute(text("""
        SELECT v.id, v.numero, v.total, v.vuelto, v.estado, v.cerrada_en,
               v.tienda_id, v.caja_id, v.sesion_id,
               c.siigo_documento_id, ti.siigo_vendedor_id, ti.siigo_bodega_id,
               ti.siigo_centro_costo_id, ti.zona_horaria,
               cl.numero_documento AS cliente_documento
          FROM retail.ventas v
          JOIN retail.cajas c    ON c.id = v.caja_id
          JOIN retail.tiendas ti ON ti.id = v.tienda_id
          LEFT JOIN retail.clientes cl ON cl.id = v.cliente_id
         WHERE v.id = :v
    """), {"v": venta_id})).mappings().first()
    if v is None:
        raise RechazoDefinitivo(f"no existe la venta {venta_id}")
    if v["estado"] == "anulada":
        return "venta anulada antes de facturarse: no se emite"

    # Lo que falta de CONFIGURACIÓN no es un fallo de la venta: se espera.
    if not v["siigo_documento_id"]:
        raise Aplazar(f"la caja {v['caja_id']} no tiene comprobante de Siigo")
    if not v["siigo_vendedor_id"]:
        raise Aplazar(f"la tienda {v['tienda_id']} no tiene vendedor de Siigo")

    doc = (await t.sesion.execute(text("""
        SELECT id, estado, payload_snapshot FROM retail.documentos_fiscales
         WHERE venta_id = :v AND tipo = 'factura_electronica'
         ORDER BY creado_en DESC LIMIT 1
    """), {"v": venta_id})).mappings().first()
    if doc and doc["estado"] == "emitido":
        return "ya estaba emitida"
    if doc and doc["estado"] == "rechazado":
        raise RechazoDefinitivo("Siigo ya la rechazó; hay que corregirla a mano")

    fecha = v["cerrada_en"].astimezone(
        ZoneInfo(v["zona_horaria"] or "America/Bogota")).date().isoformat()
    marca = marca_de(v["id"], v["numero"])
    documento_id = int(v["siigo_documento_id"])

    creada = None
    if doc and doc["estado"] == "enviando":
        # Hubo un envío sin resultado. ANTES de reenviar se mira si llegó.
        creada = await io.buscar_por_marca(documento_id=documento_id,
                                           fecha=fecha, marca=marca)
        if creada:
            log.warning("[retail-fiscal] %s ya estaba en Siigo: se adopta, "
                        "no se reenvía", v["numero"])

    if creada is None:
        cuerpo = await _armar(t, v, io, documento_id=documento_id, fecha=fecha,
                              estampar=(en_modo == "produccion"))
        doc_id = doc["id"] if doc else f"{venta_id[:23]}FAC"
        resumen = cuerpo.pop("_resumen")
        await t.sesion.execute(text("""
            INSERT INTO retail.documentos_fiscales
                (id, venta_id, tipo, estado, payload_snapshot, intentos)
            VALUES (:i, :v, 'factura_electronica', 'enviando', CAST(:p AS jsonb), 1)
            ON CONFLICT (id) DO UPDATE
               SET estado = 'enviando', payload_snapshot = EXCLUDED.payload_snapshot,
                   intentos = retail.documentos_fiscales.intentos + 1
        """), {"i": doc_id, "v": venta_id,
               "p": json.dumps({**cuerpo, "_resumen": resumen, "_modo": en_modo})})
        await t.sesion.execute(text(
            "UPDATE retail.ventas SET estado_fiscal = 'enviando' WHERE id = :v"),
            {"v": venta_id})
        # SE CONFIRMA ANTES DE ENVIAR. Si el proceso muere en la línea
        # siguiente, lo que queda es «enviando» — y eso obliga a buscar en
        # Siigo antes de volver a mandar.
        await t.commit()

        try:
            creada = await io.crear_factura(cuerpo)
        except RechazoDeSiigo as e:
            await _cerrar(t, venta_id, "rechazado", error=str(e))
            await t.commit()
            raise RechazoDefinitivo(str(e)) from e
        # Cualquier otra cosa (timeout, 5xx) sube tal cual: el trabajo se
        # reintenta y, como quedó «enviando», primero verifica.

    numero = creada.get("name") or str(creada.get("number") or "")
    sello = creada.get("stamp") or {}
    ahora = datetime.now(timezone.utc)
    await t.sesion.execute(text("""
        UPDATE retail.documentos_fiscales
           SET estado = 'emitido', numero = :n, cufe = :cufe,
               documento_externo_id = :ext,
               respuesta_cruda = CAST(:cruda AS jsonb),
               emitido_en = :ts, ultimo_error = NULL
         WHERE venta_id = :v AND tipo = 'factura_electronica'
    """), {"v": venta_id, "n": numero, "cufe": sello.get("cufe"),
           "ext": str(creada.get("id") or ""), "ts": ahora,
           "cruda": json.dumps(creada, default=str)})
    await t.sesion.execute(text(
        "UPDATE retail.ventas SET estado_fiscal = 'emitido' WHERE id = :v"),
        {"v": venta_id})
    await t.auditoria.registrar(
        evento="factura.emitida", ocurrido_en=ahora,
        tienda_id=v["tienda_id"], caja_id=v["caja_id"],
        sesion_id=v["sesion_id"], usuario_id="sistema",
        agregado_tipo="venta", agregado_id=venta_id,
        payload={"numero_venta": v["numero"], "factura": numero,
                 "modo": en_modo, "siigo_id": str(creada.get("id") or "")})
    log.info("[retail-fiscal] %s → %s (%s)", v["numero"], numero, en_modo)
    return f"factura {numero} ({en_modo})"


async def _armar(t, v, io: SiigoIO, *, documento_id: int, fecha: str,
                 estampar: bool) -> dict:
    tipo = await io.tipo_documento(documento_id)
    if tipo is None or not tipo.get("active", True):
        raise Aplazar(f"Siigo no expone el comprobante {documento_id} "
                      f"(o está inactivo)")

    lineas = [dict(f) for f in (await t.sesion.execute(text("""
        SELECT sku, descripcion, cantidad, precio_unitario, descuento_monto,
               tasa_iva
          FROM retail.venta_lineas WHERE venta_id = :v ORDER BY orden
    """), {"v": v["id"]})).mappings().all()]

    pagos = [dict(f) for f in (await t.sesion.execute(text("""
        SELECT p.medio_pago_id, p.monto, m.tipo, m.siigo_forma_pago_id
          FROM retail.venta_pagos p
          JOIN retail.medios_pago m ON m.id = p.medio_pago_id
         WHERE p.venta_id = :v ORDER BY p.id
    """), {"v": v["id"]})).mappings().all()]
    # El vuelto sale del efectivo: a Siigo va lo que ENTRÓ, no lo entregado.
    pendiente = int(v["vuelto"] or 0)
    for p in pagos:
        neto = int(p["monto"])
        if p["tipo"] == "efectivo" and pendiente > 0:
            sale = min(pendiente, neto)
            neto -= sale
            pendiente -= sale
        p["neto"] = neto

    identificacion = (v["cliente_documento"] or "").strip() or None
    if identificacion and identificacion != CONSUMIDOR_FINAL:
        if not await io.existe_cliente(identificacion):
            # Crear terceros en Siigo es otro documento con sus propias
            # trampas; mientras no exista, la venta ESPERA en vez de salir a
            # nombre de otra persona.
            raise Aplazar(f"la clienta {identificacion} no existe en Siigo")

    try:
        return construir_factura(
            venta={"id": v["id"], "numero": v["numero"], "total": v["total"]},
            lineas=lineas, pagos=pagos, documento_id=documento_id,
            tipo_descuento=tipo.get("discount_type"),
            vendedor_id=int(v["siigo_vendedor_id"]), fecha=fecha,
            identificacion=identificacion,
            bodega_id=v["siigo_bodega_id"],
            centro_costo_id=v["siigo_centro_costo_id"], estampar=estampar)
    except FacturaInvalida as e:
        raise RechazoDefinitivo(str(e)) from e


async def _cerrar(t, venta_id: str, estado: str, *, error: str) -> None:
    await t.sesion.execute(text("""
        UPDATE retail.documentos_fiscales
           SET estado = :e, ultimo_error = :err
         WHERE venta_id = :v AND tipo = 'factura_electronica'
    """), {"v": venta_id, "e": estado, "err": error[:500]})
    await t.sesion.execute(text(
        "UPDATE retail.ventas SET estado_fiscal = :e WHERE id = :v"),
        {"v": venta_id, "e": estado})
