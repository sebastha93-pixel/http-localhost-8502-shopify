"""El centinela tiene que entender que estar a mitad de barrido es NORMAL.

Antes de los tramos, `completo = False` significaba que el barrido se rompió. Con
tramos significa "va por la página 22 de 44". Si esto no cambia, el semáforo queda
rojo permanente — y un semáforo siempre rojo enseña a no mirarlo, que es justo lo
contrario de para qué existe el centinela.
"""
from backend.services import salud_logistica as S


class _McFalso:
    def __init__(self, uf, edad_tramo=60.0):
        self._uf = uf
        self._edad = edad_tramo

    def ultimo_fetch(self):
        return self._uf

    def _edad_tramo(self):
        return self._edad

    def ultimo_fallo_get(self):
        return {"motivo": "", "path": "", "ts": None}

    def ultimo_guardado_bloqueado(self):
        return {"ts": None, "antes": 0, "intento": 0, "fuente": ""}


def _correr(mc):
    hallazgos, medidas = [], {}
    def marcar(nivel, clave, mensaje, **datos):
        hallazgos.append({"nivel": nivel, "clave": clave, "mensaje": mensaje})
    S._revisar_fetch(mc, marcar, medidas)
    return hallazgos, medidas


def test_a_mitad_de_barrido_no_es_rojo():
    mc = _McFalso({"generacion": 7, "pagina": 22, "paginas_estimadas": 44,
                   "en_curso": True, "motivo_fin": "tramo_ok", "completo": False,
                   "ultimo_completo_en": "2026-08-06T12:00:00",
                   "ultimo_tramo_en": "2026-08-06T13:00:00"})
    hallazgos, medidas = _correr(mc)
    assert [h for h in hallazgos if h["nivel"] == "rojo"] == []
    assert medidas["ultimo_fetch"]["pagina"] == 22


def test_barrido_atascado_es_rojo():
    """El último barrido COMPLETO puede verse reciente y aun así el barrido en
    curso llevar horas sin avanzar ni una página. Antes no tenía alarma."""
    mc = _McFalso({"generacion": 7, "pagina": 22, "paginas_estimadas": 44,
                   "en_curso": True, "motivo_fin": "tramo_ok", "completo": False,
                   "ultimo_completo_en": "2026-08-06T12:00:00",
                   "ultimo_tramo_en": "2026-08-06T09:00:00"},
                  edad_tramo=4 * 3600)
    hallazgos, _ = _correr(mc)
    assert [h["clave"] for h in hallazgos if h["nivel"] == "rojo"] == ["barrido_atascado"]


def test_tope_paginas_sigue_siendo_rojo():
    mc = _McFalso({"generacion": 7, "pagina": 60, "paginas_estimadas": 44,
                   "en_curso": True, "motivo_fin": "tope_paginas", "completo": False,
                   "ultimo_completo_en": "2026-08-06T12:00:00",
                   "ultimo_tramo_en": "2026-08-06T13:00:00"})
    hallazgos, _ = _correr(mc)
    assert "tope_paginas" in [h["clave"] for h in hallazgos if h["nivel"] == "rojo"]


def test_un_fallo_de_pagina_es_ambar_no_rojo():
    """Con cursor, una página que falla se reintenta en el tramo siguiente: es
    ruido operativo, no una caída. Rojo lo pone el reloj si deja de cerrar."""
    mc = _McFalso({"generacion": 7, "pagina": 22, "paginas_estimadas": 44,
                   "en_curso": True, "motivo_fin": "fallo_get_pagina_22:http_429",
                   "completo": False,
                   "ultimo_completo_en": "2026-08-06T12:00:00",
                   "ultimo_tramo_en": "2026-08-06T13:00:00"})
    hallazgos, _ = _correr(mc)
    niveles = {h["clave"]: h["nivel"] for h in hallazgos}
    assert niveles.get("tramo_fallido") == "amarillo"


def test_barrido_cerrado_y_al_dia_no_tiene_hallazgos():
    mc = _McFalso({"generacion": 8, "pagina": 0, "paginas_estimadas": 44,
                   "en_curso": False, "motivo_fin": "ultima_pagina", "completo": True,
                   "ultimo_completo_en": "2026-08-06T13:00:00",
                   "ultimo_tramo_en": "2026-08-06T13:00:00"})
    hallazgos, _ = _correr(mc)
    assert hallazgos == []
