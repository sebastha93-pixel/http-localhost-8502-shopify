"""Clientas — búsqueda y creación desde la caja.

POR QUÉ EXISTE ESTO EN EL POS. No es un CRM: es el dato mínimo que exige la
factura electrónica. Tipo de documento, número, nombre, teléfono y correo — a
ese correo le llega la factura, así que un correo mal escrito es una factura
que nunca llega.

LA BÚSQUEDA ES SÓLO POR NÚMERO DE IDENTIFICACIÓN, por decisión del handoff, y
es la correcta: buscar por nombre en un mostrador devuelve seis "María
González" y la cajera tiene que adivinar. El documento es único y la clienta
lo sabe de memoria.

CREAR NO TOCA SIIGO. El cliente se registra en nuestra base al instante —así
funciona sin internet— y se crea en Siigo perezosamente, al emitir su primer
documento. Ir a Siigo aquí pondría a la clienta a esperar a un tercero.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.modules.retail.domain.venta.errores import ReglaDeNegocio

__all__ = ["BuscarClientes", "CrearCliente", "ClienteEncontrado"]

TIPOS_DOCUMENTO = {"CC", "CE", "PP", "NIT", "TI"}
_CORREO = re.compile(r"^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$")


@dataclass(frozen=True)
class ClienteEncontrado:
    id: str
    tipo_documento: str
    numero_documento: str
    nombre: str
    telefono: Optional[str]
    correo: Optional[str]
    compras: int


class BuscarClientes:
    def __init__(self, sesion: AsyncSession) -> None:
        self._s = sesion

    async def ejecutar(self, documento: str, *, limite: int = 8) -> List[ClienteEncontrado]:
        # Sólo dígitos: la cajera teclea el documento como se lo dictan, con
        # puntos o sin ellos, y ninguna de las dos formas puede fallar.
        digitos = re.sub(r"\D", "", documento or "")
        if len(digitos) < 3:
            return []

        filas = (await self._s.execute(text("""
            SELECT c.id, c.tipo_documento, c.numero_documento,
                   trim(c.nombre || ' ' || c.apellido) AS nombre,
                   c.telefono, c.correo,
                   (SELECT count(*) FROM retail.ventas v
                     WHERE v.cliente_id = c.id AND v.estado = 'cerrada') AS compras
              FROM retail.clientes c
             WHERE regexp_replace(c.numero_documento, '\\D', '', 'g') LIKE :d
             ORDER BY compras DESC, c.nombre
             LIMIT :n
        """), {"d": f"{digitos}%", "n": limite})).mappings().all()

        return [ClienteEncontrado(**dict(f)) for f in filas]


class CrearCliente:
    def __init__(self, sesion: AsyncSession) -> None:
        self._s = sesion

    async def ejecutar(self, *, cliente_id: str, tipo_documento: str,
                       numero_documento: str, nombre: str, telefono: str,
                       correo: str, creado_por: str,
                       ahora: datetime,
                       direccion: str = "", ciudad: str = "",
                       ) -> ClienteEncontrado:
        tipo = (tipo_documento or "").strip().upper()
        if tipo not in TIPOS_DOCUMENTO:
            raise ReglaDeNegocio(f"Tipo de documento no válido: {tipo_documento!r}")

        documento = re.sub(r"\s", "", numero_documento or "")
        if len(re.sub(r"\D", "", documento)) < 5:
            raise ReglaDeNegocio("El número de identificación es demasiado corto.")

        completo = " ".join((nombre or "").split())
        if len(completo) < 3:
            raise ReglaDeNegocio("Escribe el nombre completo de la clienta.")

        tel = re.sub(r"[^\d+]", "", telefono or "")
        if len(re.sub(r"\D", "", tel)) < 7:
            raise ReglaDeNegocio("El teléfono no parece completo.")

        # El correo se valida ANTES de guardar: es donde llega la factura
        # electrónica, y un error de dedo aquí es una factura que nunca llega y
        # una clienta que llama tres días después.
        limpio = (correo or "").strip().lower()
        if not _CORREO.match(limpio):
            raise ReglaDeNegocio(
                f"«{correo}» no parece un correo válido. Ahí le llega la factura."
            )

        # El nombre se parte en nombre/apellido porque así lo pide Siigo. Si
        # viene una sola palabra, el apellido queda vacío en vez de inventarse.
        partes = completo.split(" ", 1)

        try:
            await self._s.execute(text("""
                INSERT INTO retail.clientes
                    (id, tipo_documento, numero_documento, nombre, apellido,
                     telefono, correo, direccion, ciudad,
                     creado_por, creado_en, actualizado_en)
                VALUES (:id, :tipo, :doc, :nom, :ape, :tel, :mail, :dir, :ciu,
                        :por, :ts, :ts)
            """), {"id": cliente_id, "tipo": tipo, "doc": documento,
                   "nom": partes[0], "ape": partes[1] if len(partes) > 1 else "",
                   "tel": tel, "mail": limpio,
                   "dir": (direccion or "").strip() or None,
                   "ciu": (ciudad or "").strip() or None,
                   "por": creado_por, "ts": ahora})
        except Exception as e:  # noqa: BLE001
            if "ux_cliente_doc" in str(e):
                raise ReglaDeNegocio(
                    f"Ya existe una clienta con el documento {documento}. "
                    f"Búscala en vez de crearla."
                ) from e
            raise

        return ClienteEncontrado(
            id=cliente_id, tipo_documento=tipo, numero_documento=documento,
            nombre=completo, telefono=tel, correo=limpio, compras=0,
        )
