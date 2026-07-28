"""
backend.integrations.dahua.dahua_placeholder — El punto de integración real.

⚠️ ESTE ADAPTADOR NO HABLA CON NINGÚN DAHUA TODAVÍA. A propósito.

Por qué está vacío
──────────────────
Dahua tiene al menos cuatro caminos de integración —HTTP API del equipo (CGI),
SDK nativo, DSS Express, DSS Professional— y cuál aplica depende del modelo,
del firmware y de la licencia. Inventar endpoints de un CGI no documentado
produciría código que parece funcionar, pasa revisión, y falla en producción
contra un firmware distinto.

Prefiero una clase que falla ruidosamente diciendo exactamente qué falta, a
una que finge saber.

Lo que SÍ está resuelto aquí
───────────────────────────
La estructura, los contratos, el manejo de errores y la normalización de
eventos. Cuando lleguen los datos del equipo, lo que hay que escribir son los
tres métodos de `_llamar()` hacia adentro — no la arquitectura.

Lo que falta para terminar (ver DAHUA_INTEGRATION_REQUIREMENTS.md)
──────────────────────────────────────────────────────────────────
  · Modelo exacto y firmware   → decide el protocolo
  · Uno o dos terminales       → decide cómo se infiere entrada/salida
  · Código de cada empleado    → alimenta personal_mapeo_externo
  · Una exportación de muestra → valida el parser sin tocar el equipo

Ese último desbloquea más que ningún otro: con un CSV real se ajusta el
parseo completo sin acceso al aparato.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from backend.integrations.dahua.base import (
    EmpleadoExterno, ErrorProveedor, EventoExterno, InfoDispositivo,
    LoteEventos, ProveedorNoConfigurado, ResultadoConexion, SaludDispositivo,
)

log = logging.getLogger(__name__)


# Lo que hay que confirmar antes de poder implementar de verdad.
DATOS_FALTANTES = (
    "modelo_exacto",
    "version_firmware",
    "protocolo",              # http_cgi | sdk | dss_express | dss_pro
    "distingue_entrada_salida",
    "formato_id_empleado",
)


class DahuaProviderPlaceholder:
    """Estructura completa, implementación pendiente.

    Todos los métodos lanzan `ProveedorNoConfigurado` con un mensaje que dice
    qué falta. No devuelven listas vacías: una lista vacía se confunde con
    "no hubo eventos hoy", y eso enmascararía el problema hasta que alguien
    notara que la asistencia lleva una semana en blanco.
    """

    nombre = "dahua"

    def __init__(self, *, host: str = "", usuario: str = "",
                 password: str = "", puerto: int = 80,
                 protocolo: Optional[str] = None, timeout: int = 15):
        self.host = host
        self.usuario = usuario
        self.puerto = puerto
        self.protocolo = protocolo
        self.timeout = timeout

        # La contraseña se guarda en un CLOSURE, no como atributo.
        #
        # El name mangling (self.__password) NO sirve para esto: solo renombra
        # el atributo a _Clase__password, y sigue apareciendo en __dict__ —
        # es decir, en cualquier traceback que vuelque locales, en un repr
        # ingenuo, o en un log que serialice el objeto. Un test lo detectó.
        #
        # Con el closure, __dict__ solo contiene la función.
        self._password = (lambda p: (lambda: p))(password)

    def __repr__(self) -> str:
        return (f"DahuaProviderPlaceholder(host={self.host or '(sin definir)'}, "
                f"protocolo={self.protocolo or 'sin confirmar'})")

    # ── Contrato ─────────────────────────────────────────────────────────

    def probar_conexion(self) -> ResultadoConexion:
        """Único método que responde sin lanzar: reporta qué falta.

        La pantalla de dispositivos lo usa para mostrar el estado real en vez
        de un error genérico.
        """
        if not self.host:
            return ResultadoConexion(
                False, "Falta la IP del dispositivo en la configuración.")
        if not self.protocolo:
            return ResultadoConexion(
                False,
                "Protocolo sin confirmar. Se necesita el modelo exacto y el "
                "firmware del equipo para saber si habla CGI, SDK o DSS. "
                "Ver DAHUA_INTEGRATION_REQUIREMENTS.md")
        return ResultadoConexion(
            False, f"Protocolo '{self.protocolo}' aún no implementado.")

    def info_dispositivo(self) -> InfoDispositivo:
        raise ProveedorNoConfigurado(self._falta("info_dispositivo"))

    def salud(self) -> SaludDispositivo:
        raise ProveedorNoConfigurado(self._falta("salud"))

    def listar_empleados(self) -> list[EmpleadoExterno]:
        raise ProveedorNoConfigurado(self._falta("listar_empleados"))

    def obtener_eventos(self, cursor: Optional[str] = None,
                        limite: int = 200) -> LoteEventos:
        raise ProveedorNoConfigurado(self._falta("obtener_eventos"))

    # ── Andamiaje listo para cuando lleguen los datos ────────────────────

    def _falta(self, metodo: str) -> str:
        return (f"DahuaProviderPlaceholder.{metodo} no está implementado. "
                f"Faltan estos datos del equipo: {', '.join(DATOS_FALTANTES)}. "
                f"Mientras tanto, usa MockAccessControlProvider para desarrollo "
                f"o CsvAccessControlProvider para cargar una exportación real.")

    @staticmethod
    def normalizar_evento(crudo: dict) -> EventoExterno:
        """Convierte un registro del Dahua al formato interno.

        Se deja escrito porque la FORMA del evento sí la conocemos, aunque no
        el transporte: cuando llegue la exportación de muestra, aquí es donde
        se ajustan los nombres de campo, y nada más del módulo cambia.

        Los nombres de abajo son los que Dahua usa habitualmente. Hay que
        CONFIRMARLOS contra un export real antes de confiar en ellos.
        """
        ts = crudo.get("CreateTime") or crudo.get("time") or crudo.get("Time")
        if isinstance(ts, (int, float)):
            fecha = datetime.fromtimestamp(ts)          # epoch
        elif isinstance(ts, str):
            from backend.core.timeutils import parse_iso
            fecha = parse_iso(ts).replace(tzinfo=None)
        else:
            raise ErrorProveedor("evento_sin_timestamp_reconocible")

        direccion = str(crudo.get("Direction") or crudo.get("direction") or "").lower()
        if direccion in ("1", "in", "entry"):
            direccion = "entrada"
        elif direccion in ("2", "0", "out", "exit"):
            direccion = "salida"
        else:
            direccion = "desconocida"

        estado = crudo.get("Status") or crudo.get("ErrorCode")
        resultado = "concedido" if estado in (1, "1", 0, "0", None) else "denegado"

        return EventoExterno(
            id_externo=str(crudo.get("RecNo") or crudo.get("id") or "") or None,
            id_empleado_externo=str(crudo.get("UserID") or crudo.get("CardNo") or ""),
            timestamp=fecha,
            direccion=direccion,
            resultado=resultado,
            metodo=crudo.get("Method") or crudo.get("VerifyMode"),
            puerta=crudo.get("DoorName") or crudo.get("Door"),
            crudo=crudo,
        )
