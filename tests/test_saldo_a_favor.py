"""El saldo a favor lleva el monto REAL de la nota credito.

El frontend mandaba 0 fijo, asi que el historial decia "La clienta deja $0
como saldo a favor". Ese texto es el respaldo de la clienta cuando vuelva a
reclamar su credito: con cero no sirve de nada.

Ahora lo calcula el BACKEND leyendo la NC emitida. El navegador no puede
mandar un monto equivocado porque ya no lo manda.
"""
from backend.services import postventa_fiscal as PF


def test_toma_el_monto_de_la_nota_credito_emitida(monkeypatch):
    monkeypatch.setattr(PF, "_fiscal_existente",
                        lambda cid, k: {"amount": 169900.0} if k == "nota_credito" else None)
    assert PF.credito_disponible("c1") == 169900.0


def test_sin_nota_credito_no_hay_credito(monkeypatch):
    monkeypatch.setattr(PF, "_fiscal_existente", lambda cid, k: None)
    assert PF.credito_disponible("c1") == 0.0


def test_una_nc_sin_monto_no_revienta(monkeypatch):
    monkeypatch.setattr(PF, "_fiscal_existente", lambda cid, k: {"amount": None})
    assert PF.credito_disponible("c1") == 0.0
