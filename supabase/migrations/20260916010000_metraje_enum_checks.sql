-- Los valores de enum de la feature "permiso de metraje" (2026-08-05) se
-- escribieron en el codigo pero nunca se amplio el CHECK de la base:
--   · anular_rollo_no_recibido  -> estado='no_recibido', mov tipo='anulacion_no_recibido'
--   · actualizar_rollo_ingreso  -> mov tipo='correccion_metraje'
-- Sin esto, anular un rollo revienta DESPUES de borrar el consumo y los
-- movimientos (corrupcion), y cada correccion de metraje pierde su rastro de
-- auditoria en silencio. Ampliacion aditiva y permisiva: ninguna fila actual
-- viola el nuevo CHECK.

ALTER TABLE movimientos_inventario DROP CONSTRAINT IF EXISTS movimientos_inventario_tipo_check;
ALTER TABLE movimientos_inventario ADD CONSTRAINT movimientos_inventario_tipo_check
  CHECK (tipo = ANY (ARRAY['ingreso','corte','ajuste','anulacion_no_recibido','correccion_metraje']));

ALTER TABLE rollos_tela DROP CONSTRAINT IF EXISTS rollos_tela_estado_check;
ALTER TABLE rollos_tela ADD CONSTRAINT rollos_tela_estado_check
  CHECK (estado = ANY (ARRAY['disponible','en_corte','agotado','con_novedad','no_recibido']));
