"""
Motor de Conciliación Financiera — Male Denim OS
Cruza: pedido ↔ pago ↔ desembolso ↔ banco

Fuentes soportadas:
  - Wompi   : reporte de transacciones (CSV)
  - Melonn COD : liquidación de contraentregas (CSV)
  - Banco   : extracto bancario (CSV)
  - Addi    : reporte de transacciones (CSV)

Flujo:
  1. Cargar cada fuente a la tabla correspondiente del DB
  2. Cruzar pagos_plataforma ↔ pedidos (por orden_shopify)
  3. Cruzar liquidaciones ↔ pedidos (por orden_melonn, COD)
  4. Cruzar movimientos_banco ↔ desembolsos (por referencia / monto+fecha)
  5. Marcar pedidos como conciliados y calcular diferencias
  6. Generar reporte de diferencias y pendientes
"""

import csv
import re
from datetime import date, datetime
from pathlib import Path
from typing import Optional, List, Dict, Tuple
import sys

sys.path.insert(0, str(Path(__file__).parent))
from db import get_conn

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _limpiar_monto(val) -> float:
    """Convierte string de monto colombiano/internacional a float."""
    if val is None or str(val).strip() in ("", "-", "N/A"):
        return 0.0
    s = str(val).strip().replace("$", "").replace(" ", "").replace("\xa0", "")
    # Formato colombiano: punto = miles, coma = decimal  →  1.509.700,00
    if "," in s and "." in s:
        if s.index(",") > s.rindex("."):          # 1.509.700,00
            s = s.replace(".", "").replace(",", ".")
        else:                                      # 1,509,700.00 (US format)
            s = s.replace(",", "")
    elif "," in s:                                 # 1509700,00
        s = s.replace(",", ".")
    # Si solo puntos: puede ser miles o decimal (ambiguo; asumimos miles si > 2 decimales)
    elif "." in s:
        partes = s.split(".")
        if len(partes[-1]) != 2:                  # 1.509.700 → miles
            s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _parse_fecha(val, formatos=None) -> Optional[str]:
    """Intenta parsear una fecha y retorna ISO 8601 (YYYY-MM-DD) o None."""
    if not val or str(val).strip() in ("", "N/A"):
        return None
    s = str(val).strip()
    if formatos is None:
        formatos = [
            "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y",
            "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%z",
        ]
    for fmt in formatos:
        try:
            return datetime.strptime(s[:len(fmt)], fmt).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            continue
    # Intento con fromisoformat
    try:
        return datetime.fromisoformat(s[:19]).strftime("%Y-%m-%d")
    except Exception:
        return None


def _leer_csv_flexible(ruta: str, sep_candidatos=(",", ";", "\t")) -> List[Dict]:
    """Lee un CSV probando separadores automáticamente."""
    ruta_p = Path(ruta)
    if not ruta_p.exists():
        raise FileNotFoundError(f"Archivo no encontrado: {ruta}")
    with open(ruta_p, encoding="utf-8-sig", errors="replace") as f:
        muestra = f.read(4096)
        f.seek(0)
        # Detectar separador por frecuencia
        sep = max(sep_candidatos, key=lambda s: muestra.count(s))
        reader = csv.DictReader(f, delimiter=sep)
        return [dict(row) for row in reader]


# ─────────────────────────────────────────────────────────────────────────────
# INGESTORES — una función por fuente
# ─────────────────────────────────────────────────────────────────────────────

class ResultadoIngesta:
    def __init__(self, fuente: str):
        self.fuente = fuente
        self.leidos = 0
        self.insertados = 0
        self.actualizados = 0
        self.errores: List[str] = []

    def __str__(self):
        return (
            f"[{self.fuente}] leídos={self.leidos} "
            f"insertados={self.insertados} actualizados={self.actualizados} "
            f"errores={len(self.errores)}"
        )


def ingestar_wompi(ruta_csv: str) -> ResultadoIngesta:
    """
    Procesa reporte de transacciones Wompi.
    Columnas esperadas: referencia, monto, estado, fecha, orden (referencia interna)
    Wompi exporta con headers variables — se detectan por nombre parcial.
    """
    res = ResultadoIngesta("wompi")
    filas = _leer_csv_flexible(ruta_csv)
    res.leidos = len(filas)

    # Mapeo flexible de columnas Wompi (pueden cambiar entre versiones)
    def _col(fila: dict, *candidatos) -> str:
        for c in candidatos:
            for k in fila:
                if c.lower() in k.lower():
                    return fila[k]
        return ""

    sql_ins = """
    INSERT OR IGNORE INTO pagos_plataforma
        (plataforma, referencia_plataforma, orden_shopify,
         valor_bruto, comision, valor_neto,
         estado, fecha_transaccion, fecha_desembolso)
    VALUES (?,?,?,?,?,?,?,?,?)
    """
    sql_upd = """
    UPDATE pagos_plataforma
    SET estado=?, valor_bruto=?, valor_neto=?, fecha_desembolso=?
    WHERE referencia_plataforma=?
    """

    with get_conn() as conn:
        for fila in filas:
            try:
                ref    = _col(fila, "referencia", "id transaccion", "payment_id", "transaction_id")
                orden  = _col(fila, "orden", "order_id", "referencia tienda", "shopify")
                monto  = _limpiar_monto(_col(fila, "monto", "valor", "amount", "total"))
                comis  = _limpiar_monto(_col(fila, "comision", "fee", "cargo"))
                neto   = monto - comis if monto else _limpiar_monto(_col(fila, "neto", "net"))
                estado = _col(fila, "estado", "status", "estado transaccion")
                f_txn  = _parse_fecha(_col(fila, "fecha", "date", "created_at", "fecha transaccion"))
                f_desemb = _parse_fecha(_col(fila, "desembolso", "payout", "fecha pago", "settlement"))

                if not ref:
                    res.errores.append(f"Fila sin referencia: {dict(list(fila.items())[:3])}")
                    continue

                existing = conn.execute(
                    "SELECT id FROM pagos_plataforma WHERE referencia_plataforma=?", (ref,)
                ).fetchone()

                if existing:
                    conn.execute(sql_upd, (estado, monto, neto, f_desemb, ref))
                    res.actualizados += 1
                else:
                    conn.execute(sql_ins, (
                        "wompi", ref, orden or None,
                        monto, comis, neto,
                        estado, f_txn, f_desemb
                    ))
                    res.insertados += 1
            except Exception as e:
                res.errores.append(f"{e}")

    return res


def ingestar_liquidacion_melonn(ruta_csv: str, referencia_liquidacion: str = None) -> ResultadoIngesta:
    """
    Procesa liquidación COD de Melonn.
    Crea/actualiza una liquidación y vincula los pedidos COD incluidos.
    """
    res = ResultadoIngesta("melonn_cod")
    filas = _leer_csv_flexible(ruta_csv)
    res.leidos = len(filas)

    def _col(fila, *candidatos):
        for c in candidatos:
            for k in fila:
                if c.lower() in k.lower():
                    return fila[k]
        return ""

    if not referencia_liquidacion:
        referencia_liquidacion = f"LIQ-{date.today().isoformat()}"

    # Calcular totales de la liquidación
    total_pedidos = 0
    valor_total = 0.0
    filas_validas = []

    for fila in filas:
        orden = _col(fila, "orden", "order", "melonn", "referencia")
        valor = _limpiar_monto(_col(fila, "valor", "monto", "cod", "contraentrega", "recaudo"))
        if not orden:
            continue
        total_pedidos += 1
        valor_total += valor
        filas_validas.append((orden, valor, fila))

    sql_liq = """
    INSERT INTO liquidaciones
        (referencia_liquidacion, fecha_liquidacion, total_pedidos, valor_liquidado, estado)
    VALUES (?,?,?,?,'pendiente')
    ON CONFLICT(referencia_liquidacion) DO UPDATE SET
        total_pedidos=excluded.total_pedidos,
        valor_liquidado=excluded.valor_liquidado
    """

    sql_pedido_cod = """
    UPDATE pedidos
    SET estado_recaudo='recaudado',
        valor_cod=?,
        fecha_recaudo=?,
        liquidacion_id=(SELECT id FROM liquidaciones WHERE referencia_liquidacion=?),
        actualizado_en=CURRENT_TIMESTAMP
    WHERE orden_melonn=?
    """

    with get_conn() as conn:
        conn.execute(sql_liq, (
            referencia_liquidacion,
            date.today().isoformat(),
            total_pedidos,
            valor_total,
        ))

        for orden, valor, fila in filas_validas:
            try:
                f_recaudo = _parse_fecha(_col(fila, "fecha", "date", "pago", "recaudo"))
                conn.execute(sql_pedido_cod, (
                    valor, f_recaudo, referencia_liquidacion, orden
                ))
                res.insertados += 1
            except Exception as e:
                res.errores.append(f"{orden}: {e}")

    return res


def ingestar_banco(ruta_csv: str) -> ResultadoIngesta:
    """
    Procesa extracto bancario.
    Detecta ingresos de Wompi, Melonn y Addi por descripción.
    """
    res = ResultadoIngesta("banco")
    filas = _leer_csv_flexible(ruta_csv)
    res.leidos = len(filas)

    def _col(fila, *candidatos):
        for c in candidatos:
            for k in fila:
                if c.lower() in k.lower():
                    return fila[k]
        return ""

    def _detectar_origen(desc: str) -> str:
        desc_up = desc.upper()
        if "WOMPI" in desc_up:         return "wompi"
        if "MELONN" in desc_up:        return "melonn"
        if "ADDI" in desc_up:          return "addi"
        if "MERCADOPAGO" in desc_up or "MERCADO PAGO" in desc_up: return "mercadopago"
        if "SHOPIFY" in desc_up:       return "shopify"
        return "otro"

    sql = """
    INSERT OR IGNORE INTO movimientos_banco
        (fecha, descripcion, valor, tipo, origen, referencia)
    VALUES (?,?,?,?,?,?)
    """

    with get_conn() as conn:
        for fila in filas:
            try:
                fecha  = _parse_fecha(_col(fila, "fecha", "date", "value_date", "fecha movimiento"))
                desc   = _col(fila, "descripcion", "descripcion", "concepto", "detalle", "description")
                valor  = _limpiar_monto(_col(fila, "valor", "monto", "debito", "credito", "amount"))
                tipo_raw = _col(fila, "tipo", "type", "db/cr", "debito", "credito").lower()
                tipo   = "egreso" if any(x in tipo_raw for x in ["db", "deb", "egreso", "cargo", "debito"]) else "ingreso"
                ref    = _col(fila, "referencia", "ref", "numero", "transaction_id")
                origen = _detectar_origen(desc)

                if not fecha or not valor:
                    res.errores.append(f"Fila incompleta: {dict(list(fila.items())[:3])}")
                    continue

                cur = conn.execute(sql, (fecha, desc, abs(valor), tipo, origen, ref or None))
                if cur.rowcount:
                    res.insertados += 1
                else:
                    res.actualizados += 1
            except Exception as e:
                res.errores.append(str(e))

    return res


# ─────────────────────────────────────────────────────────────────────────────
# MOTOR DE CONCILIACIÓN
# ─────────────────────────────────────────────────────────────────────────────

class ResultadoConciliacion:
    def __init__(self):
        self.conciliados   = 0
        self.diferencias   = 0
        self.sin_pago      = 0
        self.sin_pedido    = 0
        self.total_diferencia = 0.0
        self.detalles: List[Dict] = []


def conciliar_wompi_vs_pedidos() -> ResultadoConciliacion:
    """
    Cruza pagos_plataforma (Wompi) con pedidos por orden_shopify.
    Marca el pedido como pagado y detecta diferencias de monto.
    """
    res = ResultadoConciliacion()

    sql_pagos = """
    SELECT pp.id, pp.referencia_plataforma, pp.orden_shopify,
           pp.valor_neto, pp.estado, pp.fecha_desembolso
    FROM pagos_plataforma pp
    WHERE pp.plataforma = 'wompi'
      AND pp.conciliado = 0
      AND pp.estado IN ('APROBADO', 'aprobado', 'approved', 'APPROVED')
    """

    sql_pedido = """
    SELECT id, precio_venta, valor_pagado, estado_pago
    FROM pedidos
    WHERE orden_shopify = ?
    LIMIT 1
    """

    sql_upd_pedido = """
    UPDATE pedidos
    SET estado_pago = 'pagado',
        valor_desembolsado = ?,
        fecha_desembolso = ?,
        conciliado = 1,
        estado_conciliacion = ?,
        diferencia = ?,
        actualizado_en = CURRENT_TIMESTAMP
    WHERE id = ?
    """

    sql_upd_pago = "UPDATE pagos_plataforma SET pedido_id=?, conciliado=1 WHERE id=?"

    with get_conn() as conn:
        pagos = conn.execute(sql_pagos).fetchall()

        for pago in pagos:
            orden = pago["orden_shopify"]
            if not orden:
                res.sin_pedido += 1
                continue

            pedido = conn.execute(sql_pedido, (orden,)).fetchone()
            if not pedido:
                res.sin_pedido += 1
                res.detalles.append({
                    "tipo": "pago_sin_pedido",
                    "referencia": pago["referencia_plataforma"],
                    "orden_shopify": orden,
                    "valor": pago["valor_neto"],
                })
                continue

            valor_esperado = pedido["precio_venta"] or pedido["valor_pagado"] or 0
            valor_recibido = pago["valor_neto"] or 0
            diferencia = round(valor_recibido - valor_esperado, 2)
            estado_concil = "ok" if abs(diferencia) < 1 else "diferencia"

            if abs(diferencia) >= 1:
                res.diferencias += 1
                res.total_diferencia += diferencia
                res.detalles.append({
                    "tipo": "diferencia_wompi",
                    "orden_shopify": orden,
                    "referencia": pago["referencia_plataforma"],
                    "esperado": valor_esperado,
                    "recibido": valor_recibido,
                    "diferencia": diferencia,
                })
            else:
                res.conciliados += 1

            conn.execute(sql_upd_pedido, (
                valor_recibido, pago["fecha_desembolso"],
                estado_concil, diferencia, pedido["id"]
            ))
            conn.execute(sql_upd_pago, (pedido["id"], pago["id"]))

    return res


def conciliar_cod_vs_banco() -> ResultadoConciliacion:
    """
    Cruza liquidaciones COD (Melonn) con movimientos bancarios.
    Busca ingreso bancario con monto similar en ±3 días de la fecha de liquidación.
    """
    res = ResultadoConciliacion()
    TOLERANCIA_DIAS  = 3
    TOLERANCIA_MONTO = 0.01  # 1% de diferencia aceptable

    sql_liqs = """
    SELECT id, referencia_liquidacion, fecha_liquidacion,
           valor_liquidado, valor_recibido_banco, estado
    FROM liquidaciones
    WHERE estado IN ('pendiente', 'parcial')
    """

    sql_banco = """
    SELECT id, fecha, valor, referencia
    FROM movimientos_banco
    WHERE tipo = 'ingreso'
      AND origen = 'melonn'
      AND conciliado = 0
      AND ABS(julianday(fecha) - julianday(?)) <= ?
    ORDER BY ABS(valor - ?) ASC
    LIMIT 5
    """

    sql_upd_liq = """
    UPDATE liquidaciones
    SET valor_recibido_banco = ?,
        diferencia = ?,
        estado = ?,
        observaciones = ?
    WHERE id = ?
    """

    sql_upd_banco = "UPDATE movimientos_banco SET conciliado=1, pedido_id=? WHERE id=?"

    with get_conn() as conn:
        liquidaciones = conn.execute(sql_liqs).fetchall()

        for liq in liquidaciones:
            candidatos = conn.execute(sql_banco, (
                liq["fecha_liquidacion"],
                TOLERANCIA_DIAS,
                liq["valor_liquidado"],
            )).fetchall()

            if not candidatos:
                res.sin_pago += 1
                continue

            # Tomar el candidato con menor diferencia de monto
            mejor = min(
                candidatos,
                key=lambda r: abs(r["valor"] - liq["valor_liquidado"])
            )
            diferencia = round(mejor["valor"] - liq["valor_liquidado"], 2)
            pct_diff   = abs(diferencia) / max(liq["valor_liquidado"], 1)
            estado_nuevo = "completo" if pct_diff <= TOLERANCIA_MONTO else "parcial"
            obs = f"Banco: {mejor['fecha']} ${mejor['valor']:,.0f}"

            if pct_diff > TOLERANCIA_MONTO:
                res.diferencias += 1
                res.total_diferencia += diferencia
                res.detalles.append({
                    "tipo": "diferencia_cod_banco",
                    "liquidacion": liq["referencia_liquidacion"],
                    "esperado": liq["valor_liquidado"],
                    "recibido": mejor["valor"],
                    "diferencia": diferencia,
                })
            else:
                res.conciliados += 1

            conn.execute(sql_upd_liq, (
                mejor["valor"], diferencia, estado_nuevo, obs, liq["id"]
            ))
            conn.execute(sql_upd_banco, (None, mejor["id"]))

    return res


def pedidos_sin_conciliar() -> List[Dict]:
    """Retorna pedidos que deberían tener pago pero no han sido conciliados."""
    sql = """
    SELECT orden_melonn, orden_shopify, nombre_cliente, ciudad_destino,
           precio_venta, metodo_pago, es_contraentrega, valor_cod,
           estado_pago, estado_recaudo, estado_conciliacion, diferencia,
           fecha_pedido, fecha_entrega
    FROM pedidos
    WHERE conciliado = 0
      AND (
            (es_contraentrega = 0 AND estado_pago != 'pendiente')
         OR (es_contraentrega = 1 AND fecha_entrega IS NOT NULL)
      )
    ORDER BY fecha_pedido ASC
    """
    with get_conn() as conn:
        rows = conn.execute(sql).fetchall()
    return [dict(r) for r in rows]


def resumen_conciliacion() -> Dict:
    """Estadísticas globales del estado de conciliación."""
    with get_conn() as conn:
        total     = conn.execute("SELECT COUNT(*) FROM pedidos").fetchone()[0]
        concil    = conn.execute("SELECT COUNT(*) FROM pedidos WHERE conciliado=1").fetchone()[0]
        dif       = conn.execute("SELECT COUNT(*) FROM pedidos WHERE estado_conciliacion='diferencia'").fetchone()[0]
        sum_dif   = conn.execute("SELECT COALESCE(SUM(diferencia),0) FROM pedidos WHERE estado_conciliacion='diferencia'").fetchone()[0]
        pend_cod  = conn.execute(
            "SELECT COUNT(*) FROM pedidos WHERE es_contraentrega=1 AND estado_recaudo='pendiente' AND fecha_entrega IS NULL"
        ).fetchone()[0]
        liqs      = conn.execute("SELECT COUNT(*), COALESCE(SUM(valor_liquidado),0) FROM liquidaciones WHERE estado!='completo'").fetchone()
        mov_banco = conn.execute("SELECT COUNT(*) FROM movimientos_banco WHERE conciliado=0").fetchone()[0]
        pagos_pp  = conn.execute("SELECT COUNT(*) FROM pagos_plataforma WHERE conciliado=0").fetchone()[0]

    return {
        "total_pedidos":         total,
        "conciliados":           concil,
        "con_diferencia":        dif,
        "suma_diferencias":      round(sum_dif, 2),
        "pct_conciliado":        round(concil / total * 100, 1) if total else 0,
        "cod_recaudo_pendiente": pend_cod,
        "liquidaciones_abiertas": liqs[0],
        "valor_liq_abierto":     round(liqs[1], 2),
        "movimientos_sin_cruzar": mov_banco,
        "pagos_sin_cruzar":      pagos_pp,
    }


# ─────────────────────────────────────────────────────────────────────────────
# GENERADOR DE REPORTE
# ─────────────────────────────────────────────────────────────────────────────

OUTPUT_DIR = Path(__file__).parent.parent / "data" / "conciliacion" / "reportes"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def generar_reporte_conciliacion() -> Path:
    """Escribe conciliacion_FECHA.csv con diferencias y pendientes."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT
                p.orden_melonn, p.orden_shopify, p.nombre_cliente,
                p.ciudad_destino, p.metodo_pago, p.es_contraentrega,
                p.precio_venta, p.valor_cod, p.valor_desembolsado,
                p.estado_pago, p.estado_recaudo, p.estado_conciliacion,
                p.diferencia, p.fecha_pedido, p.fecha_entrega,
                p.fecha_desembolso, p.referencia_bancaria, p.conciliado
            FROM pedidos p
            ORDER BY p.conciliado ASC, p.diferencia DESC, p.fecha_pedido ASC
        """).fetchall()

    fecha_hoy = date.today().isoformat()
    ruta = OUTPUT_DIR / f"conciliacion_{fecha_hoy}.csv"

    with open(ruta, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "orden_melonn", "orden_shopify", "nombre_cliente",
            "ciudad_destino", "metodo_pago", "es_contraentrega",
            "precio_venta", "valor_cod", "valor_desembolsado",
            "estado_pago", "estado_recaudo", "estado_conciliacion",
            "diferencia", "fecha_pedido", "fecha_entrega",
            "fecha_desembolso", "referencia_bancaria", "conciliado"
        ], extrasaction="ignore")
        writer.writeheader()
        writer.writerows([dict(r) for r in rows])

    return ruta


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def run_conciliacion(
    wompi_csv:   Optional[str] = None,
    melonn_liq:  Optional[str] = None,
    banco_csv:   Optional[str] = None,
    ref_liq:     Optional[str] = None,
    solo_reporte: bool = False,
) -> None:
    """
    Ejecuta el ciclo completo de conciliación.
    Cada argumento CSV es opcional — se procesan los que se pasen.
    """
    print(f"\n{'═'*55}")
    print(f"  MOTOR DE CONCILIACIÓN — {date.today()}")
    print(f"{'═'*55}\n")

    # ── 1. Ingestión de fuentes
    if wompi_csv:
        r = ingestar_wompi(wompi_csv)
        print(f"  Wompi:    {r}")
        if r.errores[:3]:
            for e in r.errores[:3]: print(f"    ⚠ {e}")

    if melonn_liq:
        r = ingestar_liquidacion_melonn(melonn_liq, ref_liq)
        print(f"  Melonn COD: {r}")

    if banco_csv:
        r = ingestar_banco(banco_csv)
        print(f"  Banco:    {r}")

    if not solo_reporte:
        # ── 2. Cruzar Wompi con pedidos
        rc_wompi = conciliar_wompi_vs_pedidos()
        print(f"\n  Wompi vs pedidos:")
        print(f"    ✓ Conciliados: {rc_wompi.conciliados}")
        print(f"    ≠ Diferencias: {rc_wompi.diferencias}  (Σ ${rc_wompi.total_diferencia:,.0f})")
        print(f"    ? Sin pedido:  {rc_wompi.sin_pedido}")

        # ── 3. Cruzar COD con banco
        rc_cod = conciliar_cod_vs_banco()
        print(f"\n  COD vs banco:")
        print(f"    ✓ Conciliados: {rc_cod.conciliados}")
        print(f"    ≠ Diferencias: {rc_cod.diferencias}  (Σ ${rc_cod.total_diferencia:,.0f})")
        print(f"    ? Sin ingreso: {rc_cod.sin_pago}")

    # ── 4. Resumen final
    stats = resumen_conciliacion()
    print(f"\n{'─'*55}")
    print(f"  RESUMEN DE CONCILIACIÓN")
    print(f"{'─'*55}")
    MONTOS = {"suma_diferencias", "valor_liq_abierto"}
    PORCENTAJES = {"pct_conciliado"}
    for k, v in stats.items():
        if k in MONTOS:
            print(f"  {k:<30} ${v:>12,.0f}")
        elif k in PORCENTAJES:
            print(f"  {k:<30} {v:>11.1f}%")
        else:
            print(f"  {k:<30} {v:>12}")

    # ── 5. Reporte
    ruta = generar_reporte_conciliacion()
    print(f"\n  Reporte: {ruta}\n")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Motor de Conciliación — Male Denim OS")
    ap.add_argument("--wompi",   help="CSV de transacciones Wompi")
    ap.add_argument("--liq",     help="CSV de liquidación COD Melonn")
    ap.add_argument("--banco",   help="CSV de extracto bancario")
    ap.add_argument("--ref-liq", help="Referencia de liquidación (ej: LIQ-2026-05)")
    ap.add_argument("--reporte", action="store_true", help="Solo genera reporte sin re-ingestar")
    args = ap.parse_args()

    run_conciliacion(
        wompi_csv=args.wompi,
        melonn_liq=args.liq,
        banco_csv=args.banco,
        ref_liq=args.ref_liq,
        solo_reporte=args.reporte,
    )
