"""API HTTP del módulo retail.

FORMA DE LA API. Una venta llega **completa** en una sola petición, no
construida línea por línea desde el servidor. No es una simplificación: es lo
que exige el diseño offline-first (ADR-005). El carrito vive en el
dispositivo, en IndexedDB, y sobrevive a que se caiga internet a mitad de la
venta. Un carrito que viviera en el servidor obligaría a estar conectado para
poder vender, que es justo lo que este POS no puede permitirse.

De ahí sale la otra propiedad: el `venta_id` lo genera el dispositivo, así que
esta petición es idempotente. Reintentarla veinte veces produce una venta.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.core.security import CurrentUser, require_permission
from backend.modules.retail.application.comandos.cerrar_venta import (
    CerrarVenta,
    RelojDelSistema,
)
from backend.modules.retail.application.comandos.clientes import (
    BuscarClientes,
    CrearCliente,
)
from backend.modules.retail.application.consultas.buscar_producto import BuscarProducto
from backend.modules.retail.application.consultas.listar_referencias import (
    ListarReferencias,
)
from backend.modules.retail.domain.shared.dinero import Dinero
from backend.modules.retail.domain.shared.sku import Sku
from backend.modules.retail.domain.venta.descuento import Descuento
from backend.modules.retail.domain.venta.errores import (
    ReglaDeNegocio,
    RequiereAutorizacion,
)
from backend.modules.retail.domain.venta.venta import Venta
from backend.modules.retail.interfaces.http.dependencias import (
    unidad_de_trabajo,
    sesion_lectura,
)

router = APIRouter(prefix="/api/retail", tags=["retail"])


# ── Contratos ───────────────────────────────────────────────────────────────

class LineaEntrada(BaseModel):
    sku: str
    cantidad: int = Field(gt=0)
    precio_unitario_centavos: int = Field(ge=0)
    tasa_iva: str = "19"
    descripcion: str = ""
    descuento_porcentaje: Optional[str] = None
    descuento_valor_centavos: Optional[int] = None
    descuento_motivo: Optional[str] = None
    obsequio: bool = False


class PagoEntrada(BaseModel):
    medio_pago_id: str
    monto_centavos: int = Field(gt=0)
    es_efectivo: bool = False
    referencia: Optional[str] = None


class VentaEntrada(BaseModel):
    """La venta completa, tal como la armó el dispositivo."""

    venta_id: str = Field(description="ULID generado en el dispositivo")
    numero: str
    tienda_id: str
    caja_id: str
    sesion_id: str
    ubicacion_id: str
    cliente_id: Optional[str] = None
    dispositivo_id: Optional[str] = None
    moneda: str = "COP"
    # `fuera_de_linea` cuando la venta se cobró sin red y llegó por la cola.
    # Lo dice el dispositivo porque es el único que lo sabe: al servidor le
    # llega igual en los dos casos, y sin esto TODAS las ventas parecen hechas
    # con conexión — incluidas las que se cobraron sin poder ver el stock.
    origen: str = "en_linea"
    lineas: List[LineaEntrada]
    pagos: List[PagoEntrada]


class TicketSalida(BaseModel):
    venta_id: str
    numero: str
    total_centavos: int
    pagado_centavos: int
    vuelto_centavos: int
    iva_centavos: int
    descuento_centavos: int
    estado_fiscal: str
    duplicada: bool = False


class ResultadoBusqueda(BaseModel):
    variante_id: str
    sku: str
    referencia: str
    talla: str
    color: str
    nombre: str
    precio_con_iva_centavos: int
    disponible: int
    es_escaneo: bool


# ── Catálogo ────────────────────────────────────────────────────────────────

@router.get("/catalogo/buscar", response_model=List[ResultadoBusqueda])
async def buscar(
    q: str = Query(min_length=1),
    ubicacion_id: str = Query(),
    limite: int = Query(default=24, le=60),
    sesion=Depends(sesion_lectura),
    _: CurrentUser = Depends(require_permission("retail", "ver")),
):
    """Respaldo del buscador. En operación normal esto no se llama: el
    dispositivo busca en su copia local y no viaja a la red (ADR-009)."""
    resultados = await BuscarProducto(sesion).ejecutar(
        q, ubicacion_id=ubicacion_id, limite=limite)
    return [
        ResultadoBusqueda(
            **{k: v for k, v in r.__dict__.items()
               if k not in ("tasa_iva", "codigo_barras")},
        )
        for r in resultados
    ]


# El catálogo YA guarda el precio de vitrina: no hay nada que convertir. Antes
# aquí se sumaba el IVA a una base, y ese viaje no siempre regresaba — de ahí
# salían los «$139.900,01» de la rejilla.


# ── Ventas ──────────────────────────────────────────────────────────────────

@router.post("/ventas/cerrar", response_model=TicketSalida)
async def cerrar_venta(
    entrada: VentaEntrada,
    uow=Depends(unidad_de_trabajo),
    usuario: CurrentUser = Depends(require_permission("retail", "modificar")),
):
    """Cierra una venta completa. Idempotente por `venta_id`.

    Devuelve el ticket de inmediato: el documento fiscal queda encolado y lo
    emite el worker (ADR-002). Esperar a Siigo aquí convertiría 800 ms en lo
    que Siigo quiera ese día.
    """
    # Idempotencia: si esta venta ya se cerró, se devuelve su ticket en vez de
    # un error. El dispositivo reintenta por diseño y no puede distinguir
    # «no llegó» de «llegó y se perdió la respuesta».
    async with uow as t:
        ya = await t.ventas.obtener(entrada.venta_id)
    if ya is not None and ya.estado.value != "borrador":
        return TicketSalida(
            venta_id=ya.id, numero=ya.numero,
            total_centavos=ya.total().centavos,
            pagado_centavos=ya.pagado().centavos,
            vuelto_centavos=ya.vuelto().centavos,
            iva_centavos=ya.iva_total().centavos,
            descuento_centavos=ya.descuento_total().centavos,
            estado_fiscal=ya.estado_fiscal.value, duplicada=True,
        )

    try:
        venta, variante_por_sku = await _armar(entrada, uow, usuario.id)
        await _exigir_numero_arrendado(uow, venta)
        resultado = await CerrarVenta(uow, reloj=RelojDelSistema()).ejecutar(
            venta, variante_por_sku=variante_por_sku,
            ubicacion_id=entrada.ubicacion_id, usuario_id=usuario.id)
    except RequiereAutorizacion as e:
        # Ya no hay diálogo de PIN que abrir: la vía es que entre alguien con
        # un tope mayor. La bandera se conserva para que la pantalla lo diga
        # así en vez de pintar un error rojo sin salida.
        raise HTTPException(403, {"error": "sobre_el_tope",
                                  "mensaje": str(e),
                                  "accion_sugerida": "entrar_con_otro_usuario"})
    except ReglaDeNegocio as e:
        raise HTTPException(400, {"error": "regla_de_negocio",
                                  "mensaje": str(e)})
    except IntegrityError as e:
        # El índice único del número es la última red, y saltaba como un 500
        # sin explicación. Que llegue aquí significa que dos ventas DISTINTAS
        # traen el mismo número: un dispositivo con el bloque desincronizado.
        if "ux_venta_numero" not in str(e):
            raise
        raise HTTPException(409, {
            "error": "numero_repetido",
            "mensaje": f"El número {entrada.numero} ya está usado por otra "
                       f"venta. Vuelve a abrir el turno para pedir numeración "
                       f"nueva; la venta no se registró.",
            "accion_sugerida": "reabrir_turno"})

    return TicketSalida(
        venta_id=resultado.venta_id, numero=resultado.numero,
        total_centavos=resultado.total_centavos,
        pagado_centavos=venta.pagado().centavos,
        vuelto_centavos=resultado.vuelto_centavos,
        iva_centavos=venta.iva_total().centavos,
        descuento_centavos=venta.descuento_total().centavos,
        estado_fiscal=resultado.estado_fiscal,
    )


async def _exigir_numero_arrendado(uow, venta) -> None:
    """El número llega en la petición; hay que comprobar de dónde salió.

    El dispositivo numera sin red dentro del bloque que arrendó — ese es todo
    el punto del diseño offline. Pero aceptar cualquier número deja que un
    cliente con un error (o modificado) numere encima de la otra caja o fuera
    de todo rango, y eso no se descubre hasta que alguien cuadra la numeración
    meses después.

    NO se exige que sea el bloque VIGENTE: una venta hecha sin red puede llegar
    cuando la caja ya renovó, y rechazarla ahí sería perder justo la venta que
    todo esto existe para no perder.
    """
    async with uow as t:
        ok = await t.consecutivos.pertenece_a_un_bloque(
            caja_id=venta.caja_id, prefijo=venta.prefijo,
            consecutivo=venta.consecutivo)
    if not ok:
        raise ReglaDeNegocio(
            f"El número {venta.numero} no sale de ningún bloque arrendado por "
            f"esta caja. Vuelve a abrir el turno para pedir uno."
        )


async def _armar(entrada: VentaEntrada, uow, usuario_id: str) -> tuple:
    """Reconstruye el agregado desde el cuerpo de la petición.

    Los precios los manda el dispositivo porque los congeló al agregar la
    prenda al carrito. Cambiar el precio del catálogo a mitad de una venta no
    puede cambiar lo que la cajera ya le dijo a la clienta.
    """
    venta = Venta.abrir(
        id=entrada.venta_id, numero=entrada.numero, tienda_id=entrada.tienda_id,
        caja_id=entrada.caja_id, sesion_id=entrada.sesion_id,
        cajera_id=usuario_id, moneda=entrada.moneda,
        dispositivo_id=entrada.dispositivo_id,
        origen=("fuera_de_linea" if entrada.origen == "fuera_de_linea"
                else "en_linea"))
    if entrada.cliente_id:
        venta.asignar_cliente(entrada.cliente_id)

    skus = [l.sku for l in entrada.lineas]
    async with uow as t:
        from sqlalchemy import text as _t
        filas = (await t.sesion.execute(_t("""
            SELECT id, sku FROM retail.variantes WHERE sku = ANY(:skus)
        """), {"skus": skus})).mappings().all()
        # EL TOPE SE LEE AQUÍ, no llega en el cuerpo. Antes viajaba como
        # `tope_descuento` desde el navegador: un cliente modificado que
        # mandara "100" aprobaba cualquier descuento solo. Con el PIN eso
        # quedaba tapado —hacía falta la firma igual—; sin PIN, el tope es EL
        # control, y un control que el cliente se autoasigna no es un control.
        tope = Decimal(str((await t.sesion.execute(_t("""
            SELECT coalesce(tope_descuento_pct, 0) FROM retail.permisos_pos
             WHERE usuario_id = :u AND activo
        """), {"u": usuario_id})).scalar() or 0))
    variante_por_sku = {f["sku"]: f["id"] for f in filas}

    faltan = [s for s in skus if s not in variante_por_sku]
    if faltan:
        raise ReglaDeNegocio(
            f"Estas referencias no están en el catálogo: {', '.join(faltan)}")

    for entrada_linea in entrada.lineas:
        linea = venta.agregar_linea(
            sku=Sku.parsear(entrada_linea.sku),
            descripcion=entrada_linea.descripcion or entrada_linea.sku,
            cantidad=entrada_linea.cantidad,
            precio_unitario=Dinero(entrada_linea.precio_unitario_centavos,
                                   entrada.moneda),
            tasa_iva=Decimal(entrada_linea.tasa_iva),
        )
        if entrada_linea.obsequio:
            venta.marcar_obsequio(linea.numero, autorizado_por=usuario_id)
        elif entrada_linea.descuento_porcentaje or entrada_linea.descuento_valor_centavos:
            venta.aplicar_descuento_linea(
                linea.numero, _descuento(entrada_linea, entrada.moneda),
                tope_de_quien_aplica=tope, aplicado_por=usuario_id)

    for p in entrada.pagos:
        venta.registrar_pago(p.medio_pago_id,
                             Dinero(p.monto_centavos, entrada.moneda),
                             es_efectivo=p.es_efectivo, referencia=p.referencia)

    return venta, variante_por_sku


def _descuento(l: LineaEntrada, moneda: str) -> Descuento:
    motivo = l.descuento_motivo or ""
    if l.descuento_porcentaje:
        return Descuento.porcentaje(Decimal(l.descuento_porcentaje), motivo=motivo)
    return Descuento.valor(Dinero(l.descuento_valor_centavos or 0, moneda),
                           motivo=motivo)


# ── Autorización ────────────────────────────────────────────────────────────

# ── Catálogo agrupado por referencia (la rejilla del diseño) ────────────────

class TallaSalida(BaseModel):
    variante_id: str
    sku: str
    talla: str
    disponible: int


class ReferenciaSalida(BaseModel):
    referencia: str
    nombre: str
    color: str
    categoria: str
    precio_con_iva_centavos: int
    tasa_iva: str
    tallas: List[TallaSalida]


class CatalogoSalida(BaseModel):
    categorias: List[str]
    referencias: List[ReferenciaSalida]


@router.get("/catalogo/referencias", response_model=CatalogoSalida)
async def listar_referencias(
    ubicacion_id: str = Query(),
    q: str = Query(default=""),
    categoria: str = Query(default=""),
    limite: int = Query(default=60, le=120),
    sesion=Depends(sesion_lectura),
    _: CurrentUser = Depends(require_permission("retail", "ver")),
):
    """Una fila por REFERENCIA con sus tallas — la forma que pide la rejilla.

    Las categorías se devuelven en la misma respuesta para que los chips no
    necesiten una segunda petición: la pantalla los pinta al arrancar.
    """
    consulta = ListarReferencias(sesion)
    refs = await consulta.ejecutar(
        ubicacion_id=ubicacion_id, texto=q, categoria=categoria, limite=limite)
    return CatalogoSalida(
        categorias=await consulta.categorias(),
        referencias=[
            ReferenciaSalida(
                referencia=r.referencia, nombre=r.nombre, color=r.color,
                categoria=r.categoria,
                precio_con_iva_centavos=r.precio_con_iva_centavos,
                tasa_iva=r.tasa_iva,
                tallas=[
                    TallaSalida(variante_id=t.variante_id, sku=t.sku,
                                talla=t.talla, disponible=t.disponible)
                    for t in r.tallas
                ],
            )
            for r in refs
        ],
    )


# ── Clientas ────────────────────────────────────────────────────────────────

class ClienteSalida(BaseModel):
    id: str
    tipo_documento: str
    numero_documento: str
    nombre: str
    telefono: Optional[str] = None
    correo: Optional[str] = None
    compras: int


class ClienteNuevo(BaseModel):
    cliente_id: str = Field(description="ULID generado en el dispositivo")
    tipo_documento: str
    numero_documento: str
    nombre: str
    telefono: str
    correo: str


@router.get("/clientes/buscar", response_model=List[ClienteSalida])
async def buscar_clientes(
    documento: str = Query(min_length=3),
    sesion=Depends(sesion_lectura),
    _: CurrentUser = Depends(require_permission("retail", "ver")),
):
    """Sólo por número de identificación, por decisión del diseño — y es la
    correcta: buscar por nombre en un mostrador devuelve seis «María González»
    y la cajera tiene que adivinar."""
    encontradas = await BuscarClientes(sesion).ejecutar(documento)
    return [ClienteSalida(**c.__dict__) for c in encontradas]


@router.post("/clientes", response_model=ClienteSalida)
async def crear_cliente(
    entrada: ClienteNuevo,
    uow=Depends(unidad_de_trabajo),
    usuario: CurrentUser = Depends(require_permission("retail", "modificar")),
):
    """Crea la clienta y la devuelve lista para asignar a la venta.

    NO toca Siigo: el registro fiscal se crea perezosamente al emitir su
    primer documento. Ir a Siigo aquí pondría a la clienta a esperar a un
    tercero en pleno mostrador.
    """
    from datetime import datetime, timezone

    async with uow as t:
        try:
            c = await CrearCliente(t.sesion).ejecutar(
                cliente_id=entrada.cliente_id,
                tipo_documento=entrada.tipo_documento,
                numero_documento=entrada.numero_documento,
                nombre=entrada.nombre, telefono=entrada.telefono,
                correo=entrada.correo, creado_por=usuario.id,
                ahora=datetime.now(timezone.utc))
        except ReglaDeNegocio as e:
            raise HTTPException(400, {"error": "regla_de_negocio",
                                      "mensaje": str(e)})
        await t.commit()

    return ClienteSalida(**c.__dict__)


# ── Turno de caja (vista 1 del handoff) ─────────────────────────────────────


class TurnoSalida(BaseModel):
    sesion_id: str
    numero_turno: int
    tienda_id: str
    caja_id: str
    cajera_id: str
    cajera_nombre: str
    tope_descuento_pct: str
    base_inicial_centavos: int
    reanudado: bool = False
    # EL BLOQUE DE CONSECUTIVOS. Es lo que permite numerar sin red: el
    # dispositivo asigna dentro de su rango sin volver a preguntar. Antes la
    # pantalla numeraba con `Date.now() % 100000`, que se repite cada 100 s y
    # choca contra `ux_venta_numero`.
    prefijo: str = ""
    consecutivo_desde: int = 0
    consecutivo_hasta: int = 0
    consecutivo_siguiente: int = 0


class AbrirTurnoEntrada(BaseModel):
    """Sin PIN: quién abre el turno sale del JWT, y ese JWT viene del login del
    ERP con correo y contraseña."""

    sesion_id: str = Field(description="ULID generado en el dispositivo")
    tienda_id: str
    caja_id: str
    # Quién es este equipo. No autentica nada —de eso se encarga el login del
    # ERP— pero sin él dos tabletas en la misma caja comparten bloque de
    # numeración y sacan tiquetes con el mismo número.
    dispositivo_id: Optional[str] = None
    dispositivo_nombre: Optional[str] = None


@router.get("/caja/turno-actual", response_model=Optional[TurnoSalida])
async def turno_actual(
    caja_id: str = Query(),
    dispositivo_id: Optional[str] = Query(None),
    dispositivo_nombre: Optional[str] = Query(None),
    uow=Depends(unidad_de_trabajo),
    usuario: CurrentUser = Depends(require_permission("retail", "ver")),
):
    """Si la caja ya tiene turno abierto, se REANUDA. Recargar la pantalla a
    media mañana no puede costar volver a entrar."""
    from sqlalchemy import text as _t

    async with uow as t:
        abierta = await t.turnos.abierta_de(caja_id)
        if abierta is None:
            return None
        tope = (await t.sesion.execute(_t(
            "SELECT tope_descuento_pct FROM retail.permisos_pos WHERE usuario_id=:u"
        ), {"u": abierta["abierta_por"]})).scalar()
        # Reanudar NO arrienda: recargar la pantalla a media mañana dejaría un
        # hueco de 500 números cada vez.
        #
        # PERO EL EQUIPO SE IDENTIFICA IGUAL. Esta es la vía por la que entra
        # una SEGUNDA tableta —abre el POS y encuentra el turno ya abierto—, y
        # sin decir quién es se llevaría el bloque de la primera: las dos
        # numerando desde el mismo punto.
        prefijo = await _prefijo_de(t, caja_id)
        if dispositivo_id:
            await t.consecutivos.registrar_dispositivo(
                dispositivo_id=dispositivo_id, caja_id=caja_id,
                nombre=dispositivo_nombre or "Equipo sin nombre",
                usuario_id=usuario.id)
        bloque = await t.consecutivos.vigente_o_arrendar(
            caja_id=caja_id, prefijo=prefijo, dispositivo_id=dispositivo_id)
        await t.commit()

    return TurnoSalida(
        sesion_id=abierta["id"], numero_turno=abierta["numero_turno"],
        tienda_id=abierta["tienda_id"], caja_id=caja_id,
        cajera_id=abierta["abierta_por"],
        cajera_nombre=abierta["cajera_nombre"],
        tope_descuento_pct=str(tope or 0),
        base_inicial_centavos=int(abierta["base_inicial"]), reanudado=True,
        prefijo=bloque["prefijo"], consecutivo_desde=bloque["desde"],
        consecutivo_hasta=bloque["hasta"],
        consecutivo_siguiente=bloque["siguiente"],
    )


@router.post("/caja/turno", response_model=TurnoSalida)
async def abrir_turno(
    entrada: AbrirTurnoEntrada,
    uow=Depends(unidad_de_trabajo),
    usuario: CurrentUser = Depends(require_permission("retail", "modificar")),
):
    """Abre el turno para el usuario AUTENTICADO.

    No pide PIN: quien está en la caja ya entró con su correo y contraseña por
    el login del ERP, y volver a pedirle una credencial para abrir su propio
    turno es un paso que no protege nada.

    La base tampoco se digita: sale de la configuración de la tienda, como
    decidió el diseño. Pedirla a diario es un paso que se responde en
    automático hasta que un día se responde mal.
    """
    from datetime import datetime, timezone
    from sqlalchemy import text as _t

    ahora = datetime.now(timezone.utc)

    async with uow as t:
        ya = await t.turnos.abierta_de(entrada.caja_id)
        if ya is not None:
            # Otra persona con el turno abierto NO se sobreescribe: el arqueo
            # es suyo y cerrarlo es su responsabilidad (o la de un supervisor).
            tope = (await t.sesion.execute(_t(
                "SELECT tope_descuento_pct FROM retail.permisos_pos WHERE usuario_id=:u"
            ), {"u": ya["abierta_por"]})).scalar()
            prefijo = await _prefijo_de(t, entrada.caja_id)
            await _anotar_equipo(t, entrada, usuario.id)
            bloque = await t.consecutivos.vigente_o_arrendar(
                caja_id=entrada.caja_id, prefijo=prefijo,
                dispositivo_id=entrada.dispositivo_id)
            await t.commit()
            return TurnoSalida(
                sesion_id=ya["id"], numero_turno=ya["numero_turno"],
                tienda_id=ya["tienda_id"], caja_id=entrada.caja_id,
                cajera_id=ya["abierta_por"], cajera_nombre=ya["cajera_nombre"],
                tope_descuento_pct=str(tope or 0),
                base_inicial_centavos=int(ya["base_inicial"]), reanudado=True,
                prefijo=bloque["prefijo"], consecutivo_desde=bloque["desde"],
                consecutivo_hasta=bloque["hasta"],
                consecutivo_siguiente=bloque["siguiente"],
            )

        try:
            base = await t.turnos.base_de_tienda(entrada.tienda_id)
            turno = await t.turnos.abrir(
                sesion_id=entrada.sesion_id, tienda_id=entrada.tienda_id,
                caja_id=entrada.caja_id, usuario_id=usuario.id,
                base_inicial=base, ahora=ahora)
            # El bloque se arrienda EN LA MISMA TRANSACCIÓN que el turno: un
            # turno abierto sin bloque es una caja que no puede numerar, y una
            # caja que no puede numerar no puede vender.
            prefijo = await _prefijo_de(t, entrada.caja_id)
            await _anotar_equipo(t, entrada, usuario.id)
            bloque = await t.consecutivos.vigente_o_arrendar(
                caja_id=entrada.caja_id, prefijo=prefijo,
                dispositivo_id=entrada.dispositivo_id)
            await t.auditoria.registrar(
                evento="caja.abierta", ocurrido_en=ahora,
                tienda_id=entrada.tienda_id, caja_id=entrada.caja_id,
                sesion_id=entrada.sesion_id, usuario_id=usuario.id,
                agregado_tipo="sesion_caja", agregado_id=entrada.sesion_id,
                payload={"numero_turno": turno["numero_turno"],
                         "base_inicial": base,
                         "consecutivos": f"{bloque['desde']}-{bloque['hasta']}"})
            await t.commit()
        except ReglaDeNegocio as e:
            raise HTTPException(400, {"error": "regla_de_negocio",
                                      "mensaje": str(e)})

        tope = (await t.sesion.execute(_t(
            "SELECT coalesce(tope_descuento_pct, 0) FROM retail.permisos_pos "
            "WHERE usuario_id = :u"), {"u": usuario.id})).scalar()

    return TurnoSalida(
        sesion_id=entrada.sesion_id, numero_turno=turno["numero_turno"],
        tienda_id=entrada.tienda_id, caja_id=entrada.caja_id,
        cajera_id=usuario.id, cajera_nombre=usuario.nombre,
        tope_descuento_pct=str(tope or 0), base_inicial_centavos=base,
        prefijo=bloque["prefijo"], consecutivo_desde=bloque["desde"],
        consecutivo_hasta=bloque["hasta"],
        consecutivo_siguiente=bloque["siguiente"],
    )


class ContextoCaja(BaseModel):
    tienda_id: str
    tienda_nombre: str
    caja_id: str
    caja_nombre: str
    base_caja_centavos: int
    ubicacion_id: Optional[str] = None
    # EL ENCABEZADO DE LA TIRILLA. Viaja aquí —y no sólo en el endpoint de la
    # tirilla— para que el dispositivo lo tenga guardado ANTES de quedarse sin
    # red. Sin esto, una venta offline se cierra pero no se puede imprimir: la
    # clienta se va sin papel justo cuando más falta hace un comprobante.
    razon_social: str = ""
    nit: str = ""
    direccion: str = ""
    telefono: str = ""
    mensaje_tirilla: Optional[str] = None
    # Si la tienda ya tiene resolución. Offline nunca se imprime como factura
    # —no hay documento emitido— pero el dato viaja para no tener que
    # adivinarlo al reconectar.
    tiene_resolucion: bool = False


@router.get("/caja/contexto", response_model=ContextoCaja)
async def contexto_caja(
    caja_id: str = Query(),
    sesion=Depends(sesion_lectura),
    _: CurrentUser = Depends(require_permission("retail", "ver")),
):
    """Los nombres de la tienda y la caja, y la base configurada.

    La pantalla de apertura los necesita ANTES de que exista un turno. Mostrar
    `florida_caja1` en vez de «Caja 01» delata que nadie miró esa pantalla.
    """
    from sqlalchemy import text as _t
    fila = (await sesion.execute(_t("""
        SELECT c.id AS caja_id, c.nombre AS caja_nombre,
               t.id AS tienda_id, t.nombre AS tienda_nombre, t.base_caja,
               coalesce(t.razon_social, t.nombre) AS razon_social,
               coalesce(t.nit, '')        AS nit,
               coalesce(t.direccion, '')  AS direccion,
               coalesce(t.telefono, '')   AS telefono,
               t.mensaje_tirilla,
               (t.resolucion_dian IS NOT NULL) AS tiene_resolucion,
               (SELECT u.id FROM retail.ubicaciones u
                 WHERE u.tienda_id = t.id AND u.tipo = 'tienda' LIMIT 1) AS ubicacion
          FROM retail.cajas c JOIN retail.tiendas t ON t.id = c.tienda_id
         WHERE c.id = :c
    """), {"c": caja_id})).mappings().first()

    if fila is None:
        raise HTTPException(404, {"error": "caja_desconocida",
                                  "mensaje": f"No existe la caja {caja_id}."})

    return ContextoCaja(
        tienda_id=fila["tienda_id"], tienda_nombre=fila["tienda_nombre"],
        caja_id=fila["caja_id"], caja_nombre=fila["caja_nombre"],
        base_caja_centavos=int(fila["base_caja"]),
        ubicacion_id=fila["ubicacion"],
        razon_social=fila["razon_social"], nit=fila["nit"],
        direccion=fila["direccion"], telefono=fila["telefono"],
        mensaje_tirilla=fila["mensaje_tirilla"],
        tiene_resolucion=bool(fila["tiene_resolucion"]),
    )


# ── Cierre de caja (vista 7 del handoff) ────────────────────────────────────

class MedioResumen(BaseModel):
    medio_pago_id: str
    nombre: str
    es_efectivo: bool
    # Un medio que NO entra al arqueo (crédito a 30 días) igual hay que
    # declararlo, pero no se cuenta: no hay nada físico. La pantalla lo
    # prellena con el total del sistema y lo deja de sólo lectura.
    entra_al_arqueo: bool
    total_centavos: int


class ResumenCierre(BaseModel):
    sesion_id: str
    numero_turno: int
    cajera_nombre: str
    abierta_en: str
    transacciones: int
    ventas_brutas_centavos: int
    descuentos_centavos: int
    anuladas: int
    monto_anulado_centavos: int
    medios: List[MedioResumen]
    base_inicial_centavos: int
    ventas_en_borrador: int
    documentos_pendientes: int
    cierre_ciego: bool
    umbral_descuadre_centavos: int
    # Sólo viene si NO es ciego o si quien mira tiene permiso de verlo.
    esperado_por_medio: Optional[dict] = None


class ConteoEntrada(BaseModel):
    medio_pago_id: str
    contado_centavos: int = Field(ge=0)


class CerrarCajaEntrada(BaseModel):
    sesion_id: str
    conteos: List[ConteoEntrada]
    justificacion: Optional[str] = None


class CierreSalida(BaseModel):
    sesion_id: str
    numero_turno: int
    diferencia_centavos: int
    cuadro: bool
    autorizado_por: Optional[str] = None
    # El id sirve para la auditoría; a la pantalla hay que darle el NOMBRE.
    # «autorizado por laura» delata que nadie miró esa frase.
    autorizado_por_nombre: Optional[str] = None


@router.get("/caja/cierre/resumen", response_model=ResumenCierre)
async def resumen_cierre(
    sesion_id: str = Query(),
    uow=Depends(unidad_de_trabajo),
    usuario: CurrentUser = Depends(require_permission("retail", "ver")),
):
    """Lo que se ve antes de contar.

    EN CIERRE CIEGO NO VIENE EL ESPERADO. No es un olvido: si la cajera ve
    cuánto debería haber, escribe cuánto debería haber, y el arqueo deja de
    medir nada. Se revela al declarar el conteo, o antes si quien mira tiene
    permiso para verlo (un supervisor).
    """
    from sqlalchemy import text as _t

    async with uow as t:
        sesion = await t.turnos.cargar(sesion_id)
        datos = await t.turnos.resumen(sesion_id)
        borradores = await t.turnos.ventas_en_borrador(sesion_id)
        pendientes = await t.turnos.documentos_pendientes(sesion_id)
        cab = (await t.sesion.execute(_t("""
            SELECT s.numero_turno, s.abierta_en, s.base_inicial,
                   coalesce(p.nombre, s.abierta_por) AS cajera,
                   coalesce(pp.puede_ver_esperado, false) AS puede_ver
              FROM retail.sesiones_caja s
              LEFT JOIN retail.permisos_pos p ON p.usuario_id = s.abierta_por
              LEFT JOIN retail.permisos_pos pp ON pp.usuario_id = :quien
             WHERE s.id = :i
        """), {"i": sesion_id, "quien": usuario.id})).mappings().one()

    puede_ver = bool(cab["puede_ver"]) or not sesion.cierre_ciego
    esperado = None
    if puede_ver:
        esperado = {
            m: sesion.esperado_de(m, autorizado_a_ver=True).centavos
            for m in sesion.medios_movidos()
        }

    return ResumenCierre(
        sesion_id=sesion_id, numero_turno=cab["numero_turno"],
        cajera_nombre=cab["cajera"], abierta_en=cab["abierta_en"].isoformat(),
        transacciones=datos["transacciones"],
        ventas_brutas_centavos=datos["ventas_brutas"],
        descuentos_centavos=datos["descuentos"],
        anuladas=datos["anuladas"],
        monto_anulado_centavos=datos["monto_anulado"],
        medios=[MedioResumen(medio_pago_id=m["medio_pago_id"],
                             nombre=m["nombre"], es_efectivo=m["es_efectivo"],
                             entra_al_arqueo=m["entra_al_arqueo"],
                             total_centavos=int(m["total"]))
                for m in datos["medios"]],
        base_inicial_centavos=int(cab["base_inicial"]),
        ventas_en_borrador=borradores,
        documentos_pendientes=pendientes,
        cierre_ciego=sesion.cierre_ciego,
        umbral_descuadre_centavos=sesion.umbral_descuadre.centavos,
        esperado_por_medio=esperado,
    )


@router.post("/caja/cierre", response_model=CierreSalida)
async def cerrar_caja(
    entrada: CerrarCajaEntrada,
    uow=Depends(unidad_de_trabajo),
    usuario: CurrentUser = Depends(require_permission("retail", "modificar")),
):
    """Cierra el turno. Las reglas las pone el AGREGADO, no este endpoint.

    Si la diferencia supera el umbral exige justificación escrita y firma de
    un supervisor — un faltante sin explicación no se puede cerrar solo.
    """
    from datetime import datetime, timezone
    from sqlalchemy import text as _t
    from backend.modules.retail.domain.shared.dinero import Dinero

    ahora = datetime.now(timezone.utc)

    async with uow as t:
        sesion = await t.turnos.cargar(entrada.sesion_id)
        borradores = await t.turnos.ventas_en_borrador(entrada.sesion_id)
        pendientes = await t.turnos.documentos_pendientes(entrada.sesion_id)

        # El permiso lo trae quien tiene la sesión abierta. Ya no hay un PIN
        # que un tercero teclee: o este usuario puede cerrar con descuadre, o
        # tiene que entrar alguien que pueda, con su correo y contraseña.
        fila_permiso = (await t.sesion.execute(_t("""
            SELECT coalesce(puede_cerrar_con_descuadre, false) AS puede,
                   coalesce(nombre, usuario_id) AS nombre
              FROM retail.permisos_pos WHERE usuario_id = :u AND activo
        """), {"u": usuario.id})).mappings().first()
        puede_descuadre = bool(fila_permiso and fila_permiso["puede"])
        quien = fila_permiso["nombre"] if fila_permiso else usuario.nombre

        try:
            # `confirmado=True` porque la pantalla ya mostró los pendientes y
            # la cajera siguió: bloquear el cierre por una caída de Siigo
            # dejaría a la tienda sin poder cerrar.
            sesion.iniciar_arqueo(ventas_en_borrador=borradores,
                                  documentos_fiscales_pendientes=pendientes,
                                  confirmado=True)
            conteos = {}
            for c in entrada.conteos:
                monto = Dinero(c.contado_centavos, sesion.moneda)
                sesion.declarar_conteo(c.medio_pago_id, monto,
                                       usuario_id=usuario.id)
                conteos[c.medio_pago_id] = monto

            evento = sesion.cerrar(
                usuario_id=usuario.id, ahora=ahora,
                justificacion=entrada.justificacion,
                puede_cerrar_con_descuadre=puede_descuadre)
        except RequiereAutorizacion as e:
            raise HTTPException(403, {"error": "sin_permiso_descuadre",
                                      "mensaje": str(e),
                                      "accion_sugerida": "entrar_con_otro_usuario"})
        except ReglaDeNegocio as e:
            raise HTTPException(400, {"error": "regla_de_negocio",
                                      "mensaje": str(e)})

        await t.turnos.cerrar(
            sesion=sesion, conteos=conteos, usuario_id=usuario.id,
            justificacion=entrada.justificacion,
            autorizado_por=evento.autorizado_por, ahora=ahora)
        # Tres niveles, no dos. Marcar CRÍTICO cualquier diferencia —incluso
        # $100 de vuelto mal dado— llena el log de críticos todos los días, y
        # un log que siempre tiene críticos no lo revisa nadie: el descuadre
        # que sí importa se pierde entre el ruido. El umbral de la tienda ya
        # define cuál es «el que importa»; se usa ese mismo.
        if evento.cuadro:
            severidad = "info"
        elif abs(evento.diferencia.centavos) > sesion.umbral_descuadre.centavos:
            severidad = "critico"
        else:
            severidad = "aviso"

        await t.auditoria.registrar(
            evento="caja.cerrada", ocurrido_en=ahora,
            severidad=severidad,
            tienda_id=sesion.tienda_id, caja_id=sesion.caja_id,
            sesion_id=sesion.id, usuario_id=usuario.id,
            agregado_tipo="sesion_caja", agregado_id=sesion.id,
            payload={"numero_turno": sesion.numero_turno,
                     "diferencia": evento.diferencia.centavos,
                     "cuadro": evento.cuadro,
                     "justificacion": entrada.justificacion,
                     "cerrada_por": usuario.id})
        await t.commit()

    return CierreSalida(
        sesion_id=sesion.id, numero_turno=sesion.numero_turno,
        diferencia_centavos=evento.diferencia.centavos,
        cuadro=evento.cuadro, autorizado_por=evento.autorizado_por,
        autorizado_por_nombre=quien if evento.autorizado_por else None,
    )


# ── Inventario (vista 6 del handoff) ────────────────────────────────────────

class CeldaTallaSalida(BaseModel):
    talla: str
    disponible: int
    minimo: int
    es_bajo: bool


class FilaInventarioSalida(BaseModel):
    referencia: str
    nombre: str
    color: str
    categoria: str
    precio_con_iva_centavos: int
    tallas: List[CeldaTallaSalida]
    total: int
    en_otras_ubicaciones: int
    estado: str


class InventarioSalida(BaseModel):
    # Las columnas de talla VIENEN CON LOS DATOS. El handoff dibuja T24…T32
    # (tallaje americano); los SKU de MALE parsean a 4, 6, 8, 10, 12. Fijarlas
    # en la pantalla haría que una talla nueva no apareciera nunca.
    columnas_talla: List[str]
    filas: List[FilaInventarioSalida]
    umbral_tienda: int
    referencias: int
    con_stock_bajo: int
    categorias: List[str]


@router.get("/inventario", response_model=InventarioSalida)
async def consultar_inventario(
    ubicacion_id: str = Query(),
    tienda_id: str = Query(),
    q: str = Query("", max_length=120),
    categoria: str = Query(""),
    solo_bajos: bool = Query(False),
    uow=Depends(unidad_de_trabajo),
    usuario: CurrentUser = Depends(require_permission("retail", "ver")),
):
    """Stock por referencia y talla en ESTA ubicación.

    Es una consulta, no un comando: no reserva ni mueve nada. El número que
    devuelve ya descuenta lo reservado por otras cajas.
    """
    from backend.modules.retail.application.consultas.consultar_inventario import (
        ConsultarInventario,
    )
    from backend.modules.retail.application.consultas.listar_referencias import (
        ListarReferencias,
    )

    async with uow as t:
        inv = await ConsultarInventario(t.sesion).ejecutar(
            ubicacion_id=ubicacion_id, tienda_id=tienda_id, texto=q,
            categoria=categoria, solo_bajos=solo_bajos)
        categorias = await ListarReferencias(t.sesion).categorias()

    return InventarioSalida(
        columnas_talla=inv.columnas_talla,
        filas=[FilaInventarioSalida(
            referencia=f.referencia, nombre=f.nombre, color=f.color,
            categoria=f.categoria,
            precio_con_iva_centavos=f.precio_con_iva_centavos,
            tallas=[CeldaTallaSalida(talla=c.talla, disponible=c.disponible,
                                     minimo=c.minimo, es_bajo=c.es_bajo)
                    for c in f.tallas],
            total=f.total, en_otras_ubicaciones=f.en_otras_ubicaciones,
            estado=f.estado,
        ) for f in inv.filas],
        umbral_tienda=inv.umbral_tienda,
        referencias=inv.referencias, con_stock_bajo=inv.con_stock_bajo,
        categorias=categorias,
    )


# ── Panel de ventas del día (vista 8 del handoff) ───────────────────────────

class BarraHoraSalida(BaseModel):
    hora: int
    etiqueta: str
    ventas_centavos: int
    transacciones: int


class MasVendidoSalida(BaseModel):
    posicion: int
    referencia: str
    nombre: str
    color: str
    unidades: int
    valor_centavos: int


class PanelSalida(BaseModel):
    # La fecha viaja porque es la de LA TIENDA, no la del navegador. Un panel
    # que no dice de qué día habla es una cifra sin contexto — y el corte del
    # día en UTC−5 no coincide con el del servidor.
    fecha: str
    tienda_nombre: str
    ventas_centavos: int
    transacciones: int
    ticket_promedio_centavos: int
    unidades: int
    anuladas: int
    monto_anulado_centavos: int
    descuentos_centavos: int
    horas: List[BarraHoraSalida]
    mas_vendidos: List[MasVendidoSalida]


@router.get("/panel", response_model=PanelSalida)
async def panel_del_dia(
    tienda_id: str = Query(),
    uow=Depends(unidad_de_trabajo),
    usuario: CurrentUser = Depends(require_permission("retail", "ver")),
):
    """Cómo va el día en ESTA tienda."""
    from backend.modules.retail.application.consultas.panel_ventas import (
        PanelVentas,
    )

    try:
        async with uow as t:
            p = await PanelVentas(t.sesion).ejecutar(tienda_id=tienda_id)
    except ReglaDeNegocio as e:
        raise HTTPException(400, {"error": "regla_de_negocio",
                                  "mensaje": str(e)})

    return PanelSalida(
        fecha=p.fecha, tienda_nombre=p.tienda_nombre,
        ventas_centavos=p.ventas_centavos, transacciones=p.transacciones,
        ticket_promedio_centavos=p.ticket_promedio_centavos,
        unidades=p.unidades, anuladas=p.anuladas,
        monto_anulado_centavos=p.monto_anulado_centavos,
        descuentos_centavos=p.descuentos_centavos,
        horas=[BarraHoraSalida(hora=h.hora, etiqueta=h.etiqueta,
                               ventas_centavos=h.ventas_centavos,
                               transacciones=h.transacciones) for h in p.horas],
        mas_vendidos=[MasVendidoSalida(
            posicion=m.posicion, referencia=m.referencia, nombre=m.nombre,
            color=m.color, unidades=m.unidades,
            valor_centavos=m.valor_centavos) for m in p.mas_vendidos],
    )


# ── La tirilla ──────────────────────────────────────────────────────────────

class LineaTirillaSalida(BaseModel):
    sku: str
    descripcion: str
    cantidad: int
    precio_unitario_centavos: int
    descuento_centavos: int
    descuento_motivo: Optional[str] = None
    total_centavos: int


class PagoTirillaSalida(BaseModel):
    nombre: str
    monto_centavos: int
    referencia: Optional[str] = None


class TirillaSalida(BaseModel):
    razon_social: str
    nit: str
    direccion: str
    telefono: str
    tienda_nombre: str
    resolucion_dian: Optional[str] = None
    mensaje: Optional[str] = None
    numero: str
    fecha: str
    caja_nombre: str
    cajera_nombre: str
    cliente_nombre: Optional[str] = None
    cliente_documento: Optional[str] = None
    lineas: List[LineaTirillaSalida]
    pagos: List[PagoTirillaSalida]
    subtotal_centavos: int
    descuento_centavos: int
    total_centavos: int
    base_gravable_centavos: int
    iva_centavos: int
    pagado_centavos: int
    vuelto_centavos: int
    unidades: int
    estado_fiscal: str
    documento_fiscal: Optional[str] = None
    cufe: Optional[str] = None
    anulada: bool
    # El QR ya dibujado: `qr_ruta` es el atributo `d` de un <path> SVG. Se
    # genera en el servidor, junto a los datos fiscales — un QR mal codificado
    # en un papel fiscal es peor que no tenerlo, y nadie lo descubre hasta que
    # alguien lo escanea. Viene vacío mientras no haya documento emitido.
    qr_contenido: Optional[str] = None
    qr_ruta: Optional[str] = None
    qr_modulos: int = 0
    # Decide el encabezado del papel. Si es False, la tirilla se imprime como
    # COMPROBANTE INTERNO y lo dice: un papel con pinta de documento fiscal
    # que no lo es convierte un problema de software en uno con la DIAN.
    es_documento_fiscal: bool


@router.get("/ventas/{venta_id}/tirilla", response_model=TirillaSalida)
async def tirilla(
    venta_id: str,
    uow=Depends(unidad_de_trabajo),
    usuario: CurrentUser = Depends(require_permission("retail", "ver")),
):
    """Lo que se imprime, LEÍDO DE LA BASE.

    No se arma desde el carrito que la pantalla todavía tiene en memoria: la
    tirilla es el comprobante de lo que quedó registrado. Si el servidor guardó
    algo distinto —un redondeo, una línea que no entró—, el papel tiene que
    decir lo que quedó, no lo que la pantalla creía.

    Es también lo que permite reimprimir tres días después, que es cuando la
    clienta vuelve a cambiar la prenda.
    """
    from backend.modules.retail.application.consultas.tirilla import ArmarTirilla

    try:
        async with uow as t:
            d = await ArmarTirilla(t.sesion).ejecutar(venta_id)
    except ReglaDeNegocio as e:
        raise HTTPException(404, {"error": "no_encontrada", "mensaje": str(e)})

    return TirillaSalida(
        razon_social=d.razon_social, nit=d.nit, direccion=d.direccion,
        telefono=d.telefono, tienda_nombre=d.tienda_nombre,
        resolucion_dian=d.resolucion_dian, mensaje=d.mensaje,
        numero=d.numero, fecha=d.fecha, caja_nombre=d.caja_nombre,
        cajera_nombre=d.cajera_nombre, cliente_nombre=d.cliente_nombre,
        cliente_documento=d.cliente_documento,
        lineas=[LineaTirillaSalida(
            sku=l.sku, descripcion=l.descripcion, cantidad=l.cantidad,
            precio_unitario_centavos=l.precio_unitario_centavos,
            descuento_centavos=l.descuento_centavos,
            descuento_motivo=l.descuento_motivo,
            total_centavos=l.total_centavos) for l in d.lineas],
        pagos=[PagoTirillaSalida(nombre=p.nombre, monto_centavos=p.monto_centavos,
                                 referencia=p.referencia) for p in d.pagos],
        subtotal_centavos=d.subtotal_centavos,
        descuento_centavos=d.descuento_centavos,
        total_centavos=d.total_centavos,
        base_gravable_centavos=d.base_gravable_centavos,
        iva_centavos=d.iva_centavos, pagado_centavos=d.pagado_centavos,
        vuelto_centavos=d.vuelto_centavos, unidades=d.unidades,
        estado_fiscal=d.estado_fiscal, documento_fiscal=d.documento_fiscal,
        cufe=d.cufe, anulada=d.anulada,
        qr_contenido=d.qr_contenido, qr_ruta=d.qr_ruta,
        qr_modulos=d.qr_modulos,
        es_documento_fiscal=d.es_documento_fiscal,
    )


# ── Consecutivos ────────────────────────────────────────────────────────────

class BloqueSalida(BaseModel):
    prefijo: str
    desde: int
    hasta: int
    siguiente: int


@router.post("/caja/consecutivos", response_model=BloqueSalida)
async def arrendar_bloque(
    caja_id: str = Query(),
    dispositivo_id: Optional[str] = Query(None),
    uow=Depends(unidad_de_trabajo),
    usuario: CurrentUser = Depends(require_permission("retail", "modificar")),
):
    """Arrienda el bloque siguiente. Lo pide el dispositivo al 80 % consumido.

    Al 80 % y no al agotarse: si se espera al último número, la petición cae
    justo cuando ya no quedan, y si en ese momento no hay red la caja se queda
    sin poder vender.
    """
    async with uow as t:
        prefijo = await _prefijo_de(t, caja_id)
        bloque = await t.consecutivos.arrendar(
            caja_id=caja_id, prefijo=prefijo, dispositivo_id=dispositivo_id)
        await t.commit()

    return BloqueSalida(prefijo=bloque["prefijo"], desde=bloque["desde"],
                        hasta=bloque["hasta"], siguiente=bloque["siguiente"])


async def _anotar_equipo(t, entrada, usuario_id: str) -> None:
    """Deja constancia del equipo antes de arrendarle numeración.

    El bloque referencia al dispositivo, así que tiene que existir primero.
    Si la pantalla no manda id —un cliente viejo— se sigue igual: el bloque
    queda sin dueño y se comporta como antes.
    """
    if not entrada.dispositivo_id:
        return
    await t.consecutivos.registrar_dispositivo(
        dispositivo_id=entrada.dispositivo_id, caja_id=entrada.caja_id,
        nombre=entrada.dispositivo_nombre or "Equipo sin nombre",
        usuario_id=usuario_id)


async def _prefijo_de(t, caja_id: str) -> str:
    """El de Siigo si ya está confirmado; si no, uno local.

    `cajas.prefijo_factura` nace NULL a propósito: el sistema se niega a
    facturar con un prefijo adivinado. Pero el número del TIQUETE no es el
    fiscal —ese lo asigna Siigo al emitir— así que la caja puede numerar desde
    el primer día con un prefijo propio. El día que Siigo quede configurado, el
    prefijo cambia y la numeración simplemente arranca de nuevo bajo el nuevo:
    el índice único es por (caja, prefijo, consecutivo).
    """
    from sqlalchemy import text as _t
    return (await t.sesion.execute(_t("""
        SELECT coalesce(prefijo_factura, 'POS') FROM retail.cajas WHERE id = :c
    """), {"c": caja_id})).scalar() or "POS"
