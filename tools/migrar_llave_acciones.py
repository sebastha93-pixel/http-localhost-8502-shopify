#!/usr/bin/env python3
"""
Normaliza la llave de la tabla `acciones`: orden_tienda → orden_melonn.

EL PROBLEMA (medido 2026-07-29): las acciones se guardaban con la llave que
tuviera a mano el llamador. Las autorizaciones de despacho quedaron bajo
orden_tienda ("61288") mientras el frontend pide el historial con orden_melonn
("M1785..."). Resultado: despachos autorizados reales, invisibles en la app.

El código ya se arregló (memoria.normalizar_orden se aplica al escribir y al
leer, y la lectura consulta ambas llaves). Este script deja además la BASE
consistente, para que el histórico no dependa del fallback de lectura.

USO:
    python3 tools/migrar_llave_acciones.py            # solo reporta, no toca nada
    python3 tools/migrar_llave_acciones.py --aplicar  # ejecuta los updates

Es IDEMPOTENTE: las filas que ya tienen M-id se saltan. Correrlo dos veces no
hace daño.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def main() -> int:
    aplicar = "--aplicar" in sys.argv

    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_KEY", "").strip()
    if not url or not key:
        print("Faltan SUPABASE_URL / SUPABASE_KEY en el entorno.")
        return 1

    from supabase import create_client
    sb = create_client(url, key)

    import melonn_client as mc
    hit = mc._cache_leer(ignorar_ttl=True)
    if not hit:
        print("No hay caché de Melonn — sin él no se puede traducir. Aborto.")
        return 1
    mapa = {str(p["orden_tienda"]): str(p["orden_melonn"])
            for p in hit[0]
            if p.get("orden_tienda") and p.get("orden_melonn")}
    print(f"mapa de traducción: {len(mapa)} pedidos en caché\n")

    filas = (sb.table("acciones").select("id,orden,tipo,autor,creada_en")
               .order("creada_en", desc=True).limit(5000).execute()).data or []

    def es_melonn(o: str) -> bool:
        o = str(o or "")
        return len(o) > 1 and o[0] in "Mm" and o[1:].isdigit()

    ya_ok = [f for f in filas if es_melonn(f["orden"])]
    traducibles, huerfanas = [], []
    for f in filas:
        if es_melonn(f["orden"]):
            continue
        (traducibles if str(f["orden"]) in mapa else huerfanas).append(f)

    print(f"total filas revisadas : {len(filas)}")
    print(f"  ya canónicas (M-id) : {len(ya_ok)}")
    print(f"  traducibles         : {len(traducibles)}")
    print(f"  sin equivalente     : {len(huerfanas)}  (se dejan como están)")
    print()

    if traducibles:
        print("muestra de lo que se traduciría:")
        for f in traducibles[:10]:
            print(f"  {f['orden']:12} → {mapa[str(f['orden'])]:22} {f['tipo']:22} {f['autor'][:20]}")
        print()

    if huerfanas:
        print("sin equivalente en caché (pedidos viejos ya archivados, probablemente):")
        for f in huerfanas[:5]:
            print(f"  {f['orden']:12} {f['tipo']:22} {f['creada_en'][:10]}")
        print("  -> la lectura los sigue encontrando por el fallback de doble llave.")
        print()

    if not aplicar:
        print("MODO REPORTE. Nada se modificó.")
        print("Para ejecutar: python3 tools/migrar_llave_acciones.py --aplicar")
        return 0

    if not traducibles:
        print("Nada que migrar.")
        return 0

    ok = err = 0
    for f in traducibles:
        try:
            sb.table("acciones").update(
                {"orden": mapa[str(f["orden"])]}
            ).eq("id", f["id"]).execute()
            ok += 1
        except Exception as e:
            err += 1
            print(f"  fallo en id={f['id']}: {str(e)[:120]}")
    print(f"\nmigradas: {ok}   fallidas: {err}")
    return 0 if err == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
