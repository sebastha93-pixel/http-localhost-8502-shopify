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

export function Tirilla({ datos }: { datos: Datos }) {
  return (
    <div className="tirilla" aria-label="Comprobante de venta">
      <style>{ESTILOS}</style>

      <header className="t-centro">
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
        {datos.es_documento_fiscal
          ? "FACTURA ELECTRÓNICA DE VENTA"
          : "COMPROBANTE DE VENTA"}
      </div>
      {datos.es_documento_fiscal && datos.resolucion_dian && (
        <div className="t-centro t-chico">{datos.resolucion_dian}</div>
      )}
      {!datos.es_documento_fiscal && (
        <div className="t-centro t-chico">
          Documento interno · no válido como factura
        </div>
      )}

      <div className="t-sep" />

      <div className="t-fila">
        <span>No.</span>
        <span className="t-fuerte">{datos.numero}</span>
      </div>
      <div className="t-fila">
        <span>Fecha</span>
        <span>{datos.fecha}</span>
      </div>
      <div className="t-fila">
        <span>Caja</span>
        <span>{datos.caja_nombre}</span>
      </div>
      <div className="t-fila">
        <span>Atendió</span>
        <span>{datos.cajera_nombre}</span>
      </div>
      {datos.cliente_nombre && (
        <>
          <div className="t-fila">
            <span>Clienta</span>
            <span>{datos.cliente_nombre}</span>
          </div>
          {datos.cliente_documento && (
            <div className="t-fila">
              <span>Documento</span>
              <span>{datos.cliente_documento}</span>
            </div>
          )}
        </>
      )}

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

      <div className="t-fila">
        <span>Subtotal</span>
        <span>{formatear(datos.subtotal_centavos)}</span>
      </div>
      {datos.descuento_centavos > 0 && (
        <div className="t-fila">
          <span>Descuentos</span>
          <span>−{formatear(datos.descuento_centavos)}</span>
        </div>
      )}
      {/* IVA INCLUIDO, no sumado. El precio de la etiqueta ES el total; el
          impuesto se lee de él. Ponerlo como una línea que suma daría un total
          distinto al que la clienta ya vio en la vitrina. */}
      <div className="t-fila t-chico">
        <span>Base gravable</span>
        <span>{formatear(datos.base_gravable_centavos)}</span>
      </div>
      <div className="t-fila t-chico">
        <span>IVA incluido</span>
        <span>{formatear(datos.iva_centavos)}</span>
      </div>

      <div className="t-sep" />

      <div className="t-fila t-total">
        <span>TOTAL</span>
        <span>{formatear(datos.total_centavos)}</span>
      </div>

      <div className="t-sep-fino" />

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

      {datos.es_documento_fiscal ? (
        <>
          {datos.documento_fiscal && (
            <div className="t-centro t-chico">DIAN {datos.documento_fiscal}</div>
          )}
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
        </>
      ) : (
        <div className="t-centro t-chico">
          {datos.estado_fiscal === "pendiente" || datos.estado_fiscal === "enviando"
            ? "La factura electrónica se envía por correo."
            : "Sin factura electrónica asociada."}
        </div>
      )}

      {datos.mensaje && (
        <>
          <div className="t-sep-fino" />
          <div className="t-centro t-chico">{datos.mensaje}</div>
        </>
      )}

      <div className="t-centro t-chico t-pie">
        Conserve este comprobante para cambios.
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
