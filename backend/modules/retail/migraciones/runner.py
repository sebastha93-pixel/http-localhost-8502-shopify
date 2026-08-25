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


if __name__ == "__main__":  # pragma: no cover
    # ── Migrar desde la línea de comandos ────────────────────────────────────
    #
    # Existe para el DESPLIEGUE. Sin esto, aplicar las migraciones a una base
    # nueva exige abrir un intérprete de Python en el servidor y escribir tres
    # líneas de memoria — que es justo el momento en el que alguien se equivoca
    # de URL y migra la base equivocada.
    #
    #   python -m backend.modules.retail.migraciones.runner "postgresql+psycopg://..."
    #
    # La URL se pasa como argumento y NO se lee del entorno a propósito: hay
    # varias bases en juego y `RETAIL_DATABASE_URL` puede estar apuntando a
    # otra cosa en la sesión donde se corre.
    import sys

    if len(sys.argv) < 2:
        print("uso: python -m backend.modules.retail.migraciones.runner <URL> [revision]")
        raise SystemExit(2)

    url = sys.argv[1]
    revision = sys.argv[2] if len(sys.argv) > 2 else "head"
    # Se enseña a DÓNDE se va a migrar, sin la contraseña. Migrar la base
    # equivocada no se deshace.
    import re
    visible = re.sub(r"://[^@]*@", "://···@", url)
    print(f"migrando {visible} → {revision}")
    aplicar(url, revision)
    print("listo")
