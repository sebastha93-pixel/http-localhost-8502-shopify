/**
 * MALE'DENIM OS — Guardar y firmar (reset a 0 + archivar)
 *
 * Replica en Google Sheets lo que el módulo hace automáticamente:
 * al firmar un precosteo, archiva el formato en "Histórico Precosteo"
 * y limpia el formato para el siguiente.
 *
 * INSTALAR:
 *   1) Sube Produccion_Sheet_Plantilla.xlsx a Google Drive y ábrelo como Google Sheet.
 *   2) Extensiones → Apps Script.
 *   3) Borra lo que haya y pega TODO este archivo. Guarda.
 *   4) Recarga la hoja. Aparece el menú "MALE'DENIM" arriba.
 *   5) Llena el Precosteo y usa: MALE'DENIM → Guardar y firmar precosteo.
 */

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu("MALE'DENIM")
    .addItem('Guardar y firmar precosteo', 'guardarYFirmarPrecosteo')
    .addToUi();
}

function guardarYFirmarPrecosteo() {
  var ui = SpreadsheetApp.getUi();
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var f  = ss.getSheetByName('Precosteo (formato)');
  var h  = ss.getSheetByName('Histórico Precosteo');
  if (!f || !h) { ui.alert('Faltan las hojas "Precosteo (formato)" o "Histórico Precosteo".'); return; }

  var ref = f.getRange('B2').getValue();
  if (!ref) { ui.alert('Falta la REF del precosteo.'); return; }

  var estado = String(f.getRange('B38').getValue()).toLowerCase();
  if (estado !== 'autorizada') {
    var r = ui.alert('El estado no es "autorizada". ¿Archivar de todas formas?', ui.ButtonSet.YES_NO);
    if (r !== ui.Button.YES) return;
  }

  // 1) Archivar la fila resumen en el histórico
  h.appendRow([
    new Date(),                    // fecha_firma
    ref,                           // ref
    f.getRange('D2').getValue(),   // nombre
    f.getRange('B3').getValue(),   // tela
    f.getRange('D3').getValue(),   // color
    f.getRange('F29').getValue(),  // costo_total_sin_iva
    f.getRange('G29').getValue(),  // costo_total_con_iva
    f.getRange('D34').getValue(),  // precio_final_con_iva (primer margen)
    f.getRange('D38').getValue()   // autorizado_por
  ]);

  // 2) Limpiar el formato a 0 (cabecera, valores/cantidades de las líneas, y autorización)
  f.getRangeList(['B2','D2','G2','B3','D3','B38','D38','G38']).clearContent();
  f.getRange('C6:D28').clearContent();

  ui.alert('Precosteo "' + ref + '" archivado en el histórico. Formato listo en 0.');
}
