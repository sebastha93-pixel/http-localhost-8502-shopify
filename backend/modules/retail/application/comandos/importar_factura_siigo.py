"""Traer al POS una factura de Siigo POS, para poder hacerle un cambio.

LO QUE ENTRA ES UN REGISTRO, NO UNA VENTA NUEVA. La plata ya entró y la prenda
ya salió, semanas atrás y en otro sistema. Por eso esto:

  · NO mueve inventario — la prenda no está en la tienda, está en la casa de
    la clienta. Entra cuando ella la devuelve, por la devolución.
  · NO toca ningún arqueo — cuelga de un turno histórico, cerrado y en cero.
  · NO encola nada hacia Siigo — la factura ya existe allá; aquí se guarda su
    número, su CUFE y su id para que la nota crédito la encuentre.

LOS VALORES SE COPIAN DE SIIGO. Cada línea entra con el total que Siigo le
calculó; es lo que la clienta pagó y lo que se le devuelve.

ES IDEMPOTENTE por el id de la factura en Siigo: buscarla dos veces, o que dos
cajas la busquen a la vez, no la duplica.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, time as _hora, timedelta, timezone
from typing import Callable, Optional

from sqlalchemy import text

from backend.modules.retail.domain.venta.errores import ReglaDeNegocio

__all__ = ["ImportarFacturaSiigo", "VentaImportada"]

_BOGOTA = timezone(timedelta(hours=-5))
_ALFABETO = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
USUARIO = "siigo_pos"


def _ulid_de(texto: str) -> str:
    n = int.from_bytes(hashlib.sha256(texto.encode()).digest(), "big")
    salida = []
    for _ in range(26):
        n, r = divmod(n, 32)
        salida.append(_ALFABETO[r])
    return "".join(reversed(salida))


def _c(valor) -> int:
    """Pesos de Siigo → centavos, redondeando bien (`134910.0` → 13491000)."""
    return int(round(float(valor or 0) * 100))


@dataclass(frozen=True)
class VentaImportada:
    venta_id: str
    numero: str
    ya_estaba: bool


class ImportarFacturaSiigo:
    def __init__(self, sesion) -> None:
        self._s = sesion

    async def ejecutar(self, factura: dict, *, comprobante: dict,
                       nuevo_id: Callable[[], str],
                       cliente_id: Optional[str] = None,
                       ahora: Optional[datetime] = None) -> VentaImportada:
        """`comprobante` es la fila de `facturas_tienda.COMPROBANTES`."""
        siigo_id = str(factura.get("id") or "")
        prefijo = (factura.get("prefix") or comprobante["prefijo"]).strip().upper()
        consecutivo = factura.get("number")
        if not siigo_id or consecutivo is None:
            raise ReglaDeNegocio("La factura de Siigo vino sin número.")
        numero = f"{prefijo}-{int(consecutivo)}"

        ya = (await self._s.execute(text("""
            SELECT v.id, v.numero FROM retail.documentos_fiscales d
              JOIN retail.ventas v ON v.id = d.venta_id
             WHERE d.documento_externo_id = :s AND d.tipo = 'factura_electronica'
             LIMIT 1
        """), {"s": siigo_id})).mappings().first()
        if ya:
            return VentaImportada(ya["id"], ya["numero"], True)

        items = [i for i in (factura.get("items") or [])
                 if int(float(i.get("quantity") or 0)) > 0 and _c(i.get("total")) > 0]
        if not items:
            raise ReglaDeNegocio(
                f"La factura {numero} no tiene prendas que se puedan devolver.")

        ahora = ahora or datetime.now(timezone.utc)
        caja_id, tienda_id = comprobante["caja_id"], comprobante["tienda_id"]
        sesion_id = await self._turno_historico(caja_id, tienda_id)
        cuando = self._fecha(factura)

        venta_id = nuevo_id()
        lineas, bruto, descuentos, base, iva, total = [], 0, 0, 0, 0, 0
        for orden, it in enumerate(items, start=1):
            cant = int(float(it["quantity"]))
            total_linea = _c(it.get("total"))
            iva_linea = sum(_c(t.get("value")) for t in (it.get("taxes") or []))
            dcto = it.get("discount")
            dcto_base = _c(dcto.get("value")) if isinstance(dcto, dict) else 0
            # El descuento, con IVA, es lo que le falta al total para llegar
            # al precio de lista: así `cantidad × precio − descuento` da
            # EXACTAMENTE el total de Siigo, sin recalcular nada.
            tasa = 19 if iva_linea else 0
            dcto_con_iva = int(round(dcto_base * (100 + tasa) / 100))
            unitario = int(round((total_linea + dcto_con_iva) / cant))
            dcto_con_iva = unitario * cant - total_linea
            if dcto_con_iva < 0:
                unitario, dcto_con_iva = -(-total_linea // cant), 0
                dcto_con_iva = unitario * cant - total_linea
            variante = await self._variante(it, unitario)
            lineas.append({
                "id": _ulid_de(f"{venta_id}:{orden}"), "venta": venta_id,
                "orden": orden, "variante": variante, "sku": it["code"],
                "desc": (it.get("description") or it["code"])[:200],
                "cant": cant, "precio": unitario, "dcto": dcto_con_iva,
                "motivo": "descuento en Siigo POS" if dcto_con_iva else None,
                "tasa": tasa, "base": total_linea - iva_linea,
                "iva": iva_linea, "total": total_linea})
            bruto += unitario * cant
            descuentos += dcto_con_iva
            base += total_linea - iva_linea
            iva += iva_linea
            total += total_linea

        await self._s.execute(text("""
            INSERT INTO retail.ventas
                (id, numero, prefijo, consecutivo, tienda_id, caja_id, sesion_id,
                 cajera_id, cliente_id, estado, estado_fiscal, origen, subtotal,
                 descuento_total, base_gravable, iva_total, total, pagado,
                 vuelto, creada_en, cerrada_en, sincronizada_en)
            VALUES (:id, :numero, :prefijo, :cons, :tienda, :caja, :sesion,
                    :cajera, :cliente, 'cerrada', 'emitido', 'siigo_pos', :sub,
                    :dcto, :base, :iva, :total, :total, 0, :cuando, :cuando, :ahora)
        """), {"id": venta_id, "numero": numero, "prefijo": prefijo,
               "cons": int(consecutivo), "tienda": tienda_id, "caja": caja_id,
               "sesion": sesion_id, "cajera": USUARIO, "cliente": cliente_id,
               "sub": bruto, "dcto": descuentos, "base": base, "iva": iva,
               "total": total, "cuando": cuando, "ahora": ahora})
        for l in lineas:
            await self._s.execute(text("""
                INSERT INTO retail.venta_lineas
                    (id, venta_id, orden, variante_id, sku, descripcion, cantidad,
                     precio_unitario, descuento_monto, descuento_motivo,
                     tasa_iva, base_gravable, iva_monto, total_linea)
                VALUES (:id, :venta, :orden, :variante, :sku, :desc, :cant,
                        :precio, :dcto, :motivo, :tasa, :base, :iva, :total)
            """), l)

        sello = factura.get("stamp") or {}
        await self._s.execute(text("""
            INSERT INTO retail.documentos_fiscales
                (id, venta_id, tipo, estado, numero, cufe, documento_externo_id,
                 payload_snapshot, respuesta_cruda, emitido_en)
            VALUES (:id, :venta, 'factura_electronica', 'emitido', :numero,
                    :cufe, :ext, CAST(:snap AS jsonb), CAST(:cruda AS jsonb),
                    :cuando)
        """), {"id": _ulid_de(f"{venta_id}:FAC"), "venta": venta_id,
               "numero": numero, "cufe": (sello.get("cufe") or None),
               "ext": siigo_id, "cuando": cuando,
               "snap": json.dumps({"origen": "siigo_pos",
                                   "name": factura.get("name")}),
               "cruda": json.dumps(factura, default=str)})
        return VentaImportada(venta_id, numero, False)

    # ── Piezas ──────────────────────────────────────────────────────────────

    @staticmethod
    def _fecha(factura: dict) -> datetime:
        """El día de la factura, a mediodía de Bogotá: Siigo da la fecha, y la
        hora exacta no cambia nada para un cambio."""
        try:
            dia = datetime.strptime(str(factura.get("date"))[:10], "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return datetime.now(timezone.utc)
        return datetime.combine(dia, _hora(12, 0), tzinfo=_BOGOTA)

    async def _turno_historico(self, caja_id: str, tienda_id: str) -> str:
        """El turno del que cuelgan las ventas traídas de Siigo POS: uno por
        caja, cerrado y en cero. Nunca se abre ni se arquea."""
        sid = _ulid_de(f"siigo_pos:{caja_id}")
        await self._s.execute(text("""
            INSERT INTO retail.sesiones_caja
                (id, tienda_id, caja_id, numero_turno, estado, base_inicial,
                 abierta_por, abierta_en, cerrada_por, cerrada_en,
                 diferencia_total, justificacion)
            VALUES (:id, :tienda, :caja, 0, 'cerrada', 0, :u,
                    TIMESTAMPTZ '2020-01-01 00:00:00-05', :u,
                    TIMESTAMPTZ '2020-01-01 00:00:00-05', 0,
                    'Turno histórico: ventas de Siigo POS traídas para cambios')
            ON CONFLICT (id) DO NOTHING
        """), {"id": sid, "tienda": tienda_id, "caja": caja_id, "u": USUARIO})
        return sid

    async def _variante(self, item: dict, unitario: int) -> str:
        """La prenda en el catálogo del POS. Si no está —un código que ya no
        se vende, o el «genérico» de precio libre— se crea APAGADA: sirve para
        recibir la devolución y no aparece para venderse."""
        code = (item.get("code") or "").strip()
        vid = (await self._s.execute(text(
            "SELECT id FROM retail.variantes WHERE upper(sku) = upper(:s)"),
            {"s": code})).scalar()
        if vid:
            return vid
        from backend.modules.retail.catalogo_desde_siigo import ref_talla
        ref, talla = ref_talla(code)
        return (await self._s.execute(text("""
            INSERT INTO retail.variantes
                (id, sku, referencia, talla, color, nombre, categoria,
                 precio_con_iva, activa)
            VALUES (:id, :sku, :ref, :talla, '', :nom, 'Sin categoría', :p, false)
            RETURNING id
        """), {"id": _ulid_de(f"variante:{code}"), "sku": code,
               "ref": ref or code, "talla": talla or "U",
               "nom": (item.get("description") or code)[:200],
               "p": max(unitario, 1)})).scalar()
