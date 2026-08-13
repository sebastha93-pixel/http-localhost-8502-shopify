"""La tirilla — lo que se lleva la clienta en la mano.

SE LEE DE LA BASE, NO DEL CARRITO. La pantalla ya tiene los datos de la venta
que acaba de cerrar y sería más rápido imprimir desde ahí. No se hace: la
tirilla es el comprobante de lo que quedó REGISTRADO, y si por lo que sea el
servidor guardó otra cosa —un redondeo distinto, una línea que no entró— el
papel tiene que decir lo que quedó, no lo que la pantalla creía.

También es lo que permite reimprimir tres días después, que es cuando la
clienta vuelve a cambiar la prenda.

**LO QUE ESTA TIRILLA NO ES.** No es una factura electrónica. Mientras la
tienda no tenga resolución DIAN y Siigo no haya emitido (Fase 3), esto es un
comprobante interno de venta y va impreso diciéndolo. Imprimir un papel con
pinta de documento fiscal sin serlo no es un detalle de redacción: es lo que
convierte un problema de software en un problema con la DIAN.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.modules.retail.domain.venta.errores import ReglaDeNegocio

__all__ = ["ArmarTirilla", "Tirilla", "LineaTirilla", "PagoTirilla"]


@dataclass(frozen=True)
class LineaTirilla:
    sku: str
    descripcion: str
    cantidad: int
    precio_unitario_centavos: int
    descuento_centavos: int
    descuento_motivo: Optional[str]
    total_centavos: int


@dataclass(frozen=True)
class PagoTirilla:
    nombre: str
    monto_centavos: int
    referencia: Optional[str]


@dataclass
class Tirilla:
    # Emisor
    razon_social: str
    nit: str
    direccion: str
    telefono: str
    tienda_nombre: str
    resolucion_dian: Optional[str]
    mensaje: Optional[str]

    # Venta
    numero: str
    fecha: str
    caja_nombre: str
    cajera_nombre: str

    # Clienta (opcional: en el mostrador la mayoría no la da)
    cliente_nombre: Optional[str]
    cliente_documento: Optional[str]

    lineas: List[LineaTirilla] = field(default_factory=list)
    pagos: List[PagoTirilla] = field(default_factory=list)

    subtotal_centavos: int = 0
    descuento_centavos: int = 0
    total_centavos: int = 0
    base_gravable_centavos: int = 0
    iva_centavos: int = 0
    pagado_centavos: int = 0
    vuelto_centavos: int = 0
    unidades: int = 0

    estado_fiscal: str = "pendiente"
    documento_fiscal: Optional[str] = None
    cufe: Optional[str] = None
    anulada: bool = False

    # El QR se dibuja en el servidor, junto a los datos fiscales. `qr_ruta` es
    # el atributo `d` de un <path> SVG: se pinta nítido a cualquier tamaño, no
    # engorda la respuesta como un PNG en base64, y al no ser marcado no hay
    # que inyectarlo como HTML crudo en la pantalla.
    qr_contenido: Optional[str] = None
    qr_ruta: Optional[str] = None
    qr_modulos: int = 0

    @property
    def es_documento_fiscal(self) -> bool:
        """Sólo cuando existe de verdad: hay resolución Y el documento salió.

        Las dos condiciones. Con resolución pero sin emitir, el papel todavía
        no ampara nada; emitido sin resolución no puede pasar, pero si pasara
        sería un dato corrupto y tampoco hay que creerle.
        """
        return bool(self.resolucion_dian) and self.estado_fiscal == "emitido"


class ArmarTirilla:
    def __init__(self, sesion: AsyncSession) -> None:
        self._s = sesion

    async def ejecutar(self, venta_id: str) -> Tirilla:
        v = (await self._s.execute(text("""
            SELECT v.numero, v.cerrada_en, v.estado, v.subtotal,
                   v.descuento_total, v.total, v.base_gravable, v.iva_total,
                   v.pagado, v.vuelto, v.estado_fiscal, v.cliente_id,
                   coalesce(t.razon_social, t.nombre) AS razon_social,
                   coalesce(t.nit, '')        AS nit,
                   coalesce(t.direccion, '')  AS direccion,
                   coalesce(t.telefono, '')   AS telefono,
                   t.nombre                   AS tienda_nombre,
                   t.resolucion_dian, t.mensaje_tirilla,
                   t.zona_horaria,
                   coalesce(c.nombre, v.caja_id)   AS caja_nombre,
                   coalesce(p.nombre, v.cajera_id) AS cajera_nombre
              FROM retail.ventas v
              JOIN retail.tiendas t ON t.id = v.tienda_id
              LEFT JOIN retail.cajas c ON c.id = v.caja_id
              LEFT JOIN retail.permisos_pos p ON p.usuario_id = v.cajera_id
             WHERE v.id = :i
        """), {"i": venta_id})).mappings().first()
        if v is None:
            raise ReglaDeNegocio(f"No existe la venta {venta_id}.")
        if v["cerrada_en"] is None:
            raise ReglaDeNegocio(
                "Esa venta todavía no se ha cerrado: no hay nada que imprimir.")

        tz = v["zona_horaria"] or "America/Bogota"
        fecha = (await self._s.execute(text("""
            SELECT to_char(:ts AT TIME ZONE :tz, 'DD/MM/YYYY HH24:MI')
        """), {"ts": v["cerrada_en"], "tz": tz})).scalar()

        lineas = (await self._s.execute(text("""
            SELECT sku, descripcion, cantidad, precio_unitario,
                   descuento_monto, descuento_motivo, total_linea
              FROM retail.venta_lineas WHERE venta_id = :i ORDER BY orden
        """), {"i": venta_id})).mappings().all()

        pagos = (await self._s.execute(text("""
            SELECT coalesce(m.nombre, g.medio_pago_id) AS nombre,
                   g.monto, g.referencia
              FROM retail.venta_pagos g
              LEFT JOIN retail.medios_pago m ON m.id = g.medio_pago_id
             WHERE g.venta_id = :i ORDER BY g.id
        """), {"i": venta_id})).mappings().all()

        cliente = None
        if v["cliente_id"]:
            cliente = (await self._s.execute(text("""
                SELECT trim(concat_ws(' ', nombre, apellido)) AS nombre,
                       tipo_documento, numero_documento
                  FROM retail.clientes WHERE id = :i
            """), {"i": v["cliente_id"]})).mappings().first()

        doc = (await self._s.execute(text("""
            SELECT numero, cufe, qr_datos FROM retail.documentos_fiscales
             WHERE venta_id = :i AND estado = 'emitido'
             ORDER BY emitido_en DESC LIMIT 1
        """), {"i": venta_id})).mappings().first()

        tirilla = Tirilla(
            razon_social=v["razon_social"], nit=v["nit"],
            direccion=v["direccion"], telefono=v["telefono"],
            tienda_nombre=v["tienda_nombre"],
            resolucion_dian=v["resolucion_dian"],
            mensaje=v["mensaje_tirilla"],
            numero=v["numero"], fecha=fecha,
            caja_nombre=v["caja_nombre"], cajera_nombre=v["cajera_nombre"],
            cliente_nombre=cliente["nombre"] if cliente else None,
            cliente_documento=(
                f"{cliente['tipo_documento']} {cliente['numero_documento']}"
                if cliente else None),
            lineas=[LineaTirilla(
                sku=l["sku"], descripcion=l["descripcion"],
                cantidad=int(l["cantidad"]),
                precio_unitario_centavos=int(l["precio_unitario"]),
                descuento_centavos=int(l["descuento_monto"]),
                descuento_motivo=l["descuento_motivo"],
                total_centavos=int(l["total_linea"])) for l in lineas],
            pagos=[PagoTirilla(nombre=p["nombre"], monto_centavos=int(p["monto"]),
                               referencia=p["referencia"]) for p in pagos],
            subtotal_centavos=int(v["subtotal"]),
            descuento_centavos=int(v["descuento_total"]),
            total_centavos=int(v["total"]),
            base_gravable_centavos=int(v["base_gravable"]),
            iva_centavos=int(v["iva_total"]),
            pagado_centavos=int(v["pagado"]),
            vuelto_centavos=int(v["vuelto"]),
            unidades=sum(int(l["cantidad"]) for l in lineas),
            estado_fiscal=v["estado_fiscal"],
            documento_fiscal=doc["numero"] if doc else None,
            cufe=doc["cufe"] if doc else None,
            anulada=v["estado"] == "anulada",
        )
        _poner_qr(tirilla, doc, con_resolucion=bool(v["resolucion_dian"]))
        return tirilla


# ── El QR ───────────────────────────────────────────────────────────────────

# El catálogo público de la DIAN. Es el respaldo, NO la fuente de verdad: si el
# documento trae `qr_datos` del proveedor, manda ese. Ver migración 0009.
_CATALOGO_DIAN = "https://catalogo-vpfe.dian.gov.co/document/searchqr?documentkey="


def _poner_qr(tirilla: Tirilla, doc, *, con_resolucion: bool) -> None:
    """Dibuja el QR, y SÓLO cuando hay algo real que verificar.

    Sin documento emitido no hay nada que escanear. Imprimir un QR igualmente
    —aunque llevara a una página de error— haría que el papel pareciera fiscal
    a simple vista, que es exactamente lo que esta tirilla evita mientras no lo
    sea.
    """
    if not doc or not con_resolucion:
        return
    contenido = (doc["qr_datos"] or "").strip()
    if not contenido:
        if not doc["cufe"]:
            return
        contenido = f"{_CATALOGO_DIAN}{doc['cufe']}"

    import segno

    # Corrección M (~15 %). En papel térmico, que se borra con el calor y el
    # roce del bolsillo, L deja el código ilegible en semanas; Q y H lo hacen
    # más grande y en 72 mm de ancho el tamaño es el recurso escaso.
    codigo = segno.make(contenido, error="m")
    matriz = list(codigo.matrix)

    trozos = []
    for y, fila in enumerate(matriz):
        x = 0
        while x < len(fila):
            if fila[x]:
                inicio = x
                while x < len(fila) and fila[x]:
                    x += 1
                # Un rectángulo por RACHA de módulos encendidos, no uno por
                # módulo: baja la ruta de ~1.400 tramos a ~300 en un QR de
                # versión 9, y el navegador la pinta sin pensarlo.
                trozos.append(f"M{inicio} {y}h{x - inicio}v1h-{x - inicio}z")
            else:
                x += 1

    tirilla.qr_contenido = contenido
    tirilla.qr_ruta = "".join(trozos)
    tirilla.qr_modulos = len(matriz)
