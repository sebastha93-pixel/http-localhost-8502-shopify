"""UnidadDeTrabajo sobre SQLAlchemy async.

Una instancia = una transacción de Postgres. Los repositorios comparten la
misma `AsyncSession`, así que todo lo que escriben entra o sale junto.

EL DEFAULT ES ROLLBACK. Si el bloque `async with` termina sin `commit()`
—porque hubo una excepción, o porque alguien olvidó llamarlo— la transacción
se revierte. Olvidar el commit pierde datos, que es molesto y visible;
olvidar el rollback los deja a medio escribir, que es silencioso y peor.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

__all__ = ["UnidadDeTrabajoSQL", "crear_motor"]


def normalizar_url(url: str) -> str:
    """`postgresql://` → `postgresql+psycopg://`.

    ES UNA TRAMPA CON CONSECUENCIA INVISIBLE, y por eso se arregla en código y
    no en la documentación. Railway (y Heroku, y Supabase) entregan la cadena
    como `postgresql://…`; SQLAlchemy en modo async necesita que diga qué
    driver usar. Con el prefijo pelado, `create_async_engine` levanta
    «InvalidRequestError: The asyncio extension requires an async driver».

    Y ese error NO se ve: `main.py` monta el módulo retail dentro de un
    `try/except`, así que lo único que pasa es que el POS no aparece. La caja
    no falla — sencillamente no existe, y hay que ir a leer los logs del
    arranque para saber por qué.

    Estaba escrito como advertencia en `docs/retail-pos/despliegue.md` («ojo
    con el prefijo… es lo primero a mirar»). Una advertencia en un documento
    protege a quien la leyó; esto protege a quien pegue la referencia de
    Railway tal cual, que es lo que uno hace.

    `postgres://` también se acepta: es el alias viejo que todavía usan varios
    proveedores.
    """
    if url.startswith("postgresql+"):          # ya trae driver explícito
        return url
    for prefijo in ("postgresql://", "postgres://"):
        if url.startswith(prefijo):
            return "postgresql+psycopg://" + url[len(prefijo):]
    return url


def crear_motor(url: str, *, echo: bool = False) -> AsyncEngine:
    """El motor async del módulo retail.

    `pool_pre_ping` está encendido porque Supabase corta conexiones ociosas y
    una caja que lleva media hora sin vender no puede fallar la primera venta
    de la tarde con «server closed the connection unexpectedly».
    """
    if not url:
        raise ValueError(
            "la URL de la base es obligatoria y no tiene valor por defecto"
        )
    return create_async_engine(
        normalizar_url(url), echo=echo, pool_pre_ping=True,
        pool_size=5, max_overflow=10
    )


class UnidadDeTrabajoSQL:
    """Implementa el puerto `UnidadDeTrabajo`."""

    def __init__(self, sesion_factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = sesion_factory
        self.sesion: Optional[AsyncSession] = None
        self._confirmada = False

    async def __aenter__(self) -> "UnidadDeTrabajoSQL":
        self.sesion = self._factory()
        self._confirmada = False

        # Import local: evita un ciclo entre repositorios y unidad de trabajo.
        from backend.modules.retail.infrastructure.persistencia.repo_venta import (
            RepositorioVentasSQL,
        )
        from backend.modules.retail.infrastructure.persistencia.repo_inventario import (
            RepositorioInventarioSQL,
        )
        from backend.modules.retail.infrastructure.persistencia.repo_caja import (
            RepositorioCajaSQL,
        )
        from backend.modules.retail.infrastructure.persistencia.repo_auditoria import (
            RepositorioAuditoriaSQL,
            RepositorioOutboxSQL,
        )
        from backend.modules.retail.infrastructure.persistencia.repo_consecutivos import (
            RepositorioConsecutivosSQL,
        )
        from backend.modules.retail.infrastructure.persistencia.repo_sesion_caja import (
            RepositorioSesionCajaSQL,
        )

        self.ventas = RepositorioVentasSQL(self.sesion)
        self.inventario = RepositorioInventarioSQL(self.sesion)
        self.caja = RepositorioCajaSQL(self.sesion)
        self.auditoria = RepositorioAuditoriaSQL(self.sesion)
        self.outbox = RepositorioOutboxSQL(self.sesion)
        self.turnos = RepositorioSesionCajaSQL(self.sesion)
        self.consecutivos = RepositorioConsecutivosSQL(self.sesion)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        assert self.sesion is not None
        try:
            if not self._confirmada:
                await self.sesion.rollback()
        finally:
            await self.sesion.close()
            self.sesion = None

    async def commit(self) -> None:
        assert self.sesion is not None
        await self.sesion.commit()
        self._confirmada = True

    async def rollback(self) -> None:
        assert self.sesion is not None
        await self.sesion.rollback()


def crear_fabrica(motor: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(motor, expire_on_commit=False)
