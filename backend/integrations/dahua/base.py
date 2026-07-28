"""
backend.integrations.dahua.base — Contrato con el control de acceso.

Todo lo que el módulo sabe del mundo exterior pasa por aquí. El Dahua es UNA
implementación, no la única: hay simulador para desarrollo, CSV para carga
histórica y respaldo, y mañana podría haber otro fabricante.

Por qué una interfaz y no llamar al Dahua directo
─────────────────────────────────────────────────
Todavía no sabemos el modelo exacto, el firmware ni el protocolo. Inventar
endpoints de un CGI no documentado produciría código que falla en producción
con otro firmware. Con esta interfaz, el resto del módulo se construye y se
prueba completo, y cuando lleguen los datos del equipo el trabajo restante es
UNA clase.

Ver DAHUA_INTEGRATION_REQUIREMENTS.md para la lista exacta de lo que falta.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Protocol, runtime_checkable


@dataclass(frozen=True)
class EventoExterno:
    """Un hecho tal como lo reporta el dispositivo.

    Se mantiene deliberadamente cerca de lo que entrega el equipo: la
    interpretación es trabajo del motor, no del conector.
    """
    id_externo: Optional[str]          # id del evento en el equipo, si lo da
    id_empleado_externo: str           # el código con que el Dahua identifica a la persona
    timestamp: datetime
    direccion: str = "desconocida"     # entrada | salida | desconocida
    resultado: str = "concedido"       # concedido | denegado | desconocido
    metodo: Optional[str] = None       # facial | tarjeta | huella | clave
    puerta: Optional[str] = None
    crudo: dict = field(default_factory=dict)

    def a_payload(self) -> dict:
        """Forma que espera POST /api/personal/access-events."""
        return {
            "id_evento_externo":   self.id_externo,
            "id_externo_empleado": self.id_empleado_externo,
            "event_timestamp":     self.timestamp.isoformat(),
            "direccion_acceso":    self.direccion,
            "resultado_acceso":    self.resultado,
            "metodo_autenticacion": self.metodo,
            "nombre_puerta":       self.puerta,
            "raw_payload_json":    self.crudo or {},
        }


@dataclass(frozen=True)
class EmpleadoExterno:
    """Una persona registrada en el dispositivo. NUNCA incluye biométricos."""
    id_externo: str
    nombre: Optional[str] = None
    tarjeta: Optional[str] = None
    activo: bool = True


@dataclass(frozen=True)
class LoteEventos:
    """Página de eventos más el cursor para pedir la siguiente.

    El cursor es opaco a propósito: cada proveedor decide qué significa
    (un id, un timestamp, un offset). El conector solo lo guarda y lo devuelve.
    """
    eventos: list[EventoExterno]
    cursor: Optional[str] = None
    hay_mas: bool = False


@dataclass(frozen=True)
class ResultadoConexion:
    ok: bool
    mensaje: str
    latencia_ms: Optional[int] = None


@dataclass(frozen=True)
class InfoDispositivo:
    fabricante: str = "desconocido"
    modelo: Optional[str] = None
    serie: Optional[str] = None
    firmware: Optional[str] = None
    # Si el equipo NO distingue entrada de salida, hay que inferirla
    # alternando marcaciones — mucho más frágil y con más incidencias.
    distingue_direccion: bool = False


@dataclass(frozen=True)
class SaludDispositivo:
    en_linea: bool
    ultimo_evento_at: Optional[datetime] = None
    # Desfase del reloj del equipo contra el del conector. Un Dahua con la
    # hora corrida convierte todas las jornadas en basura, y es un problema
    # que no se nota hasta que alguien revisa.
    desfase_reloj_seg: Optional[int] = None
    mensaje: str = ""


@runtime_checkable
class ProveedorControlAcceso(Protocol):
    """Lo que debe implementar cualquier fuente de eventos."""

    nombre: str

    def probar_conexion(self) -> ResultadoConexion: ...

    def info_dispositivo(self) -> InfoDispositivo: ...

    def salud(self) -> SaludDispositivo: ...

    def listar_empleados(self) -> list[EmpleadoExterno]: ...

    def obtener_eventos(self, cursor: Optional[str] = None,
                        limite: int = 200) -> LoteEventos: ...


class ErrorProveedor(RuntimeError):
    """Falla al hablar con la fuente de eventos.

    Se distingue de un error genérico para que el conector sepa que debe
    reintentar en vez de descartar el ciclo.
    """


class ProveedorNoConfigurado(ErrorProveedor):
    """Falta información para poder hablar con el equipo.

    Es el estado normal del DahuaProviderPlaceholder hasta que tengamos
    modelo, firmware y protocolo confirmados.
    """
