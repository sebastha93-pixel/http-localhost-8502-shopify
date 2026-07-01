/**
 * MALE'DENIM OS — Acciones de la plantilla de producción
 *
 *  • Guardar y firmar precosteo   → archiva en "Histórico Precosteo" y limpia el formato.
 *  • Imprimir etiquetas de rollos → abre una ventana con los códigos de barra (Code 128) y un botón Imprimir.
 *  • Firmar orden de corte         → archiva en "Histórico Cortes", registra el corte (descuenta inventario) y limpia.
 *
 * INSTALAR: Extensiones → Apps Script → pega este archivo → Guarda → recarga la hoja.
 * (Para imprimir etiquetas NO necesitas instalar ninguna fuente: el barcode se genera solo.)
 */

/* ═══════════════ PERMISOS (correos autorizados) ═══════════════ */
// Solo estos correos pueden FIRMAR el precosteo:
var FIRMANTES_PRECOSTEO = ['sebastian.hurtado@maledenim.com', 'maria.alejandra@maledenim.com'];
// Solo estos correos pueden AUTORIZAR la orden de corte (el diseñador):
var AUTORIZA_CORTE = ['CORREO_DEL_DISENADOR@maledenim.com'];   // ← reemplaza por el correo real del diseñador
// Imprimir etiquetas: cualquiera (sin restricción).

function _puede(lista) {
  var u = (Session.getActiveUser().getEmail() || '').toLowerCase();
  for (var i = 0; i < lista.length; i++) {
    if (String(lista[i]).toLowerCase() === u) return true;
  }
  SpreadsheetApp.getUi().alert('No tienes permiso para esta acción.\n\nUsuario actual: ' + (u || '(no identificado)') +
    '\nAutorizados: ' + lista.join(', '));
  return false;
}

/* ═══════════════ NOTIFICACIONES ═══════════════ */
var NOTIFICAR = ['sebastian.hurtado@maledenim.com', 'maria.alejandra@maledenim.com']; // reciben aviso al firmar

// WhatsApp: desactivado hasta conectar un proveedor. Rellena y pon WHATSAPP_ON = true.
var WHATSAPP_ON = false;
var WHATSAPP_TO = ['+57XXXXXXXXXX'];   // números destino
var WHATSAPP_ENDPOINT = '';            // URL del proveedor (Meta Cloud API / Twilio / Wati)
var WHATSAPP_TOKEN = '';               // token / bearer

function _notificar(asunto, cuerpo) {
  try { MailApp.sendEmail(NOTIFICAR.join(','), asunto, cuerpo); } catch (e) {}
  _whatsapp(asunto + '\n' + cuerpo);
}

function _whatsapp(msg) {
  if (!WHATSAPP_ON || !WHATSAPP_ENDPOINT) return;   // listo para conectar (ver instrucciones)
  for (var i = 0; i < WHATSAPP_TO.length; i++) {
    try {
      UrlFetchApp.fetch(WHATSAPP_ENDPOINT, {
        method: 'post',
        headers: { 'Authorization': 'Bearer ' + WHATSAPP_TOKEN, 'Content-Type': 'application/json' },
        payload: JSON.stringify({ messaging_product: 'whatsapp', to: WHATSAPP_TO[i], type: 'text', text: { body: msg } }),
        muteHttpExceptions: true
      });
    } catch (e) {}
  }
}

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu("MALE'DENIM")
    .addItem('Firmar precosteo (Sebastián / Alejandra)', 'guardarYFirmarPrecosteo')
    .addSeparator()
    .addItem('Imprimir etiquetas de rollos', 'imprimirEtiquetas')
    .addSeparator()
    .addItem('Autorizar orden de corte (diseñador)', 'firmarOrdenCorte')
    .addSeparator()
    .addItem('Generar remisión de insumos', 'generarRemisionInsumos')
    .addToUi();
}

/* ───────────────────────── PRECOSTEO ───────────────────────── */
function guardarYFirmarPrecosteo() {
  var ui = SpreadsheetApp.getUi();
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var f  = ss.getSheetByName('Precosteo (formato)');
  var h  = ss.getSheetByName('Histórico Precosteo');
  if (!f || !h) { ui.alert('Faltan las hojas "Precosteo (formato)" o "Histórico Precosteo".'); return; }
  if (!_puede(FIRMANTES_PRECOSTEO)) return;            // solo Sebastián / Alejandra
  var ref = f.getRange('B2').getValue();
  if (!ref) { ui.alert('Falta la REF del precosteo.'); return; }
  var estado = String(f.getRange('B38').getValue()).toLowerCase();
  if (estado !== 'autorizada') {
    var r = ui.alert('El estado no es "Autorizada". ¿Archivar de todas formas?', ui.ButtonSet.YES_NO);
    if (r !== ui.Button.YES) return;
  }
  var dp = ss.getSheetByName('Detalle Precosteo');
  if (!dp) { ui.alert('Falta la hoja "Detalle Precosteo".'); return; }

  // ID secuencial (trazabilidad)
  var nExist = 0, col = h.getRange(2, 3, Math.max(h.getLastRow() - 1, 1), 1).getValues();
  for (var i = 0; i < col.length; i++) { if (col[i][0]) nExist++; }
  var id = 'PC-2026-' + ('0000' + (nExist + 1)).slice(-4);
  var nombre = f.getRange('D2').getValue();

  // Resumen (con ID)
  h.appendRow([ id, new Date(), ref, nombre, f.getRange('B3').getValue(), f.getRange('D3').getValue(),
    f.getRange('F29').getValue(), f.getRange('G29').getValue(), f.getRange('B34').getValue(),
    f.getRange('D38').getValue() ]);

  // Detalle: TODAS las líneas (A6:G28), rellenando la categoría combinada
  var lines = f.getRange('A6:G28').getValues(), cat = '', out = [];
  for (var j = 0; j < lines.length; j++) {
    if (lines[j][0]) cat = lines[j][0];
    var item = lines[j][1];
    if (!item) continue;
    out.push([new Date(), id, ref, nombre, cat, item, lines[j][2], lines[j][3], lines[j][4], lines[j][5], lines[j][6]]);
  }
  if (out.length) dp.getRange(dp.getLastRow() + 1, 1, out.length, 11).setValues(out);

  _notificar('Precosteo firmado: ' + ref + ' (' + id + ')',
    'Referencia ' + ref + ' — ' + nombre + '\nID: ' + id +
    '\nCosto con IVA: ' + f.getRange('G29').getValue() +
    '\nPrecio venta con IVA: ' + f.getRange('B34').getValue() +
    '\nAutorizado por: ' + f.getRange('D38').getValue() +
    '\nLíneas archivadas: ' + out.length);

  f.getRangeList(['B2','D2','G2','B3','D3','B38','D38','G38']).clearContent();
  f.getRange('C6:D28').clearContent();
  ui.alert('Precosteo "' + ref + '" (' + id + ') archivado con ' + out.length + ' líneas. Formato listo en 0.');
}

/* ───────────────────────── ETIQUETAS (imprime directo) ───────────────────────── */
function imprimirEtiquetas() {
  var ui = SpreadsheetApp.getUi();
  var ing = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('Órdenes de Ingreso');
  if (!ing) { ui.alert('Falta la hoja "Órdenes de Ingreso".'); return; }
  var last = ing.getLastRow();
  if (last < 2) { ui.alert('No hay rollos para etiquetar.'); return; }
  var rows = ing.getRange(2, 1, last - 1, 16).getValues();
  var labels = [];
  for (var i = 0; i < rows.length; i++) {
    var r = rows[i], code = r[14];               // O = código interno
    if (!r[0] || !code) continue;
    labels.push({
      code: String(code),
      desc: String(r[10] || ''),                 // K descripción
      tono: String(r[8] || ''),                  // I tono
      metros: String(r[12] || ''),               // M metros
      lote: String(r[7] || ''),                  // H lote
      fecha: r[3] ? Utilities.formatDate(new Date(r[3]), Session.getScriptTimeZone(), 'yyyy-MM-dd') : ''
    });
  }
  if (!labels.length) { ui.alert('No hay rollos con datos para etiquetar.'); return; }
  var t = HtmlService.createTemplate(ETIQUETAS_HTML);
  t.labels = labels;
  ui.showModalDialog(t.evaluate().setWidth(840).setHeight(640), 'Etiquetas de rollos');
}

var ETIQUETAS_HTML =
'<!DOCTYPE html><html><head><meta charset="utf-8">' +
'<script src="https://cdn.jsdelivr.net/npm/jsbarcode@3.11.6/dist/JsBarcode.all.min.js"><\/script>' +
'<style>' +
'body{font-family:Montserrat,Arial,sans-serif;margin:0;color:#213033}' +
'.bar{position:sticky;top:0;background:#213033;color:#fff;padding:10px 16px;display:flex;justify-content:space-between;align-items:center}' +
'.bar button{background:#fff;color:#213033;border:0;padding:8px 16px;font-weight:700;border-radius:4px;cursor:pointer}' +
'#grid{display:flex;flex-wrap:wrap;gap:10px;padding:14px}' +
'.lbl{width:250px;border:1px solid #213033;border-radius:6px;padding:10px;box-sizing:border-box;text-align:center}' +
'.lbl .brand{font-weight:800;font-size:11px;letter-spacing:1px}' +
'.lbl .code{font-weight:700;font-size:12px;margin:4px 0}' +
'.lbl .meta{font-size:11px;color:#444;margin-top:4px}' +
'.lbl .metros{font-weight:700}' +
'@media print{.bar{display:none}.lbl{page-break-inside:avoid;width:250px}}' +
'</style></head><body>' +
'<div class="bar"><strong>Etiquetas de rollos</strong><button onclick="window.print()">Imprimir</button></div>' +
'<div id="grid"></div>' +
'<script>' +
'var DATA = <?!= JSON.stringify(labels) ?>;' +
'var g=document.getElementById("grid");' +
'DATA.forEach(function(d,i){' +
'  var el=document.createElement("div"); el.className="lbl";' +
'  el.innerHTML=\'<div class="brand">MALE\\u0027DENIM</div>\'+' +
'    \'<svg id="bc\'+i+\'"></svg>\'+' +
'    \'<div class="code">\'+d.code+\'</div>\'+' +
'    \'<div class="meta">\'+d.desc+(d.tono?\' · Tono \'+d.tono:\'\')+\'</div>\'+' +
'    \'<div class="meta metros">\'+d.metros+\' m\'+(d.lote?\' · Lote \'+d.lote:\'\')+\'</div>\'+' +
'    \'<div class="meta">\'+d.fecha+\'</div>\';' +
'  g.appendChild(el);' +
'});' +
'DATA.forEach(function(d,i){ JsBarcode("#bc"+i, d.code, {format:"CODE128", height:48, width:1.6, fontSize:12, margin:4}); });' +
'<\/script></body></html>';

/* ─────────────────────── AUTORIZAR ORDEN DE CORTE (planeación) ─────────────────────── */
function firmarOrdenCorte() {
  var ui = SpreadsheetApp.getUi();
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var oc = ss.getSheetByName('Orden de Corte (formato)');
  var hc = ss.getSheetByName('Histórico Cortes');
  if (!oc || !hc) { ui.alert('Faltan hojas: Orden de Corte / Histórico Cortes.'); return; }
  if (!_puede(AUTORIZA_CORTE)) return;                 // solo el diseñador

  var cons = oc.getRange('B4').getValue();
  var tela = oc.getRange('B6').getValue();
  var resp = oc.getRange('B8').getValue();
  var firma = oc.getRange('B34').getValue();
  var estado = String(oc.getRange('G34').getValue()).toLowerCase();
  var TALLAS = [4, 6, 8, 10, 12, 14, 16];

  var items = oc.getRange('A12:K16').getValues();   // A ref, B-H tallas, I cantidad, J rend.teórico, K consumo teórico
  var validas = [];
  for (var i = 0; i < items.length; i++) {
    var ref = items[i][0], cant = Number(items[i][8]);
    if (!ref || !cant) continue;
    var rendTeo = Number(items[i][9]) || 0;
    var consumoTeo = Number(items[i][10]) || (cant * rendTeo);
    var curva = [], tallaVals = [];
    for (var t = 0; t < TALLAS.length; t++) {
      var q = Number(items[i][1 + t]);
      tallaVals.push(q || '');
      if (q) curva.push(TALLAS[t] + ':' + q);
    }
    validas.push([ref, curva.join(' '), tallaVals, cant, rendTeo, consumoTeo]);
  }
  if (!validas.length) { ui.alert('Agrega al menos una referencia con cantidad (curva de tallas).'); return; }

  if (!firma || estado !== 'autorizada') {
    var r = ui.alert('La orden no está firmada/Autorizada. ¿Autorizar y planear de todas formas?', ui.ButtonSet.YES_NO);
    if (r !== ui.Button.YES) return;
  }

  var total = 0;
  for (var j = 0; j < validas.length; j++) {
    var v = validas[j];   // [ref, curvaStr, tallaVals(7), cant, rendTeo, consumoTeo]
    // Fecha, Consecutivo, Ref, Tela, Curva, T4..T16, Cantidad, Rend.teórico, Consumo teórico, Consumo real, Diferencia, Responsable, Firma
    var row = [new Date(), cons, v[0], tela, v[1]].concat(v[2]).concat([v[3], v[4], v[5], '', '', resp, firma]);
    hc.appendRow(row);
    total += v[5];
  }

  _notificar('Orden de corte ' + (cons || ''),
    'Orden ' + cons + ' planeada.\nTela: ' + tela + '\nReferencias: ' + validas.length +
    '\nConsumo teórico total: ' + total.toFixed(1) + ' m\nResponsable: ' + resp);

  // NO se descuenta inventario: el Informe de Corte cruzará el consumo real más adelante.
  oc.getRange('A12:K16').clearContent();
  oc.getRangeList(['B6','B8','A30','B34','G34']).clearContent();
  ui.alert('Orden "' + (cons || '') + '" planeada y archivada: ' + validas.length + ' referencia(s), ' +
    total.toFixed(1) + ' m de consumo teórico.\nNO se descontó inventario (pendiente de cruce con consumo real).');
}

/* ─────────────────────── REMISIÓN DE INSUMOS ─────────────────────── */
function generarRemisionInsumos() {
  var ui = SpreadsheetApp.getUi();
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var ri = ss.getSheetByName('Remisión de Insumos');
  var log = ss.getSheetByName('Remisiones Insumos');
  if (!ri || !log) { ui.alert('Faltan hojas: Remisión de Insumos / Remisiones Insumos.'); return; }

  var cons = ri.getRange('B2').getValue();
  var fecha = ri.getRange('D2').getValue() || new Date();
  var destino = ri.getRange('B3').getValue();
  var destinatario = ri.getRange('D3').getValue();
  if (!destino || !destinatario) { ui.alert('Indica el Destino y el Destinatario.'); return; }

  var items = ri.getRange('A7:B16').getValues();
  var n = 0;
  for (var i = 0; i < items.length; i++) {
    var ins = items[i][0], cant = Number(items[i][1]);
    if (!ins || !cant) continue;
    log.appendRow([fecha, cons, destino, destinatario, ins, cant]);
    n++;
  }
  if (n === 0) { ui.alert('No hay insumos con cantidad para remisionar.'); return; }

  _notificar('Remisión de insumos ' + (cons || ''),
    'Remisión a ' + destinatario + ' (' + destino + ')\nConsecutivo: ' + cons + '\nInsumos: ' + n);

  ri.getRange('A7:B16').clearContent();
  ri.getRangeList(['B2','D2','B3','D3','B4']).clearContent();
  ui.alert(n + ' insumo(s) remisionado(s) a ' + destinatario + ' (' + destino + '). Stock descontado. Formato listo.');
}
