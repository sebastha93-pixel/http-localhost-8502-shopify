"""Repositorio del turno de caja.

INV-C1 —una sola sesion abierta por caja— NO se comprueba aqui con un SELECT
previo: es el indice unico parcial `ux_sesion_abierta` el que lo garantiza.
Comprobarlo en Python dejaria una ventana entre la lectura y el INSERT en la
que dos dispositivos abren turno a la vez, y el arqueo se vuelve imposible.

Por eso `abrir` intenta insertar y traduce el choque del indice a un mensaje
que la cajera entiende, en vez de preguntar antes.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.modules.retail.domain.venta.errores import ReglaDeNegocio

__all__ = ["RepositorioSesionCajaSQL"]


class RepositorioSesionCajaSQL:
    def __init__(self, sesion: AsyncSession) -> None:
        self._s = sesion

    async def medio_efectivo(self) -> str:
        """Cuál medio de pago ES el efectivo.

        Se consulta, no se asume. Estaba escrito 'efectivo' a mano en dos
        sitios: el día que una tienda lo registre como 'caja' o 'cash', la
        base inicial se anotaría contra un medio que no existe y el arqueo
        saldría corto por el valor de la base, todos los días, sin error.
        """
        medio = (await self._s.execute(text("""
            SELECT id FROM retail.medios_pago
             WHERE tipo = 'efectivo' AND activo ORDER BY orden, id LIMIT 1
        """))).scalar()
        if medio is None:
            raise ReglaDeNegocio(
                "No hay ningún medio de pago de tipo efectivo configurado. "
                "Sin eso no se puede arquear la caja."
            )
        return medio

    async def abierta_de(self, caja_id: str) -> Optional[dict]:
        fila = (await self._s.execute(text("""
            SELECT s.id, s.numero_turno, s.abierta_por, s.abierta_en,
                   s.base_inicial, s.tienda_id, s.estado,
                   coalesce(p.nombre, s.abierta_por) AS cajera_nombre
              FROM retail.sesiones_caja s
              LEFT JOIN retail.permisos_pos p ON p.usuario_id = s.abierta_por
             WHERE s.caja_id = :c AND s.estado <> 'cerrada'
        """), {"c": caja_id})).mappings().first()
        return dict(fila) if fila else None

    async def abrir(self, *, sesion_id: str, tienda_id: str, caja_id: str,
                    usuario_id: str, base_inicial: int,
                    ahora: datetime) -> dict:
        siguiente = (await self._s.execute(text("""
            SELECT coalesce(max(numero_turno), 0) + 1
              FROM retail.sesiones_caja WHERE caja_id = :c
        """), {"c": caja_id})).scalar()

        try:
            await self._s.execute(text("""
                INSERT INTO retail.sesiones_caja
                    (id, tienda_id, caja_id, numero_turno, estado,
                     base_inicial, abierta_por, abierta_en)
                VALUES (:id, :t, :c, :n, 'abierta', :base, :u, :ts)
            """), {"id": sesion_id, "t": tienda_id, "c": caja_id,
                   "n": siguiente, "base": base_inicial, "u": usuario_id,
                   "ts": ahora})
        except Exception as e:  # noqa: BLE001
            if "ux_sesion_abierta" in str(e):
                raise ReglaDeNegocio(
                    "Esta caja ya tiene un turno abierto. Ciérralo antes de "
                    "abrir otro, o pide a un supervisor que lo cierre."
                ) from e
            raise

        # La base es plata que YA esta en el cajon: entra al arqueo desde el
        # primer minuto o el cierre saldria sobrado por ese monto.
        await self._s.execute(text("""
            INSERT INTO retail.movimientos_caja
                (id, sesion_id, tipo, medio_pago_id, monto, motivo,
                 usuario_id, creado_en)
            VALUES (:id, :s, 'base_inicial', :medio, :base,
                    'base inicial', :u, :ts)
        """), {"id": (sesion_id[:20] + "BASE000000")[:26], "s": sesion_id,
               "medio": await self.medio_efectivo(),
               "base": base_inicial, "u": usuario_id, "ts": ahora})

        return {"id": sesion_id, "numero_turno": siguiente,
                "base_inicial": base_inicial}

    async def base_de_tienda(self, tienda_id: str) -> int:
        base = (await self._s.execute(text("""
            SELECT base_caja FROM retail.tiendas WHERE id = :t
        """), {"t": tienda_id})).scalar()
        if base is None:
            raise ReglaDeNegocio(f"La tienda {tienda_id!r} no existe.")
        return int(base)

    # ── Reconstruir el agregado ─────────────────────────────────────────────

    async def cargar(self, sesion_id: str):
        """Rehidrata la SesionCaja con sus movimientos.

        Se reconstruye el AGREGADO y no se recalcula el arqueo con SQL a mano:
        las reglas del cierre —el conteo ciego, el umbral, la justificación,
        la firma— ya viven ahí y ya están probadas. Duplicarlas en una consulta
        sería tener dos versiones de la verdad, y la de SQL no tiene pruebas.
        """
        from backend.modules.retail.domain.caja.sesion_caja import SesionCaja
        from backend.modules.retail.domain.caja.estados import (
            EstadoSesion,
            TipoMovimiento,
        )
        from backend.modules.retail.domain.shared.dinero import Dinero

        fila = (await self._s.execute(text("""
            SELECT s.*, t.cierre_ciego, t.umbral_descuadre
              FROM retail.sesiones_caja s
              JOIN retail.tiendas t ON t.id = s.tienda_id
             WHERE s.id = :i
        """), {"i": sesion_id})).mappings().first()
        if fila is None:
            raise ReglaDeNegocio(f"No existe el turno {sesion_id}.")

        moneda = "COP"
        sesion = SesionCaja.abrir(
            id=fila["id"], tienda_id=fila["tienda_id"], caja_id=fila["caja_id"],
            numero_turno=fila["numero_turno"],
            base_inicial=Dinero(0, moneda),   # entra como movimiento, no doble
            abierta_por=fila["abierta_por"], abierta_en=fila["abierta_en"],
            moneda=moneda, cierre_ciego=fila["cierre_ciego"],
            umbral_descuadre=Dinero(int(fila["umbral_descuadre"]), moneda),
            medio_efectivo_id=await self.medio_efectivo(),
        )
        # `abrir` ya anotó una base en cero; se descarta y se cargan las reales.
        sesion.movimientos.clear()
        sesion._siguiente = 1

        movs = (await self._s.execute(text("""
            SELECT m.tipo, m.medio_pago_id, m.monto, m.motivo, m.usuario_id,
                   m.autorizado_por, m.venta_id,
                   coalesce(p.tipo = 'efectivo', true) AS es_efectivo
              FROM retail.movimientos_caja m
              LEFT JOIN retail.medios_pago p ON p.id = m.medio_pago_id
             WHERE m.sesion_id = :i
             ORDER BY m.creado_en, m.id
        """), {"i": sesion_id})).mappings().all()

        for m in movs:
            sesion._anotar(
                TipoMovimiento(m["tipo"]), Dinero(int(m["monto"]), moneda),
                medio_pago_id=m["medio_pago_id"], motivo=m["motivo"],
                usuario_id=m["usuario_id"], es_efectivo=m["es_efectivo"],
                autorizado_por=m["autorizado_por"], venta_id=m["venta_id"],
            )

        sesion.estado = EstadoSesion(fila["estado"])
        return sesion

    async def ventas_en_borrador(self, sesion_id: str) -> int:
        """INV-C2: un carrito abierto es plata sin registrar."""
        return (await self._s.execute(text("""
            SELECT count(*) FROM retail.ventas
             WHERE sesion_id = :i AND estado = 'borrador'
        """), {"i": sesion_id})).scalar() or 0

    async def documentos_pendientes(self, sesion_id: str) -> int:
        return (await self._s.execute(text("""
            SELECT count(*) FROM retail.ventas
             WHERE sesion_id = :i AND estado = 'cerrada'
               AND estado_fiscal IN ('pendiente','enviando','rechazado','fallido')
        """), {"i": sesion_id})).scalar() or 0

    async def resumen(self, sesion_id: str) -> dict:
        """Lo que se imprime al cerrar el día."""
        cab = (await self._s.execute(text("""
            SELECT count(*) FILTER (WHERE estado = 'cerrada')       AS transacciones,
                   coalesce(sum(total) FILTER (WHERE estado='cerrada'), 0) AS brutas,
                   coalesce(sum(descuento_total) FILTER (WHERE estado='cerrada'), 0)
                       AS descuentos,
                   count(*) FILTER (WHERE estado = 'anulada')       AS anuladas,
                   coalesce(sum(total) FILTER (WHERE estado='anulada'), 0) AS anulado
              FROM retail.ventas WHERE sesion_id = :i
        """), {"i": sesion_id})).mappings().one()

        medios = (await self._s.execute(text("""
            SELECT m.medio_pago_id, coalesce(p.nombre, m.medio_pago_id) AS nombre,
                   coalesce(p.tipo = 'efectivo', true)  AS es_efectivo,
                   coalesce(p.entra_al_arqueo, true)    AS entra_al_arqueo,
                   sum(m.monto)::bigint AS total
              FROM retail.movimientos_caja m
              LEFT JOIN retail.medios_pago p ON p.id = m.medio_pago_id
             WHERE m.sesion_id = :i AND m.medio_pago_id IS NOT NULL
             GROUP BY 1, 2, 3, 4
             ORDER BY min(coalesce(p.orden, 0)), 2
        """), {"i": sesion_id})).mappings().all()

        return {"transacciones": int(cab["transacciones"]),
                "ventas_brutas": int(cab["brutas"]),
                "descuentos": int(cab["descuentos"]),
                "anuladas": int(cab["anuladas"]),
                "monto_anulado": int(cab["anulado"]),
                "medios": [dict(m) for m in medios]}

    async def cerrar(self, *, sesion, conteos: dict, usuario_id: str,
                     justificacion, autorizado_por, ahora) -> dict:
        """Persiste el cierre que el AGREGADO ya validó."""
        for medio, declarado in conteos.items():
            await self._s.execute(text("""
                INSERT INTO retail.arqueo_conteos
                    (sesion_id, medio_pago_id, declarado, esperado,
                     declarado_por, declarado_en)
                VALUES (:s, :m, :d, :e, :u, :ts)
                ON CONFLICT (sesion_id, medio_pago_id) DO UPDATE
                    SET declarado = EXCLUDED.declarado,
                        esperado = EXCLUDED.esperado
            """), {"s": sesion.id, "m": medio, "d": declarado.centavos,
                   "e": sesion.esperado_de(medio, autorizado_a_ver=True).centavos,
                   "u": usuario_id, "ts": ahora})

        diferencia = sesion.diferencia_total()
        await self._s.execute(text("""
            UPDATE retail.sesiones_caja
               SET estado = 'cerrada', cerrada_por = :u, cerrada_en = :ts,
                   diferencia_total = :dif, justificacion = :just,
                   autorizada_por = :aut
             WHERE id = :i
        """), {"i": sesion.id, "u": usuario_id, "ts": ahora,
               "dif": diferencia.centavos, "just": justificacion,
               "aut": autorizado_por})
        return {"diferencia_centavos": diferencia.centavos}
