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
from backend.modules.retail.application.comandos.autorizar import (
    PinBloqueado,
    PinInvalido,
    ValidarPin,
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
    autorizado_por: Optional[str] = None
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
    tope_descuento: str = "0"
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
        venta, variante_por_sku = await _armar(entrada, uow)
        resultado = await CerrarVenta(uow, reloj=RelojDelSistema()).ejecutar(
            venta, variante_por_sku=variante_por_sku,
            ubicacion_id=entrada.ubicacion_id, usuario_id=usuario.id)
    except RequiereAutorizacion as e:
        # 403 con una bandera para que la pantalla abra el diálogo del PIN en
        # vez de mostrar un error rojo: la operación es posible, sólo falta
        # que alguien la firme.
        raise HTTPException(403, {"error": "requiere_autorizacion",
                                  "mensaje": str(e),
                                  "accion_sugerida": "pedir_autorizacion"})
    except ReglaDeNegocio as e:
        raise HTTPException(400, {"error": "regla_de_negocio",
                                  "mensaje": str(e)})

    return TicketSalida(
        venta_id=resultado.venta_id, numero=resultado.numero,
        total_centavos=resultado.total_centavos,
        pagado_centavos=venta.pagado().centavos,
        vuelto_centavos=resultado.vuelto_centavos,
        iva_centavos=venta.iva_total().centavos,
        descuento_centavos=venta.descuento_total().centavos,
        estado_fiscal=resultado.estado_fiscal,
    )


async def _armar(entrada: VentaEntrada, uow) -> tuple:
    """Reconstruye el agregado desde el cuerpo de la petición.

    Los precios los manda el dispositivo porque los congeló al agregar la
    prenda al carrito. Cambiar el precio del catálogo a mitad de una venta no
    puede cambiar lo que la cajera ya le dijo a la clienta.
    """
    venta = Venta.abrir(
        id=entrada.venta_id, numero=entrada.numero, tienda_id=entrada.tienda_id,
        caja_id=entrada.caja_id, sesion_id=entrada.sesion_id,
        cajera_id="", moneda=entrada.moneda,
        dispositivo_id=entrada.dispositivo_id)
    if entrada.cliente_id:
        venta.asignar_cliente(entrada.cliente_id)

    skus = [l.sku for l in entrada.lineas]
    async with uow as t:
        from sqlalchemy import text as _t
        filas = (await t.sesion.execute(_t("""
            SELECT id, sku FROM retail.variantes WHERE sku = ANY(:skus)
        """), {"skus": skus})).mappings().all()
    variante_por_sku = {f["sku"]: f["id"] for f in filas}

    faltan = [s for s in skus if s not in variante_por_sku]
    if faltan:
        raise ReglaDeNegocio(
            f"Estas referencias no están en el catálogo: {', '.join(faltan)}")

    tope = Decimal(entrada.tope_descuento)
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
            venta.marcar_obsequio(linea.numero,
                                  autorizado_por=entrada_linea.autorizado_por)
        elif entrada_linea.descuento_porcentaje or entrada_linea.descuento_valor_centavos:
            venta.aplicar_descuento_linea(
                linea.numero, _descuento(entrada_linea, entrada.moneda),
                tope_de_quien_aplica=tope,
                autorizado_por=entrada_linea.autorizado_por)

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

class PinEntrada(BaseModel):
    pin: str = Field(min_length=4, max_length=6)
    tienda_id: str


class AutorizacionSalida(BaseModel):
    autorizado_por: str
    nombre: str
    tope_descuento_pct: str


@router.post("/autorizacion", response_model=AutorizacionSalida)
async def autorizar(
    entrada: PinEntrada,
    uow=Depends(unidad_de_trabajo),
    _: CurrentUser = Depends(require_permission("retail", "ver")),
):
    """Valida el PIN de un supervisor y devuelve quién firma.

    NO devuelve un token ni abre una sesión: sólo dice quién autorizó ESTA
    operación, y ese nombre viaja con la venta hasta la auditoría. Una firma
    que sirviera para varias operaciones dejaría de ser una firma.

    VA SOBRE LA UNIDAD DE TRABAJO, no sobre una sesión de lectura, porque
    escribe: pone el contador de intentos en cero al acertar y lo sube al
    fallar. Con una sesión sin commit esos incrementos se revertían al cerrar
    —o sea que el bloqueo por intentos no existía y el PIN se podía adivinar
    sin límite. Lo encontró una prueba, no la operación.

    El commit ocurre TAMBIÉN en el camino de error: si se revirtiera al
    rechazar, cada intento fallido borraría la cuenta del anterior.
    """
    from datetime import datetime, timezone

    async with uow as t:
        try:
            a = await ValidarPin(t.sesion).ejecutar(
                pin=entrada.pin, tienda_id=entrada.tienda_id,
                ahora=datetime.now(timezone.utc))
        except (PinBloqueado, PinInvalido) as e:
            await t.commit()          # ← conserva el intento fallido
            if isinstance(e, PinBloqueado):
                raise HTTPException(429, {"error": "pin_bloqueado",
                                          "mensaje": str(e)})
            raise HTTPException(403, {"error": "pin_invalido", "mensaje": str(e)})
        await t.commit()

    return AutorizacionSalida(
        autorizado_por=a.usuario_id, nombre=a.nombre,
        tope_descuento_pct=str(a.tope_descuento_pct),
    )


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


class AbrirTurnoEntrada(BaseModel):
    """Sin PIN: quién abre el turno sale del JWT, y ese JWT viene del login del
    ERP con correo y contraseña."""

    sesion_id: str = Field(description="ULID generado en el dispositivo")
    tienda_id: str
    caja_id: str


@router.get("/caja/turno-actual", response_model=Optional[TurnoSalida])
async def turno_actual(
    caja_id: str = Query(),
    uow=Depends(unidad_de_trabajo),
    _: CurrentUser = Depends(require_permission("retail", "ver")),
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

    return TurnoSalida(
        sesion_id=abierta["id"], numero_turno=abierta["numero_turno"],
        tienda_id=abierta["tienda_id"], caja_id=caja_id,
        cajera_id=abierta["abierta_por"],
        cajera_nombre=abierta["cajera_nombre"],
        tope_descuento_pct=str(tope or 0),
        base_inicial_centavos=int(abierta["base_inicial"]), reanudado=True,
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
            return TurnoSalida(
                sesion_id=ya["id"], numero_turno=ya["numero_turno"],
                tienda_id=ya["tienda_id"], caja_id=entrada.caja_id,
                cajera_id=ya["abierta_por"], cajera_nombre=ya["cajera_nombre"],
                tope_descuento_pct=str(tope or 0),
                base_inicial_centavos=int(ya["base_inicial"]), reanudado=True,
            )

        try:
            base = await t.turnos.base_de_tienda(entrada.tienda_id)
            turno = await t.turnos.abrir(
                sesion_id=entrada.sesion_id, tienda_id=entrada.tienda_id,
                caja_id=entrada.caja_id, usuario_id=usuario.id,
                base_inicial=base, ahora=ahora)
            await t.auditoria.registrar(
                evento="caja.abierta", ocurrido_en=ahora,
                tienda_id=entrada.tienda_id, caja_id=entrada.caja_id,
                sesion_id=entrada.sesion_id, usuario_id=usuario.id,
                agregado_tipo="sesion_caja", agregado_id=entrada.sesion_id,
                payload={"numero_turno": turno["numero_turno"],
                         "base_inicial": base})
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
    )


class ContextoCaja(BaseModel):
    tienda_id: str
    tienda_nombre: str
    caja_id: str
    caja_nombre: str
    base_caja_centavos: int
    ubicacion_id: Optional[str] = None


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
    pin_autorizacion: Optional[str] = None


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
    from backend.modules.retail.application.comandos.autorizar import (
        PinInvalido,
        ValidarPin,
    )
    from backend.modules.retail.domain.shared.dinero import Dinero

    ahora = datetime.now(timezone.utc)

    async with uow as t:
        sesion = await t.turnos.cargar(entrada.sesion_id)
        borradores = await t.turnos.ventas_en_borrador(entrada.sesion_id)
        pendientes = await t.turnos.documentos_pendientes(entrada.sesion_id)

        autorizado_por = None
        autorizado_nombre = None
        if entrada.pin_autorizacion:
            try:
                firma = await ValidarPin(t.sesion).ejecutar(
                    pin=entrada.pin_autorizacion, tienda_id=sesion.tienda_id,
                    ahora=ahora)
                autorizado_por = firma.usuario_id
                autorizado_nombre = firma.nombre
            except PinInvalido as e:
                await t.commit()      # conserva el intento fallido
                raise HTTPException(403, {"error": "pin_invalido",
                                          "mensaje": str(e)})

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

            evento = sesion.cerrar(usuario_id=usuario.id, ahora=ahora,
                                   justificacion=entrada.justificacion,
                                   autorizado_por=autorizado_por)
        except RequiereAutorizacion as e:
            raise HTTPException(403, {"error": "requiere_autorizacion",
                                      "mensaje": str(e),
                                      "accion_sugerida": "pedir_autorizacion"})
        except ReglaDeNegocio as e:
            raise HTTPException(400, {"error": "regla_de_negocio",
                                      "mensaje": str(e)})

        await t.turnos.cerrar(
            sesion=sesion, conteos=conteos, usuario_id=usuario.id,
            justificacion=entrada.justificacion, autorizado_por=autorizado_por,
            ahora=ahora)
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
                     "autorizado_por": autorizado_por})
        await t.commit()

    return CierreSalida(
        sesion_id=sesion.id, numero_turno=sesion.numero_turno,
        diferencia_centavos=evento.diferencia.centavos,
        cuadro=evento.cuadro, autorizado_por=autorizado_por,
        autorizado_por_nombre=autorizado_nombre,
    )
