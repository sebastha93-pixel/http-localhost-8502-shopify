"""
backend.services.avisos_produccion — Los 3 avisos del módulo de producción.

Vive aparte de services.notificaciones a propósito: ese es el transporte
(guardar, listar, marcar leída) y este es la POLÍTICA (a quién le llega cada
cosa y con qué texto). Así el día que cambie "a quién avisamos" se toca un
archivo, no diez sitios del código de producción.

Ruteo acordado con Sebastián (2026-07-29):
  · cortador cierra un corte      → al diseñador que CREÓ esa orden
  · lote cambia de etapa          → al diseñador que creó la orden del lote
  · diseñador crea una orden      → a quien tenga permiso de cortador
    (acá no hay "acción previa" de un cortador a quien devolverle el aviso,
     así que es el único de los tres que va por rol y no por persona)

TODAS las funciones son `avisar_*` y NO LEVANTAN EXCEPCIONES. Cerrar un corte
no puede fallar porque el aviso falló.
"""
from __future__ import annotations

import logging
from typing import Optional

from backend.services import notificaciones as notif


log = logging.getLogger(__name__)

# Módulo cuyo permiso identifica al cortador.
MODULO_CORTADOR = "produccion_cortador"

# Etiquetas legibles de las 7 etapas de hoja_ruta_lote (ETAPAS_RUTA en
# services.produccion). Se avisa en TODAS — decisión explícita del usuario.
ETAPA_TEXTO = {
    "asignado":              "asignado al confeccionista",
    "aceptado":              "aceptado por el confeccionista",
    "en_confeccion":         "en confección",
    "lavanderia":            "enviado a lavandería",
    "terminacion_recibida":  "recibido en terminación",
    "terminacion_terminada": "terminado",
    "despachado":            "despachado",
}


def _creador_de_orden(oc: Optional[dict]) -> str:
    """Email del diseñador que creó la orden de corte."""
    if not isinstance(oc, dict):
        return ""
    return (oc.get("created_by") or "").strip()


def _consecutivo(oc: Optional[dict]) -> str:
    if not isinstance(oc, dict):
        return "?"
    return str(oc.get("consecutivo") or oc.get("id") or "?")


def avisar_precosteo_autorizado(p: dict, *, autorizado_por: str) -> None:
    """Se autorizó (firmó) un precosteo → avisar al diseñador que lo creó.

    POR QUÉ EXISTE (2026-08-04): era el único punto del flujo donde alguien
    quedaba esperando SIN SABERLO. Hasta que el precosteo no está autorizado, el
    diseñador no puede crear la orden de corte — y nada le decía que ya podía.
    Sebastián autorizó 26620-1 y 26621-1 y preguntó por qué no llegó el aviso: no
    se había perdido, no existía.

    Va al CREADOR y no por rol, igual que `corte_cerrado`: hay una persona
    concreta esperando esta autorización, no un puesto.
    """
    try:
        dest = (p.get("created_by") or "").strip()
        cod = str(p.get("codigo_referencia") or p.get("id") or "?")
        if not dest:
            log.info(f"[avisos] precosteo {cod} sin created_by — sin aviso")
            return
        nombre = (p.get("nombre") or "").strip()
        detalle = f" · {nombre}" if nombre else ""
        notif.crear(
            destinatario_email=dest,
            tipo="precosteo_autorizado",
            titulo=f"Precosteo {cod} autorizado",
            mensaje=(f"{autorizado_por or 'Dirección'} autorizó la referencia "
                     f"{cod}{detalle}. Ya puedes crear la orden de corte."),
            enlace=f"/produccion/precosteo/{p.get('id') or ''}",
            meta={"precosteo_id": p.get("id"), "codigo_referencia": cod},
            creado_por=autorizado_por,
        )
    except Exception as e:
        log.warning(f"[avisos] precosteo_autorizado falló: {str(e)[:160]}")


def avisar_corte_creado(oc: dict, *, creado_por: str) -> None:
    """Diseñador creó una orden de corte → avisar a los cortadores."""
    try:
        cons = _consecutivo(oc)
        notif.crear_para_modulo(
            modulo=MODULO_CORTADOR,
            tipo="corte_creado",
            titulo=f"Nueva orden de corte {cons}",
            mensaje=(f"{creado_por or 'Diseño'} generó la orden {cons}. "
                     f"Ya puedes empezar el tendido."),
            enlace=f"/produccion/corte/{oc.get('id') or ''}",
            meta={"orden_corte_id": oc.get("id"), "consecutivo": cons},
            creado_por=creado_por,
        )
    except Exception as e:
        log.warning(f"[avisos] corte_creado falló: {str(e)[:160]}")


def avisar_corte_cerrado(oc: dict, *, cerrado_por: str) -> None:
    """Cortador cerró la orden → avisar al diseñador que la creó."""
    try:
        dest = _creador_de_orden(oc)
        if not dest:
            log.info(f"[avisos] corte {_consecutivo(oc)} sin created_by — sin aviso")
            return
        cons = _consecutivo(oc)
        unidades = oc.get("unidades_cortadas")
        detalle = f" · {unidades} unidades" if unidades else ""
        notif.crear(
            destinatario_email=dest,
            tipo="corte_cerrado",
            titulo=f"Corte {cons} cerrado",
            mensaje=(f"{cerrado_por or 'El cortador'} cerró la orden {cons}"
                     f"{detalle}."),
            enlace=f"/produccion/corte/{oc.get('id') or ''}",
            meta={"orden_corte_id": oc.get("id"), "consecutivo": cons,
                  "unidades_cortadas": unidades},
            creado_por=cerrado_por,
        )
    except Exception as e:
        log.warning(f"[avisos] corte_cerrado falló: {str(e)[:160]}")


def avisar_lote_avanzo(ruta: dict, *, etapa_nueva: str, oc: Optional[dict],
                       movido_por: str = "") -> None:
    """Lote cambió de etapa → avisar al diseñador que creó la orden de corte."""
    try:
        dest = _creador_de_orden(oc)
        if not dest:
            return
        cons = _consecutivo(oc)
        texto = ETAPA_TEXTO.get(etapa_nueva, etapa_nueva)
        notif.crear(
            destinatario_email=dest,
            tipo="lote_etapa",
            titulo=f"Lote {cons}: {texto}",
            mensaje=f"El lote del corte {cons} pasó a «{texto}».",
            # Al panel de rutas, sin query param: /produccion/rutas NO lee
            # ningún `?lote=`, así que pasarlo era decorativo — el enlace
            # prometía llevar al lote y solo abría la lista.
            enlace="/produccion/rutas",
            meta={"ruta_id": ruta.get("id"),
                  "orden_corte_id": (oc or {}).get("id"),
                  "consecutivo": cons, "etapa": etapa_nueva},
            creado_por=movido_por,
        )
    except Exception as e:
        log.warning(f"[avisos] lote_etapa falló: {str(e)[:160]}")
