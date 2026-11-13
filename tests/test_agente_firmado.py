"""Agente de impresión firmado (auditoría de seguridad 2026-11, informe 15 #26, #9 y #27).

Antes el servidor MDS se instalaba con `irm … | iex`: corría como administrador lo que
entregara el backend, sin firma. Ahora el instalador verifica una firma RSA con una llave
pública fijada en el PC, y la llave privada vive solo en el Mac del dueño.

Lo que vigila este archivo:
- Que cada archivo servido tenga una firma VÁLIDA. Si alguien edita el agente y olvida
  correr `tools/firmar_agente.sh`, el PC rechazaría la actualización: mejor que lo diga
  el test que la impresora callada.
- Que la llave pegada en instalar.ps1 sea la misma de llave_publica.xml.
- Que el endpoint público solo entregue la lista blanca.
- Que marcar como impreso o lanzar pruebas ya no se pueda con solo «ver» (#9).

La verificación RSA se hace a mano (PKCS#1 v1.5 + SHA-256) para no meter una dependencia.
"""
import base64
import hashlib
import os
import re

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.api import produccion
from backend.core.security import CurrentUser

DIST = produccion._AGENTE_DIST
FIRMADOS = ["agente_impresion.ps1", "instalar.ps1", "oyente.js", "package.json", "instalar_oyente.ps1"]
# DigestInfo DER de SHA-256 (RFC 8017, 9.2): lo que va dentro de la firma PKCS#1 v1.5.
_DIGEST_INFO_SHA256 = bytes.fromhex("3031300d060960864801650304020105000420")


def _llave(xml: str) -> tuple[int, int]:
    n = re.search(r"<Modulus>([^<]+)</Modulus>", xml).group(1)
    e = re.search(r"<Exponent>([^<]+)</Exponent>", xml).group(1)
    return (int.from_bytes(base64.b64decode(n), "big"), int.from_bytes(base64.b64decode(e), "big"))


def _verifica(datos: bytes, firma_b64: str, llave: tuple[int, int]) -> bool:
    n, e = llave
    k = (n.bit_length() + 7) // 8
    try:
        firma = base64.b64decode(firma_b64.strip(), validate=True)
    except Exception:
        return False
    if len(firma) != k:
        return False
    em = pow(int.from_bytes(firma, "big"), e, n).to_bytes(k, "big")
    t = _DIGEST_INFO_SHA256 + hashlib.sha256(datos).digest()
    esperado = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
    return em == esperado


def _leer(nombre: str, modo: str = "rb"):
    with open(os.path.join(DIST, nombre), modo) as f:
        return f.read()


LLAVE = _llave(_leer("llave_publica.xml", "r"))


# ── Firmas ──────────────────────────────────────────────────────────────────

def test_la_llave_es_rsa_de_3072():
    assert LLAVE[0].bit_length() == 3072
    assert LLAVE[1] == 65537


@pytest.mark.parametrize("nombre", FIRMADOS)
def test_cada_archivo_servido_tiene_su_firma_valida(nombre):
    # Si falla: se cambió el archivo sin volver a firmar. Correr tools/firmar_agente.sh.
    assert _verifica(_leer(nombre), _leer(nombre + ".firma", "r"), LLAVE), (
        f"{nombre}.firma no corresponde al archivo: correr tools/firmar_agente.sh"
    )


def test_la_verificacion_rechaza_un_byte_cambiado_y_una_firma_cruzada():
    datos = bytearray(_leer("agente_impresion.ps1"))
    firma = _leer("agente_impresion.ps1.firma", "r")
    datos[100] ^= 1
    assert not _verifica(bytes(datos), firma, LLAVE)
    assert not _verifica(_leer("agente_impresion.ps1"), _leer("instalar.ps1.firma", "r"), LLAVE)
    assert not _verifica(_leer("agente_impresion.ps1"), "basura", LLAVE)


def test_instalar_ps1_trae_pegada_la_misma_llave():
    ps1 = _leer("instalar.ps1", "r")
    m = re.search(r"\$LlavePublica = '([^']+)'", ps1)
    assert m, "instalar.ps1 perdió la llave pública"
    assert _llave(m.group(1)) == LLAVE


def test_instalar_ps1_ya_no_usa_iex_ni_busca_en_escritorios():
    ps1 = _leer("instalar.ps1", "r")
    # Fuera de comentarios y de los mensajes que se le muestran a la persona (`Di "..."`).
    codigo = "\n".join(l for l in ps1.splitlines() if not l.lstrip().startswith(("#", "Di ")))
    assert "| iex" not in codigo and "Invoke-Expression" not in codigo
    assert "Desktop" not in codigo and "Escritorio" not in codigo
    assert "MaleDenim\\AgenteImpresion" in codigo
    assert "Test-Firma" in codigo


def test_instalar_ps1_es_ascii():
    # Windows PowerShell 5.1 lee un .ps1 sin BOM como ANSI: un carácter fuera de ASCII
    # en un texto que se imprime saldría roto.
    assert all(b < 128 for b in _leer("instalar.ps1"))


# ── Endpoint de distribución ────────────────────────────────────────────────

@pytest.fixture
def cliente():
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(produccion.router)
    return TestClient(app)


def test_todo_lo_de_la_lista_blanca_existe():
    for nombre in produccion._AGENTE_ARCHIVOS:
        assert os.path.isfile(os.path.join(DIST, nombre)), nombre


@pytest.mark.parametrize("nombre", FIRMADOS)
def test_sirve_el_archivo_y_su_firma_tal_cual(cliente, nombre):
    r = cliente.get(f"/api/produccion/agente/{nombre}")
    assert r.status_code == 200 and r.content == _leer(nombre)
    f = cliente.get(f"/api/produccion/agente/{nombre}.firma")
    assert f.status_code == 200 and _verifica(r.content, f.text, LLAVE)


@pytest.mark.parametrize("nombre", [
    "config.json", "llave_publica.xml", "INSTALAR_ARRANQUE_AUTOMATICO.bat",
    "..%2Fapi%2Fproduccion.py", "agente_impresion.ps1.nuevo",
])
def test_no_sirve_nada_fuera_de_la_lista(cliente, nombre):
    assert cliente.get(f"/api/produccion/agente/{nombre}").status_code == 404


# ── #9: marcar impreso y lanzar pruebas ─────────────────────────────────────

def _usuario(email: str, acciones: list[str], rol: str = "user") -> CurrentUser:
    return CurrentUser(id="u1", email=email, nombre="x", rol=rol,
                       permisos={"produccion_remisiones": acciones})


def test_el_agente_pasa_aunque_solo_tenga_ver():
    produccion._exigir_agente_o_modificar(_usuario("Impresion@MaleDenim.com", ["ver"]))


def test_quien_puede_modificar_pasa():
    produccion._exigir_agente_o_modificar(_usuario("jefa@x.com", ["ver", "modificar"]))
    produccion._exigir_agente_o_modificar(_usuario("dueno@x.com", [], rol="admin"))


@pytest.mark.parametrize("rol", ["user", "lector"])
def test_con_solo_ver_ya_no_se_saca_nada_de_la_cola(rol):
    with pytest.raises(HTTPException) as e:
        produccion._exigir_agente_o_modificar(_usuario("mira@x.com", ["ver"], rol=rol))
    assert e.value.status_code == 403


@pytest.mark.parametrize("ruta", [
    "/impresion/{rem_id}/impresa",
    "/impresion/trabajos/{trabajo_id}/impreso",
    "/impresion/prueba",
])
def test_los_tres_post_pasan_por_la_compuerta(ruta):
    import inspect
    rutas = {r.path: r for r in produccion.router.routes if "POST" in getattr(r, "methods", set())}
    fn = rutas[f"/api/produccion{ruta}"].endpoint
    assert "_exigir_agente_o_modificar(user)" in inspect.getsource(fn)


# ── Oyente del grupo: se actualiza solo cada 15 min como SYSTEM ─────────────

import shutil
import subprocess


def _bloque_firma_oyente() -> str:
    js = _leer("oyente.js", "r")
    m = re.search(r"// <firma>.*?\n(.*?)// </firma>", js, re.S)
    assert m, "oyente.js perdió el bloque <firma>"
    return m.group(1)


def test_el_oyente_trae_pegada_la_misma_llave():
    pem = re.search(r"-----BEGIN PUBLIC KEY-----(.*?)-----END PUBLIC KEY-----",
                    _bloque_firma_oyente(), re.S).group(1)
    der = base64.b64decode("".join(pem.split()))
    n, e = LLAVE
    # El módulo y el exponente de llave_publica.xml van dentro del DER.
    assert n.to_bytes(384, "big") in der and e.to_bytes(3, "big") in der


@pytest.mark.skipif(not shutil.which("node"), reason="sin node")
def test_firmaValida_del_oyente_acepta_lo_firmado_y_rechaza_lo_demas(tmp_path):
    js = _bloque_firma_oyente() + """
const fs = require("fs");
const [, , datos, firma, otraFirma] = process.argv;
const b = fs.readFileSync(datos);
const f = fs.readFileSync(firma, "utf8");
const m = Buffer.from(b); m[100] ^= 1;
console.log(JSON.stringify([
  firmaValida(b, f),
  firmaValida(m, f),
  firmaValida(b, fs.readFileSync(otraFirma, "utf8")),
  firmaValida(b, "basura"),
  firmaValida(b, ""),
  firmaValida(b, undefined),
]));
"""
    prueba = tmp_path / "prueba.js"
    prueba.write_text(js)
    r = subprocess.run(["node", str(prueba), os.path.join(DIST, "oyente.js"),
                        os.path.join(DIST, "oyente.js.firma"),
                        os.path.join(DIST, "package.json.firma")],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "[true,false,false,false,false,false]"


def test_la_autoactualizacion_exige_firma_antes_de_escribir():
    js = _leer("oyente.js", "r")
    cuerpo = js[js.index("async function buscarActualizacion"):]
    cuerpo = cuerpo[:cuerpo.index("\n}\n")]
    i_firma = cuerpo.index("firmaValida(bytes")
    assert "oyente.js.firma" in cuerpo
    assert i_firma < cuerpo.index("writeFileSync(tmp")
    assert i_firma < cuerpo.index("renameSync(tmp")


def test_el_oyente_blinda_su_carpeta_por_sid():
    js = _leer("oyente.js", "r")
    assert "blindarCarpeta();" in js
    for sid in ("*S-1-5-32-544:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F", "/inheritance:r"):
        assert sid in js


def test_el_instalador_del_oyente_verifica_firma_y_no_usa_iex():
    ps1 = _leer("instalar_oyente.ps1", "r")
    codigo = "\n".join(l for l in ps1.splitlines() if not l.lstrip().startswith(("#", "Write-Host")))
    assert "| iex" not in codigo and "Invoke-Expression" not in codigo
    assert "Test-Firma" in codigo and ".firma" in codigo and "/inheritance:r" in codigo
    m = re.search(r"\$LlavePublica = '([^']+)'", ps1)
    assert m and _llave(m.group(1)) == LLAVE
