"""insumos_catalogo.py — las reglas de cada insumo, declaradas y no adivinadas.

EL PROBLEMA QUE RESUELVE (2026-07-31): el nombre del insumo es texto libre en el
precosteo, y TODAS las reglas se decidían leyendo ese texto — si contenía
"CIERRE" se separaba por talla, si contenía "boton" llevaba 1% de merma. Un
insumo mal escrito no dispara ninguna regla y NADIE SE ENTERA. Ya estaba
pasando: de los 3 insumos de confección que existían, uno era "ELAASTICO" (doble
A) y por eso quedaba fuera de todo.

Ahora las propiedades viven en columnas (`insumos_catalogo`): unidad, si se
separa por talla, cuánta merma lleva, qué tabla de medidas aplica.

DEGRADA SOLO: si la tabla todavía no existe (migración sin correr), se cae a las
mismas reglas por substring de antes. Así el deploy no depende de la migración y
la app no se rompe en el intervalo.
"""
from __future__ import annotations

import logging
import time
import unicodedata
from typing import Optional

log = logging.getLogger(__name__)

# ── Reglas VIEJAS, por substring del nombre ──────────────────────────────────
# Se conservan como respaldo para dos casos: la migración aún no corrió, o el
# insumo que alguien escribió no está en el catálogo. NO se borran: mientras el
# nombre siga siendo libre, un insumo puede caer fuera del catálogo.
_POR_TALLA_SUBSTR = ("cierre", "marquilla", "cremallera")
_CON_MERMA_SUBSTR = ("boton", "remache", "lavado", "pretin")
_MERMA_DEFECTO_PCT = 1.0

# Caché en memoria: el catálogo cambia muy poco y se consulta por cada insumo de
# cada lote. TTL corto para que un cambio se refleje sin reiniciar.
_CACHE: dict = {"ts": 0.0, "por_nombre": {}}
_TTL_SEG = 120


def _norm(s: str) -> str:
    """minúsculas y sin tildes, para comparar nombres escritos a mano."""
    n = unicodedata.normalize("NFD", (s or "").strip().lower())
    return n.encode("ascii", "ignore").decode()


def _cargar() -> dict:
    """{nombre_normalizado: fila} del catálogo. {} si la tabla no existe."""
    ahora = time.time()
    if _CACHE["por_nombre"] and (ahora - _CACHE["ts"]) < _TTL_SEG:
        return _CACHE["por_nombre"]
    try:
        from backend.services.produccion import _sb
        sb = _sb()
        if sb is None:
            return _CACHE["por_nombre"]
        filas = (sb.table("insumos_catalogo").select("*")
                   .eq("activo", True).execute()).data or []
        _CACHE["por_nombre"] = {_norm(f.get("nombre")): f for f in filas}
        _CACHE["ts"] = ahora
        return _CACHE["por_nombre"]
    except Exception as e:
        # Tabla inexistente (migración pendiente) o error de red: se sigue con
        # las reglas por substring. Se avisa una vez cada TTL, no en cada item.
        if (ahora - _CACHE["ts"]) > _TTL_SEG:
            log.info(f"[insumos] catálogo no disponible, uso reglas por nombre: "
                     f"{str(e)[:120]}")
            _CACHE["ts"] = ahora
        return {}


def propiedades(nombre: str) -> dict:
    """Reglas del insumo. Siempre devuelve algo usable.

    Claves:
      unidad        'unidad' | 'metro' | 'par'
      por_talla     bool  — se separa talla por talla
      merma_pct     float — 0 = exacto
      tabla_medidas str|None — 'cierres_jean' u otra
      en_catalogo   bool  — False = se resolvió por substring (revisar el nombre)
    """
    cat = _cargar()
    fila = cat.get(_norm(nombre))
    if fila:
        return {
            "unidad": (fila.get("unidad") or "unidad"),
            "por_talla": bool(fila.get("por_talla")),
            "merma_pct": float(fila.get("merma_pct") or 0),
            "tabla_medidas": fila.get("tabla_medidas") or None,
            "en_catalogo": True,
        }
    n = _norm(nombre)
    return {
        "unidad": "unidad",
        "por_talla": any(k in n for k in _POR_TALLA_SUBSTR),
        "merma_pct": (_MERMA_DEFECTO_PCT
                      if any(k in n for k in _CON_MERMA_SUBSTR) else 0.0),
        "tabla_medidas": "cierres_jean" if "cierre" in n or "cremallera" in n else None,
        "en_catalogo": False,
    }


def cantidad_a_separar(nombre: str, requerido: float) -> float:
    """Cuánto se manda separar, aplicando merma y redondeo según la unidad.

    Las unidades discretas se redondean HACIA ARRIBA (media hombrera no existe);
    los metros conservan decimales, porque redondear 0,8 m a 1 m en un lote de
    300 prendas son 60 metros regalados.
    """
    import math
    p = propiedades(nombre)
    con_merma = float(requerido) * (1 + p["merma_pct"] / 100.0)
    if p["unidad"] == "metro":
        return round(con_merma, 2)
    return float(math.ceil(con_merma - 1e-9))


def listar(categoria: Optional[str] = None) -> list[dict]:
    """El catálogo, para que la UI del precosteo ofrezca una lista y no texto
    libre. Vacío si la migración no ha corrido — la UI debe caer a texto libre."""
    cat = _cargar()
    filas = list(cat.values())
    if categoria:
        c = categoria.upper()
        filas = [f for f in filas if (f.get("categoria") or "").upper() == c]
    return sorted(filas, key=lambda f: (f.get("categoria") or "", f.get("nombre") or ""))
