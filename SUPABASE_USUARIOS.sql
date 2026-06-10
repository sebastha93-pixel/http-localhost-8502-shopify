-- ─────────────────────────────────────────────────────────────────────────
-- SCHEMA: tabla `usuarios` para autenticación del backend FastAPI
-- Ejecutar UNA VEZ en Supabase → SQL Editor → New Query → Run
-- ─────────────────────────────────────────────────────────────────────────

create extension if not exists "pgcrypto";

create table if not exists usuarios (
  id            uuid primary key default gen_random_uuid(),
  email         text unique not null,
  nombre        text not null,
  password_hash text not null,
  rol           text not null default 'operador',
  activo        boolean not null default true,
  creado_en     timestamptz default now(),

  constraint rol_valido check (rol in ('admin', 'operador', 'lectura'))
);

create index if not exists idx_usuarios_email on usuarios (lower(email));

-- ─────────────────────────────────────────────────────────────────────────
-- Política de Row Level Security (opcional, recomendado en producción)
-- ─────────────────────────────────────────────────────────────────────────
-- Si tienes RLS habilitado en otras tablas y usas la SUPABASE_KEY de servicio,
-- no es necesario habilitar policies aquí — el backend usa la key con rol
-- bypass-RLS. Si usas anon key, agrega policies.
