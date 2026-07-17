-- ═══════════════════════════════════════════════════════════════════════
-- Impresión automática de remisiones (agente local por IP → RICOH).
-- ═══════════════════════════════════════════════════════════════════════
-- Cada remisión nueva nace con impresa_at = NULL (pendiente de imprimir).
-- El agente local la imprime y marca impresa_at = now(). Las remisiones que
-- YA existen se marcan como impresas para no reimprimir el backlog.
-- Idempotente.

alter table remisiones add column if not exists impresa_at timestamptz;

-- No reimprimir lo ya existente al activar el agente por primera vez.
update remisiones set impresa_at = now() where impresa_at is null;
