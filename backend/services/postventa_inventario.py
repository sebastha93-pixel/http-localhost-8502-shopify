"""
backend.services.postventa_inventario — Inventario de tienda en nuestra base.

POR QUÉ EXISTE: la búsqueda de la prenda de reemplazo le pedía a Siigo el
catálogo completo — hasta 80 páginas a ~1 petición por segundo. Además el
backend corre con 4 workers de uvicorn y el caché vivía en memoria, uno POR
PROCESO: la búsqueda caía en un worker con caché caliente (instantánea) y la
verificación en otro con caché frío, que no alcanzaba a recorrer el catálogo
y respondía "no se pudo leer el inventario" sobre una prenda que sí existía.

Con la tabla los cuatro workers leen lo mismo y la respuesta es inmediata.
Siigo se consulta una vez por refresco, no en cada clic.

EL PRECIO: el dato tiene la edad del último refresco. Por eso se muestra
siempre la frescura y se avisa cuando está viejo — la caja del POS puede
haber vendido esa talla hace un rato.
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger("postventa_inventario")

TABLA = "postventa_inventario"

# Pasado esto, el dato deja de ser confiable para prometerle una prenda a una
# clienta que está enfrente. No lo bloquea: lo advierte.
VIEJO_SEGUNDOS = 3600


def precio_base(producto: dict) -> Optional[float]:
    """Precio de venta del producto SIN IVA, como lo quiere el payload.

    Siigo lo trae en `prices[].price_list[].value` y declara en `tax_included`
    si ese valor ya lleva IVA. Normalizarlo al revés duplica o parte el precio
    y nada avisa: la factura sale, con el número equivocado.

    None si no hay precio — y sin precio NO se factura. Un cambio de 169.900
    salió por 67.960 justamente por tomar el precio de otra fuente.
    """
    listas = (producto or {}).get("prices") or []
    valor = None
    for l in listas:
        for item in (l.get("price_list") or []):
            v = item.get("value")
            if v:
                valor = float(v)
                break
        if valor:
            break
    if not valor or valor <= 0:
        return None
    if producto.get("tax_included"):
        return round(valor / (1 + IVA_PORCENTAJE / 100), 2)
    return round(valor, 2)


IVA_PORCENTAJE = 19


def filas_desde_siigo(inventario: dict, *, brand_id: str) -> list[dict]:
    """Aplana el inventario de Siigo a una fila por (referencia, bodega).

    Siigo lo devuelve como {code, stock: {bodega: cantidad}}. Aquí se abre
    para poder indexar y buscar por bodega, que es como lo usa la asesora.
    """
    salida = []
    for f in ((inventario or {}).get("referencias") or []):
        if not isinstance(f, dict):
            continue
        for bodega, cant in (f.get("stock") or {}).items():
            try:
                c = float(cant or 0)
            except (TypeError, ValueError):
                continue
            if c <= 0:
                continue          # una bodega en cero no aporta nada
            salida.append({
                "brand_id": brand_id,
                "code": f.get("code"),
                "referencia": f.get("referencia"),
                "talla": f.get("talla"),
                "nombre": f.get("nombre"),
                "bodega": bodega,
                "cantidad": c,
                # Precio de la TIENDA. El de Shopify puede estar en promoción y
                # no es el que paga quien compra en el local.
                "precio_base": f.get("precio_base"),
            })
    return salida


def frescura_texto(segundos: Optional[float]) -> str:
    """De cuándo es el dato, en palabras. La asesora decide si le sirve."""
    if segundos is None:
        return "sin actualizar"
    s = max(0, int(segundos))
    if s < 60:
        return "actualizado hace un momento"
    if s < 3600:
        return f"actualizado hace {s // 60} minutos"
    if s < 86400:
        h = s // 3600
        return f"actualizado hace {h} hora{'s' if h > 1 else ''}"
    d = s // 86400
    return f"actualizado hace {d} día{'s' if d > 1 else ''}"


def esta_viejo(segundos: Optional[float]) -> bool:
    """Sin fecha se considera viejo: no se puede afirmar que sea reciente."""
    return segundos is None or segundos > VIEJO_SEGUNDOS


# ── Acceso a la base ──────────────────────────────────────────────────

def _sb():
    from backend.services import postventa as pv
    return pv._sb()


def _brand():
    from backend.services import postventa as pv
    return pv._brand_id()


def sincronizar() -> dict:
    """Trae el inventario de Siigo y lo deja en la tabla.

    Lo corre el worker LÍDER en su scheduler, no una petición del panel: son
    minutos de paginación y no puede colgar a la asesora.
    """
    from backend.services import siigo
    sb = _sb()
    if sb is None:
        return {"_error": "supabase_no_configurado"}
    if not siigo.siigo_configurado():
        return {"_error": "siigo_no_configurado"}

    crudo = siigo.inventario_por_bodega(force=True)
    filas = filas_desde_siigo(crudo, brand_id=_brand())
    if not filas:
        # No se borra lo que hay: un fallo de Siigo dejaría a las tiendas sin
        # inventario y sin poder facturar un cambio.
        return {"_error": "siigo_sin_datos",
                "detalle": "Siigo no devolvió inventario. Se conserva el "
                           "anterior en vez de dejar las tiendas en cero."}

    ahora = datetime.now(timezone.utc).isoformat()
    for f in filas:
        f["actualizado_en"] = ahora
    sb.table(TABLA).upsert(filas, on_conflict="brand_id,code,bodega").execute()
    # Lo que ya no vino de Siigo se agotó: se borra por fecha, no por lista,
    # para no armar un DELETE gigante.
    sb.table(TABLA).delete().eq("brand_id", _brand()).lt("actualizado_en", ahora).execute()
    return {"filas": len(filas), "actualizado_en": ahora}


def _edad(fila: dict) -> Optional[float]:
    val = fila.get("actualizado_en")
    if not val:
        return None
    try:
        t = datetime.fromisoformat(str(val).replace("Z", "+00:00")[:32])
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - t).total_seconds()


def buscar(bodega: str, *, q: str = "", limite: int = 60) -> dict:
    """Referencias que ESA tienda puede entregar. Instantáneo."""
    sb = _sb()
    if sb is None:
        return {"opciones": [], "_error": "supabase_no_configurado"}
    consulta = (sb.table(TABLA).select("*")
                  .eq("brand_id", _brand()).eq("bodega", bodega).gt("cantidad", 0))
    termino = (q or "").strip()
    if termino:
        consulta = consulta.or_(
            f"code.ilike.%{termino}%,nombre.ilike.%{termino}%,"
            f"referencia.ilike.%{termino}%")
    filas = (consulta.limit(limite).execute().data or [])
    filas.sort(key=lambda f: (f.get("referencia") or "", _talla_num(f.get("talla"))))
    edad = _edad(filas[0]) if filas else None
    return {
        "bodega": bodega,
        "opciones": [{"code": f["code"], "referencia": f.get("referencia"),
                      "talla": f.get("talla"), "nombre": f.get("nombre"),
                      "stock": int(float(f.get("cantidad") or 0)),
                      "precio_base": f.get("precio_base"),
                      "bodega": bodega} for f in filas],
        "frescura": frescura_texto(edad),
        "viejo": esta_viejo(edad),
    }


def _talla_num(talla) -> tuple:
    try:
        return (0, int(str(talla or "").strip()))
    except ValueError:
        return (1, 0)


def disponible(bodega: str, code: str) -> tuple[bool, str]:
    """¿Se puede entregar esta prenda en este punto? Una sola consulta."""
    sb = _sb()
    if sb is None:
        return False, "No se pudo consultar el inventario."
    filas = (sb.table(TABLA).select("*")
               .eq("brand_id", _brand()).eq("bodega", bodega)
               .eq("code", (code or "").strip()).limit(1).execute().data or [])
    if not filas:
        return False, f"{code} no tiene existencias en {bodega}."
    cant = int(float(filas[0].get("cantidad") or 0))
    if cant <= 0:
        return False, f"{code} está en cero en {bodega}."
    edad = _edad(filas[0])
    aviso = "" if not esta_viejo(edad) else f" (ojo: {frescura_texto(edad)})"
    return True, f"{cant} disponible(s) en {bodega}{aviso}"


# ── Refresco automático ───────────────────────────────────────────────
_hilo = None
_parar = None

# Cada cuánto se refresca. Un cambio en tienda se atiende con la clienta
# enfrente, así que el dato no puede tener horas; pero recorrer el catálogo
# de Siigo cuesta minutos, así que tampoco puede ser cada rato.
INTERVALO_SEGUNDOS = int(os.environ.get("POSTVENTA_INV_INTERVALO", "1800"))
ESPERA_INICIAL = 60


def arrancar_refresco():
    """Refresca el inventario en segundo plano. Lo llama SOLO el worker líder.

    Si lo corrieran los cuatro workers, serían cuatro recorridas simultáneas
    del catálogo de Siigo — y Siigo tiene límite de peticiones.
    """
    global _hilo, _parar
    if _hilo is not None and _hilo.is_alive():
        return _hilo
    _parar = threading.Event()

    def _loop():
        if _parar.wait(ESPERA_INICIAL):
            return
        while not _parar.is_set():
            try:
                r = sincronizar()
                if r.get("_error"):
                    log.warning("[inventario] refresco: %s", r["_error"])
                else:
                    log.info("[inventario] %s referencias actualizadas", r.get("filas"))
            except Exception as e:  # noqa: BLE001
                log.warning("[inventario] refresco fallo: %s", e)
            if _parar.wait(INTERVALO_SEGUNDOS):
                break

    _hilo = threading.Thread(target=_loop, daemon=True,
                             name="postventa-inventario")
    _hilo.start()
    return _hilo


def precio_de(bodega: str, code: str) -> Optional[float]:
    """Precio SIN IVA con que esa tienda vende esa referencia."""
    sb = _sb()
    if sb is None:
        return None
    filas = (sb.table(TABLA).select("precio_base")
               .eq("brand_id", _brand()).eq("bodega", bodega)
               .eq("code", (code or "").strip()).limit(1).execute().data or [])
    if not filas:
        return None
    v = filas[0].get("precio_base")
    return float(v) if v else None
