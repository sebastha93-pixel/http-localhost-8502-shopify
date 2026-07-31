"""
backend.services.postventa_logic — Lógica pura del módulo Postventa.

Sin I/O, sin dependencias externas: constantes del dominio, máquina de
estados, validaciones y cálculos. 100% testeable con pytest.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

# ── Estados ──────────────────────────────────────────────────────────
ESTADOS: set[str] = {
    "creado",
    "pendiente_validacion",
    "aprobado",
    "rechazado",
    # ── Logística inversa: la prenda viaja de vuelta ──
    "esperando_envio_cliente",
    "en_transito_bodega",
    "recibido_bodega",
    # ── Cierre fiscal y despacho del reemplazo ──
    "nota_credito_emitida",
    "factura_emitida",
    "cambio_enviado",
    "cerrado",
    "escalado",
}

ESTADOS_TERMINALES: set[str] = {"rechazado", "cerrado"}

# Transiciones válidas (además de "cualquiera -> cerrado", ver transicion_valida)
TRANSICIONES: dict[str, set[str]] = {
    "creado":                {"pendiente_validacion"},
    "pendiente_validacion":  {"aprobado", "rechazado", "escalado"},
    # Tras aprobar: o se pide la devolución física, o se salta directo a la NC
    # (cuando la prenda ya está en bodega o el caso no requiere retorno).
    "aprobado":              {"esperando_envio_cliente", "nota_credito_emitida"},
    "esperando_envio_cliente": {"en_transito_bodega"},
    "en_transito_bodega":    {"recibido_bodega"},
    "recibido_bodega":       {"nota_credito_emitida"},
    "nota_credito_emitida":  {"factura_emitida"},
    "factura_emitida":       {"cambio_enviado"},
    "cambio_enviado":        set(),
    "escalado":              {"aprobado", "rechazado"},
    "rechazado":             set(),
    "cerrado":               set(),
}


# El reemplazo NO se despacha hasta que la prenda devuelta llegó a bodega.
# Si el caso pasó por logística inversa, debe haber tocado 'recibido_bodega'.
ESTADOS_LOGISTICA_INVERSA: set[str] = {
    "esperando_envio_cliente", "en_transito_bodega",
}


def requiere_recepcion(estado_actual: str) -> bool:
    """True si el caso está esperando que la prenda llegue a bodega."""
    return estado_actual in ESTADOS_LOGISTICA_INVERSA


def transicion_valida(actual: str, nuevo: str) -> bool:
    """True si se puede pasar de `actual` a `nuevo`.

    Reglas:
      - No se sale de un estado terminal (rechazado, cerrado).
      - Cualquier estado NO terminal puede ir a 'cerrado' (cierre manual).
      - El resto según el grafo TRANSICIONES.
    """
    if actual not in ESTADOS or nuevo not in ESTADOS:
        return False
    if actual in ESTADOS_TERMINALES:
        return False
    if nuevo == "cerrado":
        return True
    return nuevo in TRANSICIONES.get(actual, set())


# ── Catálogos ────────────────────────────────────────────────────────
TIPOS: set[str] = {
    "cambio_talla", "cambio_ref", "reembolso", "bono", "garantia",
}

MOTIVOS: list[str] = [
    "talla_pequena", "talla_grande", "no_le_gusto_como_quedo",
    "color_diferente", "producto_defectuoso", "producto_equivocado",
    "pedido_incompleto", "demora_entrega", "arrepentimiento",
    "calidad_percibida", "error_asesoria", "error_logistico",
    "cambio_por_otro", "garantia", "otro",
]

PRIORIDADES: set[str] = {"baja", "media", "alta"}


def validar_tipo(t: str) -> bool:
    return t in TIPOS


def validar_motivo(m: str) -> bool:
    return m in MOTIVOS


def validar_prioridad(p: str) -> bool:
    return p in PRIORIDADES


# ── Cálculos ─────────────────────────────────────────────────────────
def calcular_diferencia(original: float, requested: Optional[float]) -> float:
    """Diferencia de precio del item. Convención: + cobra, - devuelve.

    - requested None (reembolso/bono) -> se devuelve todo el original.
    - requested con valor -> requested - original.
    Se usa Decimal para no arrastrar error de punto flotante y se
    devuelve float con 2 decimales (COP).
    """
    o = Decimal(str(original))
    if requested is None:
        return float(-o)
    r = Decimal(str(requested))
    return float(r - o)


def formato_case_number(anio: int, consecutivo: int) -> str:
    """Consecutivo legible: PV-2026-0001 (mínimo 4 dígitos, crece si hace falta)."""
    return f"PV-{anio}-{consecutivo:04d}"


# ── Qué necesita que un humano lo autorice ────────────────────────────
# Un cambio de talla no lo necesita: la clienta está ahí con la prenda y la
# asesora ya la vio. Pedir aprobación en cada caso es un paso vacío.
#
# Sí lo necesitan:
#   · garantía  — alguien tiene que mirar el defecto y decidir si aplica;
#   · reembolso y bono — sacan plata, no se auto-aprueban.
# Ante un tipo desconocido, se pide aprobación: el default seguro es el
# que hace que un humano mire.
TIPOS_SIN_APROBACION: set[str] = {"cambio_talla", "cambio_ref"}


def requiere_aprobacion(tipo: str) -> bool:
    return (tipo or "").strip() not in TIPOS_SIN_APROBACION


def estado_inicial(tipo: str) -> str:
    """Dónde nace el caso. Los cambios simples arrancan aprobados."""
    return "creado" if requiere_aprobacion(tipo) else "aprobado"


# ── Ventana para cambiar ──────────────────────────────────────────────
# Pasado el plazo la prenda ya no se cambia. Se controla contra la fecha de
# la FACTURA, no la del caso: lo que importa es hace cuánto compró.
DIAS_CAMBIO_DEFAULT = 30


def dias_de_cambio() -> int:
    """Política de la marca, no del código: otra puede tener 15 o 60."""
    crudo = os.environ.get("POSTVENTA_DIAS_CAMBIO", "").strip()
    if crudo:
        try:
            v = int(crudo)
            if v > 0:
                return v
        except ValueError:
            pass
    return DIAS_CAMBIO_DEFAULT


def _fecha(valor) -> Optional[date]:
    """Siigo manda '2026-07-29' o '2026-07-29T10:30:00Z'."""
    if not valor:
        return None
    try:
        return date.fromisoformat(str(valor)[:10])
    except ValueError:
        return None


def dias_desde(fecha_factura, *, hoy=None) -> Optional[int]:
    f = _fecha(fecha_factura)
    if f is None:
        return None
    ref = _fecha(hoy) or datetime.now(timezone.utc).date()
    return (ref - f).days


def dentro_de_ventana(fecha_factura, *, hoy=None) -> bool:
    """¿La compra todavía admite cambio?

    Sin fecha legible devuelve False: no se puede afirmar que esté en plazo,
    y dejar pasar un cambio vencido cuesta una nota crédito que tocará anular.
    """
    d = dias_desde(fecha_factura, hoy=hoy)
    return d is not None and d <= dias_de_cambio()


def motivo_fuera_de_ventana(fecha_factura, *, hoy=None) -> str:
    d = dias_desde(fecha_factura, hoy=hoy)
    if d is None:
        return "La factura no tiene fecha legible: no se puede validar el plazo."
    return (f"La compra tiene {d} días y el plazo para cambios es de "
            f"{dias_de_cambio()} días.")


# Tipos que NO llevan factura de reemplazo: la clienta no se lleva prenda
# nueva, solo se le devuelve el valor.
TIPOS_SIN_FACTURA: set[str] = {"reembolso", "bono"}


def ciclo_del_caso(tipo: str, *, tienda: str = "") -> list[str]:
    """Los pasos que ESTE caso recorre de verdad.

    Pintarle los 12 estados posibles a todos los casos hace que un cambio de
    talla en tienda —que son cuatro pasos— parezca un trámite de diez, con
    logística inversa que nunca va a ocurrir porque la clienta trae la prenda
    en la mano. Un flujo se siente pesado sobre todo porque se VE pesado.

    Tres cosas lo determinan:
      · si el tipo necesita que alguien lo autorice (solo garantía y las
        salidas de dinero);
      · si es presencial — ahí no hay nada que enviar ni que recibir;
      · si lleva factura de reemplazo (reembolso y bono no).
    """
    presencial = bool((tienda or "").strip())
    pasos: list[str] = []

    if requiere_aprobacion(tipo):
        pasos += ["creado", "pendiente_validacion"]
    pasos.append("aprobado")

    if not presencial:
        pasos += ["esperando_envio_cliente", "en_transito_bodega",
                  "recibido_bodega"]

    pasos.append("nota_credito_emitida")
    lleva_factura = (tipo or "").strip() not in TIPOS_SIN_FACTURA
    if lleva_factura:
        pasos.append("factura_emitida")
    # Solo hay algo que despachar si hay prenda de reemplazo. Un reembolso se
    # cierra con la nota crédito: no sale nada de la bodega.
    if not presencial and lleva_factura:
        pasos.append("cambio_enviado")

    pasos.append("cerrado")
    return pasos


def hubo_cambio_de_reemplazo(anterior, nuevo) -> bool:
    """¿La prenda elegida cambió de verdad?

    La asesora vuelve a la lista y reelige mientras ajusta el precio o revisa
    tallas. Registrar cada clic deja el historial lleno de líneas iguales — y
    el historial es lo que se mira cuando algo no cuadra.
    """
    a = (anterior or "").strip().lower()
    b = (nuevo or "").strip().lower()
    return a != b
