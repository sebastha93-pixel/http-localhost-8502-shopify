"""Sticker LIBRE (sin talla): segundas por precio. El QR lleva el código tal
cual y la leyenda visible puede ser distinta del dato del QR."""
from backend.services import produccion as svc


def _trabajo(**payload):
    return {"tipo": "sticker_codigo", "payload": payload}


def test_sticker_libre_qr_sin_talla_y_leyenda():
    zpl = svc.generar_zpl_trabajo(_trabajo(
        codigo_referencia="SEGUNDA-40000", texto="SEGUNDA 40.000",
        sin_talla=True, copias=50))
    assert zpl.count("^FDQA,SEGUNDA-40000^FS") == 50      # 50 QR, sin 'T'+talla
    assert zpl.count("^FDSEGUNDA 40.000^FS") == 50         # leyenda visible
    assert "SEGUNDA-40000T" not in zpl
    assert zpl.count("^XA") == 17                           # 16 filas de 3 + 1 de 2


def test_sticker_libre_sin_texto_muestra_el_codigo():
    zpl = svc.generar_zpl_trabajo(_trabajo(
        codigo_referencia="SEGUNDA-99000", sin_talla=True, copias=2))
    assert zpl.count("^FDSEGUNDA-99000^FS") == 2


def test_sticker_con_talla_no_cambia():
    zpl = svc.generar_zpl_trabajo(_trabajo(
        codigo_referencia="26640-1", tallas={"10": 2, "8": 1}))
    assert zpl.count("^FDQA,26640-1T10^FS") == 2
    assert zpl.count("^FD26640-1T8^FS") == 1
    assert zpl.count("^XA") == 1


def test_ajuste_de_posicion_dx_dy():
    zpl = svc.generar_zpl_trabajo(_trabajo(
        codigo_referencia="SEGUNDA-40000", sin_talla=True, copias=1, dx=8, dy=38))
    x0 = svc.ZPL_STK_X0 + 8
    assert f"^FO{x0 + svc.ZPL_STK_MARGEN},44^" in zpl      # MALE DENIM 6+38
    assert ",68^BQN" in zpl                                 # QR 30+38
    assert f"^FO{x0 + svc.ZPL_STK_MARGEN},190^" in zpl     # leyenda 152+38


def test_sin_ajuste_queda_igual():
    zpl = svc.generar_zpl_trabajo(_trabajo(
        codigo_referencia="26640-1", tallas={"10": 1}))
    assert ",30^BQN" in zpl and ",152^FB" in zpl
