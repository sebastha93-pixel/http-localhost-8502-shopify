"""¿Puede el POS emitir con los comprobantes de las tiendas?

LA PREGUNTA QUE BLOQUEA LA FASE FISCAL. El plan es que este POS se quede con
las resoluciones que hoy usa Siigo POS (`FL`, `FV-11`, `FV-12`, `FV-6`), no
crear unas nuevas. Y hay evidencia, medida contra producción y anotada en
`codigo/backend/services/tiendas.py`, de que eso hoy NO se puede:

    POST /invoices → "The id cannot be used, you must verify the document
                      settings" · Params: ["document.id"]

EL MECANISMO NO ES UNA BANDERA, ES UNA AUSENCIA. La documentación oficial de
`/document-types` lista `id, code, name, type, active, consecutive,
automatic_number, electronic_type, prefix, cost_center…` y **no tiene ningún
campo que diga «es de punto de venta»**. Lo que pasa es que esos comprobantes
sencillamente NO APARECEN en la respuesta. Por eso el diagnóstico es tan
simple: se pregunta si el prefijo está en la lista.

TRES RESPUESTAS EN UNA LLAMADA, y las tres bloquean cosas distintas:

  · **¿Aparece el prefijo?** Si no, hay que reconfigurar el comprobante en
    Siigo antes de escribir una línea del emisor.
  · **`consecutive`** — dónde va la numeración AHORA. Es el número del relevo,
    leído de la API en vez de un papel impreso. Sin esto, el POS arranca en 1 y
    pisa facturas que Siigo ya emitió bajo la misma resolución.
  · **`automatic_number`** — quién pone el número. Si lo pone Siigo, el número
    que la tableta ya imprimió en la tirilla NO es el de la factura, y eso
    cambia cómo se numera. La numeración ya está en producción de pruebas.
"""
from __future__ import annotations

__all__ = ["diagnostico_comprobantes"]


def diagnostico_comprobantes(prefijos_buscados=None) -> dict:
    """Sólo lectura. No emite nada."""
    from backend.services import siigo

    if not siigo.siigo_configurado():
        return {"_error": "siigo_no_configurado"}

    buscados = list(prefijos_buscados or ["FL", "FV-11", "FV-12", "FV-6", "FV-1"])

    crudo = siigo.siigo_get("/document-types", {"type": "FV"})
    tipos = crudo if isinstance(crudo, list) else (crudo.get("results") or [])

    por_prefijo = {}
    for t in tipos:
        if not isinstance(t, dict):
            continue
        por_prefijo[(t.get("code") or t.get("prefix") or "").strip().upper()] = t

    # Se dictamina sobre los buscados Y sobre todo lo que Siigo devuelva: un
    # comprobante que no estaba en la lista puede ser justo la alternativa que
    # sirve, y esconderlo obligaría a adivinar cuál pedir.
    veredicto = {}
    for p in list(dict.fromkeys(buscados + sorted(por_prefijo))):
        t = por_prefijo.get(p.strip().upper())
        if t is None:
            veredicto[p] = {
                "emitible_por_api": False,
                "por_que": "no aparece en /document-types — el comprobante está "
                           "atado al punto de venta de Siigo. Hay que "
                           "reconfigurarlo en Siigo antes de poder emitir "
                           "desde aquí.",
            }
            continue
        veredicto[p] = {
            "emitible_por_api": bool(t.get("active", True)),
            "document_id": t.get("id"),
            "nombre": t.get("name"),
            # EL NÚMERO DEL RELEVO. Leerlo de aquí y no de una tirilla impresa.
            "consecutive": t.get("consecutive"),
            # Si es true, el número lo pone SIIGO y el que imprimió la tableta
            # no es el de la factura.
            "automatic_number": t.get("automatic_number"),
            "electronic_type": t.get("electronic_type"),
            "exige_centro_costo": t.get("cost_center_mandatory"),
            "activo": t.get("active"),
        }

    emitibles = [p for p, v in veredicto.items() if v["emitible_por_api"]]
    de_tienda = [p for p in ("FL", "FV-11", "FV-12", "FV-6")
                 if p in veredicto and not veredicto[p]["emitible_por_api"]]

    return {
        "prefijos_que_devuelve_siigo": sorted(por_prefijo),
        "veredicto": veredicto,
        "resumen": _resumen(emitibles, de_tienda),
        # Las formas de pago con SU ID, que es lo que falta para Addi, Wompi y
        # Sumas. El código de MALE sólo lee el NOMBRE de los pagos de una
        # factura (`payments[].name`), nunca el id — por eso no estaban.
        "formas_pago": siigo.siigo_get("/payment-types", {"document_type": "FV"}),
    }


def _resumen(emitibles, de_tienda) -> str:
    """Las dos mitades se dicen por separado: que un prefijo sirva no borra que
    otro no, y juntarlas en una sola frase hace perder la mitad del mensaje."""
    partes = []

    if de_tienda:
        partes.append(
            f"Los comprobantes de tienda {', '.join(de_tienda)} NO se pueden usar "
            f"desde la API — no aparecen en /document-types. Antes de escribir el "
            f"emisor hay que preguntarle a Siigo si se pueden reconfigurar para "
            f"que acepten documentos por API en vez de por su módulo POS.")

    if emitibles:
        partes.append(
            f"Sí se puede emitir con {', '.join(emitibles)}. Revisar el "
            f"`consecutive` de cada uno: ahí va la numeración hoy, y el POS "
            f"tiene que continuar desde ese número, no desde 1.")
        if de_tienda:
            partes.append(
                "Usarlos mientras tanto sirve para probar el emisor, a costa de "
                "mezclar el canal en los reportes.")
    elif de_tienda:
        partes.append("Y no hay ningún comprobante disponible como alternativa.")

    if not partes:
        return "Siigo no devolvió ningún comprobante FV. Revisar las credenciales."
    return " ".join(partes)
