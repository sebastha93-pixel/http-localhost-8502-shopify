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


def test_ajuste_por_elemento_se_suma_a_dy():
    zpl = svc.generar_zpl_trabajo(_trabajo(
        codigo_referencia="SEGUNDA-40000", sin_talla=True, copias=1,
        dy=34, dy_marca=16, dy_qr=8))
    m = svc.ZPL_STK_X0 + svc.ZPL_STK_MARGEN
    assert f"^FO{m},56^" in zpl          # marca 6+34+16
    assert ",72^BQN" in zpl              # QR 30+34+8
    assert f"^FO{m},186^" in zpl         # leyenda 152+34


def test_lista_con_referencia_y_precio():
    zpl = svc.generar_zpl_trabajo(_trabajo(
        codigo_referencia="REPOSICION", dy=34, dy_marca=16, dy_qr=8,
        items=[{"dato": "26630-1T8", "precio": "$149.900", "qty": 4},
               {"dato": "66638TM", "precio": "$99.900", "qty": 2}]))
    assert zpl.count("^FDQA,26630-1T8^FS") == 4
    assert zpl.count("^FDQA,66638TM^FS") == 2
    assert zpl.count("^FD26630-1T8^FS") == 4               # referencia visible
    assert zpl.count("^FD$149.900^FS") == 4
    assert zpl.count("^FD$99.900^FS") == 2
    assert zpl.count("^XA") == 2                            # 6 stickers = 2 filas
    m = svc.ZPL_STK_X0 + svc.ZPL_STK_MARGEN
    assert f"^FO{m},174^" in zpl and f"^FO{m},192^" in zpl  # ref y precio
    assert "REPOSICION" not in zpl


def test_layout_precio_grande():
    zpl = svc.generar_zpl_trabajo(_trabajo(
        codigo_referencia="REPOSICION",
        layout={"marca": [56, 18], "qr": [64], "ref": [166, 16], "precio": [181, 30, 30]},
        items=[{"dato": "26630-1T8", "precio": "$149.900", "qty": 1}]))
    assert ",56^FB" in zpl and "^A0N,18,18^FDMALE DENIM^FS" in zpl
    assert ",64^BQN,2,4^FDQA,26630-1T8^FS" in zpl
    assert "^A0N,16,16^FD26630-1T8^FS" in zpl
    assert ",181^FB240,1,0,C,0^A0N,30,30^FD$149.900^FS" in zpl


def test_layout_referencia_y_precio_en_un_renglon():
    zpl = svc.generar_zpl_trabajo(_trabajo(
        codigo_referencia="REPOSICION",
        layout={"marca": [56, 26], "qr": [72], "linea": [184, 22, 20]},
        items=[{"dato": "26630-1T10", "precio": "$149.900", "qty": 1}]))
    assert "^A0N,26,26^FDMALE DENIM^FS" in zpl
    assert ",72^BQN,2,4^FDQA,26630-1T10^FS" in zpl
    assert ",184^FB240,1,0,C,0^A0N,22,20^FD26630-1T10 $149.900^FS" in zpl
    assert zpl.count("$149.900") == 1
