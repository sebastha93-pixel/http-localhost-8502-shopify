"""
melonn_tracking.py — Portal de tracking de Melonn (transportadora + guía real)

QUÉ ES ESTO Y POR QUÉ EXISTE (2026-07-29)
-----------------------------------------
La Sellers API (`api.orbita.melonn.com`) NO expone la transportadora ni el número
de guía: se verificó volcando las 17 claves del detalle, probando los 10 valores
imaginables de `?fields=` (la doc confirma que solo existe `sell_order_promises`)
y recorriendo los 24 endpoints de su colección de Postman. El único endpoint que
lo daría, `/sell-orders/{n}/delivery-documents`, responde 404 para toda nuestra
cuenta — y su hermano `/vas` devuelve 403 con un *deny* explícito de IAM, así que
es un permiso que Melonn tiene que habilitar.

Lo que la Sellers API SÍ devuelve es `melonn_tracking_link`, o sea la página
pública de rastreo. Leyendo el bundle JS de esa página se encuentra la API que la
alimenta, y ahí sí está el dato:

    GET https://api.melonn.com/v1/buyer/sell-orders/{internalOrderNumber}
    -> { "status": "SHIPPED",
         "courierCompany": "Coordinadora Mercantil",
         "externalTrackingNumber": "16143225165", ... }

Verificado contra el pedido 61316, cuya guía real ya conocíamos por otra vía.

TRES COSAS QUE IMPORTAN:

1. Es OTRO HOST (`api.melonn.com`, no `api.orbita`). NO consume la cuota de
   10.000/día de la Sellers API. Ver [[architecture_melonn_api_quota]].
2. NO necesita autenticación: en el SPA el `id-token` es opcional
   (`headers: t ? {"id-token": t} : {}`).
3. Reemplaza al bot de Playwright para este dato: 0,6 s por pedido contra ~8 s,
   sin navegador y sin memoria de más.

OJO CON LAS ENTREGAS LOCALES: en el área metropolitana de Medellín entregan
mensajeros (Rapiboy, EASYWAY, Cabify, CORDIANDINA) que NO emiten número de guía.
Ahí `courierCompany` llega pero `externalTrackingNumber` viene null, y eso es
correcto, no un fallo: la guía no existe. Medido el 2026-07-29: el 93% de los
pedidos sin guía son del área metro, contra el 9% de los que sí la tienen.
"""
from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

_BASE = "https://api.melonn.com/v1/buyer/sell-orders"
_TIMEOUT = 20
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
_HEADERS = {
    "User-Agent": _UA,
    "Accept": "application/json",
    # El portal manda estos dos; se replican para no parecer tráfico raro.
    "Origin": "https://tracking.melonn.com",
    "Referer": "https://tracking.melonn.com/",
}

# Un M-id (M1785245936464547) es el número interno de Melonn, NO una guía de
# transportadora. Si alguna vez llega en ese campo, se descarta.
_RE_MID = re.compile(r"^[Mm]\d{10,}$")

# Estados del portal, en español, para mostrarlos tal cual en la app.
ESTADO_ES = {
    "RECEIVED":   "Recibido en bodega",
    "PROCESSING": "En preparación",
    "SHIPPED":    "En tránsito",
    "DELIVERED":  "Entregado",
    "CANCELED":   "Cancelado",
    "CANCELLED":  "Cancelado",
    "RETURNED":   "Devuelto",
}


def _pedir(mid: str) -> dict | None:
    req = urllib.request.Request(f"{_BASE}/{mid}", headers=_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as f:
            d = json.load(f)
    except urllib.error.HTTPError as e:
        if e.code in (400, 404):
            return None          # el portal no conoce ese pedido
        raise
    if not isinstance(d, dict):
        return None
    return d.get("data", d)


def consultar(mid: str, reintentos: int = 1) -> dict | None:
    """Transportadora, guía y estado de un pedido según el portal de tracking.

    Devuelve None si no se pudo resolver (para que el llamador no lo marque como
    procesado y se vuelva a intentar después).

    Las claves de la respuesta:
      carrier   str  — nombre de la transportadora ("" si aún no hay)
      guia      str  — número de guía real ("" cuando la transportadora no emite)
      estado    str  — estado crudo del portal (SHIPPED, DELIVERED, ...)
      estado_es str  — el mismo estado en español, listo para mostrar
      entregado_en str — fecha de entrega si ya se entregó
    """
    mid = str(mid or "").strip()
    if not mid:
        return None
    for intento in range(reintentos + 1):
        try:
            d = _pedir(mid)
            if d is None:
                return None
            guia = str(d.get("externalTrackingNumber") or "").strip()
            if _RE_MID.match(guia):
                guia = ""        # es el M-id, no una guía
            estado = str(d.get("status") or "").strip().upper()
            # OJO: son DOS cosas distintas y antes venían mezcladas en un solo
            # campo. `detailedDeliveredDate` es la entrega al cliente por la
            # transportadora; `pickedUpDate` es cuando el cliente lo recogió él
            # mismo en un punto (solo aparece en pedidos de recogida — medido
            # 2026-07-30: existe en 4 de 120). Para medir cuánto tardó una
            # entrega sirve la primera; la segunda cierra el pedido igual, así
            # que se conserva aparte y `entregado_en` cae a ella si no hay otra.
            entrega = str(d.get("detailedDeliveredDate") or "").strip()
            recogida = str(d.get("pickedUpDate") or "").strip()
            return {
                "carrier": str(d.get("courierCompany") or "").strip(),
                "guia": guia,
                "estado": estado,
                "estado_es": ESTADO_ES.get(estado, estado.title()),
                "entregado_el": entrega[:10],
                "recogido_el": recogida[:10],
                "entregado_en": str(entrega or recogida).strip(),
            }
        except Exception as e:
            if intento < reintentos:
                time.sleep(1.5)
                continue
            log.debug(f"tracking {mid}: {e}")
            return None
    return None
