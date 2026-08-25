-- ═══════════════════════════════════════════════════════════════════════════
-- CACHÉ DE FACTURAS DE VENTA DE SIIGO — para poder cruzar sin reventar la API
-- ═══════════════════════════════════════════════════════════════════════════
--
-- QUÉ PASÓ (2026-08-11): el bloque de cartera contraentrega mostraba
-- «No se pudo consultar la cartera en Siigo · 429 intento 5». La causa era mía:
-- para cruzar los pedidos entregados contra sus facturas hay que recorrer ~112
-- páginas de /invoices, y Siigo aguanta cerca de UNA petición por segundo. El
-- backoff se rinde a los 23 segundos, así que el recorrido nunca terminaba.
--
-- Y peor: el backend corre con CUATRO workers de Uvicorn, cada uno con su propio
-- caché en memoria. Un caché en proceso significaba 4 × 112 páginas, y el que no
-- es líder del scheduler nunca lo tendría caliente.
--
-- POR ESO ESTA TABLA. Las facturas se guardan una vez y después solo se
-- sincroniza lo NUEVO (desde la última fecha vista, con dos días de traslape por
-- si alguna entra con fecha atrasada). El estado en régimen son 2 o 3 páginas
-- por sincronización en vez de 112, y lo comparten los cuatro workers.
--
-- Se guarda lo mínimo para cruzar, no la factura completa: número de orden,
-- fecha, total, saldo, y CONTRA QUÉ CUENTA se registró el pago —que es el dato
-- que de verdad importa, porque `saldo = 0` en una factura de contraentrega
-- significa «venta a crédito registrada», no «la plata llegó»—.
--
-- Idempotente. Correr en el SQL Editor de Supabase.
-- ═══════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS siigo_facturas_cod (
    factura         text PRIMARY KEY,          -- FV-1-65101
    orden           text,                      -- número de orden de Shopify
    fecha           date,
    total           numeric(14,2) NOT NULL DEFAULT 0,
    saldo           numeric(14,2) NOT NULL DEFAULT 0,
    medio           text,                      -- "CASH ON DELIVERY (COD)", "MANUAL"…
    a_credito       boolean NOT NULL DEFAULT false,  -- pago contra la cuenta de COD
    cuentas         text[],                    -- nombres de las cuentas de pago
    actualizado_en  timestamptz NOT NULL DEFAULT now()
);

-- El cruce siempre entra por número de orden.
CREATE INDEX IF NOT EXISTS idx_siigo_facturas_cod_orden
    ON siigo_facturas_cod (orden);

-- Para calcular desde dónde sincronizar.
CREATE INDEX IF NOT EXISTS idx_siigo_facturas_cod_fecha
    ON siigo_facturas_cod (fecha DESC);

COMMENT ON TABLE siigo_facturas_cod IS
    'Espejo mínimo de las facturas de venta de Siigo para cruzar contraentrega. '
    'Se sincroniza incremental porque recorrer /invoices completo son ~112 '
    'páginas y Siigo aguanta ~1 req/s. NO es la fuente de verdad: es un espejo.';

COMMENT ON COLUMN siigo_facturas_cod.a_credito IS
    'true = el pago se registró contra "CONTRA ENTREGA CREDITO 10 DIAS" (cuenta '
    '13050501), o sea venta a crédito: la plata NO ha llegado. false = se cobró '
    'por banco/ADDI/efectivo. El `saldo` de la factura NO sirve para distinguir '
    'esto: 1.328 de 1.329 facturas COD quedan en saldo 0 al emitirse.';

-- ── Comprobación ──────────────────────────────────────────────────────────
-- SELECT count(*) AS facturas, min(fecha) AS desde, max(fecha) AS hasta,
--        count(*) FILTER (WHERE a_credito) AS a_credito
--   FROM siigo_facturas_cod;
