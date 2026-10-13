"""Cruzar en Siigo el anticipo de una nota crédito con la factura que lo gastó.

SIIGO NO LO HACE SOLO. La nota crédito de un cambio deja un anticipo a nombre
de la clienta (cuenta 28050501, «De clientes») y la factura de la prenda nueva
se paga con «ANTICIPO CLIENTES» — la misma cuenta. Pero cada documento queda
abierto por su lado: la factura con saldo pendiente y el anticipo sin
consumir. Las dos facturas de reemplazo que Postventa emitió en julio seguían
así en octubre.

EL ASIENTO QUE LOS CIERRA es el que contabilidad ya usa para consumir un
anticipo de nota crédito (CC-1-5585, CC-1-5243), con la contrapartida en la
factura en vez de en el banco:

    Débito   28050501   due = la nota crédito   (NC-1-7517)
    Crédito  28050501   due = la factura nueva  (FV-14-15)

Mismo tercero, mismo valor. Probado contra la cuenta el 2026-10-13: CC-1-5600
dejó el saldo de TFL-15 en cero.

DOS COSAS QUE EL `due` EXIGE:
  · el prefijo es el CÓDIGO del comprobante (`FV-14`), no el que va impreso
    (`TFL`). Sale del `name` del documento en Siigo;
  · la fecha es el VENCIMIENTO del pago con anticipo en ese documento.

UN USO DE SALDO, UN ASIENTO. Un asiento repetido cruza dos veces y deja la
factura con saldo a favor: se marca «voy a enviar» antes de enviar, se envía
una vez, y al reintentar primero se BUSCA por su marca.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import text

from backend.modules.retail.application.comandos.drenar_outbox import (
    Aplazar,
    RechazoDefinitivo,
)
from backend.modules.retail.infrastructure.siigo.emisor_factura import (
    RechazoDeSiigo,
    SiigoIO,
    _zona,
    modo,
)
from backend.modules.retail.infrastructure.siigo.nota_credito_cambio import (
    ANTICIPO_CLIENTES_ID,
)

log = logging.getLogger("retail.fiscal")

__all__ = ["TIPO", "cruzar_anticipo", "crear_manejador", "construir_asiento",
           "marca_cruce_de", "encolar_cruces", "CUENTA_ANTICIPOS",
           "COMPROBANTE_AJUSTES"]

TIPO = "cruzar_anticipo"

#  «De clientes»: la cuenta de la forma de pago ANTICIPO CLIENTES.
CUENTA_ANTICIPOS = "28050501"
#  CC-1 «Ajustes contables»: el comprobante con el que contabilidad ya
#  consume anticipos de notas crédito.
COMPROBANTE_AJUSTES = 11831


def marca_cruce_de(codigo_saldo: str, nota_credito: str, factura: str) -> str:
    return f"POS CRUCE {codigo_saldo} · {nota_credito} con {factura}"


def _due_de(doc: dict) -> dict:
    """La referencia de cartera de un documento de Siigo, por su `name`
    (`FV-14-15` → prefijo `FV-14`, consecutivo 15)."""
    nombre = str(doc.get("name") or "")
    prefijo, _, consecutivo = nombre.rpartition("-")
    if not prefijo or not consecutivo.isdigit():
        raise ValueError(f"no se entiende el número del documento «{nombre}»")
    pago = next((p for p in (doc.get("payments") or [])
                 if int(p.get("id") or 0) == ANTICIPO_CLIENTES_ID), None)
    if pago is None:
        raise ValueError(f"{nombre} no tiene un pago con ANTICIPO CLIENTES")
    return {"prefix": prefijo, "consecutive": int(consecutivo), "quote": 1,
            "date": pago.get("due_date") or doc.get("date")}


def construir_asiento(*, factura: dict, nota_credito: dict, valor_centavos: int,
                      fecha: str, marca: str) -> dict:
    """El cuerpo de `POST /journals`. Puro: `factura` y `nota_credito` son lo
    que devuelve el GET de cada una."""
    tercero_f = factura.get("customer") or {}
    tercero_n = nota_credito.get("customer") or {}
    if str(tercero_f.get("identification")) != str(tercero_n.get("identification")):
        # En Siigo el anticipo es DE UN TERCERO. Cruzarlo con la factura de
        # otro no cierra nada: abre un descuadre en dos personas.
        raise ValueError(
            f"la nota crédito es de {tercero_n.get('identification')} y la "
            f"factura de {tercero_f.get('identification')}: no se cruzan")
    valor = float(Decimal(int(valor_centavos)) / 100)
    for doc in (factura, nota_credito):
        pago = next((p for p in (doc.get("payments") or [])
                     if int(p.get("id") or 0) == ANTICIPO_CLIENTES_ID), None)
        if pago is None or float(pago.get("value") or 0) + 0.005 < valor:
            raise ValueError(
                f"{doc.get('name')} no tiene {valor} en ANTICIPO CLIENTES")
    tercero = {"identification": tercero_f.get("identification"),
               "branch_office": tercero_f.get("branch_office", 0)}
    glosa = f"Cruce anticipo {nota_credito.get('name')} con {factura.get('name')}"

    def linea(movimiento: str, doc: dict) -> dict:
        return {"account": {"code": CUENTA_ANTICIPOS, "movement": movimiento},
                "customer": tercero, "due": _due_de(doc),
                "description": glosa, "value": valor}

    return {"document": {"id": COMPROBANTE_AJUSTES}, "date": fecha,
            "items": [linea("Debit", nota_credito), linea("Credit", factura)],
            "observations": marca}


async def encolar_cruces(t, *, saldo_id: Optional[str] = None,
                         venta_id: Optional[str] = None) -> int:
    """Encola el cruce de los usos de un saldo (o de una venta) que no lo
    tienen. Lo llaman los dos emisores: el que llegue SEGUNDO —la nota crédito
    o la factura— es el que encuentra las dos cosas listas."""
    filas = (await t.sesion.execute(text("""
        SELECT saldo_id, venta_id FROM retail.saldo_usos
         WHERE cruce_numero IS NULL
           AND coalesce(cruce_estado, '') NOT IN ('ya_cruzada', 'rechazado')
           AND (CAST(:s AS text) IS NULL OR saldo_id = :s)
           AND (CAST(:v AS text) IS NULL OR venta_id = :v)
    """), {"s": saldo_id, "v": venta_id})).mappings().all()
    for f in filas:
        await t.outbox.encolar(
            tipo=TIPO, agregado_tipo="saldo_uso",
            agregado_id=f"{f['saldo_id']}:{f['venta_id']}",
            payload={"saldo_id": f["saldo_id"], "venta_id": f["venta_id"]})
    return len(filas)


def crear_manejador(io: Optional[SiigoIO] = None):
    io = io or SiigoIO()

    async def manejador(t, payload: dict) -> Optional[str]:
        return await _cruzar(t, payload, io)
    return manejador


async def cruzar_anticipo(t, payload: dict) -> Optional[str]:
    return await _cruzar(t, payload, SiigoIO())


async def _cruzar(t, payload: dict, io: SiigoIO) -> Optional[str]:
    en_modo = modo()
    if en_modo == "apagado":
        raise Aplazar("la facturación desde el POS está apagada "
                      "(RETAIL_FISCAL_MODO)")
    if en_modo != "produccion":
        # Un asiento contable no tiene «modo prueba»: siempre es de verdad.
        return "sólo se cruza en producción"

    ids = {"s": payload["saldo_id"], "v": payload["venta_id"]}
    u = (await t.sesion.execute(text("""
        SELECT u.monto, u.cruce_estado, u.cruce_numero, s.codigo,
               v.numero AS venta, v.estado AS estado_venta, v.tienda_id,
               v.caja_id, v.sesion_id, ti.zona_horaria,
               f.estado AS f_estado, f.numero AS f_numero,
               f.documento_externo_id AS f_id,
               n.estado AS n_estado, n.numero AS n_numero,
               n.documento_externo_id AS n_id
          FROM retail.saldo_usos u
          JOIN retail.saldos_a_favor s ON s.id = u.saldo_id
          JOIN retail.ventas v ON v.id = u.venta_id
          JOIN retail.tiendas ti ON ti.id = v.tienda_id
          LEFT JOIN LATERAL (
                SELECT estado, numero, documento_externo_id
                  FROM retail.documentos_fiscales
                 WHERE venta_id = v.id AND tipo = 'factura_electronica'
                 ORDER BY creado_en DESC LIMIT 1) f ON true
          LEFT JOIN retail.documentos_fiscales n
                 ON n.id = left(s.devolucion_id::text, 23) || 'NCD'
         WHERE u.saldo_id = :s AND u.venta_id = :v
    """), ids)).mappings().first()
    if u is None:
        # La venta se anuló y el saldo volvió a su dueña: no hay qué cruzar.
        return "ese uso del saldo ya no existe"
    if u["cruce_numero"]:
        return f"ya estaba cruzado con {u['cruce_numero']}"
    if u["cruce_estado"] in ("ya_cruzada", "rechazado"):
        return f"quedó «{u['cruce_estado']}»: no se reintenta solo"
    if u["estado_venta"] == "anulada":
        return "la venta se anuló: no se cruza"
    # Quien llegue segundo —la nota crédito o la factura— vuelve a encolar.
    if u["n_estado"] != "emitido" or not u["n_id"]:
        return "todavía no sale la nota crédito del cambio: se cruza cuando salga"
    if u["f_estado"] != "emitido" or not u["f_id"]:
        return "todavía no sale la factura: se cruza cuando salga"

    marca = marca_cruce_de(u["codigo"], u["n_numero"], u["f_numero"])
    hoy = datetime.now(timezone.utc).astimezone(
        _zona(u["zona_horaria"])).date().isoformat()

    creado = None
    if u["cruce_estado"] == "enviando":
        # Hubo un envío sin resultado. ANTES de reenviar se mira si llegó.
        creado = await io.buscar_asiento_por_marca(marca=marca)
        if creado:
            log.warning("[retail-fiscal] el cruce de %s ya estaba en Siigo: "
                        "se adopta, no se reenvía", u["codigo"])

    if creado is None:
        factura = await io.leer_factura(u["f_id"])
        saldo_factura = factura.get("balance")
        if saldo_factura is not None and \
                float(saldo_factura) + 0.005 < int(u["monto"]) / 100:
            # Alguien ya la cruzó a mano. Cruzarla otra vez la dejaría con
            # saldo a favor: se anota y no se toca.
            await _anotar(t, ids, estado="ya_cruzada",
                          error=f"la factura {u['f_numero']} ya sólo tiene "
                                f"{saldo_factura} pendiente")
            await t.commit()
            return (f"la factura {u['f_numero']} ya no tiene ese saldo "
                    f"pendiente: no se cruza")
        nota = await io.leer_nota_credito(u["n_id"])
        try:
            cuerpo = construir_asiento(
                factura=factura, nota_credito=nota,
                valor_centavos=int(u["monto"]), fecha=hoy, marca=marca)
        except ValueError as e:
            await _anotar(t, ids, estado="rechazado", error=str(e))
            await t.commit()
            raise RechazoDefinitivo(str(e)) from e

        # SE CONFIRMA ANTES DE ENVIAR, igual que la factura.
        await _anotar(t, ids, estado="enviando", error=None)
        await t.commit()
        try:
            creado = await io.crear_asiento(cuerpo)
        except RechazoDeSiigo as e:
            await _anotar(t, ids, estado="rechazado", error=str(e))
            await t.commit()
            raise RechazoDefinitivo(str(e)) from e

    numero = str(creado.get("name") or creado.get("number") or "")
    ahora = datetime.now(timezone.utc)
    await t.sesion.execute(text("""
        UPDATE retail.saldo_usos
           SET cruce_estado = 'cruzado', cruce_numero = :n, cruce_siigo_id = :i,
               cruce_error = NULL, cruzado_en = :ts
         WHERE saldo_id = :s AND venta_id = :v
    """), {**ids, "n": numero, "i": str(creado.get("id") or ""), "ts": ahora})
    await t.auditoria.registrar(
        evento="anticipo.cruzado", ocurrido_en=ahora, severidad="aviso",
        tienda_id=u["tienda_id"], caja_id=u["caja_id"],
        sesion_id=u["sesion_id"], usuario_id="sistema",
        agregado_tipo="venta", agregado_id=payload["venta_id"],
        payload={"saldo": u["codigo"], "nota_credito": u["n_numero"],
                 "factura": u["f_numero"], "asiento": numero,
                 "valor": int(u["monto"])})
    log.info("[retail-fiscal] %s: %s cruzada con %s → %s", u["codigo"],
             u["n_numero"], u["f_numero"], numero)
    return f"{u['n_numero']} cruzada con {u['f_numero']}: {numero}"


async def _anotar(t, ids: dict, *, estado: str, error: Optional[str]) -> None:
    await t.sesion.execute(text("""
        UPDATE retail.saldo_usos SET cruce_estado = :e, cruce_error = :err
         WHERE saldo_id = :s AND venta_id = :v
    """), {**ids, "e": estado, "err": (error or "")[:500] or None})
