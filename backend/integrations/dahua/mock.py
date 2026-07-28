"""
backend.integrations.dahua.mock — Dispositivo simulado.

Genera marcaciones realistas para desarrollo y para los 36 casos de prueba.
Es determinista: la misma semilla produce los mismos eventos, así un test que
falla se puede reproducir.

Simula lo que realmente pasa en un dispositivo de verdad:
  · gente que llega tarde
  · marcaciones duplicadas por tocar dos veces el lector
  · alguien que olvida marcar la salida
  · un empleado que no está mapeado
  · accesos denegados
"""
from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta
from typing import Optional

from backend.integrations.dahua.base import (
    EmpleadoExterno, EventoExterno, InfoDispositivo, LoteEventos,
    ResultadoConexion, SaludDispositivo,
)


class MockAccessControlProvider:
    """Dispositivo de mentira, pero con los defectos de uno de verdad."""

    nombre = "mock"

    def __init__(self, *, empleados: Optional[list[str]] = None,
                 semilla: int = 42, distingue_direccion: bool = True,
                 caos: float = 0.15):
        """
        Args:
            caos: probabilidad de que un día salga imperfecto (0 = todo limpio).
                  Con 0.15, uno de cada siete días trae alguna anomalía — que
                  es aproximadamente lo que se ve en la realidad.
        """
        self.empleados = empleados or [f"100{i}" for i in range(1, 6)]
        self.rnd = random.Random(semilla)
        self.distingue = distingue_direccion
        self.caos = caos
        self._eventos: list[EventoExterno] = []
        self._contador = 0

    # ── Contrato ─────────────────────────────────────────────────────────

    def probar_conexion(self) -> ResultadoConexion:
        return ResultadoConexion(True, "Simulador operativo", latencia_ms=1)

    def info_dispositivo(self) -> InfoDispositivo:
        return InfoDispositivo(fabricante="Mock", modelo="SIM-1",
                               serie="MOCK000001", firmware="0.0.0",
                               distingue_direccion=self.distingue)

    def salud(self) -> SaludDispositivo:
        ultimo = self._eventos[-1].timestamp if self._eventos else None
        return SaludDispositivo(en_linea=True, ultimo_evento_at=ultimo,
                                desfase_reloj_seg=0, mensaje="simulado")

    def listar_empleados(self) -> list[EmpleadoExterno]:
        return [EmpleadoExterno(id_externo=e, nombre=f"Empleado {e}")
                for e in self.empleados]

    def obtener_eventos(self, cursor: Optional[str] = None,
                        limite: int = 200) -> LoteEventos:
        desde = int(cursor or 0)
        pagina = self._eventos[desde:desde + limite]
        nuevo = desde + len(pagina)
        return LoteEventos(eventos=pagina, cursor=str(nuevo),
                           hay_mas=nuevo < len(self._eventos))

    # ── Generación ───────────────────────────────────────────────────────

    def _ev(self, emp: str, cuando: datetime, direccion: str,
            resultado: str = "concedido") -> EventoExterno:
        self._contador += 1
        return EventoExterno(
            id_externo=f"MOCK-{self._contador:06d}",
            id_empleado_externo=emp,
            timestamp=cuando,
            direccion=direccion if self.distingue else "desconocida",
            resultado=resultado,
            metodo="facial",
            puerta="Principal",
            crudo={"simulado": True},
        )

    def generar_dia(self, dia: date, *, entrada: str = "08:30",
                    salida: str = "17:00", con_almuerzo: bool = True) -> int:
        """Genera un día para todos los empleados. Devuelve cuántos eventos creó.

        Introduce anomalías con probabilidad `caos`, para que el motor y las
        incidencias se prueben contra datos sucios y no solo contra el caso feliz.
        """
        hi = time(*map(int, entrada.split(":")))
        hf = time(*map(int, salida.split(":")))
        antes = len(self._eventos)

        for emp in self.empleados:
            r = self.rnd.random()

            # Falta un día completo
            if r < self.caos * 0.2:
                continue

            desvio = self.rnd.choice([-10, -5, 0, 0, 0, 3, 12, 25])
            t_entrada = datetime.combine(dia, hi) + timedelta(minutes=desvio)
            self._eventos.append(self._ev(emp, t_entrada, "entrada"))

            # Marcación duplicada: tocó dos veces el lector
            if r < self.caos * 0.5:
                self._eventos.append(
                    self._ev(emp, t_entrada + timedelta(seconds=8), "entrada"))

            if con_almuerzo:
                t1 = datetime.combine(dia, time(13, 0))
                self._eventos.append(self._ev(emp, t1, "salida"))
                self._eventos.append(
                    self._ev(emp, t1 + timedelta(minutes=30 + self.rnd.choice([0, 0, 15])),
                             "entrada"))

            # Olvidó marcar la salida
            if r < self.caos * 0.7 and r >= self.caos * 0.5:
                continue

            extra = self.rnd.choice([0, 0, 0, 5, 40, 95])
            self._eventos.append(
                self._ev(emp, datetime.combine(dia, hf) + timedelta(minutes=extra),
                         "salida"))

        # Un desconocido que el sistema no puede mapear
        if self.rnd.random() < self.caos:
            self._eventos.append(
                self._ev("9999", datetime.combine(dia, hi) + timedelta(minutes=2),
                         "entrada"))

        # Un intento denegado (cara no reconocida)
        if self.rnd.random() < self.caos:
            self._eventos.append(
                self._ev(self.rnd.choice(self.empleados),
                         datetime.combine(dia, hi) - timedelta(minutes=1),
                         "entrada", resultado="denegado"))

        self._eventos.sort(key=lambda e: e.timestamp)
        return len(self._eventos) - antes

    def generar_semana(self, lunes: date, **kw) -> int:
        """Cinco días hábiles. El fin de semana queda vacío a propósito."""
        return sum(self.generar_dia(lunes + timedelta(days=i), **kw)
                   for i in range(5))

    def limpiar(self) -> None:
        self._eventos.clear()
        self._contador = 0
