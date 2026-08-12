"""SesionCaja — el turno, y lo que hace que el arqueo mida algo.

DOS REGLAS GOBIERNAN ESTE ARCHIVO.

**El cierre ciego (INV-C4).** La cajera no ve cuánto debería haber hasta que
declara lo que contó. Si lo ve, escribe lo que ve, y el descuadre desaparece
de los informes sin desaparecer de la realidad. Es configurable por tienda
—hay operaciones donde estorba— pero el valor por defecto es ciego.

**La venta que llega tarde (INV-C8).** Una venta hecha sin internet puede
sincronizar después de que su turno cerró. Rechazarla sería perder una venta
real que ya ocurrió y ya se cobró; aceptarla en silencio descuadraría un
cierre ya firmado. Se acepta por una puerta distinta, se marca y se reporta.
Es el caso que rompe los POS que no lo modelaron.

INV-C1 (una sola sesión abierta por caja) no vive aquí: es un índice único
parcial en la base (`ux_sesion_abierta`). Una regla comprobada en Python tiene
una ventana de carrera; el índice no.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Dict, List, Optional

from backend.modules.retail.domain.caja.errores import ArqueoCiego, SesionYaCerrada
from backend.modules.retail.domain.caja.estados import EstadoSesion, TipoMovimiento
from backend.modules.retail.domain.caja.eventos import (
    SesionCajaCerrada,
    VentaDesfasada,
)
from backend.modules.retail.domain.caja.movimiento import MovimientoCaja
from backend.modules.retail.domain.shared.dinero import Dinero
from backend.modules.retail.domain.venta.errores import (
    ReglaDeNegocio,
    RequiereAutorizacion,
)

__all__ = ["SesionCaja"]

_ULID = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


class SesionCaja:
    """Agregado raíz del turno de caja."""

    def __init__(
        self,
        *,
        id: str,
        tienda_id: str,
        caja_id: str,
        numero_turno: int,
        base_inicial: Dinero,
        abierta_por: str,
        abierta_en: datetime,
        moneda: str,
        cierre_ciego: bool = True,
        umbral_descuadre: Optional[Dinero] = None,
        dispositivo_id: Optional[str] = None,
        medio_efectivo_id: str = "efectivo",
    ) -> None:
        if not isinstance(id, str) or not _ULID.match(id.strip().upper()):
            raise ReglaDeNegocio(f"el identificador del turno no es un ULID: {id!r}")
        if base_inicial.es_negativo():
            raise ReglaDeNegocio(
                f"la base inicial no puede ser negativa: {base_inicial.formateado()}"
            )

        self.id = id.strip().upper()
        self.tienda_id = tienda_id
        self.caja_id = caja_id
        self.numero_turno = numero_turno
        self.base_inicial = base_inicial
        self.abierta_por = abierta_por
        self.abierta_en = abierta_en
        self.moneda = moneda
        self.cierre_ciego = cierre_ciego
        self.umbral_descuadre = umbral_descuadre or Dinero.cero(moneda)
        self.dispositivo_id = dispositivo_id
        # Cuál medio de pago ES el efectivo. Se recibe, no se adivina: la base,
        # los retiros y los gastos son plata física y tienen que sumar ahí.
        # Deducirlo mirando los cobros hacía que un medio sin movimientos
        # todavía se llevara la base entera.
        self.medio_efectivo_id = medio_efectivo_id

        self.estado = EstadoSesion.ABIERTA
        self.movimientos: List[MovimientoCaja] = []
        self.cerrada_por: Optional[str] = None
        self.cerrada_en: Optional[datetime] = None
        self.justificacion: Optional[str] = None
        self.autorizada_por: Optional[str] = None

        # Conteo declarado y esperado CONGELADO en el momento de declarar.
        self._declarado: Dict[str, Dinero] = {}
        self._esperado_congelado: Dict[str, Dinero] = {}
        self._desfasadas: List[VentaDesfasada] = []

        self._siguiente = 1
        self._anotar(TipoMovimiento.BASE_INICIAL, base_inicial,
                     medio_pago_id=self.medio_efectivo_id,
                     motivo="base inicial", usuario_id=abierta_por, es_efectivo=True)

    @classmethod
    def abrir(cls, **kw) -> "SesionCaja":
        return cls(**kw)

    # ── Guardas ─────────────────────────────────────────────────────────────

    def _exigir_abierta_o_en_arqueo(self) -> None:
        if not self.estado.es_mutable():
            raise SesionYaCerrada(
                f"El turno #{self.numero_turno} ya se cerró y se firmó. "
                f"No se puede modificar."
            )

    def _cero(self) -> Dinero:
        return Dinero.cero(self.moneda)

    def _anotar(self, tipo, monto, *, medio_pago_id, motivo, usuario_id,
                es_efectivo, autorizado_por=None, venta_id=None) -> MovimientoCaja:
        mov = MovimientoCaja(
            numero=self._siguiente, tipo=tipo, monto=monto,
            medio_pago_id=medio_pago_id, motivo=motivo, usuario_id=usuario_id,
            es_efectivo=es_efectivo, autorizado_por=autorizado_por,
            venta_id=venta_id,
        )
        self.movimientos.append(mov)
        self._siguiente += 1
        return mov

    # ── Cobros ──────────────────────────────────────────────────────────────

    def registrar_cobro(self, *, medio_pago_id: str, monto: Dinero,
                        es_efectivo: bool, venta_id: str) -> None:
        self._exigir_abierta_o_en_arqueo()
        _ = self._cero() + monto
        self._anotar(TipoMovimiento.VENTA, monto, medio_pago_id=medio_pago_id,
                     motivo="venta", usuario_id=self.abierta_por,
                     es_efectivo=es_efectivo, venta_id=venta_id)

    def registrar_anulacion(self, *, medio_pago_id: str, monto: Dinero,
                            es_efectivo: bool, venta_id: str) -> None:
        self._exigir_abierta_o_en_arqueo()
        self._anotar(TipoMovimiento.ANULACION, -monto, medio_pago_id=medio_pago_id,
                     motivo="anulación", usuario_id=self.abierta_por,
                     es_efectivo=es_efectivo, venta_id=venta_id)

    # ── Movimientos de efectivo ─────────────────────────────────────────────

    def registrar_retiro(self, monto: Dinero, *, motivo: str, usuario_id: str,
                         autorizado_por: Optional[str]) -> None:
        """Sangría. INV-C6: no puede dejar el efectivo en negativo."""
        self._movimiento_manual(TipoMovimiento.RETIRO, -monto, motivo=motivo,
                                usuario_id=usuario_id,
                                autorizado_por=autorizado_por, exige_firma=True)

    def registrar_gasto(self, monto: Dinero, *, motivo: str, usuario_id: str,
                        autorizado_por: Optional[str]) -> None:
        self._movimiento_manual(TipoMovimiento.GASTO, -monto, motivo=motivo,
                                usuario_id=usuario_id,
                                autorizado_por=autorizado_por, exige_firma=True)

    def registrar_ingreso(self, monto: Dinero, *, motivo: str,
                          usuario_id: str) -> None:
        self._movimiento_manual(TipoMovimiento.INGRESO, monto, motivo=motivo,
                                usuario_id=usuario_id, autorizado_por=None,
                                exige_firma=False)

    def _movimiento_manual(self, tipo, monto_con_signo: Dinero, *, motivo: str,
                           usuario_id: str, autorizado_por: Optional[str],
                           exige_firma: bool) -> None:
        self._exigir_abierta_o_en_arqueo()
        if not (motivo or "").strip():
            raise ReglaDeNegocio(f"un {tipo.value} de caja necesita motivo escrito")
        if exige_firma and not autorizado_por:
            raise RequiereAutorizacion(
                f"Sacar plata de la caja necesita autorización de un supervisor."
            )
        if monto_con_signo.es_cero():
            raise ReglaDeNegocio("el movimiento de caja no puede ser de cero")

        # INV-C6: se evalúa ANTES de anotar, para no dejar el libro en negativo.
        if monto_con_signo.es_negativo():
            disponible = self._esperado_efectivo_actual()
            if (disponible + monto_con_signo).es_negativo():
                raise ReglaDeNegocio(
                    f"En la caja no hay {(-monto_con_signo).formateado()}: "
                    f"el efectivo esperado es {disponible.formateado()}."
                )

        self._anotar(tipo, monto_con_signo, medio_pago_id=self.medio_efectivo_id,
                     motivo=motivo.strip(),
                     usuario_id=usuario_id, es_efectivo=True,
                     autorizado_por=autorizado_por)

    # ── Esperado ────────────────────────────────────────────────────────────

    def _calcular(self, medio_pago_id: str) -> Dinero:
        """El esperado VIVO de un medio, sin mirar lo congelado."""
        return sum((m.monto for m in self.movimientos
                    if m.medio_pago_id == medio_pago_id), self._cero())

    def _esperado_efectivo_actual(self) -> Dinero:
        return self._calcular(self.medio_efectivo_id)

    def _esperado_actual_de(self, medio_pago_id: str) -> Dinero:
        """El esperado que vale para el arqueo.

        Si ya se declaró el conteo de ese medio, devuelve el valor CONGELADO en
        ese momento: una venta offline que entre después no puede cambiar una
        diferencia que la cajera ya firmó.
        """
        if medio_pago_id in self._esperado_congelado:
            return self._esperado_congelado[medio_pago_id]
        return self._calcular(medio_pago_id)

    def esperado_de(self, medio_pago_id: str, *,
                    autorizado_a_ver: bool = False) -> Dinero:
        """Cuánto debería haber de ese medio.

        En cierre ciego se niega a responder hasta que el conteo esté declarado
        (INV-C4). No es un fallo: es la regla funcionando.
        """
        if not self._puede_revelar(medio_pago_id, autorizado_a_ver):
            raise ArqueoCiego(
                "El sistema no muestra lo esperado hasta que declares el conteo. "
                "Así el arqueo mide algo real."
            )
        return self._esperado_actual_de(medio_pago_id)

    def _puede_revelar(self, medio_pago_id: str, autorizado_a_ver: bool) -> bool:
        if not self.cierre_ciego or autorizado_a_ver:
            return True
        if self.estado is EstadoSesion.CERRADA:
            return True
        return medio_pago_id in self._declarado

    def medios_movidos(self) -> List[str]:
        """Los medios que hay que declarar en el arqueo, en orden de aparición.

        El efectivo entra siempre, aunque no se haya vendido nada: la base
        está ahí y hay que contarla.
        """
        vistos: List[str] = [self.medio_efectivo_id]
        for m in self.movimientos:
            if m.medio_pago_id and m.medio_pago_id not in vistos:
                vistos.append(m.medio_pago_id)
        return vistos

    # ── Arqueo ──────────────────────────────────────────────────────────────

    def iniciar_arqueo(self, *, ventas_en_borrador: int,
                       documentos_fiscales_pendientes: int = 0,
                       confirmado: bool = False) -> None:
        self._exigir_abierta_o_en_arqueo()
        # INV-C2: un carrito abierto es plata sin registrar.
        if ventas_en_borrador:
            raise ReglaDeNegocio(
                f"Hay {ventas_en_borrador} venta(s) en borrador sin cerrar. "
                f"Termínalas o descártalas antes de arquear."
            )
        # INV-C3: avisa, no bloquea. Bloquear por algo que depende de Siigo
        # dejaría a la tienda sin poder cerrar por una caída ajena.
        if documentos_fiscales_pendientes and not confirmado:
            raise ReglaDeNegocio(
                f"Quedan {documentos_fiscales_pendientes} documento(s) fiscal(es) "
                f"por emitir. Puedes cerrar igual, pero confírmalo: la venta ya "
                f"está en el arqueo y la factura sale cuando vuelva Siigo."
            )
        self.estado = EstadoSesion.EN_ARQUEO

    def declarar_conteo(self, medio_pago_id: str, monto: Dinero, *,
                        usuario_id: str) -> None:
        """Congela el esperado de ese medio en el momento de declarar.

        Si se recalculara al leer, una venta offline que entre después
        cambiaría la diferencia que la cajera ya firmó.
        """
        self._exigir_abierta_o_en_arqueo()
        if self.estado is not EstadoSesion.EN_ARQUEO:
            raise ReglaDeNegocio("Primero hay que iniciar el arqueo.")
        if monto.es_negativo():
            raise ReglaDeNegocio("el conteo no puede ser negativo")
        self._esperado_congelado[medio_pago_id] = self._esperado_actual_de(medio_pago_id)
        self._declarado[medio_pago_id] = monto

    def diferencia_por_medio(self) -> Dict[str, Dinero]:
        return {
            medio: declarado - self._esperado_actual_de(medio)
            for medio, declarado in self._declarado.items()
        }

    def diferencia_total(self) -> Dinero:
        return sum(self.diferencia_por_medio().values(), self._cero())

    # ── Cierre ──────────────────────────────────────────────────────────────

    def cerrar(self, *, usuario_id: str, ahora: datetime,
               justificacion: Optional[str] = None,
               puede_cerrar_con_descuadre: bool = False) -> SesionCajaCerrada:
        """Cierra el turno.

        LA FIRMA ES DE QUIEN CIERRA. Antes, un descuadre grande pedía el PIN de
        un supervisor y quedaban dos nombres: quien contó y quien aprobó. El
        PIN se quitó por decisión del negocio —una sola credencial, correo y
        contraseña—, así que el permiso lo trae el usuario que tiene la sesión
        abierta: o puede cerrar con descuadre, o no puede.

        La justificación escrita SE QUEDA. Es lo que convierte un faltante en
        algo revisable; sin ella el descuadre es un número sin historia.
        """
        self._exigir_abierta_o_en_arqueo()
        if self.estado is not EstadoSesion.EN_ARQUEO:
            raise ReglaDeNegocio("Primero hay que arquear la caja.")

        faltan = [m for m in self.medios_movidos() if m not in self._declarado]
        if faltan:
            raise ReglaDeNegocio(
                f"Falta declarar el conteo de: {', '.join(faltan)}."
            )

        diferencia = self.diferencia_total()
        # INV-C5. El sobrante también cuenta: es plata sin venta que la explique.
        excede = self._excede_umbral(diferencia)
        if excede:
            if not (justificacion or "").strip():
                raise ReglaDeNegocio(
                    f"La diferencia de {diferencia.formateado()} supera el umbral "
                    f"de {self.umbral_descuadre.formateado()}. "
                    f"Escribe la justificación."
                )
            if not puede_cerrar_con_descuadre:
                raise RequiereAutorizacion(
                    "Cerrar con una diferencia de este tamaño necesita un "
                    "usuario con permiso para hacerlo. Pide que entre un "
                    "supervisor con su correo y contraseña."
                )

        self.estado = EstadoSesion.CERRADA
        self.cerrada_por = usuario_id
        self.cerrada_en = ahora
        self.justificacion = (justificacion or "").strip() or None
        # Quien cierra ES quien firma: no hay un segundo nombre que registrar.
        self.autorizada_por = usuario_id if excede else None

        return SesionCajaCerrada(
            ocurrido_en=ahora,
            sesion_id=self.id,
            tienda_id=self.tienda_id,
            caja_id=self.caja_id,
            numero_turno=self.numero_turno,
            cerrada_por=usuario_id,
            diferencia=diferencia,
            diferencia_por_medio=dict(self.diferencia_por_medio()),
            cuadro=diferencia.es_cero(),
            justificacion=self.justificacion,
            autorizado_por=self.autorizada_por,
        )

    def _excede_umbral(self, diferencia: Dinero) -> bool:
        if diferencia.es_cero():
            return False
        magnitud = -diferencia if diferencia.es_negativo() else diferencia
        return magnitud > self.umbral_descuadre

    # ── INV-C8: la venta que llega tarde ────────────────────────────────────

    def registrar_venta_desfasada(self, *, venta_id: str, medio_pago_id: str,
                                  monto: Dinero, es_efectivo: bool,
                                  ocurrido_en: datetime) -> VentaDesfasada:
        """Una venta offline que sincronizó después de que el turno cerró.

        NO entra al arqueo: ese cierre ya está firmado y su diferencia tiene
        que seguir siendo reproducible. Queda registrada aparte y se reporta al
        supervisor, que decide qué hacer con la plata.

        Rechazarla sería perder una venta real, ya cobrada, que existe.
        """
        desfase = VentaDesfasada(
            ocurrido_en=ocurrido_en,
            sesion_id=self.id,
            tienda_id=self.tienda_id,
            caja_id=self.caja_id,
            venta_id=venta_id,
            medio_pago_id=medio_pago_id,
            monto=monto,
            es_efectivo=es_efectivo,
        )
        self._desfasadas.append(desfase)
        return desfase

    def tiene_ventas_desfasadas(self) -> bool:
        return bool(self._desfasadas)

    @property
    def ventas_desfasadas(self):
        return tuple(self._desfasadas)

    def __repr__(self) -> str:
        return (f"SesionCaja(#{self.numero_turno} {self.caja_id} · "
                f"{self.estado.value})")
