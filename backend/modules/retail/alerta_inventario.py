"""El aviso diario a contabilidad: lo que se vendió sin existencia.

El POS deja vender una talla que el sistema tiene en cero. Es a propósito —la
prenda está en la mano de la cajera y el inventario de Siigo no siempre va al
día—, pero cada una de esas ventas es una diferencia entre lo que hay y lo
que Siigo cree que hay. Si nadie la mira, se acumula hasta el inventario
físico de fin de año.

Cada mañana sale un correo con las de AYER: qué prenda, en qué tienda, con qué
factura y en cuánto quedó el saldo. Sin casos no sale nada.

    python -m backend.modules.retail.alerta_inventario 2026-10-09   # sólo mirar

QUÉ CUENTA COMO «SIN EXISTENCIA». La fuente es el libro de inventario, no el
saldo: un asiento de venta cuyo `saldo_despues` quedó en negativo. El saldo de
hoy ya no sirve —la sincronización con Siigo lo corrige cada hora—; el libro
es append-only y conserva lo que pasó. Las ventas que después se anularon no
cuentan: la prenda volvió.
"""
from __future__ import annotations

import html as _html
import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy import create_engine, text

from backend.modules.retail.infrastructure.persistencia.unidad_de_trabajo import (
    normalizar_url,
)

log = logging.getLogger("retail.inventario")

__all__ = ["casos_del_dia", "armar_correo", "enviar_la_de_ayer",
           "destinatarios", "HORA_DE_ENVIO"]

TIPO = "vendido_sin_existencia"
#  Hora de Bogotá a partir de la cual sale el correo del día anterior.
HORA_DE_ENVIO = int(os.environ.get("RETAIL_ALERTA_INVENTARIO_HORA", 7))
_BOGOTA = timezone(timedelta(hours=-5))      # Colombia no tiene horario de verano


def destinatarios() -> List[str]:
    """`RETAIL_ALERTA_INVENTARIO_PARA`, separados por coma. Vacío = no se envía."""
    crudo = os.environ.get("RETAIL_ALERTA_INVENTARIO_PARA", "")
    return [c.strip() for c in crudo.split(",") if "@" in c]


def casos_del_dia(c, dia: date) -> List[dict]:
    """Los asientos de venta de ese día (hora de Bogotá) que dejaron el saldo
    en negativo, uno por prenda vendida."""
    filas = c.execute(text("""
        SELECT t.nombre AS tienda, v.sku, v.nombre AS prenda, v.talla,
               -m.delta AS vendidas, m.saldo_despues AS saldo,
               ve.numero AS venta,
               (SELECT d.numero FROM retail.documentos_fiscales d
                 WHERE d.venta_id = ve.id AND d.tipo = 'factura_electronica'
                   AND d.estado = 'emitido'
                 ORDER BY d.emitido_en DESC LIMIT 1) AS factura,
               coalesce(p.nombre, ve.cajera_id) AS cajera,
               to_char(m.creado_en AT TIME ZONE 'America/Bogota', 'HH24:MI') AS hora
          FROM retail.movimientos_inventario m
          JOIN retail.variantes v   ON v.id = m.variante_id
          JOIN retail.ubicaciones u ON u.id = m.ubicacion_id
          LEFT JOIN retail.tiendas t ON t.id = u.tienda_id
          JOIN retail.ventas ve     ON ve.id = m.referencia_id
          LEFT JOIN retail.permisos_pos p ON p.usuario_id = ve.cajera_id
         WHERE m.motivo = 'venta' AND m.referencia_tipo = 'venta'
           AND m.saldo_despues < 0
           AND ve.estado = 'cerrada'
           AND (m.creado_en AT TIME ZONE 'America/Bogota')::date = :dia
         ORDER BY t.nombre, m.creado_en
    """), {"dia": dia}).mappings().all()
    salida = []
    for f in filas:
        d = dict(f)
        # De lo vendido en ese asiento, cuánto NO estaba: si había 1 y se
        # vendieron 2, el saldo quedó en −1 y sin existencia fue una.
        d["sin_existencia"] = min(int(d["vendidas"]), -int(d["saldo"]))
        salida.append(d)
    return salida


def armar_correo(casos: List[dict], dia: date) -> tuple:
    """(asunto, html, texto)."""
    unidades = sum(c["sin_existencia"] for c in casos)
    fecha = f"{dia:%d/%m/%Y}"
    asunto = (f"POS · {unidades} prenda{'s' if unidades != 1 else ''} "
              f"vendida{'s' if unidades != 1 else ''} sin existencia el {fecha}")
    e = _html.escape
    filas = "".join(
        "<tr>" + "".join(
            f'<td style="padding:6px 10px;border-bottom:1px solid #eee">{e(str(v))}</td>'
            for v in (c["tienda"] or "", c["sku"], c["prenda"],
                      c["sin_existencia"], c["saldo"],
                      c["factura"] or "sin factura aún", c["venta"],
                      c["cajera"] or "", c["hora"])) + "</tr>"
        for c in casos)
    cabeza = "".join(
        f'<th style="padding:6px 10px;text-align:left;border-bottom:2px solid #222">{t}</th>'
        for t in ("Tienda", "Código", "Prenda", "Vendidas sin existencia",
                  "Saldo que quedó", "Factura", "Venta POS", "Asesora", "Hora"))
    cuerpo = f"""
<div style="font-family:system-ui,Arial,sans-serif;font-size:14px;color:#222">
  <p>El {fecha} las tiendas vendieron <strong>{unidades}</strong> prenda(s) que
  el sistema tenía en cero.</p>
  <p>La venta y la factura están bien: la prenda estaba en la tienda. Lo que
  hay que revisar es <strong>el inventario de Siigo</strong> de esa bodega, que
  quedó en negativo o no tenía registrada la prenda (falta un traslado, una
  entrada, o hay un error de conteo).</p>
  <table style="border-collapse:collapse;font-size:13px">
    <thead><tr>{cabeza}</tr></thead><tbody>{filas}</tbody>
  </table>
  <p style="color:#666;font-size:12px">Aviso automático del POS de MALE DENIM.
  Sale cada mañana sólo si el día anterior hubo casos.</p>
</div>"""
    texto = "\n".join(
        [f"Prendas vendidas sin existencia el {fecha}: {unidades}", ""] +
        [f"- {c['tienda']} · {c['sku']} {c['prenda']} · {c['sin_existencia']} und · "
         f"saldo {c['saldo']} · {c['factura'] or 'sin factura aún'} · "
         f"{c['venta']} · {c['hora']}" for c in casos])
    return asunto, cuerpo, texto


def enviar_la_de_ayer(url: str, *, ahora: Optional[datetime] = None,
                      enviar=None) -> dict:
    """Manda el correo de ayer si toca. Idempotente: una vez por día.

    `enviar(para, asunto, html, texto) -> {"ok": bool, ...}`; por defecto, el
    servicio de correo del ERP.
    """
    ahora = (ahora or datetime.now(timezone.utc)).astimezone(_BOGOTA)
    if ahora.hour < HORA_DE_ENVIO:
        return {"enviado": False, "motivo": "todavía no es la hora"}
    para = destinatarios()
    if not para:
        return {"enviado": False, "motivo": "sin destinatarios configurados"}
    dia = ahora.date() - timedelta(days=1)

    motor = create_engine(normalizar_url(url), future=True)
    try:
        with motor.begin() as c:
            # EL CANDADO. Quien logra insertar la fila es quien envía; un
            # segundo proceso, o un reinicio, se encuentra con que ya está.
            mio = c.execute(text("""
                INSERT INTO retail.alertas_enviadas (tipo, fecha, destinatarios)
                VALUES (:t, :f, :d) ON CONFLICT DO NOTHING RETURNING 1
            """), {"t": TIPO, "f": dia, "d": ", ".join(para)}).first()
            if mio is None:
                return {"enviado": False, "motivo": "ya se había enviado"}
            casos = casos_del_dia(c, dia)
            if not casos:
                c.execute(text("""
                    UPDATE retail.alertas_enviadas SET resultado = 'sin casos'
                     WHERE tipo = :t AND fecha = :f"""), {"t": TIPO, "f": dia})
                return {"enviado": False, "motivo": "sin casos", "dia": str(dia)}

            if enviar is None:
                from backend.services import correo
                enviar = lambda **kw: correo.enviar(**kw)       # noqa: E731
            asunto, cuerpo, texto = armar_correo(casos, dia)
            resultados = [enviar(para=p, asunto=asunto, html=cuerpo, texto=texto)
                          for p in para]
            bien = [r for r in resultados if r.get("ok")]
            if not bien:
                # Ninguno salió: se suelta el candado para reintentar luego.
                raise RuntimeError(
                    f"el correo no salió: {resultados[0].get('error')}")
            c.execute(text("""
                UPDATE retail.alertas_enviadas
                   SET casos = :n, resultado = :r
                 WHERE tipo = :t AND fecha = :f
            """), {"t": TIPO, "f": dia, "n": len(casos),
                   "r": f"enviado a {len(bien)} de {len(para)}"})
            log.info("[retail-inventario] alerta del %s: %d casos a %d "
                     "destinatarios", dia, len(casos), len(bien))
            return {"enviado": True, "dia": str(dia), "casos": len(casos),
                    "destinatarios": len(bien)}
    finally:
        motor.dispose()


def main(argv: List[str]) -> int:
    url = os.environ.get("RETAIL_DATABASE_URL", "").strip()
    if not url:
        print("Falta RETAIL_DATABASE_URL.", file=sys.stderr)
        return 2
    dia = datetime.strptime(argv[0], "%Y-%m-%d").date() if argv else (
        datetime.now(_BOGOTA).date() - timedelta(days=1))
    motor = create_engine(normalizar_url(url), future=True)
    try:
        with motor.connect() as c:
            casos = casos_del_dia(c, dia)
    finally:
        motor.dispose()
    print(f"\n  {dia}: {len(casos)} caso(s). No se envía nada desde aquí.\n")
    for c in casos:
        print(f"    {c['tienda']} · {c['sku']} · {c['sin_existencia']} und · "
              f"saldo {c['saldo']} · {c['factura']} · {c['venta']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
