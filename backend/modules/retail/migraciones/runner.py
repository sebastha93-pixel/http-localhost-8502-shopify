"""Correr las migraciones del módulo retail desde Python.

Existe para que las pruebas de integración apliquen el esquema sin depender de
que alguien haya corrido `alembic` a mano, y para poder invocarlo desde un
script de despliegue.

La URL va SIEMPRE explícita. No hay valor por defecto a propósito: un default
apuntando a la base equivocada es la clase de error que se descubre después de
haber borrado algo.
"""
from __future__ import annotations

import os
from pathlib import Path

from alembic import command
from alembic.config import Config

_AQUI = Path(__file__).resolve().parent


def _config(url: str) -> Config:
    if not url:
        raise ValueError("la URL de la base es obligatoria")
    cfg = Config(str(_AQUI / "alembic.ini"))
    cfg.set_main_option("script_location", str(_AQUI))
    os.environ["RETAIL_DATABASE_URL"] = url
    return cfg


def aplicar(url: str, revision: str = "head") -> None:
    command.upgrade(_config(url), revision)


def revertir(url: str, revision: str = "base") -> None:
    command.downgrade(_config(url), revision)
