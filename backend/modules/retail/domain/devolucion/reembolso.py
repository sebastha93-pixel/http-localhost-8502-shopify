"""Cómo se le devuelve la plata a la clienta.

LO QUE ESTE ENUM DECIDE DE VERDAD es si el cajón se abre o no, y eso no es un
detalle de pantalla: el efectivo que sale tiene que aparecer en el arqueo del
turno que lo entregó, o el cierre de esa cajera no cuadra y la diferencia se
la queda ella encima.

  · `efectivo`         → sale plata del cajón. Exige turno abierto y deja un
                         movimiento de caja en contra.
  · `metodo_original`  → vuelve por donde vino (datáfono, transferencia). El
                         cajón no se toca; lo reversa el adquirente.
  · `credito_tienda`   → no sale plata: queda un saldo a favor. Postventa ya
                         sabe manejarlo (`/casos/{id}/saldo-a-favor`).

Los dos últimos NO piden turno abierto a propósito. Pedirlo dejaría a una
clienta esperando en el mostrador a que alguien abra una caja para un trámite
que no toca ninguna caja.
"""
from __future__ import annotations

from enum import Enum

__all__ = ["Reembolso"]


class Reembolso(Enum):
    EFECTIVO = "efectivo"
    METODO_ORIGINAL = "metodo_original"
    CREDITO_TIENDA = "credito_tienda"

    @property
    def sale_del_cajon(self) -> bool:
        """Si este método mueve el arqueo del turno en curso."""
        return self is Reembolso.EFECTIVO
