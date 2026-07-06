-- ═══════════════════════════════════════════════════════════════════
-- RESET DE DATOS DE PRUEBA · Módulo Producción
-- Borra TODO lo transaccional para arrancar una prueba desde cero,
-- INCLUYENDO el directorio de proveedores. CONSERVA: usuarios.
-- Correr en Supabase SQL Editor. IRREVERSIBLE.
-- ═══════════════════════════════════════════════════════════════════

BEGIN;

-- 1. Notas y hojas de ruta de lotes
DELETE FROM notas_hoja_ruta;
DELETE FROM hoja_ruta_lote;

-- 2. Remisiones
DELETE FROM remision_items;
DELETE FROM remisiones;

-- 3. Órdenes de corte (y sus rollos asignados)
DELETE FROM orden_corte_rollos;
DELETE FROM ordenes_corte;

-- 4. Precosteos
DELETE FROM precosteo_items;
DELETE FROM referencias_precosteo;

-- 5. Inventario de tela (movimientos, rollos, ingresos)
DELETE FROM movimientos_inventario;
DELETE FROM rollos_tela;
DELETE FROM ordenes_ingreso;

-- 6. Inventario de insumos (stock + movimientos)
-- Si estas tablas aún no existen (migración pendiente), comenta estas 2 líneas.
DELETE FROM insumos_movimientos;
DELETE FROM insumos;

-- 7. Reiniciar consecutivos (ING, OC, REM, ROLLO, etc. vuelven a 0001)
DELETE FROM produccion_consecutivos;

-- 8. Directorio de proveedores (confección/terminación/lavandería/otros)
DELETE FROM confeccionistas;

COMMIT;

-- Verificación: todo debe dar 0
SELECT 'hoja_ruta_lote' AS tabla, COUNT(*) FROM hoja_ruta_lote
UNION ALL SELECT 'remisiones', COUNT(*) FROM remisiones
UNION ALL SELECT 'ordenes_corte', COUNT(*) FROM ordenes_corte
UNION ALL SELECT 'referencias_precosteo', COUNT(*) FROM referencias_precosteo
UNION ALL SELECT 'rollos_tela', COUNT(*) FROM rollos_tela
UNION ALL SELECT 'ordenes_ingreso', COUNT(*) FROM ordenes_ingreso
UNION ALL SELECT 'insumos', COUNT(*) FROM insumos
UNION ALL SELECT 'confeccionistas', COUNT(*) FROM confeccionistas;
