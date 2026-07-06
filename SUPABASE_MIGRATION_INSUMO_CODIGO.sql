-- Migración: código único (QR) por insumo — mismo control que los rollos.
-- Ejecutar UNA vez en Supabase SQL Editor.

ALTER TABLE insumos
  ADD COLUMN IF NOT EXISTS codigo TEXT UNIQUE;
