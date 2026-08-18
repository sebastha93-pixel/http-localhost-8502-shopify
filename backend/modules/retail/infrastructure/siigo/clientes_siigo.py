"""Traer la base de clientas que ya existe en Siigo.

POR QUÉ NO ES UNA COMODIDAD. MALE lleva años facturando desde Siigo POS: cada
factura tiene una clienta con su documento, su dirección y su teléfono. Si el
POS nuevo arranca con la tabla vacía pasan dos cosas, y la segunda es la grave:

  1. Cada clienta que vuelve hay que volver a crearla. Molesto.
  2. **Se crea un DUPLICADO de alguien que Siigo ya tiene.** Y en el momento en
     que empecemos a emitir, esa factura o crea una clienta repetida en la
     contabilidad de MALE o se cae. Arreglar eso después es fusionar clientes a
     mano en Siigo, factura por factura.

`retail.clientes.siigo_customer_id` existe desde la migración 0001 y no lo
escribía nadie. Es exactamente el campo que evita el punto 2.

LA FORMA DEL JSON NO ESTÁ VERIFICADA CONTRA LA CUENTA DE MALE. El mapeo de
abajo sale de la documentación de Siigo, no de una respuesta real. Por eso
`muestra()` existe: se mira primero lo que la cuenta devuelve DE VERDAD y
después se importa. Es el mismo orden que ya siguió el motor fiscal con
`inspeccionar_facturas`, y por el que se descubrió que la bodega «5» no era 5.
"""
from __future__ import annotations

from typing import Iterator, Optional

__all__ = ["muestra", "paginar", "a_cliente", "TIPOS_DOCUMENTO"]

# Siigo identifica el tipo de documento por CÓDIGO, no por nombre.
# Fuente: catálogo de la DIAN que usa Siigo. Si la cuenta de MALE devolviera
# un código que no está aquí, `a_cliente` lo deja como viene en vez de
# adivinar: un tipo de documento equivocado en una factura es un rechazo.
TIPOS_DOCUMENTO = {
    "11": "RC",   # Registro civil
    "12": "TI",   # Tarjeta de identidad
    "13": "CC",   # Cédula de ciudadanía
    "21": "TE",   # Tarjeta de extranjería
    "22": "CE",   # Cédula de extranjería
    "31": "NIT",
    "41": "PP",   # Pasaporte
    "42": "DIE",  # Documento de identificación extranjero
}


def muestra(cuantas: int = 3) -> dict:
    """Unas pocas clientas REALES, tal cual las devuelve la cuenta.

    Sólo lectura. Existe para mirar la forma antes de tocar nada: el mapeo de
    este archivo está escrito contra la documentación, y la documentación y la
    cuenta no siempre coinciden.
    """
    from backend.services import siigo

    if not siigo.siigo_configurado():
        return {"_error": "siigo_no_configurado"}
    cruda = siigo.siigo_get("/customers", {"page": 1, "page_size": cuantas})
    filas = cruda.get("results") or []
    mapeadas = [a_cliente(f) for f in filas]
    return {
        "total_en_siigo": cruda.get("pagination", {}).get("total_results"),
        # EL VEREDICTO PRIMERO. Debajo va el crudo y el mapeado para poder
        # mirar, pero lo que decide si se puede importar es esto.
        "cobertura": cobertura(mapeadas),
        "crudas": filas,
        "mapeadas": mapeadas,
    }


def cobertura(mapeadas: list) -> dict:
    """Cuántas clientas trajeron cada campo, y el veredicto.

    POR QUÉ NO BASTA DEVOLVER EL CRUDO Y EL MAPEADO AL LADO. Eso deja el
    trabajo de decidir en quien mire, y el fallo que hay que cazar es
    silencioso: si el correo se lee del sitio equivocado, la columna sale VACÍA
    —no incorrecta— y una columna vacía se confunde con «esa clienta no tenía
    correo». Contarlas convierte la duda en un número.

    El correo y la dirección importan más que los demás: sin correo la factura
    electrónica no llega a nadie, y sin dirección sale incompleta.
    """
    n = len(mapeadas) or 1
    def con(campo):
        return sum(1 for m in mapeadas if (m.get(campo) or "").strip())

    campos = {c: con(c) for c in
              ("numero_documento", "nombre", "apellido", "telefono",
               "correo", "direccion", "ciudad", "dv", "siigo_customer_id")}

    problemas = []
    if campos["numero_documento"] < len(mapeadas):
        problemas.append("hay clientas SIN DOCUMENTO: no se podrán buscar ni "
                         "facturar, y la importación las va a saltar")
    if campos["siigo_customer_id"] < len(mapeadas):
        problemas.append("falta el id de Siigo en alguna: sin él la factura "
                         "duplicaría la clienta en la contabilidad, que es lo "
                         "que esta importación viene a evitar")
    if campos["correo"] == 0:
        problemas.append("NINGUNA trajo correo — o la cuenta no los tiene, o "
                         "se está leyendo del sitio equivocado. En Siigo vive "
                         "en `contacts[].email`, no en la raíz")
    if campos["direccion"] == 0:
        problemas.append("ninguna trajo dirección — la factura electrónica la "
                         "imprime; revisar `address.address`")

    return {
        "clientas_miradas": len(mapeadas),
        "con_cada_campo": campos,
        "porcentaje": {c: round(100 * v / n) for c, v in campos.items()},
        "problemas": problemas,
        "veredicto": ("se puede importar" if not problemas
                      else "REVISAR ANTES DE IMPORTAR"),
    }


def paginar(page_size: int = 100, tope_paginas: int = 500) -> Iterator[dict]:
    """Recorre TODAS las clientas, y grita si no pudo terminar.

    EL TOPE NO SE PUEDE CRUZAR EN SILENCIO. Un recorrido paginado que corta y
    devuelve lo que alcanzó produce un número que se lee como prueba y es
    falso: «importé 4.000 clientas» cuando había 7.000, y las 3.000 que faltan
    no se descubren hasta que una de ellas llega al mostrador.

    Por eso al agotar el tope se lanza, en vez de devolver una lista corta.
    """
    from backend.services import siigo

    pagina = 1
    vistas = 0
    total: Optional[int] = None
    while pagina <= tope_paginas:
        r = siigo.siigo_get("/customers", {"page": pagina, "page_size": page_size})
        filas = r.get("results") or []
        if total is None:
            total = (r.get("pagination") or {}).get("total_results")
        if not filas:
            break
        for f in filas:
            vistas += 1
            yield f
        if len(filas) < page_size:
            break
        pagina += 1
    else:
        raise RuntimeError(
            f"Siigo devolvió más de {tope_paginas} páginas de clientas "
            f"({vistas} leídas). No se importa una base a medias: sube el tope "
            f"o revisa por qué la paginación no termina."
        )

    if total is not None and vistas < total:
        raise RuntimeError(
            f"Siigo dice que hay {total} clientas y sólo se leyeron {vistas}. "
            f"Importar así dejaría fuera a {total - vistas} sin que se note."
        )


def a_cliente(c: dict) -> dict:
    """Del JSON de Siigo a nuestras columnas.

    Defensivo a propósito: cada campo puede faltar. Una clienta sin correo o
    sin dirección se importa igual —el documento y el nombre son lo que hace
    falta para reconocerla en el mostrador— y lo que falte se completa el día
    que compre.
    """
    nombre_partes = c.get("name") or []
    if isinstance(nombre_partes, str):
        nombre_partes = [nombre_partes]
    nombre = (nombre_partes[0] if nombre_partes else "").strip()
    apellido = " ".join(p.strip() for p in nombre_partes[1:]).strip()

    tipo_crudo = ((c.get("id_type") or {}).get("code") or "").strip()
    direccion = (c.get("address") or {}).get("address") or ""
    ciudad = (((c.get("address") or {}).get("city") or {}).get("city_name") or "")

    telefonos = c.get("phones") or []
    telefono = (telefonos[0].get("number") if telefonos else "") or ""

    # El correo vive en `contacts`, no en la raíz. Es donde llega la factura
    # electrónica, así que leerlo del sitio equivocado deja a la clienta sin
    # recibirla y sin que nadie se entere.
    correo = ""
    for contacto in (c.get("contacts") or []):
        if contacto.get("email"):
            correo = contacto["email"].strip()
            break

    return {
        "siigo_customer_id": c.get("id") or None,
        "tipo_documento": TIPOS_DOCUMENTO.get(tipo_crudo, tipo_crudo or "CC"),
        "numero_documento": (c.get("identification") or "").strip(),
        "dv": (c.get("check_digit") or None),
        "nombre": nombre,
        "apellido": apellido,
        "telefono": telefono.strip(),
        "correo": correo,
        "direccion": direccion.strip(),
        "ciudad": ciudad.strip(),
        "activo_en_siigo": bool(c.get("active", True)),
    }
