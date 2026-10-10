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

CREADA EN SIIGO NO ES FACTURA TODAVÍA. Una factura electrónica existe cuando
la DIAN la valida y le pone el CUFE; antes de eso es un borrador con número.
Por eso hay un cuarto paso: el documento queda en `verificando` y se le
pregunta a Siigo hasta que el sello diga «Accepted». Sólo entonces la venta
pasa a `emitido` — y sólo entonces la tirilla puede decir «factura».

EL NÚMERO LO PONE SIIGO, bajo la resolución de la tienda. El número del POS
(`ARRPOS-…`) es una referencia interna y nunca se presenta como el fiscal.

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
from datetime import datetime, timedelta, timezone
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
from backend.modules.retail.infrastructure.siigo.tercero_siigo import (
    ClienteIncompleto,
    cuerpo_de_cliente,
)

log = logging.getLogger("retail.fiscal")

__all__ = ["TIPO", "emitir_factura", "crear_manejador", "modo", "SiigoIO",
           "RechazoDeSiigo"]

TIPO = "emitir_documento_fiscal"
MODOS = ("apagado", "prueba", "produccion")

#  Cuánto se espera a la DIAN antes de pedir que alguien mire. Lo normal son
#  segundos; horas ya es que algo se quedó atascado entre Siigo y la DIAN.
HORAS_SIN_VALIDAR = 6


def modo() -> str:
    m = os.environ.get("RETAIL_FISCAL_MODO", "apagado").strip().lower()
    return m if m in MODOS else "apagado"


def _zona(nombre: Optional[str]):
    """La zona de la tienda, para que la factura lleve la fecha en que se
    vendió y no la de UTC — una venta de las 8 p. m. caería al día siguiente.

    Si el servidor no trae la base de zonas horarias, `ZoneInfo` revienta al
    usarse. Colombia no tiene horario de verano: UTC−5 fijo da lo mismo.
    """
    try:
        return ZoneInfo(nombre or "America/Bogota")
    except Exception:  # noqa: BLE001
        return timezone(timedelta(hours=-5))


class RechazoDeSiigo(Exception):
    """Siigo respondió 4xx: el documento NO se creó y no se va a crear así."""


# ── La puerta a Siigo ───────────────────────────────────────────────────────

class SiigoIO:
    """Todo lo que este manejador le pide a Siigo. Las pruebas ponen otro.

    Los imports son LOCALES: `backend.services.siigo` es del ERP y el módulo
    retail tiene que poder cargarse sin él.
    """

    #  La DIAN suele validar en segundos. Se le pregunta unas pocas veces ahí
    #  mismo —la clienta está esperando su factura en el mostrador— y si no,
    #  se sigue preguntando desde la cola. La pausa respeta el ~1 req/s.
    consultas_inmediatas = 4
    pausa = 2.0

    async def leer_factura(self, siigo_id: str) -> dict:
        def ir():
            from backend.services.siigo import siigo_get
            return siigo_get(f"/invoices/{siigo_id}")
        return await asyncio.to_thread(ir)

    async def _post_una_vez(self, ruta: str, cuerpo: dict) -> dict:
        """UN intento. `siigo_post` reintenta solo ante un 502, y si el
        documento sí se creó, ese reintento crea el segundo."""
        def ir():
            import httpx
            from backend.services import siigo as s
            r = httpx.post(s.SIIGO_BASE + ruta, json=cuerpo, timeout=60,
                           headers={"Authorization": f"Bearer {s._get_token()}",
                                    "Partner-Id": os.getenv("SIIGO_PARTNER_ID", ""),
                                    "Content-Type": "application/json"})
            if r.status_code in (200, 201):
                return r.json()
            if 400 <= r.status_code < 500 and r.status_code != 429:
                raise RechazoDeSiigo(f"HTTP {r.status_code}: {r.text[:400]}")
            raise RuntimeError(f"Siigo HTTP {r.status_code}: {r.text[:200]}")
        return await asyncio.to_thread(ir)

    async def crear_cliente(self, cuerpo: dict) -> dict:
        """Un cliente repetido en la contabilidad se arregla fusionando a
        mano: tampoco se reintenta."""
        return await self._post_una_vez("/customers", cuerpo)

    # ── Notas crédito ───────────────────────────────────────────────────────

    async def crear_nota_credito(self, cuerpo: dict) -> dict:
        return await self._post_una_vez("/credit-notes", cuerpo)

    async def leer_nota_credito(self, siigo_id: str) -> dict:
        def ir():
            from backend.services.siigo import siigo_get
            return siigo_get(f"/credit-notes/{siigo_id}")
        return await asyncio.to_thread(ir)

    async def buscar_nc_por_marca(self, *, desde: str, marca: str) -> Optional[dict]:
        def ir():
            from backend.services.siigo import siigo_get
            for pagina in range(1, 21):
                r = siigo_get("/credit-notes", {
                    "created_start": desde, "page": pagina, "page_size": 100})
                filas = r.get("results", []) if isinstance(r, dict) else []
                for f in filas:
                    if marca in (f.get("observations") or ""):
                        return f
                if len(filas) < 100:
                    return None
            return None
        return await asyncio.to_thread(ir)

    async def tipo_documento(self, documento_id: int) -> Optional[dict]:
        def ir():
            from backend.services.siigo import siigo_get
            tipos = siigo_get("/document-types", {"type": "FV"})
            return next((t for t in tipos if int(t.get("id") or 0) == int(documento_id)),
                        None)
        return await asyncio.to_thread(ir)

    async def sucursal_de_cliente(self, identificacion: str) -> Optional[int]:
        """La sucursal con la que Siigo tiene a la clienta; `None` si no está.

        NO BASTA CON SABER QUE EXISTE. Siigo identifica a un tercero por
        identificación Y sucursal, y hay clientas creadas hace años con una
        sucursal distinta de 0. Facturarle a la 0 a quien está en la 17
        devuelve «The customer doesn't exist» aunque la consulta la acabe de
        encontrar (Florida, 2026-10-10, FLPOS-2539).
        """
        def ir():
            from backend.services.siigo import siigo_get
            r = siigo_get("/customers", {"identification": identificacion})
            filas = r.get("results", []) if isinstance(r, dict) else (r or [])
            # `identification` es de los filtros que Siigo a veces ignora y
            # devuelve la lista entera: se comprueba el dato, no que haya filas.
            sucursales = sorted(
                int(c.get("branch_office") or 0) for c in filas
                if str(c.get("identification")) == str(identificacion)
                and c.get("active", True) is not False)
            # Si está en varias, la principal (0) o, a falta de ella, la menor.
            return sucursales[0] if sucursales else None
        return await asyncio.to_thread(ir)

    async def existe_cliente(self, identificacion: str) -> bool:
        return await self.sucursal_de_cliente(identificacion) is not None

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
        return await self._post_una_vez("/invoices", cuerpo)


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
               cl.id AS cliente_id, cl.numero_documento AS cliente_documento,
               cl.correo AS cliente_correo
          FROM retail.ventas v
          JOIN retail.cajas c    ON c.id = v.caja_id
          JOIN retail.tiendas ti ON ti.id = v.tienda_id
          LEFT JOIN retail.clientes cl ON cl.id = v.cliente_id
         WHERE v.id = :v
    """), {"v": venta_id})).mappings().first()
    if v is None:
        raise RechazoDefinitivo(f"no existe la venta {venta_id}")

    doc = (await t.sesion.execute(text("""
        SELECT id, estado, numero, documento_externo_id, creado_en
          FROM retail.documentos_fiscales
         WHERE venta_id = :v AND tipo = 'factura_electronica'
         ORDER BY creado_en DESC LIMIT 1
    """), {"v": venta_id})).mappings().first()

    anulada = v["estado"] == "anulada"
    if anulada and (doc is None or doc["estado"] not in ("enviando", "verificando")):
        # Se anuló antes de que saliera nada hacia Siigo: no se emite.
        return "venta anulada antes de facturarse: no se emite"
    # SI SE ANULÓ CON LA FACTURA EN CAMINO, NO SE SUELTA. Puede que ya exista
    # en Siigo: hay que terminar de averiguarlo, y si existe, anularla con
    # nota crédito. Lo que no se hace es enviarla (más abajo).

    # Lo que falta de CONFIGURACIÓN no es un fallo de la venta: se espera.
    if not v["siigo_documento_id"]:
        raise Aplazar(f"la caja {v['caja_id']} no tiene comprobante de Siigo")
    if not v["siigo_vendedor_id"]:
        raise Aplazar(f"la tienda {v['tienda_id']} no tiene vendedor de Siigo")
    if doc and doc["estado"] == "emitido":
        return "ya estaba emitida"
    if doc and doc["estado"] in ("rechazado", "discrepante"):
        raise RechazoDefinitivo("Siigo o la DIAN ya la rechazaron; hay que "
                                "corregirla a mano")
    if doc and doc["estado"] == "verificando":
        # YA ESTÁ EN SIIGO. De aquí en adelante sólo se PREGUNTA: no hay
        # camino por el que esta rama vuelva a enviar.
        return await _esperar_dian(
            t, v, io, en_modo=en_modo, siigo_id=doc["documento_externo_id"],
            numero=doc["numero"], desde=doc["creado_en"])

    fecha = v["cerrada_en"].astimezone(
        _zona(v["zona_horaria"])).date().isoformat()
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

    if creada is None and anulada:
        # El envío nunca llegó a Siigo y la venta ya no existe: no se manda.
        await t.sesion.execute(text("""
            UPDATE retail.documentos_fiscales
               SET estado = 'fallido',
                   ultimo_error = 'la venta se anuló antes de que la factura llegara a Siigo'
             WHERE venta_id = :v AND tipo = 'factura_electronica'
        """), {"v": venta_id})
        await t.sesion.execute(text(
            "UPDATE retail.ventas SET estado_fiscal = 'no_aplica' WHERE id = :v"),
            {"v": venta_id})
        return "venta anulada y la factura no llegó a Siigo: no se emite"

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

    numero = _numero_de(creada)
    siigo_id = str(creada.get("id") or "")

    if en_modo != "produccion":
        # Sin estampar no hay DIAN que esperar: el documento existe en Siigo
        # y ahí se queda, revisable. NO es una factura y la tirilla no lo dice
        # (no tiene CUFE).
        return await _anotar_emitida(t, v, creada, en_modo=en_modo)

    # Se deja escrito QUE YA ESTÁ EN SIIGO antes de esperar a la DIAN: si el
    # proceso muere esperando, el reintento pregunta por este id, no reenvía.
    await t.sesion.execute(text("""
        UPDATE retail.documentos_fiscales
           SET estado = 'verificando', numero = :n, documento_externo_id = :ext,
               respuesta_cruda = CAST(:cruda AS jsonb), ultimo_error = NULL
         WHERE venta_id = :v AND tipo = 'factura_electronica'
    """), {"v": venta_id, "n": numero, "ext": siigo_id,
           "cruda": json.dumps(creada, default=str)})
    await t.commit()
    return await _esperar_dian(t, v, io, en_modo=en_modo, siigo_id=siigo_id,
                               numero=numero, desde=datetime.now(timezone.utc),
                               ya_leida=creada)


def _numero_de(factura: dict) -> str:
    """El número LEGAL: prefijo de la resolución + consecutivo.

    NO es `name`. Medido contra la cuenta el 2026-10-08: una factura de
    Arrayanes trae `name: "FV-6-11451"` —el código interno del comprobante en
    Siigo— y `prefix: "TARR"`, `number: 11451`. Lo que la DIAN validó y lo que
    va impreso es `TARR-11451`.
    """
    prefijo = (factura.get("prefix") or "").strip()
    numero = factura.get("number")
    if prefijo and numero is not None:
        return f"{prefijo}-{numero}"
    return factura.get("name") or str(numero or "")


def _sello(factura: dict) -> tuple:
    """(estado en minúsculas, cufe). Siigo responde `Accepted` cuando la DIAN
    validó; mientras tanto `Draft` o lo que esté haciendo."""
    sello = factura.get("stamp") or {}
    return (str(sello.get("status") or "").strip().lower(),
            (sello.get("cufe") or "").strip() or None)


async def _esperar_dian(t, v, io: SiigoIO, *, en_modo: str, siigo_id: str,
                        numero: str, desde: datetime,
                        ya_leida: Optional[dict] = None) -> str:
    """Pregunta hasta que la DIAN valide. Nunca envía nada."""
    factura = ya_leida
    for vuelta in range(io.consultas_inmediatas + 1):
        if factura is None:
            factura = await io.leer_factura(siigo_id)
        estado, cufe = _sello(factura)
        if estado == "accepted" and cufe:
            return await _anotar_emitida(t, v, factura, en_modo=en_modo)
        if estado == "rejected":
            motivo = json.dumps((factura.get("stamp") or {}), default=str)[:400]
            await _cerrar(t, v["id"], "rechazado",
                          error=f"la DIAN rechazó {numero}: {motivo}")
            await t.commit()
            raise RechazoDefinitivo(
                f"la DIAN rechazó la factura {numero}: {motivo}")
        if vuelta == io.consultas_inmediatas:
            break
        await asyncio.sleep(io.pausa)
        factura = None

    if datetime.now(timezone.utc) - desde > timedelta(hours=HORAS_SIN_VALIDAR):
        # Existe en Siigo con número, pero la DIAN no la ha validado en horas.
        # No se reintenta sola para siempre: alguien tiene que mirarla.
        await _cerrar(t, v["id"], "discrepante",
                      error=f"{numero} lleva más de {HORAS_SIN_VALIDAR} h en "
                            f"Siigo sin validación de la DIAN")
        await t.commit()
        raise RechazoDefinitivo(
            f"la factura {numero} está en Siigo pero la DIAN no la ha validado "
            f"en {HORAS_SIN_VALIDAR} h: revisar en Siigo")
    raise Aplazar(f"{numero} creada en Siigo; esperando la validación de la "
                  f"DIAN", minutos=1)


async def _anotar_emitida(t, v, factura: dict, *, en_modo: str) -> str:
    numero = _numero_de(factura)
    _, cufe = _sello(factura)
    siigo_id = str(factura.get("id") or "")
    ahora = datetime.now(timezone.utc)
    await t.sesion.execute(text("""
        UPDATE retail.documentos_fiscales
           SET estado = 'emitido', numero = :n, cufe = :cufe,
               documento_externo_id = :ext,
               respuesta_cruda = CAST(:cruda AS jsonb),
               emitido_en = :ts, ultimo_error = NULL
         WHERE venta_id = :v AND tipo = 'factura_electronica'
    """), {"v": v["id"], "n": numero, "cufe": cufe, "ext": siigo_id,
           "ts": ahora, "cruda": json.dumps(factura, default=str)})
    await t.sesion.execute(text(
        "UPDATE retail.ventas SET estado_fiscal = 'emitido' WHERE id = :v"),
        {"v": v["id"]})
    # LO QUE COBRÓ LA CAJA CONTRA LO QUE FACTURÓ SIIGO. Deberían ser iguales
    # salvo, como mucho, un centavo de redondeo. Queda escrito en la auditoría
    # para que un descuadre se vea el mismo día y no en la declaración.
    diferencia = None
    if factura.get("total") is not None:
        diferencia = round(float(factura["total"]) * 100 - int(v["total"]))
        if abs(diferencia) > 1:
            log.warning("[retail-fiscal] %s: Siigo facturó %s y la caja cobró "
                        "%s centavos", numero, factura["total"], v["total"])
    await t.auditoria.registrar(
        evento="factura.emitida", ocurrido_en=ahora,
        tienda_id=v["tienda_id"], caja_id=v["caja_id"],
        sesion_id=v["sesion_id"], usuario_id="sistema",
        agregado_tipo="venta", agregado_id=v["id"],
        payload={"numero_venta": v["numero"], "factura": numero,
                 "modo": en_modo, "siigo_id": siigo_id,
                 "validada_dian": bool(cufe),
                 "diferencia_centavos": diferencia})
    log.info("[retail-fiscal] %s → %s (%s)", v["numero"], numero, en_modo)

    if v["estado"] == "anulada":
        # La venta se anuló mientras su factura estaba en camino. `AnularVenta`
        # no encoló la nota crédito —en ese momento no había factura— y sin
        # esto quedaría una factura viva de una venta que no existe.
        await t.outbox.encolar(
            tipo="emitir_nota_credito", agregado_tipo="venta",
            agregado_id=v["id"],
            payload={"venta_id": v["id"],
                     "motivo": "anulada con la factura en trámite"})
        return f"factura {numero} ({en_modo}) de una venta ANULADA: se encola su nota crédito"
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
    con_clienta = bool(identificacion and identificacion != CONSUMIDOR_FINAL)
    sucursal = 0
    if con_clienta:
        hallada = await io.sucursal_de_cliente(identificacion)
        if hallada is None:
            # Recién creada queda en la sucursal 0, que es la que se manda.
            await _crear_clienta(t, v, io, identificacion)
        else:
            sucursal = hallada

    try:
        return construir_factura(
            venta={"id": v["id"], "numero": v["numero"], "total": v["total"]},
            lineas=lineas, pagos=pagos, documento_id=documento_id,
            tipo_descuento=tipo.get("discount_type"),
            vendedor_id=int(v["siigo_vendedor_id"]), fecha=fecha,
            identificacion=identificacion, sucursal=sucursal,
            bodega_id=v["siigo_bodega_id"],
            centro_costo_id=v["siigo_centro_costo_id"], estampar=estampar,
            # La entrega de la factura: a quien dejó correo, Siigo se la manda.
            enviar_correo=bool(estampar and con_clienta
                               and (v["cliente_correo"] or "").strip()))
    except FacturaInvalida as e:
        raise RechazoDefinitivo(str(e)) from e


async def _crear_clienta(t, v, io: SiigoIO, identificacion: str) -> None:
    """La clienta que el POS registró y Siigo no conoce.

    Lo que falle aquí ESPERA, no rechaza: una ficha con un solo nombre se
    completa en diez segundos y la factura sale sola en la siguiente vuelta.
    Lo que nunca pasa es facturarle a otra persona.
    """
    c = (await t.sesion.execute(text("""
        SELECT tipo_documento, numero_documento, dv, nombre, apellido,
               telefono, correo, ciudad, direccion
          FROM retail.clientes WHERE id = :i
    """), {"i": v["cliente_id"]})).mappings().first()
    try:
        cuerpo = cuerpo_de_cliente(dict(c))
    except ClienteIncompleto as e:
        raise Aplazar(f"clienta {identificacion}: {e}") from e

    try:
        creada = await io.crear_cliente(cuerpo)
    except RechazoDeSiigo as e:
        # Puede ser que otra caja la creara un segundo antes. Si ya está,
        # se sigue; si no, se espera con el motivo a la vista.
        if not await io.existe_cliente(identificacion):
            raise Aplazar(f"Siigo no dejó crear a la clienta "
                          f"{identificacion}: {e}") from e
        return
    if creada.get("id"):
        await t.sesion.execute(text(
            "UPDATE retail.clientes SET siigo_customer_id = :s WHERE id = :i"),
            {"s": str(creada["id"]), "i": v["cliente_id"]})
    log.info("[retail-fiscal] clienta %s creada en Siigo", identificacion)


async def _cerrar(t, venta_id: str, estado: str, *, error: str) -> None:
    await t.sesion.execute(text("""
        UPDATE retail.documentos_fiscales
           SET estado = :e, ultimo_error = :err
         WHERE venta_id = :v AND tipo = 'factura_electronica'
    """), {"v": venta_id, "e": estado, "err": error[:500]})
    await t.sesion.execute(text(
        "UPDATE retail.ventas SET estado_fiscal = :e WHERE id = :v"),
        {"v": venta_id, "e": estado})
