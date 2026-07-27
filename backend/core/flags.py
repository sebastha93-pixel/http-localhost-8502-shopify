"""
backend.core.flags — Lectura uniforme de feature flags de entorno.

Por qué existe
──────────────
El repo tenía tres formas distintas de parsear el mismo tipo de variable:

    os.environ.get("BOT_AUTO_ENABLED", "false").lower() == "true"
    os.environ.get("REVENUE_CRON_ENABLED", "true").lower() in ("true","1","yes")
    os.environ.get("METRICS_WARMER", "on").lower() != "off"

Consecuencia concreta: `BOT_AUTO_ENABLED=1` NO activa nada (compara con "true"
exacto), mientras que `REVENUE_CRON_ENABLED=1` sí. Es una trampa silenciosa —
el flag "está puesto" en Railway y no hace nada.

Este módulo acepta todas las formas razonables de decir sí y no, para que
poner `=1`, `=true`, `=on` o `=yes` funcione igual.

Uso
───
    from backend.core.flags import flag

    if flag("TIME_MANAGEMENT_ENABLED"):
        app.include_router(personal.router)

Los flags se leen en CADA llamada (es un dict lookup, no cuesta nada). Eso
permite cambiar el valor en tests con monkeypatch sin recargar módulos. Ojo:
los flags que gobiernan el registro de routers se evalúan una sola vez en el
boot, así que cambiarlos exige redeploy.
"""
from __future__ import annotations

import os


# Formas aceptadas, en minúsculas y sin espacios.
_VERDADEROS = frozenset({"1", "true", "yes", "y", "on", "si", "sí"})
_FALSOS     = frozenset({"0", "false", "no", "n", "off"})


def flag(nombre: str, default: bool = False) -> bool:
    """Lee un feature flag de entorno.

    Devuelve `default` si la variable no existe, está vacía, o tiene un valor
    que no reconocemos. Preferimos el default sobre adivinar: un typo como
    `TIME_MANAGEMENT_ENABLED=ture` no debe activar un módulo entero.

    >>> os.environ["X"] = "1";     flag("X")   # True
    >>> os.environ["X"] = "OFF";   flag("X")   # False
    >>> os.environ["X"] = "ture";  flag("X")   # False (default) — no adivina
    """
    crudo = os.environ.get(nombre)
    if crudo is None:
        return default
    valor = crudo.strip().lower()
    if valor in _VERDADEROS:
        return True
    if valor in _FALSOS:
        return False
    return default


def flags_activos(*nombres: str) -> dict[str, bool]:
    """Estado de varios flags de una vez. Para health checks y diagnóstico."""
    return {n: flag(n) for n in nombres}


# ── Flags del módulo Personal ────────────────────────────────────────────────
# Todos arrancan apagados: el módulo no existe para nadie hasta activarlo.

TIME_MANAGEMENT = "TIME_MANAGEMENT_ENABLED"
DAHUA_CONNECTOR = "DAHUA_CONNECTOR_ENABLED"
PAYROLL_EXPORT = "PAYROLL_EXPORT_ENABLED"
TIME_MANAGEMENT_AI = "TIME_MANAGEMENT_AI_INSIGHTS_ENABLED"

FLAGS_PERSONAL = (TIME_MANAGEMENT, DAHUA_CONNECTOR, PAYROLL_EXPORT, TIME_MANAGEMENT_AI)


def personal_habilitado() -> bool:
    """Puerta principal del módulo Personal.

    Los demás flags del módulo son jerárquicos: no sirve de nada activar el
    conector Dahua o la exportación de nómina si el módulo está apagado.
    """
    return flag(TIME_MANAGEMENT)


def conector_dahua_habilitado() -> bool:
    return personal_habilitado() and flag(DAHUA_CONNECTOR)


def export_nomina_habilitado() -> bool:
    return personal_habilitado() and flag(PAYROLL_EXPORT)


def ia_personal_habilitada() -> bool:
    return personal_habilitado() and flag(TIME_MANAGEMENT_AI)
