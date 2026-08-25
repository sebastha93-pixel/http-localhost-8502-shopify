"""SaldoUbicacion — el inventario como libro contable.

`stock = stock - 1` no se puede auditar. Una suma de asientos sí. Por eso cada
movimiento genera un `MovimientoInventario` inmutable, y el saldo materializado
siempre debe poder reconstruirse sumando el libro (INV-I4). Un job diario lo
verifica: si no cuadra, alguien tocó la tabla por fuera de la aplicación.

DOS DECISIONES QUE SE NOTAN EN LA TIENDA.

**La reserva es atómica y se hace antes de vender** (INV-I1). En la base es una
sola sentencia `UPDATE ... WHERE cantidad - reservado >= n`: sin `SELECT`
previo, sin ventana de carrera. Aquí en el dominio es el mismo contrato.

**Sin internet se permite el negativo** (INV-I2). La prenda física ya está en
la mano de la clienta; bloquear la venta pierde plata real para proteger un
dato que de todos modos está desactualizado. El sobregiro se marca, se alerta,
y se corrige en el conteo.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Iterable, List, Optional

from backend.modules.retail.domain.inventario.errores import SinStock
from backend.modules.retail.domain.inventario.motivo import Motivo
from backend.modules.retail.domain.venta.errores import ReglaDeNegocio

__all__ = ["SaldoUbicacion", "MovimientoInventario", "Reserva"]


@dataclass(frozen=True)
class MovimientoInventario:
    """Un asiento. INV-I5: inmutable. Corregir es un movimiento contrario."""

    ubicacion_id: str
    variante_id: str
    delta: int
    saldo_despues: int
    motivo: Motivo
    referencia_tipo: str
    referencia_id: str
    usuario_id: str
    creado_en: datetime
    detalle: str = ""


@dataclass
class Reserva:
    """Unidades apartadas para un carrito abierto. No es un asiento todavía."""

    id: str
    cantidad: int
    referencia: str
    creada_en: datetime
    sobregiro: bool = False
    confirmada: bool = False


class SaldoUbicacion:
    """Agregado raíz: el stock de UNA variante en UNA ubicación."""

    def __init__(self, *, ubicacion_id: str, variante_id: str,
                 cantidad: int, stock_minimo: int = 0) -> None:
        self.ubicacion_id = ubicacion_id
        self.variante_id = variante_id
        self.cantidad = cantidad
        self.stock_minimo = stock_minimo
        self._reservas: Dict[str, Reserva] = {}
        self._secuencia = 0

    # ── Lectura ─────────────────────────────────────────────────────────────

    def reservado(self) -> int:
        return sum(r.cantidad for r in self._reservas.values() if not r.confirmada)

    def disponible(self) -> int:
        return self.cantidad - self.reservado()

    def bajo_minimo(self) -> bool:
        return self.cantidad <= self.stock_minimo

    # ── Reservas ────────────────────────────────────────────────────────────

    def reservar(self, cantidad: int, *, referencia: str, ahora: datetime,
                 permitir_negativo: bool = False) -> Reserva:
        """Aparta unidades para un carrito. No mueve el saldo todavía.

        `permitir_negativo` es el modo sin internet (INV-I2). No es un atajo:
        es la decisión de que la prenda física manda sobre el dato.
        """
        self._cantidad_positiva(cantidad)
        if not (referencia or "").strip():
            raise ReglaDeNegocio("una reserva sin referencia no se puede rastrear")

        sobregiro = cantidad > self.disponible()
        if sobregiro and not permitir_negativo:
            raise SinStock(
                f"Sólo quedan {self.disponible()} unidad(es) disponibles de esta "
                f"talla en este punto, y se pidieron {cantidad}."
            )

        self._secuencia += 1
        reserva = Reserva(
            id=f"{referencia}#{self._secuencia}",
            cantidad=cantidad,
            referencia=referencia.strip(),
            creada_en=ahora,
            sobregiro=sobregiro,
        )
        self._reservas[reserva.id] = reserva
        return reserva

    def liberar(self, reserva_id: str) -> None:
        reserva = self._reserva_viva(reserva_id)
        del self._reservas[reserva.id]

    def purgar_reservas_vencidas(self, *, ahora: datetime,
                                 ttl_minutos: int = 15) -> List[Reserva]:
        """INV-I6. Sin esto, el stock se evapora en carritos muertos."""
        limite = ttl_minutos * 60
        vencidas = [
            r for r in self._reservas.values()
            if not r.confirmada and (ahora - r.creada_en).total_seconds() > limite
        ]
        for r in vencidas:
            del self._reservas[r.id]
        return vencidas

    def confirmar(self, reserva_id: str, *, usuario_id: str,
                  ahora: datetime) -> MovimientoInventario:
        """La venta se cerró: la reserva se vuelve un asiento de salida.

        Se niega a confirmar dos veces. Reintentar el cierre de una venta no
        puede descargar el stock dos veces (el outbox reintenta por diseño).
        """
        reserva = self._reserva_viva(reserva_id)
        reserva.confirmada = True
        del self._reservas[reserva.id]
        return self._asentar(
            delta=-reserva.cantidad,
            motivo=Motivo.VENTA,
            referencia_tipo="venta",
            referencia_id=reserva.referencia,
            usuario_id=usuario_id,
            ahora=ahora,
        )

    def _reserva_viva(self, reserva_id: str) -> Reserva:
        reserva = self._reservas.get(reserva_id)
        if reserva is None or reserva.confirmada:
            raise ReglaDeNegocio(f"la reserva {reserva_id!r} ya no existe")
        return reserva

    # ── Asientos directos ───────────────────────────────────────────────────

    def ingresar(self, cantidad: int, *, motivo: Motivo, referencia: str,
                 usuario_id: str, ahora: datetime) -> MovimientoInventario:
        self._cantidad_positiva(cantidad)
        return self._asentar(delta=cantidad, motivo=motivo,
                             referencia_tipo=motivo.value, referencia_id=referencia,
                             usuario_id=usuario_id, ahora=ahora)

    def descargar(self, cantidad: int, *, motivo: Motivo, referencia: str,
                  usuario_id: str, ahora: datetime) -> MovimientoInventario:
        self._cantidad_positiva(cantidad)
        return self._asentar(delta=-cantidad, motivo=motivo,
                             referencia_tipo=motivo.value, referencia_id=referencia,
                             usuario_id=usuario_id, ahora=ahora)

    def ajustar(self, nueva_cantidad: int, *, motivo_texto: str,
                usuario_id: str, ahora: datetime) -> Optional[MovimientoInventario]:
        """Conteo físico. Devuelve None si el conteo confirma el saldo.

        Un conteo que da lo mismo no es un movimiento: anotarlo llenaría el
        libro de asientos en cero y escondería los que sí importan.
        """
        if not (motivo_texto or "").strip():
            raise ReglaDeNegocio(
                "un ajuste de inventario necesita explicar de dónde sale"
            )
        delta = nueva_cantidad - self.cantidad
        if delta == 0:
            return None
        return self._asentar(
            delta=delta, motivo=Motivo.AJUSTE_CONTEO,
            referencia_tipo="ajuste", referencia_id=f"{usuario_id}@{ahora.isoformat()}",
            usuario_id=usuario_id, ahora=ahora, detalle=motivo_texto.strip(),
        )

    def _asentar(self, *, delta: int, motivo: Motivo, referencia_tipo: str,
                 referencia_id: str, usuario_id: str, ahora: datetime,
                 detalle: str = "") -> MovimientoInventario:
        # INV-I3: un asiento sin origen no se puede auditar.
        if not (referencia_id or "").strip():
            raise ReglaDeNegocio(
                f"el movimiento de inventario ({motivo.value}) necesita una "
                f"referencia que permita rastrearlo"
            )
        self.cantidad += delta
        return MovimientoInventario(
            ubicacion_id=self.ubicacion_id,
            variante_id=self.variante_id,
            delta=delta,
            saldo_despues=self.cantidad,
            motivo=motivo,
            referencia_tipo=referencia_tipo,
            referencia_id=referencia_id.strip(),
            usuario_id=usuario_id,
            creado_en=ahora,
            detalle=detalle,
        )

    @staticmethod
    def _cantidad_positiva(cantidad: int) -> None:
        if isinstance(cantidad, bool) or not isinstance(cantidad, int):
            raise ReglaDeNegocio("la cantidad debe ser un entero de unidades")
        if cantidad <= 0:
            raise ReglaDeNegocio(f"la cantidad debe ser mayor que cero, no {cantidad}")

    # ── INV-I4: el saldo es la suma del libro ───────────────────────────────

    @staticmethod
    def saldo_segun_libro(movimientos: Iterable[MovimientoInventario]) -> int:
        return sum(m.delta for m in movimientos)

    def cuadra_con_el_libro(
        self, movimientos: Iterable[MovimientoInventario]
    ) -> bool:
        """Lo que corre el job diario. Si da False, el saldo está corrupto."""
        return self.cantidad == self.saldo_segun_libro(movimientos)

    def __repr__(self) -> str:
        return (f"SaldoUbicacion({self.ubicacion_id} {self.variante_id} "
                f"cant={self.cantidad} disp={self.disponible()})")
