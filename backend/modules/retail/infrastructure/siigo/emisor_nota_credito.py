"""El manejador que anula ante la DIAN la factura de una venta anulada.

Lo encola `AnularVenta` cuando la venta que se deshace ya tenía factura, y el
emisor de facturas cuando una venta se anuló MIENTRAS su factura estaba en
camino. Sin esto la venta queda anulada en el POS y viva ante la DIAN: se
declara un ingreso que no existió.

MISMA REGLA QUE LA FACTURA, por la misma razón: **una anulación, una nota
crédito.** Siigo no tiene llave de idempotencia, así que se deja escrito «voy
a enviar» antes de enviar, se envía una vez, y al reintentar primero se BUSCA
por su marca. Y creada en Siigo no es nota crédito todavía: lo es cuando la
DIAN la valida.

SÓLO ANULACIONES COMPLETAS. La devolución de una prenda sigue yendo a
Postventa, donde una persona aprueba el caso antes de que salga el documento.
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
from backend.modules.retail.infrastructure.siigo.factura_venta import FacturaInvalida
from backend.modules.retail.infrastructure.siigo.nota_credito_venta import (
    construir_nota_credito,
    marca_nc_de,
)

log = logging.getLogger("retail.fiscal")

__all__ = ["TIPO", "emitir_nota_credito", "crear_manejador"]

TIPO = "emitir_nota_credito"


def crear_manejador(io: Optional[SiigoIO] = None):
    io = io or SiigoIO()

    async def manejador(t, payload: dict) -> Optional[str]:
        return await _emitir(t, payload, io)
    return manejador


async def emitir_nota_credito(t, payload: dict) -> Optional[str]:
    return await _emitir(t, payload, SiigoIO())


def _numero_de(nc: dict) -> str:
    """Las notas crédito de la cuenta no traen `prefix`: su número es `name`
    (`NC-1-7504`). Medido el 2026-10-08."""
    prefijo = (nc.get("prefix") or "").strip()
    if prefijo and nc.get("number") is not None:
        return f"{prefijo}-{nc['number']}"
    return nc.get("name") or str(nc.get("number") or "")


def _sello(nc: dict) -> tuple:
    """(estado, código). En una nota crédito el código de la DIAN es el CUDE,
    no el CUFE (`stamp.cude`, medido contra la cuenta)."""
    sello = nc.get("stamp") or {}
    return (str(sello.get("status") or "").strip().lower(),
            (sello.get("cude") or sello.get("cufe") or "").strip() or None)


async def _emitir(t, payload: dict, io: SiigoIO) -> Optional[str]:
    en_modo = modo()
    if en_modo == "apagado":
        raise Aplazar("la facturación desde el POS está apagada "
                      "(RETAIL_FISCAL_MODO)")

    venta_id = payload["venta_id"]
    v = (await t.sesion.execute(text("""
        SELECT v.id, v.numero, v.estado, v.anulada_en, v.tienda_id, v.caja_id,
               v.sesion_id, ti.siigo_nc_documento_id, ti.siigo_bodega_id,
               ti.zona_horaria
          FROM retail.ventas v JOIN retail.tiendas ti ON ti.id = v.tienda_id
         WHERE v.id = :v
    """), {"v": venta_id})).mappings().first()
    if v is None:
        raise RechazoDefinitivo(f"no existe la venta {venta_id}")
    if v["estado"] != "anulada":
        # La nota crédito de este manejador es por el total. Acreditar una
        # venta que sigue viva sería anularle la factura a una venta real.
        raise RechazoDefinitivo(f"la venta {v['numero']} no está anulada")

    factura = (await t.sesion.execute(text("""
        SELECT estado, numero, cufe, documento_externo_id
          FROM retail.documentos_fiscales
         WHERE venta_id = :v AND tipo = 'factura_electronica'
         ORDER BY creado_en DESC LIMIT 1
    """), {"v": venta_id})).mappings().first()
    if factura is None:
        return "la venta nunca se facturó: no hay nada que acreditar"
    if factura["estado"] in ("enviando", "verificando"):
        raise Aplazar(f"la factura de {v['numero']} todavía está en trámite",
                      minutos=2)
    if factura["estado"] != "emitido":
        return (f"la factura quedó «{factura['estado']}», no emitida: no hay "
                f"nada que acreditar")
    if not factura["cufe"]:
        # Creada en modo prueba: nunca fue a la DIAN. No se le hace nota
        # crédito —Siigo no acredita una factura sin validar—: se borra allá.
        return (f"la factura {factura['numero']} no fue a la DIAN (modo "
                f"prueba): se borra en Siigo, no lleva nota crédito")

    if not v["siigo_nc_documento_id"]:
        raise Aplazar(f"la tienda {v['tienda_id']} no tiene comprobante de "
                      f"nota crédito en Siigo")

    doc = (await t.sesion.execute(text("""
        SELECT id, estado, numero, documento_externo_id, creado_en
          FROM retail.documentos_fiscales
         WHERE venta_id = :v AND tipo = 'nota_credito'
         ORDER BY creado_en DESC LIMIT 1
    """), {"v": venta_id})).mappings().first()
    if doc and doc["estado"] == "emitido":
        return "ya estaba emitida"
    if doc and doc["estado"] in ("rechazado", "discrepante"):
        raise RechazoDefinitivo("Siigo o la DIAN ya rechazaron esta nota "
                                "crédito; hay que corregirla a mano")
    if doc and doc["estado"] == "verificando":
        return await _esperar_dian(
            t, v, io, en_modo=en_modo, siigo_id=doc["documento_externo_id"],
            numero=doc["numero"], factura_numero=factura["numero"],
            desde=doc["creado_en"])

    cuando = v["anulada_en"] or datetime.now(timezone.utc)
    fecha = cuando.astimezone(_zona(v["zona_horaria"])).date().isoformat()
    marca = marca_nc_de(v["id"], v["numero"])

    creada = None
    if doc and doc["estado"] == "enviando":
        creada = await io.buscar_nc_por_marca(desde=fecha, marca=marca)
        if creada:
            log.warning("[retail-fiscal] la nota crédito de %s ya estaba en "
                        "Siigo: se adopta, no se reenvía", v["numero"])

    if creada is None:
        # La factura se lee de SIIGO, no de lo que el POS cree que mandó: la
        # nota crédito copia el documento que la DIAN validó.
        original = await io.leer_factura(factura["documento_externo_id"])
        try:
            cuerpo = construir_nota_credito(
                factura=original, documento_id=int(v["siigo_nc_documento_id"]),
                fecha=fecha, marca=marca, bodega_id=v["siigo_bodega_id"],
                estampar=(en_modo == "produccion"))
        except FacturaInvalida as e:
            raise RechazoDefinitivo(str(e)) from e

        doc_id = doc["id"] if doc else f"{venta_id[:23]}NCR"
        await t.sesion.execute(text("""
            INSERT INTO retail.documentos_fiscales
                (id, venta_id, tipo, estado, payload_snapshot, intentos)
            VALUES (:i, :v, 'nota_credito', 'enviando', CAST(:p AS jsonb), 1)
            ON CONFLICT (id) DO UPDATE
               SET estado = 'enviando', payload_snapshot = EXCLUDED.payload_snapshot,
                   intentos = retail.documentos_fiscales.intentos + 1
        """), {"i": doc_id, "v": venta_id,
               "p": json.dumps({**cuerpo, "_modo": en_modo})})
        # SE CONFIRMA ANTES DE ENVIAR, igual que la factura.
        await t.commit()

        try:
            creada = await io.crear_nota_credito(cuerpo)
        except RechazoDeSiigo as e:
            await _cerrar(t, venta_id, "rechazado", error=str(e))
            await t.commit()
            raise RechazoDefinitivo(str(e)) from e

    numero = _numero_de(creada)
    siigo_id = str(creada.get("id") or "")
    if en_modo != "produccion":
        return await _anotar_emitida(t, v, creada, en_modo=en_modo,
                                     factura_numero=factura["numero"])

    await t.sesion.execute(text("""
        UPDATE retail.documentos_fiscales
           SET estado = 'verificando', numero = :n, documento_externo_id = :ext,
               respuesta_cruda = CAST(:cruda AS jsonb), ultimo_error = NULL
         WHERE venta_id = :v AND tipo = 'nota_credito'
    """), {"v": venta_id, "n": numero, "ext": siigo_id,
           "cruda": json.dumps(creada, default=str)})
    await t.commit()
    return await _esperar_dian(t, v, io, en_modo=en_modo, siigo_id=siigo_id,
                               numero=numero, factura_numero=factura["numero"],
                               desde=datetime.now(timezone.utc), ya_leida=creada)


async def _esperar_dian(t, v, io: SiigoIO, *, en_modo: str, siigo_id: str,
                        numero: str, factura_numero: str, desde: datetime,
                        ya_leida: Optional[dict] = None) -> str:
    """Pregunta hasta que la DIAN valide. Nunca envía nada."""
    nc = ya_leida
    for vuelta in range(io.consultas_inmediatas + 1):
        if nc is None:
            nc = await io.leer_nota_credito(siigo_id)
        estado, _ = _sello(nc)
        if estado == "accepted":
            return await _anotar_emitida(t, v, nc, en_modo=en_modo,
                                         factura_numero=factura_numero)
        if estado == "rejected":
            motivo = json.dumps((nc.get("stamp") or {}), default=str)[:400]
            await _cerrar(t, v["id"], "rechazado",
                          error=f"la DIAN rechazó {numero}: {motivo}")
            await t.commit()
            raise RechazoDefinitivo(
                f"la DIAN rechazó la nota crédito {numero}: {motivo}")
        if vuelta == io.consultas_inmediatas:
            break
        await asyncio.sleep(io.pausa)
        nc = None

    if datetime.now(timezone.utc) - desde > timedelta(hours=HORAS_SIN_VALIDAR):
        await _cerrar(t, v["id"], "discrepante",
                      error=f"{numero} lleva más de {HORAS_SIN_VALIDAR} h en "
                            f"Siigo sin validación de la DIAN")
        await t.commit()
        raise RechazoDefinitivo(
            f"la nota crédito {numero} está en Siigo pero la DIAN no la ha "
            f"validado en {HORAS_SIN_VALIDAR} h: revisar en Siigo")
    raise Aplazar(f"nota crédito {numero} creada en Siigo; esperando la "
                  f"validación de la DIAN", minutos=1)


async def _anotar_emitida(t, v, nc: dict, *, en_modo: str,
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
         WHERE venta_id = :v AND tipo = 'nota_credito'
    """), {"v": v["id"], "n": numero, "cude": cude, "ext": siigo_id,
           "ts": ahora, "cruda": json.dumps(nc, default=str)})
    await t.auditoria.registrar(
        evento="nota_credito.emitida", ocurrido_en=ahora, severidad="critico",
        tienda_id=v["tienda_id"], caja_id=v["caja_id"],
        sesion_id=v["sesion_id"], usuario_id="sistema",
        agregado_tipo="venta", agregado_id=v["id"],
        payload={"numero_venta": v["numero"], "nota_credito": numero,
                 "factura": factura_numero, "modo": en_modo,
                 "siigo_id": siigo_id, "validada_dian": bool(cude)})
    log.info("[retail-fiscal] %s anulada → %s sobre %s (%s)", v["numero"],
             numero, factura_numero, en_modo)
    return f"nota crédito {numero} sobre {factura_numero} ({en_modo})"


async def _cerrar(t, venta_id: str, estado: str, *, error: str) -> None:
    await t.sesion.execute(text("""
        UPDATE retail.documentos_fiscales
           SET estado = :e, ultimo_error = :err
         WHERE venta_id = :v AND tipo = 'nota_credito'
    """), {"v": venta_id, "e": estado, "err": error[:500]})
