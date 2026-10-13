"""El manejador que emite la nota crédito de un cambio.

Lo encola `RegistrarDevolucion` cuando la clienta sale con saldo a favor. La
nota crédito es lo que hace EXISTIR ese saldo en Siigo —como anticipo a su
nombre— y lo que mete la prenda a la bodega de la tienda que la recibió.

Antes dependía de que una persona aprobara un caso en Postventa. No pasó en
tres días, y las clientas gastaron saldos que Siigo no conocía (2026-10-13).

MISMA REGLA QUE LA FACTURA Y QUE LA ANULACIÓN: **un cambio, una nota
crédito.** Se deja escrito «voy a enviar» antes de enviar, se envía una vez,
y al reintentar primero se BUSCA por su marca. Y creada en Siigo no es nota
crédito todavía: lo es cuando la DIAN la valida.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import text

from backend.modules.retail.application.comandos.drenar_outbox import (
    Aplazar,
    RechazoDefinitivo,
)
from backend.modules.retail.infrastructure.siigo.emisor_factura import (
    HORAS_SIN_VALIDAR,
    RechazoDeSiigo,
    SiigoIO,
    _zona,
    modo,
)
from backend.modules.retail.infrastructure.siigo.emisor_nota_credito import (
    _numero_de,
    _sello,
)
from backend.modules.retail.infrastructure.siigo.factura_venta import FacturaInvalida
from backend.modules.retail.infrastructure.siigo.nota_credito_cambio import (
    construir_nota_credito_cambio,
    marca_cambio_de,
)

log = logging.getLogger("retail.fiscal")

__all__ = ["TIPO", "emitir_nota_credito_cambio", "crear_manejador", "doc_id_de"]

TIPO = "emitir_nota_credito_cambio"


def doc_id_de(devolucion_id: str) -> str:
    """El id del documento fiscal de ESTA devolución. Termina en `NCD`; el de
    la anulación de una venta, en `NCR`."""
    return f"{devolucion_id[:23]}NCD"


def crear_manejador(io: Optional[SiigoIO] = None):
    io = io or SiigoIO()

    async def manejador(t, payload: dict) -> Optional[str]:
        return await _emitir(t, payload, io)
    return manejador


async def emitir_nota_credito_cambio(t, payload: dict) -> Optional[str]:
    return await _emitir(t, payload, SiigoIO())


async def _emitir(t, payload: dict, io: SiigoIO) -> Optional[str]:
    en_modo = modo()
    if en_modo == "apagado":
        raise Aplazar("la facturación desde el POS está apagada "
                      "(RETAIL_FISCAL_MODO)")

    devolucion_id = payload["devolucion_id"]
    d = (await t.sesion.execute(text("""
        SELECT d.id, d.venta_id, d.numero_venta, d.tienda_id, d.caja_id,
               d.sesion_id, d.reembolso, d.nota_credito_numero,
               d.caso_postventa, ti.siigo_nc_documento_id, ti.siigo_bodega_id,
               ti.zona_horaria
          FROM retail.devoluciones d
          JOIN retail.tiendas ti ON ti.id = d.tienda_id
         WHERE d.id = :d
    """), {"d": devolucion_id})).mappings().first()
    if d is None:
        raise RechazoDefinitivo(f"no existe la devolución {devolucion_id}")
    if d["nota_credito_numero"]:
        return f"ya tenía la nota crédito {d['nota_credito_numero']}"

    factura = (await t.sesion.execute(text("""
        SELECT estado, numero, cufe, documento_externo_id
          FROM retail.documentos_fiscales
         WHERE venta_id = :v AND tipo = 'factura_electronica'
         ORDER BY creado_en DESC LIMIT 1
    """), {"v": d["venta_id"]})).mappings().first()
    if factura is None or factura["estado"] in ("pendiente", "enviando",
                                               "verificando"):
        # La venta es de hace un rato y su factura todavía va en camino.
        raise Aplazar(f"la factura de {d['numero_venta']} todavía no está "
                      f"validada", minutos=5)
    if factura["estado"] != "emitido" or not factura["documento_externo_id"]:
        raise RechazoDefinitivo(
            f"la factura de {d['numero_venta']} quedó «{factura['estado']}»: "
            f"no hay documento que acreditar")
    if not d["siigo_nc_documento_id"]:
        raise Aplazar(f"la tienda {d['tienda_id']} no tiene comprobante de "
                      f"nota crédito en Siigo")

    doc_id = doc_id_de(devolucion_id)
    doc = (await t.sesion.execute(text("""
        SELECT id, estado, numero, documento_externo_id, creado_en
          FROM retail.documentos_fiscales WHERE id = :i
    """), {"i": doc_id})).mappings().first()
    if doc and doc["estado"] == "emitido":
        return "ya estaba emitida"
    if doc and doc["estado"] in ("rechazado", "discrepante"):
        raise RechazoDefinitivo("Siigo o la DIAN ya rechazaron esta nota "
                                "crédito; hay que corregirla a mano")
    if doc and doc["estado"] == "verificando":
        return await _esperar_dian(
            t, d, io, doc_id=doc_id, en_modo=en_modo,
            siigo_id=doc["documento_externo_id"], numero=doc["numero"],
            factura_numero=factura["numero"], desde=doc["creado_en"])

    # La fecha del día en que se EMITE: Siigo rechaza una de ayer.
    fecha = datetime.now(timezone.utc).astimezone(
        _zona(d["zona_horaria"])).date().isoformat()
    marca = marca_cambio_de(devolucion_id, d["numero_venta"])

    creada = None
    if doc and doc["estado"] == "enviando":
        desde = doc["creado_en"].astimezone(
            _zona(d["zona_horaria"])).date().isoformat()
        creada = await io.buscar_nc_por_marca(desde=desde, marca=marca)
        if creada:
            log.warning("[retail-fiscal] la nota crédito del cambio de %s ya "
                        "estaba en Siigo: se adopta, no se reenvía",
                        d["numero_venta"])

    if creada is None:
        devueltas = {r["sku"]: int(r["n"]) for r in (await t.sesion.execute(text("""
            SELECT sku, sum(cantidad) AS n FROM retail.devolucion_lineas
             WHERE devolucion_id = :d GROUP BY sku
        """), {"d": devolucion_id})).mappings()}
        # La factura se lee de SIIGO: la nota crédito copia el documento que
        # la DIAN validó, no lo que el POS cree que mandó.
        original = await io.leer_factura(factura["documento_externo_id"])
        try:
            cuerpo = construir_nota_credito_cambio(
                factura=original, devueltas=devueltas,
                documento_id=int(d["siigo_nc_documento_id"]), fecha=fecha,
                marca=marca, bodega_id=d["siigo_bodega_id"],
                estampar=(en_modo == "produccion"))
        except FacturaInvalida as e:
            if "todavía no valida" in str(e):
                raise Aplazar(str(e), minutos=10) from e
            raise RechazoDefinitivo(str(e)) from e

        await t.sesion.execute(text("""
            INSERT INTO retail.documentos_fiscales
                (id, venta_id, tipo, estado, payload_snapshot, intentos)
            VALUES (:i, :v, 'nota_credito', 'enviando', CAST(:p AS jsonb), 1)
            ON CONFLICT (id) DO UPDATE
               SET estado = 'enviando', payload_snapshot = EXCLUDED.payload_snapshot,
                   intentos = retail.documentos_fiscales.intentos + 1
        """), {"i": doc_id, "v": d["venta_id"],
               "p": json.dumps({**cuerpo, "_modo": en_modo,
                                "_devolucion": devolucion_id})})
        # SE CONFIRMA ANTES DE ENVIAR, igual que la factura.
        await t.commit()

        try:
            creada = await io.crear_nota_credito(cuerpo)
        except RechazoDeSiigo as e:
            await _cerrar(t, doc_id, "rechazado", error=str(e))
            await t.commit()
            raise RechazoDefinitivo(str(e)) from e

    numero = _numero_de(creada)
    siigo_id = str(creada.get("id") or "")
    if en_modo != "produccion":
        return await _anotar_emitida(t, d, creada, doc_id=doc_id,
                                     en_modo=en_modo,
                                     factura_numero=factura["numero"])

    await t.sesion.execute(text("""
        UPDATE retail.documentos_fiscales
           SET estado = 'verificando', numero = :n, documento_externo_id = :ext,
               respuesta_cruda = CAST(:cruda AS jsonb), ultimo_error = NULL
         WHERE id = :i
    """), {"i": doc_id, "n": numero, "ext": siigo_id,
           "cruda": json.dumps(creada, default=str)})
    await t.commit()
    return await _esperar_dian(t, d, io, doc_id=doc_id, en_modo=en_modo,
                               siigo_id=siigo_id, numero=numero,
                               factura_numero=factura["numero"],
                               desde=datetime.now(timezone.utc),
                               ya_leida=creada)


async def _esperar_dian(t, d, io: SiigoIO, *, doc_id: str, en_modo: str,
                        siigo_id: str, numero: str, factura_numero: str,
                        desde: datetime,
                        ya_leida: Optional[dict] = None) -> str:
    """Pregunta hasta que la DIAN valide. Nunca envía nada."""
    nc = ya_leida
    for vuelta in range(io.consultas_inmediatas + 1):
        if nc is None:
            nc = await io.leer_nota_credito(siigo_id)
        estado, _ = _sello(nc)
        if estado == "accepted":
            return await _anotar_emitida(t, d, nc, doc_id=doc_id,
                                         en_modo=en_modo,
                                         factura_numero=factura_numero)
        if estado == "rejected":
            motivo = json.dumps((nc.get("stamp") or {}), default=str)[:400]
            await _cerrar(t, doc_id, "rechazado",
                          error=f"la DIAN rechazó {numero}: {motivo}")
            await t.commit()
            raise RechazoDefinitivo(
                f"la DIAN rechazó la nota crédito {numero}: {motivo}")
        if vuelta == io.consultas_inmediatas:
            break
        await asyncio.sleep(io.pausa)
        nc = None

    if datetime.now(timezone.utc) - desde > timedelta(hours=HORAS_SIN_VALIDAR):
        await _cerrar(t, doc_id, "discrepante",
                      error=f"{numero} lleva más de {HORAS_SIN_VALIDAR} h en "
                            f"Siigo sin validación de la DIAN")
        await t.commit()
        raise RechazoDefinitivo(
            f"la nota crédito {numero} está en Siigo pero la DIAN no la ha "
            f"validado en {HORAS_SIN_VALIDAR} h: revisar en Siigo")
    raise Aplazar(f"nota crédito {numero} creada en Siigo; esperando la "
                  f"validación de la DIAN", minutos=1)


async def _anotar_emitida(t, d, nc: dict, *, doc_id: str, en_modo: str,
                          factura_numero: str) -> str:
    numero = _numero_de(nc)
    _, cude = _sello(nc)
    siigo_id = str(nc.get("id") or "")
    ahora = datetime.now(timezone.utc)
    await t.sesion.execute(text("""
        UPDATE retail.documentos_fiscales
           SET estado = 'emitido', numero = :n, cufe = :cude,
               documento_externo_id = :ext,
               respuesta_cruda = CAST(:cruda AS jsonb),
               emitido_en = :ts, ultimo_error = NULL
         WHERE id = :i
    """), {"i": doc_id, "n": numero, "cude": cude, "ext": siigo_id,
           "ts": ahora, "cruda": json.dumps(nc, default=str)})
    # Desde aquí la prenda YA ESTÁ en la bodega de Siigo: la sincronización
    # del inventario deja de sumarla por su cuenta.
    await t.sesion.execute(text("""
        UPDATE retail.devoluciones
           SET nota_credito_numero = :n, entro_a_siigo_en = :ts
         WHERE id = :d
    """), {"d": d["id"], "n": numero, "ts": ahora})
    # Si la clienta YA gastó ese saldo, el anticipo que acaba de nacer se
    # cruza con la factura donde lo gastó.
    from backend.modules.retail.infrastructure.siigo.cruce_anticipo import (
        encolar_cruces,
    )
    await encolar_cruces(t, saldo_id=d["id"])
    await t.auditoria.registrar(
        evento="nota_credito.emitida", ocurrido_en=ahora, severidad="aviso",
        tienda_id=d["tienda_id"], caja_id=d["caja_id"],
        sesion_id=d["sesion_id"], usuario_id="sistema",
        agregado_tipo="devolucion", agregado_id=d["id"],
        payload={"numero_venta": d["numero_venta"], "nota_credito": numero,
                 "factura": factura_numero, "modo": en_modo,
                 "siigo_id": siigo_id, "validada_dian": bool(cude),
                 "motivo": "cambio"})
    log.info("[retail-fiscal] cambio de %s → %s sobre %s (%s)",
             d["numero_venta"], numero, factura_numero, en_modo)
    return f"nota crédito {numero} sobre {factura_numero} ({en_modo})"


async def _cerrar(t, doc_id: str, estado: str, *, error: str) -> None:
    await t.sesion.execute(text("""
        UPDATE retail.documentos_fiscales
           SET estado = :e, ultimo_error = :err WHERE id = :i
    """), {"i": doc_id, "e": estado, "err": error[:500]})
