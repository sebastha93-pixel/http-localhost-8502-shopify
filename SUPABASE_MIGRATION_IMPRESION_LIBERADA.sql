-- Flujo nuevo: la remisión de confección se GENERA al cerrar el informe de
-- corte pero NO se imprime hasta que se separan los insumos. Esta bandera
-- retiene la impresión: el agente solo toma remisiones con impresion_liberada.
ALTER TABLE remisiones ADD COLUMN IF NOT EXISTS impresion_liberada boolean NOT NULL DEFAULT true;
-- Nuevas remisiones de confección auto nacen en false (ver crear_remision);
-- las viejas quedan en true (ya se imprimían al crear) — sin efecto porque
-- ya tienen impresa_at.
