"""ConteoDenominacion — la plata contada, no tecleada.

POR QUÉ EXISTE ESTE OBJETO. El cierre ya es ciego (INV-C4): la cajera no ve lo
esperado hasta que declara. Pero **declarar era escribir un número**, y quien
lleva el día en la cabeza puede escribir una cifra plausible sin abrir el
cajón. El conteo ciego más débil que existe es el que se responde de memoria.

Contar por denominación cambia cuál es el dato de entrada: la cajera mete
CANTIDADES —seis de cincuenta, cuatro de veinte— y el total lo saca el sistema.
El total deja de ser algo que se pueda escribir.

Sólo aplica al EFECTIVO. Un datáfono no tiene denominaciones y su cifra se lee
del cierre del terminal, que ya es un conteo de otra cosa.

La suma vive aquí y no en el router por la regla del módulo: la aritmética de
dinero se hace con `Dinero`, en centavos enteros, en el dominio.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Mapping, Tuple

from backend.modules.retail.domain.shared.dinero import Dinero
from backend.modules.retail.domain.venta.errores import ReglaDeNegocio

__all__ = ["ConteoDenominacion"]


class ConteoDenominacion:
    """Cuántos billetes y monedas de cada valor hay en el cajón."""

    __slots__ = ("_piezas", "_moneda")

    def __init__(self, piezas: Mapping[int, int], *, moneda: str) -> None:
        limpio: Dict[int, int] = {}
        for valor, cantidad in piezas.items():
            if not isinstance(cantidad, int) or isinstance(cantidad, bool):
                raise ReglaDeNegocio(
                    f"la cantidad de la denominación {valor} no es un entero")
            if cantidad < 0:
                raise ReglaDeNegocio(
                    "no se puede contar una cantidad negativa de billetes")
            if valor <= 0:
                raise ReglaDeNegocio(f"denominación inválida: {valor}")
            # Una denominación en cero es información: dice que se miró y no
            # había. Se conserva; lo que no se guarda es lo que nunca se contó.
            limpio[int(valor)] = cantidad
        self._piezas = limpio
        self._moneda = moneda

    @classmethod
    def vacio(cls, moneda: str) -> "ConteoDenominacion":
        return cls({}, moneda=moneda)

    @property
    def moneda(self) -> str:
        return self._moneda

    def total(self) -> Dinero:
        """Lo que hay en el cajón. Es lo ÚNICO que la cajera no escribe."""
        total = Dinero.cero(self._moneda)
        for valor, cantidad in self._piezas.items():
            total = total + Dinero(valor, self._moneda) * cantidad
        return total

    def piezas(self) -> Dict[int, int]:
        return dict(self._piezas)

    def lineas(self) -> List[Tuple[int, int]]:
        """De mayor a menor, que es el orden en que se cuenta un cajón."""
        return sorted(self._piezas.items(), key=lambda p: -p[0])

    def esta_vacio(self) -> bool:
        return not self._piezas

    def solo_denominaciones(self, permitidas: Iterable[int]) -> None:
        """Que no entre un valor que la tienda no tiene configurado.

        Sin esto, un cliente con un catálogo viejo —una tableta que no se ha
        actualizado— podría declarar 40 monedas de $50 después de que la tienda
        las dio de baja, y el total cuadraría contra un billete que ya nadie
        recibe.
        """
        sobra = sorted(set(self._piezas) - set(permitidas))
        if sobra:
            raise ReglaDeNegocio(
                "El equipo declaró denominaciones que la tienda no tiene "
                f"activas: {', '.join(str(v) for v in sobra)}. "
                "Actualiza la pantalla y vuelve a contar."
            )

    def __eq__(self, otro: object) -> bool:
        if not isinstance(otro, ConteoDenominacion):
            return NotImplemented
        return self._piezas == otro._piezas and self._moneda == otro._moneda

    def __repr__(self) -> str:
        return (f"ConteoDenominacion({len(self._piezas)} valores · "
                f"{self.total().formateado()})")
