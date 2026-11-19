"""El manejador que le pide a Melonn el despacho de una venta con envío.

Lo llama el drenador de la cola (`crear_despacho_melonn`), encolado al cerrar
la venta junto al de la factura. NO espera a la factura: la venta ya se cobró
y la prenda tiene que salir.

LO QUE ESTE ARCHIVO TIENE QUE GARANTIZAR: **una venta, un pedido en Melonn.**
Un pedido repetido son dos paquetes a la misma clienta. Y es la misma trampa
que costó 41 facturas de más en Siigo (2026-11-18), así que se cuida igual:

  1. Antes de crear, se PREGUNTA si ya existe (`GET sell-orders/{número}`): el
     número de la venta es el `external_order_number` del pedido.
  2. Se deja escrito «voy a enviar» y se confirma en la base antes de enviar.
  3. Se envía UNA vez (`melonn_client._post` reintenta solo: no se usa).
  4. Un envío sin respuesta NO se repite al minuto: Melonn puede crearlo
     tarde. Durante `MINUTOS_SIN_REENVIAR` sólo se pregunta.

EL PEDIDO VA PREPAGADO Y D2C: sin monto ni tipo de contra entrega y sin marcar
B2B. Con contra entrega entraría a la cartera COD del OS; con B2B desaparece
de sus pantallas (ver el diseño, 2026-11-13).

LO QUE MELONN RECHAZA NO SE REINTENTA A CIEGAS. Sin existencia o una dirección
que no entiende no mejoran por insistir: el despacho queda `no_creado` con el
motivo, a la vista de la oficina, que decide (otra prenda o devolver la plata).

Medido contra Melonn el 2026-11-17 (pedido de prueba PRUEBA-POS-1):
`external_order_id` es obligatorio; el SKU es el de MALE; bodega `MED-2` (la
pone Melonn); método `MEL-15`; el teléfono va `+57-3XXXXXXXXX`; Shopify baja
la existencia solo a los ~45 s.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote

from sqlalchemy import text

from backend.modules.retail.application.comandos.drenar_outbox import (
    Aplazar,
    RechazoDefinitivo,
)

log = logging.getLogger("retail.envio")

__all__ = ["TIPO", "crear_despacho", "crear_manejador", "MelonnIO",
           "RechazoDeMelonn", "CuotaAgotada", "MelonnOcupado",
           "construir_pedido", "MINUTOS_SIN_REENVIAR"]

TIPO = "crear_despacho_melonn"

#  El envío estándar de Melonn, local y nacional.
METODO_ENVIO = "MEL-15"

#  Tras un envío sin respuesta, cuánto se espera —sólo preguntando— antes de
#  volver a enviar. El mismo plazo que la factura (`emisor_factura`).
MINUTOS_SIN_REENVIAR = 45
MINUTOS_ENTRE_PREGUNTAS = 3
#  La cuota diaria de Melonn (10.000) se libera sola; no vale la pena
#  preguntar cada minuto.
MINUTOS_SI_NO_HAY_CUOTA = 30


def _ahora() -> datetime:
    """El reloj de la espera antes de reenviar. Aparte, para poder probarla."""
    return datetime.now(timezone.utc)


class RechazoDeMelonn(Exception):
    """Melonn respondió 4xx: el pedido NO se creó y no se va a crear así."""


class CuotaAgotada(Exception):
    """Se acabó la cuota diaria de Melonn. No se envió nada."""


class MelonnOcupado(Exception):
    """429/503 pasajero: Melonn no recibió la petición. No se envió nada."""


# ── La puerta a Melonn ──────────────────────────────────────────────────────

class MelonnIO:
    """Lo que el POS necesita de Melonn, de a UNA petición.

    Usa la llave, el ritmo y la detección de cuota del cliente del OS
    (`src/melonn_client.py`), pero no su `_get`/`_post`: aquéllos reintentan y
    devuelven `None` ante cualquier fallo, y aquí hace falta distinguir «no
    existe» de «no pude preguntar». El import es LOCAL: el módulo retail tiene
    que poder cargarse sin el OS.
    """

    tiempo = 45

    def _pedir(self, metodo: str, ruta: str, cuerpo: Optional[dict] = None):
        import requests
        import melonn_client as mc

        mc._rate_limiter.wait()
        r = requests.request(
            metodo, f"{mc._BASE_URL}/{ruta}", json=cuerpo, timeout=self.tiempo,
            headers={"x-api-key": mc._api_key(), "Accept": "application/json",
                     "Content-Type": "application/json"})
        if r.status_code in (429, 503):
            if mc._es_cuota_agotada(r):
                mc._marcar_cuota_agotada()
                raise CuotaAgotada("cuota diaria de Melonn agotada")
            raise MelonnOcupado(f"Melonn HTTP {r.status_code}")
        return r

    @staticmethod
    def _ruta(numero: str) -> str:
        return "sell-orders/" + quote(numero, safe="")

    async def leer_pedido(self, numero: str) -> Optional[dict]:
        """El pedido con ese `external_order_number`, o `None` si NO EXISTE
        (404). Cualquier otra cosa lanza: «no pude preguntar» no es «no hay»."""
        def ir():
            r = self._pedir("GET", self._ruta(numero))
            if r.status_code == 404:
                return None
            if r.status_code != 200:
                raise RuntimeError(f"Melonn HTTP {r.status_code}: {r.text[:200]}")
            dato = r.json() if r.content else None
            return dato if isinstance(dato, dict) and dato else None
        return await asyncio.to_thread(ir)

    async def crear_pedido(self, cuerpo: dict) -> dict:
        """UN intento. 4xx → `RechazoDeMelonn` (no se creó). Timeout o 5xx
        suben tal cual: no se sabe si se creó."""
        def ir():
            r = self._pedir("POST", "sell-orders", cuerpo)
            if r.status_code in (200, 201):
                return r.json() if r.content else {}
            if 400 <= r.status_code < 500:
                try:
                    motivo = r.json().get("message") or r.text
                except Exception:  # noqa: BLE001
                    motivo = r.text
                raise RechazoDeMelonn(f"HTTP {r.status_code}: {str(motivo)[:400]}")
            raise RuntimeError(f"Melonn HTTP {r.status_code}: {r.text[:200]}")
        return await asyncio.to_thread(ir)

    async def pedir_cancelacion(self, numero: str, motivo: str) -> None:
        def ir():
            r = self._pedir("POST", self._ruta(numero) + "/request-cancellation",
                            {"comments": motivo[:250]})
            if r.status_code in (200, 201, 204):
                return
            if 400 <= r.status_code < 500:
                raise RechazoDeMelonn(f"HTTP {r.status_code}: {r.text[:300]}")
            raise RuntimeError(f"Melonn HTTP {r.status_code}: {r.text[:200]}")
        return await asyncio.to_thread(ir)


# ── Armar el pedido. Puro. ──────────────────────────────────────────────────

def _telefono(crudo: str) -> str:
    """`300 123 4567` o `+57 3001234567` → `+57-3001234567`, que es como lo
    recibe Melonn. Se queda con los últimos diez dígitos."""
    digitos = re.sub(r"\D", "", crudo or "")
    return f"+57-{digitos[-10:]}" if len(digitos) >= 10 else digitos


def id_externo(numero_venta: str) -> str:
    """El `external_order_id` que Melonn exige. NUMÉRICO Y QUE NO SEA UN
    PEDIDO DE SHOPIFY: el OS mete ese campo en un lote `ids=` hacia Shopify, y
    aunque ya lo vacía para los números de caja (`melonn_client._normalizar`),
    no se deja la puerta abierta. `999` + diez dígitos sacados del número de
    la venta: siempre el mismo para la misma venta."""
    n = int(hashlib.sha256(numero_venta.encode()).hexdigest(), 16) % 10**10
    return f"999{n:010d}"


def construir_pedido(*, numero_venta: str, lineas: list, despacho: dict) -> dict:
    """El cuerpo de `POST /sell-orders` para una venta con envío."""
    items = [{"sku": str(linea["sku"]).strip(), "quantity": int(linea["cantidad"])}
             for linea in lineas if int(linea["cantidad"]) > 0]
    if not items:
        raise ValueError("la venta no tiene prendas que despachar")
    nombre = despacho["destinatario"].strip()
    return {
        "external_order_number": numero_venta,
        "external_order_id": id_externo(numero_venta),
        "tags": ["POS"],
        "shipping_method_code": METODO_ENVIO,
        "line_items": items,
        "shipping_info": {
            "address_l1": despacho["direccion"].strip(),
            "address_l2": (despacho.get("complemento") or "").strip(),
            "city": despacho["ciudad"].strip(),
            "region": despacho["departamento"].strip(),
            "country": "Colombia",
            "full_name": nombre,
            "phone_number": _telefono(despacho["telefono"]),
        },
        "buyer": {"full_name": nombre,
                  "phone_number": re.sub(r"\D", "", despacho["telefono"])[-10:]},
        # A PROPÓSITO no van: `payment_on_delivery_amount`,
        # `payment_on_delivery_type` ni `is_b2b`. Ver la cabecera.
    }


# ── El manejador ────────────────────────────────────────────────────────────

def crear_manejador(io: Optional[MelonnIO] = None):
    io = io or MelonnIO()

    async def manejador(t, payload: dict) -> Optional[str]:
        return await _crear(t, payload, io)
    return manejador


async def crear_despacho(t, payload: dict) -> Optional[str]:
    """El que se registra en `MANEJADORES`."""
    return await _crear(t, payload, MelonnIO())


#  Estados de Melonn que ya no son «lo tiene Melonn» (códigos del detalle,
#  los mismos que usa `melonn_client`). 15 = cancelado (medido 2026-11-17).
CODIGO_CANCELADO = 15


def _de_melonn(pedido: dict) -> dict:
    """Lo que se anota de un pedido de Melonn, venga del POST o del GET.

    El POST contesta `{"sell_order": {internal_order_number, …}}`; el GET, el
    pedido suelto. Y el estado llega como `{"code"|"id": n, "name": …}`, con
    el nombre a veces repetido (`melonn_client._estado_de`).
    """
    pedido = pedido.get("sell_order") if isinstance(pedido.get("sell_order"), dict) \
        else pedido
    crudo = pedido.get("sell_order_state") or pedido.get("state") or {}
    crudo = crudo if isinstance(crudo, dict) else {}
    try:
        codigo = int(crudo.get("code") if crudo.get("code") is not None
                     else crudo.get("id") or 0)
    except (TypeError, ValueError):
        codigo = 0
    nombre = str(crudo.get("name") or "").strip()
    mitad = len(nombre) // 2
    if nombre and len(nombre) % 2 == 0 and nombre[:mitad] == nombre[mitad:]:
        nombre = nombre[:mitad]
    return {
        "numero": str(pedido.get("internal_order_number") or ""),
        "codigo": codigo,
        "estado": nombre or "recibido",
        "seguimiento": str(pedido.get("melonn_tracking_link") or "") or None,
    }


async def _anotar_en_melonn(t, venta_id: str, pedido: dict) -> None:
    m = _de_melonn(pedido)
    await t.sesion.execute(text("""
        UPDATE retail.despachos
           SET estado = 'en_melonn', melonn_numero = :n, melonn_estado = :e,
               seguimiento_url = :s, ultimo_error = NULL, actualizado_en = now()
         WHERE venta_id = :v
    """), {"v": venta_id, "n": m["numero"] or None, "e": m["estado"],
           "s": m["seguimiento"]})


async def _crear(t, payload: dict, io: MelonnIO) -> Optional[str]:
    venta_id = payload["venta_id"]
    d = (await t.sesion.execute(text("""
        SELECT d.estado, d.destinatario, d.telefono, d.direccion, d.complemento,
               d.ciudad, d.departamento, d.melonn_estado, d.actualizado_en,
               v.numero, v.estado AS estado_venta
          FROM retail.despachos d JOIN retail.ventas v ON v.id = d.venta_id
         WHERE d.venta_id = :v
    """), {"v": venta_id})).mappings().first()
    if d is None:
        raise RechazoDefinitivo(f"la venta {venta_id} no tiene despacho")
    if d["estado"] != "pendiente":
        return f"el despacho ya está «{d['estado']}»"
    numero = d["numero"]

    # 1 · ¿YA EXISTE? Siempre antes de crear, haya o no un envío anterior.
    try:
        existente = await io.leer_pedido(numero)
    except CuotaAgotada as e:
        raise Aplazar(f"{numero}: {e}", minutos=MINUTOS_SI_NO_HAY_CUOTA) from e
    except MelonnOcupado as e:
        raise Aplazar(f"{numero}: {e}", minutos=MINUTOS_ENTRE_PREGUNTAS) from e
    if existente and _de_melonn(existente)["codigo"] == CODIGO_CANCELADO:
        # Existe, pero Melonn lo tiene cancelado: no se va a despachar y con
        # el mismo número no se puede pedir otro. A la oficina.
        m = _de_melonn(existente)
        await t.sesion.execute(text("""
            UPDATE retail.despachos
               SET estado = 'no_creado', melonn_numero = :n, melonn_estado = :e,
                   ultimo_error = 'Melonn tiene este pedido CANCELADO',
                   actualizado_en = now()
             WHERE venta_id = :v
        """), {"v": venta_id, "n": m["numero"] or None, "e": m["estado"]})
        return f"{numero} está cancelado en Melonn: lo resuelve la oficina"
    if existente:
        await _anotar_en_melonn(t, venta_id, existente)
        log.warning("[retail-envio] %s ya estaba en Melonn: se adopta, no se "
                    "crea otro", numero)
        return f"{numero} ya estaba en Melonn: se adopta"

    if d["estado_venta"] == "anulada":
        # Se anuló antes de pedir el despacho y Melonn no tiene nada.
        await t.sesion.execute(text("""
            UPDATE retail.despachos
               SET estado = 'cancelado', melonn_estado = NULL,
                   ultimo_error = 'la venta se anuló antes de pedir el despacho',
                   actualizado_en = now()
             WHERE venta_id = :v
        """), {"v": venta_id})
        return f"{numero} anulada antes de pedir el despacho: no se pide"

    # 2 · Hubo un envío sin respuesta y todavía no aparece: se espera.
    if d["melonn_estado"] == "enviando":
        enviado = d["actualizado_en"]
        if enviado.tzinfo is None:
            enviado = enviado.replace(tzinfo=timezone.utc)
        falta = MINUTOS_SIN_REENVIAR - (_ahora() - enviado).total_seconds() / 60
        if falta > 0:
            raise Aplazar(
                f"{numero}: el pedido a Melonn quedó sin respuesta; se sigue "
                f"preguntando ({round(falta)} min más) antes de volver a pedirlo",
                minutos=min(falta, MINUTOS_ENTRE_PREGUNTAS))

    # 3 · Se arma, se deja escrito «voy a enviar» y se envía UNA vez.
    lineas = (await t.sesion.execute(text("""
        SELECT sku, sum(cantidad) AS cantidad FROM retail.venta_lineas
         WHERE venta_id = :v GROUP BY sku ORDER BY sku
    """), {"v": venta_id})).mappings().all()
    try:
        cuerpo = construir_pedido(numero_venta=numero, lineas=list(lineas),
                                  despacho=dict(d))
    except ValueError as e:
        raise RechazoDefinitivo(str(e)) from e

    await t.sesion.execute(text("""
        UPDATE retail.despachos
           SET melonn_estado = 'enviando', actualizado_en = :ahora
         WHERE venta_id = :v
    """), {"v": venta_id, "ahora": _ahora()})
    await t.commit()                      # ANTES de enviar

    try:
        creado = await io.crear_pedido(cuerpo)
    except RechazoDeMelonn as e:
        # No se creó y así no se va a crear: a la oficina, con el motivo.
        await t.sesion.execute(text("""
            UPDATE retail.despachos
               SET estado = 'no_creado', melonn_estado = NULL,
                   ultimo_error = :e, actualizado_en = now()
             WHERE venta_id = :v
        """), {"v": venta_id, "e": str(e)[:500]})
        log.error("[retail-envio] Melonn NO recibió %s: %s", numero, e)
        return f"Melonn no recibió {numero}: {str(e)[:200]}"
    except (CuotaAgotada, MelonnOcupado) as e:
        # No salió nada hacia Melonn: no hay envío del que dudar.
        await t.sesion.execute(text("""
            UPDATE retail.despachos SET melonn_estado = NULL
             WHERE venta_id = :v
        """), {"v": venta_id})
        await t.commit()
        raise Aplazar(f"{numero}: {e}", minutos=(
            MINUTOS_SI_NO_HAY_CUOTA if isinstance(e, CuotaAgotada)
            else MINUTOS_ENTRE_PREGUNTAS)) from e
    # Cualquier otra cosa (timeout, 5xx) sube tal cual: el trabajo se
    # reintenta y, como quedó «enviando», primero pregunta y espera.

    await _anotar_en_melonn(t, venta_id, creado)
    log.info("[retail-envio] %s → Melonn %s", numero,
             _de_melonn(creado)["numero"] or "(sin número aún)")
    return f"{numero} pedido a Melonn"
