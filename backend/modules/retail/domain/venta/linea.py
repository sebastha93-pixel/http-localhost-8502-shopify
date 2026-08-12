"""LineaVenta — una prenda dentro de una venta.

Los datos del producto se **congelan** al agregar la línea: descripción, precio
y tarifa de IVA. Si mañana cambia el catálogo, esta línea no cambia. Es lo que
hace que una factura de ayer siga diciendo lo que decía (INV-F5).

EL PRECIO ES EL DE VITRINA, con IVA incluido. El impuesto se DERIVA del
total, no al revés.

Lo tuve al revés y costó encontrarlo. Guardando la base sin IVA, la rejilla
mostraba «$139.900,01» en una prenda de $139.900 — y resultó que ninguna base
da ese total exacto: con IVA del 19% el importe salta de 13.989.999 a
13.990.001. Uno de cada seis precios redondos es inalcanzable así.

Con este modelo eso no puede pasar: el total sale de multiplicar el precio de
la etiqueta, que es exacto por definición, y la base es una LECTURA de ese
total (`separar_iva`). Es lo que hace el comercio colombiano y lo que decía el
handoff desde el principio: «IVA incluido, calculado como total − total/1,19».
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from backend.modules.retail.domain.shared.dinero import Dinero
from backend.modules.retail.domain.shared.impuestos import separar_iva
from backend.modules.retail.domain.shared.sku import Sku
from backend.modules.retail.domain.venta.descuento import Descuento
from backend.modules.retail.domain.venta.errores import ReglaDeNegocio

__all__ = ["LineaVenta"]


class LineaVenta:
    """Entidad hija del agregado Venta. Sólo la Venta la construye y la muta."""

    def __init__(
        self,
        *,
        numero: int,
        sku: Sku,
        descripcion: str,
        cantidad: int,
        precio_unitario: Dinero,
        tasa_iva: Decimal,
    ) -> None:
        self.numero = numero
        self.sku = sku
        self.descripcion = descripcion
        self.cantidad = self._cantidad_valida(cantidad)
        self.precio_unitario = precio_unitario
        self.tasa_iva = tasa_iva
        self.descuento: Optional[Descuento] = None
        self.autorizado_por: Optional[str] = None
        self.obsequio: bool = False

        if isinstance(tasa_iva, float):
            raise TypeError("la tasa de IVA no se expresa en float")
        if tasa_iva < 0 or tasa_iva > 100:
            raise ReglaDeNegocio(f"tarifa de IVA fuera de rango: {tasa_iva}")
        # INV-V7: el precio en cero es la forma clásica de sacar mercancía. Se
        # permite sólo marcando la línea como obsequio, que exige autorización.
        if not precio_unitario.es_positivo():
            raise ReglaDeNegocio(
                f"«{descripcion}» no puede ir en {precio_unitario.formateado()}. "
                f"Para regalarla, márcala como obsequio: necesita autorización."
            )

    @staticmethod
    def _cantidad_valida(cantidad: int) -> int:
        if isinstance(cantidad, bool) or not isinstance(cantidad, int):
            raise ReglaDeNegocio("la cantidad debe ser un número entero de unidades")
        if cantidad <= 0:
            raise ReglaDeNegocio(f"la cantidad debe ser mayor que cero, no {cantidad}")
        return cantidad

    # ── Mutación (sólo desde el agregado) ───────────────────────────────────

    def cambiar_cantidad(self, cantidad: int) -> None:
        self.cantidad = self._cantidad_valida(cantidad)

    def aplicar_descuento(self, descuento: Descuento, autorizado_por: Optional[str]) -> None:
        # Valida de una vez que el descuento cabe en la línea; si no, revienta
        # aquí y no al calcular el total con la clienta esperando.
        descuento.calcular_sobre(self.subtotal())
        self.descuento = descuento
        if autorizado_por:
            self.autorizado_por = autorizado_por

    def quitar_descuento(self) -> None:
        self.descuento = None

    def marcar_obsequio(self, autorizado_por: str) -> None:
        self.obsequio = True
        self.autorizado_por = autorizado_por

    # ── Cálculo ─────────────────────────────────────────────────────────────

    def subtotal(self) -> Dinero:
        """Precio de vitrina × cantidad. CON IVA, sin descuento.

        Exacto por construcción: multiplicar un número redondo por un entero
        no puede producir un centavo fantasma.
        """
        return self.precio_unitario * self.cantidad

    def descuento_monto(self) -> Dinero:
        if self.obsequio:
            return self.subtotal()
        if self.descuento is None:
            return Dinero.cero(self.precio_unitario.moneda)
        return self.descuento.calcular_sobre(self.subtotal())

    def total(self) -> Dinero:
        """Lo que se cobra por esta línea. El número que manda.

        Todo lo demás —base e IVA— se lee DE AQUÍ, no al contrario.
        """
        return self.subtotal() - self.descuento_monto()

    def base_gravable(self) -> Dinero:
        """La parte del total que no es impuesto."""
        base, _ = separar_iva(self.total().centavos, self.tasa_iva)
        return Dinero(base, self.precio_unitario.moneda)

    def iva(self) -> Dinero:
        """INV-V12: el IVA se lee de ESTA línea.

        Derivarlo del total de la venta daría otro número en cuanto haya dos
        tarifas distintas, y ese error no revienta: sale en la factura.
        """
        _, iva = separar_iva(self.total().centavos, self.tasa_iva)
        return Dinero(iva, self.precio_unitario.moneda)

    def precio_unitario_con_iva(self) -> Dinero:
        """El precio de vitrina. YA es el precio unitario: se conserva el
        nombre para no romper a quien lo llame."""
        return self.precio_unitario

    def __repr__(self) -> str:
        return (f"LineaVenta(#{self.numero} {self.sku.codigo} ×{self.cantidad} "
                f"= {self.total().formateado()})")
