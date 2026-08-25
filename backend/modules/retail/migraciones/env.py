"""Entorno de Alembic para el schema `retail`.

La URL se toma de RETAIL_DATABASE_URL. No se lee de la config global del ERP a
propósito: este módulo habla con Postgres directo (ADR-004) mientras el resto
del ERP sigue con supabase-py, y confundir las dos conexiones sería la forma
más fácil de correr una migración contra la base equivocada.
"""
from __future__ import annotations

import os

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config

_url = os.environ.get("RETAIL_DATABASE_URL", "").strip()
if not _url:
    raise RuntimeError(
        "Falta RETAIL_DATABASE_URL. Se exige explícita para no correr una "
        "migración contra la base equivocada."
    )
config.set_main_option("sqlalchemy.url", _url)

target_metadata = None  # el DDL se escribe a mano: hay dominios y particiones


def run_migrations_offline() -> None:
    context.configure(url=_url, target_metadata=target_metadata,
                      literal_binds=True, version_table_schema="retail")
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        connection.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS retail")
        connection.commit()
        context.configure(connection=connection, target_metadata=target_metadata,
                          version_table_schema="retail")
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
