"""
Punto de entrada del sistema logístico MALE DENIM.
Procesa el CSV de Melonn, genera excepciones.csv y persiste al DB central.

Uso:
    python3 run.py ruta/al/reporte_melonn.csv
    python3 run.py  (usa la ruta configurada en DEFAULT_CSV)
"""

import sys
import csv
from datetime import date
from pathlib import Path

# Agregar src al path para importar módulos hermanos
sys.path.insert(0, str(Path(__file__).parent))

from ingest import leer_csv_melonn, resumen_ingesta
from riesgo import calcular_riesgo, ResultadoRiesgo
from db import init_db, upsert_pedido, guardar_snapshot, stats_db

DEFAULT_CSV = str(
    Path(__file__).parent.parent / "data" / "logistica" / "raw" / "melonn_2026-05-12.csv"
)

OUTPUT_DIR = Path(__file__).parent.parent / "data" / "logistica" / "reportes"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

COLUMNAS_REPORTE = [
    "prioridad",
    "nivel_riesgo",
    "score_riesgo",
    "orden_melonn",
    "orden_tienda",
    "nombre_comprador",
    "telefono_comprador",
    "ciudad_destino",
    "zona_logistica",
    "dias_en_transito",
    "sla_critico",
    "dias_sobre_sla",
    "es_contraentrega",
    "valor_cod",
    "transportadora",
    "estado_melonn",
    "incidencia",
    "categoria_incidencia",
    "promesa_vencida",
    "fecha_despacho",
    "fecha_promesa",
    "motivo_principal",
    "link_guia",
]


def _pedido_para_db(p: dict) -> dict:
    """Mapea el pedido enriquecido al formato de columnas de la tabla pedidos."""
    return {
        "orden_shopify":        p.get("orden_tienda"),
        "orden_melonn":         p.get("orden_melonn"),
        "fecha_pedido":         None,                          # no viene en CSV Melonn
        "canal":                "melonn",
        "nombre_cliente":       p.get("nombre_comprador"),
        "telefono_cliente":     p.get("telefono_comprador"),
        "email_cliente":        None,
        "ciudad_destino":       p.get("ciudad_destino"),
        "region_destino":       None,
        "sku":                  None,
        "producto":             None,
        "cantidad":             None,
        "precio_venta":         None,
        "metodo_pago":          "cod" if p.get("es_contraentrega") else "prepago",
        "plataforma_pago":      None,
        "valor_pagado":         None,
        "es_contraentrega":     1 if p.get("es_contraentrega") else 0,
        "valor_cod":            _parse_valor_cod(p.get("valor_cod", "")),
        "transportadora":       p.get("transportadora"),
        "fecha_despacho":       p.get("fecha_despacho"),
        "fecha_promesa":        p.get("fecha_promesa"),
        "fecha_entrega":        None,
        "estado_melonn":        p.get("estado_melonn"),
        "zona_logistica":       p.get("zona_logistica"),
        "dias_en_transito":     p.get("dias_en_transito"),
        "score_riesgo":         p.get("score_riesgo"),
        "nivel_riesgo":         p.get("nivel_riesgo"),
        "incidencia":           p.get("incidencia", "NINGUNO"),
        "categoria_incidencia": p.get("categoria_incidencia", "OK"),
        "link_melonn":          p.get("link_guia"),
        "fuente":               "csv",
    }


def _parse_valor_cod(val) -> float:
    """Convierte valor COD a float (maneja formato colombiano con puntos de miles)."""
    if not val:
        return 0.0
    s = str(val).replace("$", "").replace(" ", "")
    # Formato colombiano: punto = miles, coma = decimal
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(".", "")
    try:
        return float(s) if s else 0.0
    except ValueError:
        return 0.0


def procesar_pedido(p: dict) -> dict:
    """Enriquece un pedido con zona, incidencia y score de riesgo."""
    resultado: ResultadoRiesgo = calcular_riesgo(
        ciudad=p["ciudad_destino"],
        dias_en_transito=p["dias_en_transito"],
        incidencia_raw=p.get("incidencia", "NINGUNO"),
        es_contraentrega=p["es_contraentrega"],
        es_reexpedido=False,
    )

    dias_sobre_sla = max(0, p["dias_en_transito"] - resultado.zona_info.sla_critico + 1)

    return {
        **p,
        "zona_logistica":      resultado.zona_info.zona,
        "sla_critico":         resultado.zona_info.sla_critico,
        "dias_sobre_sla":      dias_sobre_sla,
        "score_riesgo":        resultado.score,
        "nivel_riesgo":        resultado.nivel,
        "prioridad":           resultado.prioridad,
        "requiere_accion":     resultado.requiere_accion,
        "categoria_incidencia": resultado.incidencia_info.categoria,
        "motivo_principal":    resultado.motivos[0] if resultado.motivos else "—",
        "valor_cod":           p.get("valor_cod_raw", ""),
    }


def generar_reporte(pedidos_enriquecidos: list, nombre_archivo: str) -> Path:
    """Escribe excepciones.csv con solo los pedidos RIESGO y CRÍTICO."""
    excepciones = [
        p for p in pedidos_enriquecidos
        if p["nivel_riesgo"] in ("RIESGO", "CRITICO")
    ]

    # Ordenar por prioridad (1=más urgente), luego por días sobre SLA
    excepciones.sort(key=lambda x: (x["prioridad"], -x["dias_sobre_sla"]))

    ruta_salida = OUTPUT_DIR / nombre_archivo
    with open(ruta_salida, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNAS_REPORTE, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(excepciones)

    return ruta_salida, excepciones


def imprimir_resumen_riesgo(pedidos_enriquecidos: list, excepciones: list) -> None:
    total = len(pedidos_enriquecidos)
    criticos  = sum(1 for p in excepciones if p["nivel_riesgo"] == "CRITICO")
    riesgo    = sum(1 for p in excepciones if p["nivel_riesgo"] == "RIESGO")
    normales  = total - len(excepciones)
    cod_critico = sum(1 for p in excepciones if p["nivel_riesgo"] == "CRITICO" and p["es_contraentrega"])

    print(f"\n{'='*55}")
    print(f"  MOTOR DE RIESGO — RESULTADOS")
    print(f"{'='*55}")
    print(f"  Total pedidos activos:    {total}")
    print(f"  NORMAL (sin acción):      {normales}")
    print(f"  RIESGO:                   {riesgo}")
    print(f"  CRÍTICO:                  {criticos}")
    print(f"  ── COD crítico (dinero):  {cod_critico}")
    print(f"{'='*55}")

    if excepciones:
        print(f"\n  TOP 10 EXCEPCIONES A ATENDER HOY:\n")
        print(f"  {'P':<3} {'Nivel':<9} {'Score':<6} {'Ciudad':<18} {'Días':<5} {'COD':<5} {'Motivo'}")
        print(f"  {'-'*90}")
        for p in excepciones[:10]:
            cod = "SÍ" if p["es_contraentrega"] else "no"
            print(
                f"  {p['prioridad']:<3} {p['nivel_riesgo']:<9} {p['score_riesgo']:<6} "
                f"{p['ciudad_destino']:<18} {p['dias_en_transito']:<5} {cod:<5} {p['motivo_principal']}"
            )
        if len(excepciones) > 10:
            print(f"\n  ... y {len(excepciones) - 10} excepciones más en el reporte CSV.")
    print()


def run(ruta_csv: str) -> None:
    print(f"\nProcesando: {Path(ruta_csv).name}")

    # 0. Asegurar que el DB existe
    init_db()

    # 1. Leer e ingestar CSV
    pedidos, omitidos = leer_csv_melonn(ruta_csv, solo_activos=True)
    resumen_ingesta(pedidos, omitidos)

    # 2. Enriquecer cada pedido con zona + incidencia + score
    pedidos_enriquecidos = [procesar_pedido(p) for p in pedidos]

    # 3. Persistir en base de datos central
    fecha_hoy = date.today().strftime("%Y-%m-%d")
    nombre_csv = Path(ruta_csv).name
    guardados = 0
    for p in pedidos_enriquecidos:
        try:
            upsert_pedido(_pedido_para_db(p))
            guardados += 1
        except Exception as e:
            print(f"  ⚠  Error guardando {p.get('orden_melonn','?')}: {e}")

    snap_count = guardar_snapshot(
        [_pedido_para_db(p) for p in pedidos_enriquecidos],
        fecha_hoy,
        nombre_csv,
    )
    print(f"  DB: {guardados} pedidos upserted · {snap_count} snapshots guardados ({fecha_hoy})")

    # 4. Generar reporte de excepciones CSV
    nombre_archivo = f"excepciones_{fecha_hoy}.csv"
    ruta_salida, excepciones = generar_reporte(pedidos_enriquecidos, nombre_archivo)

    # 5. Imprimir resumen en consola
    imprimir_resumen_riesgo(pedidos_enriquecidos, excepciones)

    # 6. Stats del DB
    s = stats_db()
    print(f"  DB total: {s['total_pedidos']} pedidos · {s['snapshots']} snapshots · {s['dias_con_datos']} días")
    print(f"  Reporte guardado en: {ruta_salida}\n")


if __name__ == "__main__":
    ruta = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CSV
    run(ruta)
