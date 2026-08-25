"""Importar la base de clientas de Siigo sin destruir nada.

TRES REGLAS, Y LAS TRES SON SOBRE NO HACER DAÑO.

**No pisa lo que alguien corrigió a mano.** Si la cajera arregló un teléfono en
el mostrador —porque la clienta se lo acaba de dictar— ese dato es MÁS nuevo
que el de Siigo. Sólo se rellenan campos vacíos. La única excepción es
`siigo_customer_id`, que siempre se escribe: es el vínculo, y sin él la
importación no sirve para lo único que de verdad importa.

**Es idempotente.** Correrlo dos veces no duplica ni cambia nada. Va a haber
que correrlo varias veces —antes del piloto, después, cuando alguien dé de alta
clientas en Siigo— y una importación que sólo se puede correr una vez es una
importación que nadie se atreve a correr.

**Tiene ensayo.** `dry_run=True` dice exactamente qué haría sin tocar la base.
Sobre la base de clientas de un negocio no se prueba en vivo.

SE IMPORTA TODA LA BASE, no sólo quien compró en el POS. Filtrar por «compró en
tienda» exigiría recorrer las facturas y cruzarlas, y el resultado sería peor:
una clienta que compró por la web entra a la tienda igual, y encontrarla con su
cédula es justo lo que evita crearla de nuevo.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Optional

from sqlalchemy import text

__all__ = ["ImportarClientes", "ResumenImportacion"]

# Campos que se rellenan SÓLO si están vacíos aquí. El orden no importa; la
# lista sí: lo que no esté aquí no se toca nunca.
_RELLENABLES = ("nombre", "apellido", "telefono", "correo", "direccion",
                "ciudad", "dv", "tipo_documento")


@dataclass
class ResumenImportacion:
    leidas_de_siigo: int = 0
    creadas: int = 0
    enlazadas: int = 0        # ya existían aquí; se les puso el id de Siigo
    completadas: int = 0      # ya existían; se les llenó algún campo vacío
    sin_documento: int = 0    # Siigo las tiene sin identificación
    inactivas: int = 0
    # Mismo número, distinto tipo de documento. NO se fusionan: ver la nota en
    # `ejecutar`. Se cuentan para que un humano decida.
    ambiguas: int = 0
    ensayo: bool = False
    ejemplos: list = field(default_factory=list)

    def como_dict(self) -> dict:
        return {
            "leidas_de_siigo": self.leidas_de_siigo,
            "creadas": self.creadas,
            "enlazadas": self.enlazadas,
            "completadas": self.completadas,
            "sin_documento": self.sin_documento,
            "inactivas_omitidas": self.inactivas,
            "ambiguas_para_revisar": self.ambiguas,
            "ensayo": self.ensayo,
            "ejemplos": self.ejemplos[:10],
        }


class ImportarClientes:
    def __init__(self, sesion) -> None:
        self._s = sesion

    async def ejecutar(self, clientas: Iterable[dict], *, usuario_id: str,
                       dry_run: bool = True,
                       nuevo_id) -> ResumenImportacion:
        """`clientas` ya viene mapeada a nuestras columnas.

        Se recibe el iterable y no se llama a Siigo aquí: así esto se puede
        probar con una lista, sin red y sin credenciales — que es la única
        forma de tener una prueba de una importación.
        """
        r = ResumenImportacion(ensayo=dry_run)
        ahora = datetime.now(timezone.utc)

        for c in clientas:
            r.leidas_de_siigo += 1

            documento = (c.get("numero_documento") or "").strip()
            if not documento:
                # Sin documento no se puede ni buscar ni facturar. Se cuenta y
                # se sigue: abortar la importación entera por una fila mala
                # dejaría la base a medias.
                r.sin_documento += 1
                continue
            if not c.get("activo_en_siigo", True):
                r.inactivas += 1
                continue

            tipo = c.get("tipo_documento") or "CC"
            # SE BUSCA POR EL PAR (tipo, número), que es como está el índice.
            #
            # Buscar sólo por número evitaría más duplicados, pero puede FUNDIR
            # a dos personas distintas: una CE y una CC con los mismos dígitos
            # son dos clientas, y fusionarlas manda la factura de una al correo
            # de la otra. Ese error es silencioso y además es un problema de
            # datos personales. Un duplicado, en cambio, se ve y se arregla.
            fila = (await self._s.execute(text("""
                SELECT id, nombre, apellido, telefono, correo, direccion,
                       ciudad, dv, tipo_documento, siigo_customer_id
                  FROM retail.clientes
                 WHERE tipo_documento = :t AND numero_documento = :d
            """), {"t": tipo, "d": documento})).mappings().first()

            if fila is None:
                # ¿El mismo número con OTRO tipo? Puede ser la misma persona
                # (el NIT de un natural es su cédula) o dos distintas. No lo
                # decide una importación: se cuenta y sigue.
                otro = (await self._s.execute(text(
                    "SELECT tipo_documento FROM retail.clientes "
                    " WHERE numero_documento = :d LIMIT 1"),
                    {"d": documento})).scalar()
                if otro:
                    r.ambiguas += 1
                    if len(r.ejemplos) < 10:
                        r.ejemplos.append(
                            f"ambigua · {documento} está como {otro} aquí y "
                            f"como {tipo} en Siigo")
                    continue
                r.creadas += 1
                if len(r.ejemplos) < 10:
                    r.ejemplos.append(f"crear · {documento} · {c.get('nombre','')}")
                if not dry_run:
                    await self._crear(c, documento, nuevo_id(), usuario_id, ahora)
                continue

            faltantes = {campo: c[campo] for campo in _RELLENABLES
                         if not (fila[campo] or "").strip() and (c.get(campo) or "").strip()}
            hay_que_enlazar = (c.get("siigo_customer_id")
                               and not fila["siigo_customer_id"])

            if not faltantes and not hay_que_enlazar:
                continue
            if hay_que_enlazar:
                r.enlazadas += 1
            if faltantes:
                r.completadas += 1
                if len(r.ejemplos) < 10:
                    r.ejemplos.append(
                        f"completar · {documento} · {', '.join(sorted(faltantes))}")
            if not dry_run:
                await self._completar(fila["id"], faltantes,
                                      c.get("siigo_customer_id") if hay_que_enlazar
                                      else None, ahora)

        return r

    async def _crear(self, c: dict, documento: str, cliente_id: str,
                     usuario_id: str, ahora: datetime) -> None:
        await self._s.execute(text("""
            INSERT INTO retail.clientes
                (id, tipo_documento, numero_documento, dv, nombre, apellido,
                 telefono, correo, direccion, ciudad, siigo_customer_id,
                 creado_por, creado_en, actualizado_en)
            VALUES (:id, :tipo, :doc, :dv, :nom, :ape, :tel, :mail, :dir,
                    :ciu, :sid, :por, :ts, :ts)
            ON CONFLICT (tipo_documento, numero_documento) DO NOTHING
        """), {"id": cliente_id, "tipo": c.get("tipo_documento") or "CC",
               "doc": documento, "dv": c.get("dv"),
               "nom": c.get("nombre") or "", "ape": c.get("apellido") or "",
               "tel": c.get("telefono") or None, "mail": c.get("correo") or None,
               "dir": c.get("direccion") or None, "ciu": c.get("ciudad") or None,
               "sid": c.get("siigo_customer_id"),
               "por": f"importacion:{usuario_id}", "ts": ahora})

    async def _completar(self, cliente_id: str, faltantes: dict,
                         siigo_id: Optional[str], ahora: datetime) -> None:
        sets, params = [], {"id": cliente_id, "ts": ahora}
        for campo, valor in faltantes.items():
            sets.append(f"{campo} = :{campo}")
            params[campo] = valor
        if siigo_id:
            sets.append("siigo_customer_id = :sid")
            params["sid"] = siigo_id
        if not sets:
            return
        await self._s.execute(text(f"""
            UPDATE retail.clientes SET {', '.join(sets)}, actualizado_en = :ts
             WHERE id = :id
        """), params)
