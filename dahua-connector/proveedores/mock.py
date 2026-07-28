"""Simulador local: genera marcaciones sin tocar ningún equipo.

Sirve para probar el conector de punta a punta —cola, envío, reintento—
antes de tener el Dahua conectado.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta


class MockLocal:
    def __init__(self, conf: dict):
        self.empleados = conf.get("empleados") or ["1001", "1002", "1003"]
        self.rnd = random.Random(conf.get("semilla", 42))
        self._eventos = []
        self._generar(conf.get("dias", 5))

    def _generar(self, dias: int) -> None:
        hoy = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        n = 0
        for d in range(dias, 0, -1):
            dia = hoy - timedelta(days=d)
            if dia.weekday() >= 5:      # el simulador no trabaja fines de semana
                continue
            for emp in self.empleados:
                for hora, direccion in ((8, "entrada"), (17, "salida")):
                    n += 1
                    t = dia + timedelta(hours=hora,
                                        minutes=30 + self.rnd.choice([-8, 0, 0, 5, 20]))
                    self._eventos.append({
                        "id_evento_externo": f"MOCK-{n:06d}",
                        "id_externo_empleado": emp,
                        "event_timestamp": t.isoformat(),
                        "direccion_acceso": direccion,
                        "resultado_acceso": "concedido",
                        "metodo_autenticacion": "facial",
                        "nombre_puerta": "Principal",
                        "raw_payload_json": {"simulado": True},
                    })
        self._eventos.sort(key=lambda e: e["event_timestamp"])

    def obtener_eventos(self, cursor=None, limite=100) -> dict:
        i = int(cursor or 0)
        pagina = self._eventos[i:i + limite]
        return {"eventos": pagina, "cursor": str(i + len(pagina)),
                "hay_mas": i + len(pagina) < len(self._eventos)}

    def salud(self) -> dict:
        return {"en_linea": True,
                "ultimo_evento_at": self._eventos[-1]["event_timestamp"]
                                    if self._eventos else None,
                "desfase_reloj_seg": 0}
