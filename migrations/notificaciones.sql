-- Avisos internos entre usuarios de MALE'DENIM OS.
-- Correr una vez en el SQL Editor de Supabase.
--
-- Se rutea por EMAIL y no por user id a propósito: ordenes_corte.created_by
-- ya guarda el email, así que evita un join extra en el camino caliente.

create table if not exists notificaciones (
  id                  uuid primary key default gen_random_uuid(),
  destinatario_email  text not null,
  tipo                text not null,
  titulo              text not null,
  mensaje             text,
  enlace              text,
  meta                jsonb not null default '{}'::jsonb,
  leida               boolean not null default false,
  creado_en           timestamptz not null default now(),
  creado_por          text
);

-- El índice que importa: el campanita consulta "mis no leídas, recientes
-- primero" cada ~20 segundos por usuario conectado.
create index if not exists idx_notif_destinatario
  on notificaciones (destinatario_email, leida, creado_en desc);

-- Para la limpieza periódica por antigüedad.
create index if not exists idx_notif_creado_en
  on notificaciones (creado_en desc);

comment on table notificaciones is
  'Avisos internos entre usuarios. Distinto de los mensajes salientes a '
  'clientas/proveedores (whatsapp, postventa). Ver services/notificaciones.py '
  'para el transporte y services/avisos_produccion.py para la política.';
