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

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu("MALE'DENIM")
    .addItem('Firmar precosteo (Sebastián / Alejandra)', 'guardarYFirmarPrecosteo')
    .addSeparator()
    .addItem('Imprimir etiquetas de rollos', 'imprimirEtiquetas')
    .addSeparator()
    .addItem('Autorizar orden de corte (diseñador)', 'firmarOrdenCorte')
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
  h.appendRow([ new Date(), ref,
    f.getRange('D2').getValue(), f.getRange('B3').getValue(), f.getRange('D3').getValue(),
    f.getRange('F29').getValue(), f.getRange('G29').getValue(), f.getRange('B34').getValue(),
    f.getRange('D38').getValue() ]);
  f.getRangeList(['B2','D2','G2','B3','D3','B38','D38','G38']).clearContent();
  f.getRange('C6:D28').clearContent();
  ui.alert('Precosteo "' + ref + '" archivado. Formato listo en 0.');
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

/* ─────────────────────── FIRMAR ORDEN DE CORTE ─────────────────────── */
function firmarOrdenCorte() {
  var ui = SpreadsheetApp.getUi();
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var oc = ss.getSheetByName('Orden de Corte (formato)');
  var co = ss.getSheetByName('Cortes');
  var hc = ss.getSheetByName('Histórico Cortes');
  if (!oc || !co || !hc) { ui.alert('Faltan hojas: Orden de Corte / Cortes / Histórico Cortes.'); return; }
  if (!_puede(AUTORIZA_CORTE)) return;                 // solo el diseñador
  var ref = oc.getRange('B5').getValue();
  if (!ref) { ui.alert('Falta la Referencia de la prenda.'); return; }
  var firma = oc.getRange('B31').getValue();
  var estado = String(oc.getRange('E31').getValue()).toLowerCase();
  if (!firma || estado !== 'autorizada') {
    var r = ui.alert('La orden no está firmada/Autorizada. ¿Firmar y registrar de todas formas?', ui.ButtonSet.YES_NO);
    if (r !== ui.Button.YES) return;
  }
  var tela = oc.getRange('B6').getValue();
  var tono = oc.getRange('D5').getValue();
  var resp = oc.getRange('B7').getValue();
  var cons = oc.getRange('B4').getValue();
  var mv = oc.getRange('E11:E14').getValues(), metros = 0;
  for (var i = 0; i < mv.length; i++) { var v = Number(mv[i][0]); if (!isNaN(v)) metros += v; }
  co.appendRow([new Date(), tela, ref, metros, tono, resp]);
  hc.appendRow([new Date(), cons, ref, tono, tela, metros, resp, firma]);
  oc.getRangeList(['B4','B5','D5','B6','B7','D7','A27','B31','E31']).clearContent();
  oc.getRange('A11:E14').clearContent();
  oc.getRangeList(['B17','D17','B18','D18','B19','D19','B20','D20']).clearContent();
  oc.getRange('B24:H24').clearContent();
  ui.alert('Orden de corte "' + (cons || ref) + '" firmada y registrada (' + metros + ' m descontados de ' + tela + '). Formato listo en 0.');
}
