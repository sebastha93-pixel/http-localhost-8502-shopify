"""Parseo tolerante de timestamps ISO venidos de Supabase/Postgres.

Motivación (bug confirmado en producción): la columna `timestamptz` de Postgres
recorta los ceros finales de la fracción de segundo. Un valor escrito como
`...19.142540` vuelve como `...19.14254+00:00` (5 dígitos). El backend corre
sobre la imagen `playwright/python:jammy` = **Python 3.10** (Railway usa el
Dockerfile, no el `runtime.txt` de 3.11), y `datetime.fromisoformat` en Python
< 3.11 solo acepta fracciones de **3 o 6** dígitos → lanza `ValueError` con
1/2/4/5 dígitos. Eso vaciaba módulos enteros o descartaba registros en silencio.

`parse_iso` evita `fromisoformat` por completo: parsea con regex, admite
cualquier longitud de fracción y cualquier zona (Z, ±HH, ±HH:MM), y **conserva
la zona horaria** (devuelve datetime aware cuando el string la trae) para no
romper comparaciones aware-vs-aware ni cálculos de antigüedad.

- `parse_iso(value)`  → datetime aware si el string trae zona; naive si no.
- `parse_iso_naive(value)` → datetime naive en UTC (para cachés/TTL que comparan
  contra `datetime.utcnow()`).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Union

# 2026-07-15[T ]19:14:25[.fraccion][zona]   — zona: Z | ±HH[:MM[:SS]] | ±HHMM
_ISO_RE = re.compile(
    r"""
    (?P<y>\d{4})-(?P<mo>\d{2})-(?P<d>\d{2})       # fecha (obligatoria)
    (?:
        [T ](?P<h>\d{2}):(?P<mi>\d{2})            # hora:minuto
        (?::(?P<s>\d{2}))?                        # segundos (opcional)
        (?:\.(?P<frac>\d+))?                      # fracción de cualquier longitud
        (?P<tz>Z|[+-]\d{2}(?::?\d{2})?(?::?\d{2})?)?   # zona (opcional)
    )?
    """,
    re.VERBOSE,
)


def _tz_from_match(tz: Union[str, None]):
    if not tz:
        return None
    if tz == "Z":
        return timezone.utc
    sign = 1 if tz[0] == "+" else -1
    body = tz[1:].replace(":", "")
    hh = int(body[0:2])
    mm = int(body[2:4]) if len(body) >= 4 else 0
    ss = int(body[4:6]) if len(body) >= 6 else 0
    delta = timedelta(hours=hh, minutes=mm, seconds=ss)
    if delta == timedelta(0):
        return timezone.utc
    return timezone(sign * delta)


def parse_iso(value) -> datetime:
    """Parsea un timestamp ISO tolerando cualquier precisión de fracción de
    segundo y cualquier zona horaria.

    Devuelve un datetime **aware** si el string trae zona (Z o ±offset), o
    **naive** si no la trae. Lanza `ValueError`/`TypeError` con entradas
    inválidas para que el `try/except` del caller pueda degradar.
    """
    if isinstance(value, datetime):
        return value
    if value is None:
        raise ValueError("timestamp vacío (None)")
    s = str(value).strip()
    if not s:
        raise ValueError("timestamp vacío")

    m = _ISO_RE.match(s)
    if not m:
        raise ValueError(f"timestamp ISO no reconocido: {s!r}")

    frac = m.group("frac")
    micro = int(frac[:6].ljust(6, "0")) if frac else 0

    return datetime(
        int(m.group("y")),
        int(m.group("mo")),
        int(m.group("d")),
        int(m.group("h") or 0),
        int(m.group("mi") or 0),
        int(m.group("s") or 0),
        micro,
        tzinfo=_tz_from_match(m.group("tz")),
    )


def parse_iso_naive(value) -> datetime:
    """Igual que `parse_iso` pero devuelve siempre un datetime **naive en UTC**.

    Para sitios de caché/TTL que comparan contra `datetime.utcnow()` (naive).
    Si el string trae zona, se convierte a UTC antes de quitar el tzinfo.
    """
    dt = parse_iso(value)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt
