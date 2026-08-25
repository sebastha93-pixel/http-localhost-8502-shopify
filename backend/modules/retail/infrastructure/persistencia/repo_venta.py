"""Repositorio de ventas: traduce entre el agregado y las tablas.

El mapeo va a mano en los dos sentidos. Es más código que un ORM declarativo,
y a cambio `Venta` no tiene un solo import de SQLAlchemy — que es lo que hace
que sus doce invariantes se prueben en 0,1 s sin base de datos.

Los totales se persisten aunque sean derivables de las líneas. No es
redundancia: un informe de fin de mes no puede recalcular 200.000 líneas, y
una venta cerrada es inmutable, así que el total guardado no puede quedar
desactualizado.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.modules.retail.domain.shared.dinero import Dinero
from backend.modules.retail.domain.shared.sku import Sku
from backend.modules.retail.domain.venta.descuento import Descuento, TipoDescuento
from backend.modules.retail.domain.venta.estados import EstadoFiscal, EstadoVenta
from backend.modules.retail.domain.venta.linea import LineaVenta
from backend.modules.retail.domain.venta.pago import Pago
from backend.modules.retail.domain.venta.venta import Venta
from backend.modules.retail.infrastructure.persistencia import tablas as T

__all__ = ["RepositorioVentasSQL"]


class RepositorioVentasSQL:
    def __init__(self, sesion: AsyncSession) -> None:
        self._s = sesion

    # ── Escritura ───────────────────────────────────────────────────────────

    async def guardar(self, venta: Venta, *, variante_por_sku: dict) -> None:
        """Persiste el agregado completo.

        `ON CONFLICT (id) DO UPDATE` en vez de un INSERT a secas: el
        dispositivo genera el id y puede reintentar el mismo cierre varias
        veces (ADR-005). Reintentar tiene que ser inofensivo, no un 500.
        """
        fila = self._fila_venta(venta)
        await self._s.execute(
            pg_insert(T.ventas).values(**fila).on_conflict_do_update(
                index_elements=[T.ventas.c.id],
                set_={k: v for k, v in fila.items() if k != "id"},
            )
        )

        # Las líneas y los pagos se reemplazan enteros. Un borrador cambia
        # muchas veces y llevar un diff por línea sería complejidad sin
        # beneficio: son unas pocas filas.
        await self._s.execute(
            T.venta_lineas.delete().where(T.venta_lineas.c.venta_id == venta.id))
        await self._s.execute(
            T.venta_pagos.delete().where(T.venta_pagos.c.venta_id == venta.id))

        if venta.lineas:
            await self._s.execute(T.venta_lineas.insert(), [
                self._fila_linea(venta, l, variante_por_sku) for l in venta.lineas
            ])
        if venta.pagos:
            await self._s.execute(T.venta_pagos.insert(), [
                self._fila_pago(venta, p) for p in venta.pagos
            ])

    def _fila_venta(self, v: Venta) -> dict:
        return {
            "id": v.id,
            "numero": v.numero,
            # Del AGREGADO, no partido aquí otra vez: el endpoint valida el
            # consecutivo contra el bloque arrendado con la misma definición.
            "prefijo": v.prefijo,
            "consecutivo": v.consecutivo,
            "tienda_id": v.tienda_id,
            "caja_id": v.caja_id,
            "sesion_id": v.sesion_id,
            "dispositivo_id": v.dispositivo_id,
            "cajera_id": v.cajera_id,
            "cliente_id": v.cliente_id,
            "estado": v.estado.value,
            "estado_fiscal": v.estado_fiscal.value,
            "origen": v.origen,
            "subtotal": v.subtotal().centavos,
            "descuento_total": v.descuento_total().centavos,
            "base_gravable": v.base_gravable().centavos,
            "iva_total": v.iva_total().centavos,
            "total": v.total().centavos,
            "pagado": v.pagado().centavos,
            "vuelto": v.vuelto().centavos,
            "moneda": v.moneda,
            "creada_en_dispositivo": v.creada_en,
            "cerrada_en": v.cerrada_en,
            "sesion_desfasada": False,
            "anulada_en": v.anulada_en,
            "motivo_anulacion": v.motivo_anulacion,
        }

    def _fila_linea(self, v: Venta, l: LineaVenta, variante_por_sku: dict) -> dict:
        d = l.descuento
        return {
            "id": f"{v.id[:22]}{l.numero:04d}"[:26],
            "venta_id": v.id,
            "orden": l.numero,
            "variante_id": variante_por_sku[l.sku.codigo],
            "sku": l.sku.codigo,
            "descripcion": l.descripcion,
            "cantidad": l.cantidad,
            "precio_unitario": l.precio_unitario.centavos,
            "descuento_tipo": d.tipo.value if d else None,
            "descuento_valor": (
                d.porcentaje_aplicado if d and d.tipo is TipoDescuento.PORCENTAJE
                else (Decimal(d.valor_aplicado.centavos) if d and d.valor_aplicado
                      else None)
            ),
            "descuento_monto": l.descuento_monto().centavos,
            # El obsequio descuenta el 100% y la BASE exige motivo cuando hay
            # descuento; se escribe el que ya quedó en la auditoría.
            "descuento_motivo": (
                d.motivo if d else ("obsequio autorizado" if l.obsequio else None)
            ),
            "autorizado_por": l.autorizado_por,
            "obsequio": l.obsequio,
            "tasa_iva": l.tasa_iva,
            "base_gravable": l.base_gravable().centavos,
            "iva_monto": l.iva().centavos,
            "total_linea": l.total().centavos,
        }

    def _fila_pago(self, v: Venta, p: Pago) -> dict:
        return {
            "id": f"{v.id[:22]}{9000 + p.numero:04d}"[:26],
            "venta_id": v.id,
            "medio_pago_id": p.medio_pago_id,
            "monto": p.monto.centavos,
            "referencia": p.referencia,
        }

    # ── Lectura ─────────────────────────────────────────────────────────────

    async def marcar_anulada(self, *, venta_id: str, motivo: str,
                             anulada_por: str, ahora) -> None:
        """Anular NO toca las líneas ni los pagos: sólo el encabezado.

        Volver a escribir la venta entera con `guardar` obligaría a traer el
        mapa de SKU→variante que la venta ya no necesita, y reescribiría filas
        que no cambiaron. Peor: si el mapa llegara incompleto —como me pasó—
        las líneas se perderían al reescribirlas.
        """
        await self._s.execute(text("""
            UPDATE retail.ventas
               SET estado = 'anulada', motivo_anulacion = :m,
                   anulada_por = :u, anulada_en = :ts
             WHERE id = :i
        """), {"i": venta_id, "m": motivo, "u": anulada_por, "ts": ahora})

    async def obtener(self, venta_id: str) -> Optional[Venta]:
        fila = (await self._s.execute(
            select(T.ventas).where(T.ventas.c.id == venta_id))).mappings().first()
        if fila is None:
            return None

        venta = Venta(
            id=fila["id"], numero=fila["numero"], tienda_id=fila["tienda_id"],
            caja_id=fila["caja_id"], sesion_id=fila["sesion_id"],
            cajera_id=fila["cajera_id"], moneda=fila["moneda"],
            dispositivo_id=fila["dispositivo_id"],
        )
        venta.cliente_id = fila["cliente_id"]

        lineas = (await self._s.execute(
            select(T.venta_lineas)
            .where(T.venta_lineas.c.venta_id == venta_id)
            .order_by(T.venta_lineas.c.orden))).mappings().all()
        for f in lineas:
            linea = venta.agregar_linea(
                sku=Sku.parsear(f["sku"]), descripcion=f["descripcion"],
                cantidad=f["cantidad"],
                # Un obsequio se guardó con precio 0; al reconstruir se usa el
                # precio real y se vuelve a marcar, para que el agregado no
                # rechace su propio dato por INV-V7.
                precio_unitario=Dinero(
                    f["precio_unitario"] or f["base_gravable"] or 1, fila["moneda"]),
                tasa_iva=Decimal(f["tasa_iva"]),
            )
            if f["obsequio"]:
                linea.marcar_obsequio(f["autorizado_por"] or "sistema")
            elif f["descuento_tipo"]:
                linea.aplicar_descuento(
                    self._descuento(f, fila["moneda"]), f["autorizado_por"])
            # El número de línea original manda: un comando en vuelo apunta a él.
            linea.numero = f["orden"]

        pagos = (await self._s.execute(
            select(T.venta_pagos)
            .where(T.venta_pagos.c.venta_id == venta_id))).mappings().all()
        for f in pagos:
            venta.registrar_pago(
                f["medio_pago_id"], Dinero(f["monto"], fila["moneda"]),
                es_efectivo=True, referencia=f["referencia"],
            )

        venta.estado = EstadoVenta(fila["estado"])
        venta.estado_fiscal = EstadoFiscal(fila["estado_fiscal"])
        venta.cerrada_en = fila["cerrada_en"]
        venta.anulada_en = fila["anulada_en"]
        venta.motivo_anulacion = fila["motivo_anulacion"]
        return venta

    @staticmethod
    def _descuento(f, moneda: str) -> Descuento:
        motivo = f["descuento_motivo"] or "descuento registrado"
        if f["descuento_tipo"] == "porcentaje":
            return Descuento.porcentaje(Decimal(f["descuento_valor"]), motivo=motivo)
        return Descuento.valor(Dinero(int(f["descuento_monto"]), moneda), motivo=motivo)
