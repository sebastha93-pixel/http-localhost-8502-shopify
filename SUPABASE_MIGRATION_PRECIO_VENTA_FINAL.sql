-- Revisión de precosteo: el precio de venta final (PVP con IVA) que el autorizador
-- digita para ver el MARGEN real de la prenda y decidir si autoriza o no.
-- El margen se calcula: (precio_sin_iva - costo_sin_iva) / precio_sin_iva,
-- con precio_sin_iva = precio_venta_final / (1 + iva_pct/100).
ALTER TABLE referencias_precosteo
  ADD COLUMN IF NOT EXISTS precio_venta_final numeric;
