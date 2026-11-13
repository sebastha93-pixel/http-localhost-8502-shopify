#!/usr/bin/env bash
# Firma el agente de impresión y su instalador (auditoría 2026-11, informe 15 #26).
#
# El PC del servidor MDS solo instala lo que venga firmado con esta llave. La
# llave privada vive SOLO en el Mac del dueño (~/.male-firma/agente_impresion.pem),
# nunca en el repo, en GitHub ni en Railway: así, tomar el backend o el repo ya
# no basta para meterle código como SYSTEM al servidor de la oficina.
#
# Uso, después de cualquier cambio en el agente, el oyente o sus instaladores:
#     tools/firmar_agente.sh
# y se commitean los .firma junto con el cambio. Si se olvida, el test
# tests/test_agente_firmado.py falla.
set -euo pipefail

LLAVE="${MALE_LLAVE_AGENTE:-$HOME/.male-firma/agente_impresion.pem}"
DIR="$(cd "$(dirname "$0")/../backend/agente_dist" && pwd)"

if [[ ! -f "$LLAVE" ]]; then
  echo "No encuentro la llave privada en $LLAVE" >&2
  exit 1
fi

for f in agente_impresion.ps1 instalar.ps1 oyente.js package.json instalar_oyente.ps1; do
  openssl dgst -sha256 -sign "$LLAVE" "$DIR/$f" | base64 | tr -d '\n' > "$DIR/$f.firma"
  echo "firmado: $f"
done
