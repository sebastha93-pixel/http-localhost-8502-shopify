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
                    ahora: datetime, base_esperada: Optional[int] = None,
                    base_justificacion: Optional[str] = None) -> dict:
        siguiente = (await self._s.execute(text("""
            SELECT coalesce(max(numero_turno), 0) + 1
              FROM retail.sesiones_caja WHERE caja_id = :c
        """), {"c": caja_id})).scalar()

        try:
            await self._s.execute(text("""
                INSERT INTO retail.sesiones_caja
                    (id, tienda_id, caja_id, numero_turno, estado,
                     base_inicial, abierta_por, abierta_en,
                     base_esperada, base_justificacion)
                VALUES (:id, :t, :c, :n, 'abierta', :base, :u, :ts, :esp, :just)
            """), {"id": sesion_id, "t": tienda_id, "c": caja_id,
                   "n": siguiente, "base": base_inicial, "u": usuario_id,
                   "ts": ahora, "esp": base_esperada,
                   "just": base_justificacion})
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

    # ── Conteo por denominación ─────────────────────────────────────────────

    async def denominaciones(self) -> list:
        """Las que la tienda cuenta hoy, de mayor a menor.

        De mayor a menor porque es el orden en que se cuenta un cajón: los
        billetes grandes salen primero y las monedas al final.
        """
        filas = (await self._s.execute(text("""
            SELECT valor_centavos, tipo FROM retail.denominaciones
             WHERE activa ORDER BY valor_centavos DESC
        """))).mappings().all()
        return [{"valor_centavos": int(f["valor_centavos"]), "tipo": f["tipo"]}
                for f in filas]

    async def guardar_conteo(self, *, sesion_id: str, momento: str,
                             conteo, usuario_id: str) -> None:
        """Deja las piezas contadas, para poder recontar sin la cajera.

        Guardar sólo el total haría irreconstruible el error más común del
        cierre: la fila mal digitada. Con las piezas, quien revisa ve «declaró
        4 de $50.000» y puede ir a mirar si en el cajón había 5.
        """
        if conteo is None or conteo.esta_vacio():
            return
        for valor, cantidad in conteo.lineas():
            await self._s.execute(text("""
                INSERT INTO retail.conteos_denominacion
                    (sesion_id, momento, valor_centavos, cantidad, usuario_id)
                VALUES (:s, :m, :v, :c, :u)
                ON CONFLICT (sesion_id, momento, valor_centavos)
                DO UPDATE SET cantidad = excluded.cantidad,
                              usuario_id = excluded.usuario_id
            """), {"s": sesion_id, "m": momento, "v": valor,
                   "c": cantidad, "u": usuario_id})

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

        # La base contada al abrir se restaura DESPUÉS de construir, no como
        # argumento. INV-C9 se decidió y se firmó en la apertura; volver a
        # evaluarlo aquí ataría un turno ya cerrado al umbral de HOY, y bajar
        # ese umbral dejaría turnos viejos sin poder ni siquiera leerse.
        sesion.base_inicial = Dinero(int(fila["base_inicial"]), moneda)
        if fila["base_esperada"] is not None:
            sesion.base_esperada = Dinero(int(fila["base_esperada"]), moneda)
        sesion.base_justificacion = fila["base_justificacion"]

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

    async def anotar_movimiento(self, *, movimiento_id: str, sesion_id: str,
                                tipo: str, monto: int, motivo: str,
                                usuario_id: str, medio_pago_id: str,
                                autorizado_por, ahora) -> None:
        """Escribe el movimiento que el AGREGADO ya validó.

        El monto llega CON SIGNO: un retiro es negativo. Guardarlo en positivo
        y decidir el signo al sumar dejaría la regla del saldo repartida entre
        la escritura y cada lectura, y basta que una se olvide para que el
        arqueo cuadre mal en una sola dirección.
        """
        await self._s.execute(text("""
            INSERT INTO retail.movimientos_caja
                (id, sesion_id, tipo, medio_pago_id, monto, motivo,
                 usuario_id, autorizado_por, creado_en)
            VALUES (:i, :s, :t, :m, :monto, :motivo, :u, :aut, :ts)
        """), {"i": movimiento_id, "s": sesion_id, "t": tipo,
               "m": medio_pago_id, "monto": monto, "motivo": motivo,
               "u": usuario_id, "aut": autorizado_por, "ts": ahora})

    async def movimientos_manuales(self, sesion_id: str) -> list:
        """Retiros, gastos e ingresos del turno — lo que NO son ventas.

        Van aparte en el cierre: mezclarlos con los cobros haría que el
        desglose por medio de pago no cuadre con lo vendido, y es justo el
        número que la administradora compara contra el informe del día.
        """
        filas = (await self._s.execute(text("""
            SELECT m.id, m.tipo, m.monto, m.motivo, m.creado_en,
                   coalesce(p.nombre, m.usuario_id) AS quien
              FROM retail.movimientos_caja m
              LEFT JOIN retail.permisos_pos p ON p.usuario_id = m.usuario_id
             WHERE m.sesion_id = :i
               AND m.tipo IN ('retiro', 'gasto', 'ingreso')
             ORDER BY m.creado_en
        """), {"i": sesion_id})).mappings().all()
        return [dict(f) for f in filas]

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
