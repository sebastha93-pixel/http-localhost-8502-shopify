"""
Ingesta de CSV exportado de Melonn.
Lee el archivo, normaliza columnas, calcula campos derivados
y retorna una lista de dicts listos para el motor de riesgo.
"""

import csv
import re
from datetime import datetime, timezone, date
from pathlib import Path
from typing import Optional

# Estados de Melonn que representan pedidos activos en tránsito
ESTADOS_EN_TRANSITO = {
    "Shipped - in transit",
    "Delivery not posible",
    "Packed",
    "Packed - on hold",
    "Prepared for dispatch",
    "All items reserved - ready for fulfillment",
    "All items reserved - fulfillment on hold - ext. conditionals",
    "on stand by - not able to fulfil - no stock",
}

# Estados ya resueltos (no necesitan seguimiento)
ESTADOS_RESUELTOS = {
    "Delivered to buyer",
    "Picked-up by buyer",
    "Canceled",
}

# Columnas del CSV de Melonn → nombre interno
MAPA_COLUMNAS = {
    "Número orden Melonn":                    "orden_melonn",
    "Número orden":                           "orden_tienda",
    "Estado orden":                           "estado_melonn",
    "Tienda":                                 "tienda",
    "Canal de venta":                         "canal_venta",
    "Valor pago contraentrega":               "valor_cod_raw",
    "Recaudo en efectivo":                    "tipo_recaudo",
    "Ciudad de destino":                      "ciudad_destino",
    "Región de destino":                      "region_destino",
    "Nombre comprador":                       "nombre_comprador",
    "Teléfono comprador":                     "telefono_comprador",
    "Transportadora":                         "transportadora",
    "Link guía":                              "link_guia",
    "Fecha de creación":                      "fecha_creacion_raw",
    "Fecha envío":                            "fecha_despacho_raw",
    "Fecha promesa máxima de entrega/recogida": "fecha_promesa_raw",
    "Fecha de entrega":                       "fecha_entrega_raw",
    "SKU":                                    "sku",
    "Producto":                               "producto",
    "Variante":                               "variante",
    "Cantidad ordenada":                      "cantidad",
    "Precio unitario canal de venta":         "precio_unitario",
}


def _parsear_fecha(texto: str) -> Optional[date]:
    """Convierte '2026-05-07 07:00:00 +0000 +0000' → date. Retorna None si vacío."""
    if not texto or not texto.strip():
        return None
    # Toma solo los primeros 10 caracteres: YYYY-MM-DD
    match = re.match(r"(\d{4}-\d{2}-\d{2})", texto.strip())
    if match:
        return datetime.strptime(match.group(1), "%Y-%m-%d").date()
    return None


def _es_contraentrega(valor_raw: str) -> bool:
    """Retorna True si el campo de valor COD tiene un número positivo."""
    if not valor_raw or not valor_raw.strip():
        return False
    limpio = valor_raw.replace(".", "").replace(",", "").strip()
    try:
        return float(limpio) > 0
    except ValueError:
        return False


def _calcular_dias_transito(fecha_despacho: Optional[date], fecha_entrega: Optional[date]) -> int:
    """
    Días desde despacho hasta entrega (si ya entregó) o hasta hoy (si aún en tránsito).
    Retorna 0 si no hay fecha de despacho.
    """
    if not fecha_despacho:
        return 0
    fin = fecha_entrega if fecha_entrega else date.today()
    delta = (fin - fecha_despacho).days
    return max(0, delta)


def _normalizar_ciudad(ciudad: str) -> str:
    """Limpia la ciudad: quita ', D.C.', ' DE INDIAS', etc."""
    if not ciudad:
        return ""
    ciudad = ciudad.upper().strip()
    ciudad = re.sub(r",?\s*D\.C\.", "", ciudad)
    ciudad = re.sub(r"\s+DE\s+INDIAS$", "", ciudad)
    return ciudad.strip()


def leer_csv_melonn(ruta: str, solo_activos: bool = True) -> list:
    """
    Lee el CSV de Melonn y retorna lista de pedidos normalizados.

    Args:
        ruta: Ruta al archivo CSV exportado de Melonn.
        solo_activos: Si True, filtra pedidos ya entregados y cancelados.

    Returns:
        Lista de dicts con campos normalizados + campos calculados.
    """
    ruta = Path(ruta)
    if not ruta.exists():
        raise FileNotFoundError(f"No se encontró el archivo: {ruta}")

    pedidos = []
    omitidos = {"resuelto": 0, "sin_despacho": 0}

    with open(ruta, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")

        for fila in reader:
            # Renombrar columnas al nombre interno
            p = {}
            for col_original, col_interna in MAPA_COLUMNAS.items():
                p[col_interna] = fila.get(col_original, "").strip()

            estado = p["estado_melonn"]

            # Filtrar pedidos ya resueltos
            if solo_activos and estado in ESTADOS_RESUELTOS:
                omitidos["resuelto"] += 1
                continue

            # Parsear fechas
            p["fecha_despacho"] = _parsear_fecha(p["fecha_despacho_raw"])
            p["fecha_entrega"]  = _parsear_fecha(p["fecha_entrega_raw"])
            p["fecha_promesa"]  = _parsear_fecha(p["fecha_promesa_raw"])
            p["fecha_creacion"] = _parsear_fecha(p["fecha_creacion_raw"])

            # Sin fecha de despacho = aún no salió de bodega, no es logística activa
            if not p["fecha_despacho"]:
                omitidos["sin_despacho"] += 1
                continue

            # Campos calculados
            p["ciudad_destino"]    = _normalizar_ciudad(p["ciudad_destino"])

            # Teléfonos en notación científica (Excel los convierte, usa coma decimal en CO)
            tel = p.get("telefono_comprador", "")
            if "E+" in tel.upper():
                try:
                    p["telefono_comprador"] = str(int(float(tel.replace(",", "."))))
                except ValueError:
                    pass
            p["es_contraentrega"]  = _es_contraentrega(p["valor_cod_raw"])
            p["dias_en_transito"]  = _calcular_dias_transito(p["fecha_despacho"], p["fecha_entrega"])
            p["esta_en_transito"]  = estado in ESTADOS_EN_TRANSITO
            p["entregado"]         = estado in ESTADOS_RESUELTOS

            # Incidencia: columna que se agrega manualmente o queda vacía
            p["incidencia"] = p.get("incidencia", "NINGUNO") or "NINGUNO"

            # Promesa vencida
            if p["fecha_promesa"] and not p["entregado"]:
                p["promesa_vencida"] = date.today() > p["fecha_promesa"]
            else:
                p["promesa_vencida"] = False

            pedidos.append(p)

    return pedidos, omitidos


def resumen_ingesta(pedidos: list, omitidos: dict) -> None:
    """Imprime estadísticas de la ingesta."""
    en_transito = sum(1 for p in pedidos if p["esta_en_transito"])
    con_cod      = sum(1 for p in pedidos if p["es_contraentrega"])
    promesa_venc = sum(1 for p in pedidos if p["promesa_vencida"])

    print(f"\n{'='*50}")
    print(f"  INGESTA MELONN")
    print(f"{'='*50}")
    print(f"  Pedidos cargados:        {len(pedidos)}")
    print(f"  En tránsito:             {en_transito}")
    print(f"  Con contraentrega (COD): {con_cod}")
    print(f"  Promesa vencida:         {promesa_venc}")
    print(f"  Omitidos (entregados):   {omitidos['resuelto']}")
    print(f"  Omitidos (sin despacho): {omitidos['sin_despacho']}")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    import sys

    ruta = (
        sys.argv[1] if len(sys.argv) > 1
        else "/Users/sebastianhurtado/Library/Containers/net.whatsapp.WhatsApp/Data/tmp/documents/18450138-4023-4958-BB1A-8D4AEBAA2BC1/report-5659_2026-05-12 21_03_02.csv"
    )

    pedidos, omitidos = leer_csv_melonn(ruta, solo_activos=True)
    resumen_ingesta(pedidos, omitidos)

    print(f"{'Orden Melonn':<22} {'Ciudad':<22} {'Transportadora':<24} {'Días':<6} {'COD':<6} {'Estado'}")
    print("-" * 100)
    for p in pedidos[:20]:
        print(
            f"{p['orden_melonn']:<22} {p['ciudad_destino']:<22} "
            f"{p['transportadora']:<24} {p['dias_en_transito']:<6} "
            f"{'SÍ' if p['es_contraentrega'] else 'no':<6} {p['estado_melonn']}"
        )
    if len(pedidos) > 20:
        print(f"  ... y {len(pedidos) - 20} pedidos más")
