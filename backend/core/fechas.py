"""Parseo de fechas ISO robusto para Railway (Python 3.10).

Py 3.10 solo acepta fracciones de segundo de 3 o 6 dígitos en
`datetime.fromisoformat`, pero Postgres/PostgREST recorta los ceros finales
(1/2/4/5 dígitos) → `ValueError`. Este helper normaliza y NUNCA revienta.

Usar SIEMPRE esto en vez de `datetime.fromisoformat(...)` directo sobre un dato
que venga de la base (el guardián lo exige para código nuevo).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


def parse_iso_utc(valor) -> Optional[datetime]:
    """ISO (con o sin fracción/zona) → datetime *aware* en UTC. None si no parsea."""
    if not valor:
        return None
    s = str(valor).strip().replace("Z", "+00:00")
    # Quitar la fracción de segundo (no la necesitamos y Py 3.10 la rechaza si no
    # trae 3/6 dígitos), conservando el offset de zona.
    if "." in s:
        cabeza, resto = s.split(".", 1)
        tz = ""
        for i, ch in enumerate(resto):
            if ch in "+-":
                tz = resto[i:]
                break
        s = cabeza + tz
    try:
        t = datetime.fromisoformat(s)  # guardian: iso-ok
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t.astimezone(timezone.utc)
