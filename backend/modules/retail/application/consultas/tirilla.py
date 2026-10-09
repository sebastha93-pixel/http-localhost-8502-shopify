"""La tirilla — lo que se lleva la clienta en la mano.

SE LEE DE LA BASE, NO DEL CARRITO. La pantalla ya tiene los datos de la venta
que acaba de cerrar y sería más rápido imprimir desde ahí. No se hace: la
tirilla es el comprobante de lo que quedó REGISTRADO, y si por lo que sea el
servidor guardó otra cosa —un redondeo distinto, una línea que no entró— el
papel tiene que decir lo que quedó, no lo que la pantalla creía.

También es lo que permite reimprimir tres días después, que es cuando la
clienta vuelve a cambiar la prenda.

**CUÁNDO ES UNA FACTURA Y CUÁNDO NO.** Una factura electrónica existe cuando
la DIAN la valida: ahí nace el CUFE. Hasta ese momento este papel es un
comprobante interno y va impreso diciéndolo. Imprimir un papel con pinta de
documento fiscal sin serlo no es un detalle de redacción: es lo que convierte
un problema de software en un problema con la DIAN.

Cuando sí lo es, el número que manda es EL DE SIIGO (`TARR-11451`), que es el
que la DIAN validó bajo la resolución de la tienda. El del POS (`ARRPOS-…`)
pasa a ser una referencia interna.
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

    # LOS TOTALES SE PRESENTAN COMO EN LA TIRILLA REAL DE SIIGO, que es la que
    # la clienta reconoce y la contadora sabe leer:
    #
    #   Total bruto   = base ANTES de descuento   (sin IVA)
    #   Descuentos    = el descuento              (sin IVA)
    #   Subtotal      = base DESPUÉS de descuento (sin IVA)
    #   IVA 19%
    #   Total a pagar
    #
    # Nosotros imprimíamos «Subtotal» para el total CON IVA. No era otro
    # nombre: era la MISMA palabra significando dos cosas en papeles de la
    # misma tienda, y quien cuadra el día encuentra números que no casan.
    #
    # El cálculo no cambia —el precio de vitrina manda y el IVA se deriva por
    # línea (INV-V12)—; cambia cómo se presenta.
    subtotal_centavos: int = 0          # con IVA, antes de dcto (interno)
    descuento_centavos: int = 0         # con IVA (interno)
    total_bruto_centavos: int = 0       # base antes de dcto → «Total bruto»
    descuento_base_centavos: int = 0    # descuento sin IVA  → «Descuentos»
    total_centavos: int = 0
    base_gravable_centavos: int = 0     # base tras dcto     → «Subtotal»
    # Base e impuesto POR TARIFA. Con una sola parece redundante; con dos es lo
    # único que permite cuadrar la factura contra la declaración, y es lo que
    # imprime Siigo hoy.
    impuestos: list = field(default_factory=list)
    iva_centavos: int = 0
    pagado_centavos: int = 0
    vuelto_centavos: int = 0
    unidades: int = 0

    estado_fiscal: str = "pendiente"
    documento_fiscal: Optional[str] = None
    cufe: Optional[str] = None
    anulada: bool = False
    # Cuándo la validó la DIAN, en hora de la tienda. La tirilla real imprime
    # dos fechas —generación y expedición— y ésta es la segunda.
    fecha_expedicion: Optional[str] = None
    # «Responsable de IVA - Actividad económica 4782.» Va impreso en la factura.
    regimen: Optional[str] = None
    # La tienda emite y esta venta todavía no tiene su factura: la pantalla
    # espera unos segundos antes de imprimir, para entregar la factura y no
    # un comprobante.
    factura_en_camino: bool = False

    # El QR se dibuja en el servidor, junto a los datos fiscales. `qr_ruta` es
    # el atributo `d` de un <path> SVG: se pinta nítido a cualquier tamaño, no
    # engorda la respuesta como un PNG en base64, y al no ser marcado no hay
    # que inyectarlo como HTML crudo en la pantalla.
    qr_contenido: Optional[str] = None
    qr_ruta: Optional[str] = None
    qr_modulos: int = 0

    @property
    def es_documento_fiscal(self) -> bool:
        """Sólo cuando existe de verdad. Tres condiciones, y las tres:

        * el documento salió (`emitido`);
        * **tiene CUFE** — es la prueba de que la DIAN lo validó. Un documento
          creado en Siigo en modo prueba queda `emitido` y sin CUFE: existe
          allá, pero no es una factura y este papel no lo llama así;
        * hay resolución que imprimir, y es la que ampara ESE número.
        """
        return (self.estado_fiscal == "emitido" and bool(self.cufe)
                and bool(self.resolucion_dian))


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
                   t.zona_horaria, t.regimen_iva, t.actividad_economica,
                   -- LA RESOLUCIÓN ES DE LA CAJA (migración 0027). Si la caja
                   -- tiene prefijo, mandan SUS datos, completos o no: nunca
                   -- se mezcla el prefijo de una con el número de otra. Sólo
                   -- una caja sin resolución propia hereda la de la tienda.
                   CASE WHEN c.autorizacion_prefijo IS NOT NULL
                        THEN c.autorizacion_numero ELSE t.autorizacion_numero END
                       AS autorizacion_numero,
                   coalesce(c.autorizacion_prefijo, t.autorizacion_prefijo)
                       AS autorizacion_prefijo,
                   CASE WHEN c.autorizacion_prefijo IS NOT NULL
                        THEN c.autorizacion_desde ELSE t.autorizacion_desde END
                       AS autorizacion_desde,
                   CASE WHEN c.autorizacion_prefijo IS NOT NULL
                        THEN c.autorizacion_hasta ELSE t.autorizacion_hasta END
                       AS autorizacion_hasta,
                   CASE WHEN c.autorizacion_prefijo IS NOT NULL
                        THEN c.autorizacion_aprobada ELSE t.autorizacion_aprobada END
                       AS autorizacion_aprobada,
                   CASE WHEN c.autorizacion_prefijo IS NOT NULL
                        THEN c.autorizacion_meses ELSE t.autorizacion_meses END
                       AS autorizacion_meses,
                   c.siigo_documento_id,
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
                   descuento_monto, descuento_motivo, total_linea,
                   tasa_iva, base_gravable, iva_monto
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
            SELECT numero, cufe, qr_datos,
                   to_char(emitido_en AT TIME ZONE :tz, 'DD/MM/YYYY HH24:MI')
                       AS expedida
              FROM retail.documentos_fiscales
             WHERE venta_id = :i AND estado = 'emitido'
               AND tipo <> 'nota_credito'
             ORDER BY emitido_en DESC LIMIT 1
        """), {"i": venta_id, "tz": tz})).mappings().first()

        resolucion = _resolucion(v, doc["numero"] if doc else None)

        tirilla = Tirilla(
            razon_social=v["razon_social"], nit=v["nit"],
            direccion=v["direccion"], telefono=v["telefono"],
            tienda_nombre=v["tienda_nombre"],
            resolucion_dian=resolucion,
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
            **_brutos(lineas), impuestos=impuestos_por_tarifa(lineas),
            iva_centavos=int(v["iva_total"]),
            pagado_centavos=int(v["pagado"]),
            vuelto_centavos=int(v["vuelto"]),
            unidades=sum(int(l["cantidad"]) for l in lineas),
            estado_fiscal=v["estado_fiscal"],
            documento_fiscal=doc["numero"] if doc else None,
            cufe=doc["cufe"] if doc else None,
            anulada=v["estado"] == "anulada",
            fecha_expedicion=doc["expedida"] if doc else None,
            regimen=_regimen(v),
            factura_en_camino=_en_camino(v),
        )
        _poner_qr(tirilla, doc, con_resolucion=tirilla.es_documento_fiscal)
        return tirilla


def _resolucion(v, numero_factura: Optional[str]) -> Optional[str]:
    """El texto de la autorización de numeración, como lo imprime Siigo:

        Número Autorización 18764083761292 aprobado en 20241120
        prefijo TARR desde el número 1 al 1000000 Vigencia: 24 meses

    SÓLO SI AMPARA ESE NÚMERO. La resolución es de un prefijo; si la factura
    que devolvió Siigo trae otro —la caja apuntando al comprobante que no
    es—, pegarle esta resolución sería imprimir un dato falso en un papel
    fiscal. Sin texto, la tirilla no se presenta como factura.

    `resolucion_dian` a mano manda: es la salida para un caso que este
    armado no contemple.
    """
    if (v["resolucion_dian"] or "").strip():
        return v["resolucion_dian"].strip()
    # Sin factura no hay número que amparar, y no se imprime la resolución
    # «por si acaso»: en un comprobante interno sólo le daría pinta de fiscal.
    if not numero_factura:
        return None
    prefijo = (v["autorizacion_prefijo"] or "").strip()
    if not (v["autorizacion_numero"] and prefijo and v["autorizacion_aprobada"]):
        return None
    if numero_factura.rsplit("-", 1)[0].strip().upper() != prefijo.upper():
        return None
    texto = (f"Número Autorización {v['autorizacion_numero']} aprobado en "
             f"{v['autorizacion_aprobada']:%Y%m%d} prefijo {prefijo}")
    if v["autorizacion_desde"] is not None and v["autorizacion_hasta"] is not None:
        texto += (f" desde el número {v['autorizacion_desde']} al "
                  f"{v['autorizacion_hasta']}")
    if v["autorizacion_meses"]:
        texto += f" Vigencia: {v['autorizacion_meses']} meses"
    return texto


def _regimen(v) -> Optional[str]:
    partes = [(v["regimen_iva"] or "").strip()]
    if (v["actividad_economica"] or "").strip():
        partes.append(f"Actividad económica {v['actividad_economica'].strip()}")
    return " - ".join(p for p in partes if p) or None


def _en_camino(v) -> bool:
    """¿Vale la pena esperar la factura antes de imprimir?

    Sólo si de verdad viene: la facturación está encendida EN PRODUCCIÓN (en
    prueba no hay DIAN ni CUFE que esperar), la caja tiene comprobante y la
    venta no ha terminado su trámite.
    """
    import os
    # La misma variable que gobierna al emisor (`RETAIL_FISCAL_MODO`).
    en_produccion = os.environ.get(
        "RETAIL_FISCAL_MODO", "").strip().lower() == "produccion"
    return (en_produccion and bool(v["siigo_documento_id"])
            and v["estado"] != "anulada"
            and v["estado_fiscal"] in ("pendiente", "enviando"))


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


def _brutos(lineas) -> dict:
    """«Total bruto» y «Descuentos» como los presenta Siigo: SIN IVA.

    Se calcula POR LÍNEA y no con una proporción sobre el total, porque cada
    línea guarda su propia tarifa: el día que entre un producto exento o al 5 %,
    una proporción sobre el total repartiría el descuento contra la tarifa
    equivocada y la base declarada saldría mal. Con dos tarifas el error no
    revienta — sale en la factura, que es peor.

    La resta queda garantizada: `total_bruto − descuentos = subtotal`, porque
    el descuento se DERIVA de esos dos y no se calcula aparte. Una columna que
    no cuadra en un papel fiscal es lo primero que alguien va a mirar.
    """
    from backend.modules.retail.domain.shared.impuestos import separar_iva

    bruto = 0
    base_neta = 0
    for l in lineas:
        antes = int(l["precio_unitario"]) * int(l["cantidad"])
        base, _ = separar_iva(antes, l["tasa_iva"])
        bruto += base
        base_neta += int(l["base_gravable"])
    return {"total_bruto_centavos": bruto,
            "descuento_base_centavos": bruto - base_neta}


def impuestos_por_tarifa(lineas) -> list:
    """El bloque «Impuestos» de la tirilla real: base e impuesto por tarifa.

    Con una sola tarifa parece redundante. Con dos es lo ÚNICO que permite
    cuadrar la factura contra la declaración, y es lo que imprime Siigo hoy.
    """
    por_tasa: dict = {}
    for l in lineas:
        t = str(l["tasa_iva"])
        acc = por_tasa.setdefault(t, {"tasa": t, "base_centavos": 0,
                                      "impuesto_centavos": 0})
        acc["base_centavos"] += int(l["base_gravable"])
        acc["impuesto_centavos"] += int(l["iva_monto"])
    return [por_tasa[k] for k in sorted(por_tasa, key=lambda x: -float(x))]
