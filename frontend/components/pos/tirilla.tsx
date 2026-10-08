"use client";

/**
 * La tirilla — 80 mm de papel térmico.
 *
 * **Por qué `window.print()` y no ESC/POS.** Mandar comandos crudos a la
 * impresora desde el navegador exige un puente nativo instalado en cada
 * equipo, y eso es una cosa más que se rompe un sábado. Con `@page` a 80 mm,
 * cualquier térmica que el sistema ya tenga instalada imprime bien y sin
 * driver propio. Se pierde el corte automático de papel; se gana no tener un
 * agente que mantener en cinco equipos.
 *
 * **Por qué se imprime desde el DOM y no desde un PDF del servidor.** Generar
 * el PDF cuesta un viaje más justo en el momento en que la clienta está
 * esperando. Los datos ya vienen del servidor; el papel se arma aquí.
 *
 * **80 mm útiles son 72 mm.** El resto es margen mecánico del cabezal. Todo
 * lo que se pase de ahí sale cortado, y eso no se ve hasta que se imprime.
 */
import { formatear } from "@/lib/pos/dinero";
import type { Tirilla as Datos } from "@/lib/pos/api";
// IMPORTADO, no servido desde `/public`: así Next lo deja bajo
// `/_next/static/`, que es lo único que el service worker guarda. Desde
// `/public` el logo desaparecería de la tirilla justo cuando no hay red.
import logo from "./logo-male-denim.png";

// Se pide al cargar la pantalla de venta, no al imprimir: la tirilla se manda
// a la impresora 60 ms después de pintarse, y una imagen que todavía viene en
// camino sale como un hueco en blanco en el papel.
if (typeof window !== "undefined") {
  new window.Image().src = logo.src;
}

/** El «tercero» de las ventas sin clienta. Una factura siempre lleva
 *  adquiriente; cuando nadie dio sus datos, es éste. */
const CONSUMIDOR_FINAL = { nombre: "Consumidor final", documento: "222222222222" };

export function Tirilla({ datos }: { datos: Datos }) {
  const fiscal = datos.es_documento_fiscal;
  return (
    <div className="tirilla" aria-label={fiscal ? "Factura electrónica de venta" : "Comprobante de venta"}>
      <style>{ESTILOS}</style>

      <header className="t-centro">
        {/* `<img>` a secas: `next/image` lo cargaría perezoso y con su propio
            optimizador, dos cosas que en un papel que sale en 60 ms sobran.
            La razón social va debajo SIEMPRE: el logo es la marca, y quien
            factura es la sociedad. */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img className="t-logo" src={logo.src} alt="MALE DENIM" />
        <div className="t-fuerte t-grande">{datos.razon_social}</div>
        {datos.nit && <div>NIT {datos.nit}</div>}
        <div>{datos.tienda_nombre}</div>
        {datos.direccion && <div>{datos.direccion}</div>}
        {datos.telefono && <div>Tel. {datos.telefono}</div>}
      </header>

      <div className="t-sep" />

      {/* EL ENCABEZADO DICE LA VERDAD. Sin resolución DIAN y sin documento
          emitido, esto no ampara nada ante la DIAN y va escrito. Un papel con
          pinta de factura que no lo es es un problema peor que no imprimir. */}
      <div className="t-centro t-fuerte">
        {fiscal ? "FACTURA ELECTRÓNICA DE VENTA" : "COMPROBANTE DE VENTA"}
      </div>
      {fiscal ? (
        // EL NÚMERO DE LA FACTURA ES EL DE SIIGO, el que la DIAN validó bajo
        // la resolución de la tienda. El del POS baja a referencia interna:
        // dos números con la misma jerarquía en un papel fiscal es la forma
        // de que alguien cite el que no es.
        <div className="t-centro t-fuerte t-grande">No. {datos.documento_fiscal}</div>
      ) : (
        <div className="t-centro t-chico">
          Documento interno · no válido como factura
        </div>
      )}

      <div className="t-sep" />

      {fiscal ? (
        <>
          <div className="t-fila">
            <span>Fecha generación</span>
            <span>{datos.fecha}</span>
          </div>
          <div className="t-fila">
            <span>Fecha expedición</span>
            <span>{datos.fecha_expedicion || datos.fecha}</span>
          </div>
          <div className="t-fila t-chico">
            <span>Ref. interna</span>
            <span>{datos.numero}</span>
          </div>
        </>
      ) : (
        <>
          <div className="t-fila">
            <span>No.</span>
            <span className="t-fuerte">{datos.numero}</span>
          </div>
          <div className="t-fila">
            <span>Fecha</span>
            <span>{datos.fecha}</span>
          </div>
        </>
      )}
      <div className="t-fila">
        <span>Caja</span>
        <span>{datos.caja_nombre}</span>
      </div>
      <div className="t-fila">
        <span>Atendió</span>
        <span>{datos.cajera_nombre}</span>
      </div>
      {datos.cliente_nombre ? (
        <>
          <div className="t-fila">
            <span>Cliente</span>
            <span>{datos.cliente_nombre}</span>
          </div>
          {datos.cliente_documento && (
            <div className="t-fila">
              <span>C.C / NIT</span>
              <span>{datos.cliente_documento}</span>
            </div>
          )}
        </>
      ) : fiscal ? (
        // Una factura no sale «sin cliente»: sale a consumidor final, que es
        // exactamente a quien se le emitió en Siigo.
        <>
          <div className="t-fila">
            <span>Cliente</span>
            <span>{CONSUMIDOR_FINAL.nombre}</span>
          </div>
          <div className="t-fila">
            <span>C.C / NIT</span>
            <span>{CONSUMIDOR_FINAL.documento}</span>
          </div>
        </>
      ) : null}

      {datos.anulada && (
        <div className="t-anulada t-centro t-fuerte">*** ANULADA ***</div>
      )}

      <div className="t-sep" />

      {datos.lineas.map((l, i) => (
        <div key={`${l.sku}-${i}`} className="t-linea">
          <div>{l.descripcion}</div>
          <div className="t-fila t-chico">
            <span>
              {l.sku} · {l.cantidad} x {formatear(l.precio_unitario_centavos)}
            </span>
            <span className="t-fuerte">{formatear(l.total_centavos)}</span>
          </div>
          {l.descuento_centavos > 0 && (
            <div className="t-fila t-chico t-sangria">
              {/* El motivo va IMPRESO. Es lo que permite que un descuento se
                  pueda revisar después sin abrir la auditoría. */}
              <span>dcto {l.descuento_motivo || ""}</span>
              <span>−{formatear(l.descuento_centavos)}</span>
            </div>
          )}
        </div>
      ))}

      <div className="t-sep" />

      {/* EL BLOQUE DE IMPUESTOS, como la tirilla real. Con una sola tarifa
          parece redundante; con dos es lo único que permite cuadrar la factura
          contra la declaración. */}
      {datos.impuestos.length > 0 && (
        <>
          <div className="t-fila t-chico">
            <span>Impuesto</span>
            <span>Base</span>
          </div>
          {datos.impuestos.map((i) => (
            <div key={i.tasa} className="t-fila t-chico">
              <span>IVA {tasaCorta(i.tasa)}%</span>
              <span>{formatear(i.base_centavos)}</span>
            </div>
          ))}
          <div className="t-sep-fino" />
        </>
      )}

      <div className="t-fila">
        <span>Total ítems</span>
        <span>{datos.unidades}</span>
      </div>
      {/* «SUBTOTAL» ES ANTES DE IVA — como en la tirilla que MALE imprime hoy.
          Aquí decía «Subtotal» al total CON IVA: la misma palabra con dos
          significados en papeles de la misma tienda, y quien cuadra el día
          encuentra números que no casan. El cálculo no cambió; la presentación
          sí. Ver docs/retail-pos/tirilla-real-siigo.md */}
      <div className="t-fila">
        <span>Total bruto</span>
        <span>{formatear(datos.total_bruto_centavos)}</span>
      </div>
      {datos.descuento_base_centavos > 0 && (
        <div className="t-fila">
          <span>Descuentos</span>
          <span>−{formatear(datos.descuento_base_centavos)}</span>
        </div>
      )}
      <div className="t-fila">
        <span>Subtotal</span>
        <span>{formatear(datos.base_gravable_centavos)}</span>
      </div>
      <div className="t-fila">
        <span>IVA {tasaCorta(datos.impuestos[0]?.tasa ?? "19")}%</span>
        <span>{formatear(datos.iva_centavos)}</span>
      </div>

      <div className="t-sep" />

      <div className="t-fila t-total">
        <span>TOTAL A PAGAR</span>
        <span>{formatear(datos.total_centavos)}</span>
      </div>

      <div className="t-sep-fino" />

      {fiscal && (
        // FORMA y MEDIO son dos cosas en una factura: contado o crédito, y
        // con qué se pagó. En el mostrador siempre es de contado.
        <div className="t-fila">
          <span>Forma de pago</span>
          <span>Contado</span>
        </div>
      )}
      {datos.pagos.map((p, i) => (
        <div key={i} className="t-fila">
          <span>
            {p.nombre}
            {p.referencia ? ` ${p.referencia}` : ""}
          </span>
          <span>{formatear(p.monto_centavos)}</span>
        </div>
      ))}
      {datos.vuelto_centavos > 0 && (
        <div className="t-fila t-fuerte">
          <span>Cambio</span>
          <span>{formatear(datos.vuelto_centavos)}</span>
        </div>
      )}

      <div className="t-sep" />

      <div className="t-centro t-chico">
        {datos.unidades} {datos.unidades === 1 ? "prenda" : "prendas"}
      </div>

      {fiscal ? (
        <>
          {datos.qr_ruta && (
            // El QR es lo que la gente escanea; el CUFE en texto es el
            // respaldo para cuando el papel térmico se borra y el código deja
            // de leerse, que en un bolsillo pasa en semanas.
            <div className="t-qr">
              <svg
                viewBox={`0 0 ${datos.qr_modulos} ${datos.qr_modulos}`}
                width="30mm"
                height="30mm"
                shapeRendering="crispEdges"
                role="img"
                aria-label="Código QR para verificar el documento ante la DIAN"
              >
                <rect width={datos.qr_modulos} height={datos.qr_modulos} fill="#fff" />
                <path d={datos.qr_ruta} fill="#000" />
              </svg>
              <div className="t-chico">Verifique este documento ante la DIAN</div>
            </div>
          )}
          {datos.cufe && (
            // El CUFE va partido: son 96 caracteres y en 72 mm no cabe de
            // corrido. Cortarlo con overflow lo dejaría ilegible justo cuando
            // alguien necesita verificarlo.
            <div className="t-cufe">
              CUFE
              <br />
              {datos.cufe.match(/.{1,32}/g)?.map((trozo, i) => (
                <span key={i}>
                  {trozo}
                  <br />
                </span>
              ))}
            </div>
          )}
          {/* LO QUE LA NORMA PIDE AL PIE, en el orden de la tirilla que MALE
              ya imprime desde Siigo: calidad tributaria, la autorización de
              numeración que ampara este número, y quién es el proveedor
              tecnológico. Ver docs/retail-pos/tirilla-real-siigo.md */}
          <div className="t-sep-fino" />
          {datos.regimen && <div className="t-centro t-chico">{datos.regimen}.</div>}
          {datos.resolucion_dian && (
            <div className="t-centro t-chico">{datos.resolucion_dian}</div>
          )}
          <div className="t-centro t-chico t-legal">
            Fabricante de software y proveedor tecnológico: Siigo S.A.S. - Nit:
            830.048.145-8. Nombre del software: Siigo Nube
          </div>
        </>
      ) : datos.factura_en_camino ? (
        // SÓLO SI DE VERDAD VIENE. Este papel decía «la factura electrónica
        // se envía por correo» en CADA venta, cuando la tienda no emitía: una
        // promesa falsa impresa. Ahora sale únicamente cuando la factura está
        // en trámite, y dice qué hacer con este papel mientras tanto.
        <div className="t-centro t-chico">
          Factura electrónica en trámite ante la DIAN. Este comprobante no la
          reemplaza: pídala en caja.
        </div>
      ) : null}

      {datos.mensaje && (
        <>
          <div className="t-sep-fino" />
          <div className="t-centro t-chico">{datos.mensaje}</div>
        </>
      )}

      <div className="t-centro t-chico t-pie">
        {fiscal
          ? "Conserve esta factura para cambios."
          : "Conserve este comprobante para cambios."}
      </div>
      {/* Papel de sobra al final: sin corte automático, la térmica deja el
          último renglón dentro del mecanismo y hay que tirar del papel. */}
      <div className="t-avance" />
    </div>
  );
}

const ESTILOS = `
.tirilla {
  /* 80 mm de papel, 72 mm imprimibles. El resto es margen del cabezal y lo
     que se pase de ahí sale cortado — y eso no se ve hasta imprimir. */
  width: 72mm;
  margin: 0 auto;
  padding: 2mm 0;
  font-family: ui-monospace, "SFMono-Regular", "Menlo", monospace;
  font-size: 10.5px;
  line-height: 1.35;
  color: #000;
  background: #fff;
}
.tirilla .t-centro   { text-align: center; }
/* 34 mm de ancho: en una térmica de 203 dpi son ~270 puntos, de sobra para
   que el trazo fino de «MALE» no se rompa, sin comerse el papel. */
.tirilla .t-logo     { display: block; width: 34mm; height: auto;
                       margin: 0 auto 1.5mm; }
.tirilla .t-fuerte   { font-weight: 700; }
.tirilla .t-grande   { font-size: 13px; letter-spacing: .03em; }
.tirilla .t-chico    { font-size: 9.5px; }
.tirilla .t-sangria  { padding-left: 3mm; }
.tirilla .t-fila     { display: flex; justify-content: space-between; gap: 2mm; }
.tirilla .t-fila > span:last-child { white-space: nowrap; }
.tirilla .t-linea    { margin-bottom: 1.2mm; }
.tirilla .t-total    { font-size: 14px; font-weight: 700; }
.tirilla .t-sep      { border-top: 1px dashed #000; margin: 1.5mm 0; }
.tirilla .t-sep-fino { border-top: 1px dotted #999; margin: 1.5mm 0; }
.tirilla .t-anulada  { margin: 1.5mm 0; letter-spacing: .1em; }
.tirilla .t-cufe     { font-size: 8px; word-break: break-all; text-align: center;
                       margin-top: 1mm; }
/* 30 mm de QR. Una térmica de 203 dpi da 8 puntos por mm: con 53 módulos salen
   ~4,5 puntos por módulo, por encima del mínimo para que un lector lo agarre.
   Más pequeño deja de escanearse; más grande se come el papel. */
.tirilla .t-qr       { text-align: center; margin: 2mm 0 1mm; }
.tirilla .t-qr svg   { display: block; margin: 0 auto 1mm; }
.tirilla .t-legal    { margin-top: 1mm; }
.tirilla .t-pie      { margin-top: 2mm; }
.tirilla .t-avance   { height: 12mm; }

@media print {
  /* Alto automático: la tirilla mide lo que mida la venta. Fijarlo cortaría
     las ventas largas o desperdiciaría papel en las de una prenda. */
  @page { size: 80mm auto; margin: 0; }
  html, body { width: 80mm; margin: 0 !important; padding: 0 !important;
               background: #fff !important; }
  /* Sólo el papel. Sin esto se imprime el POS entero detrás. */
  body * { visibility: hidden; }
  .tirilla, .tirilla * { visibility: visible; }
  .tirilla { position: absolute; left: 0; top: 0; }
}
`;

/** «19.00» → «19». La tarifa llega como NUMERIC(5,2) de la base y los ceros de
 *  la escala son ruido en un papel de 80 mm — la tirilla real dice «IVA 19%».
 *  Se recortan sólo los decimales vacíos: un 5,5 % tiene que seguir saliendo. */
function tasaCorta(t: string): string {
  return String(Number(t)).replace(".", ",");
}
