#!/usr/bin/env python3
"""
Rellena guía real + transportadora de los pedidos despachados que las perdieron.

POR QUÉ ESTE SCRIPT Y NO EL BOTÓN "Sincronizar datos": ese botón corre
sync_completo, que además del enriquecimiento de Shopify hace una pasada de
DETALLE CONTRA MELONN (tope 50 por pulsada) y una verificación de estados
(tope 25). Para rellenar guías eso es gasto puro de cuota Melonn: la guía y la
transportadora viven en los FULFILLMENTS DE SHOPIFY, no en Melonn.

Este script no le pega a Melonn ni una vez:
  · lee el caché desde Supabase (PostgREST)
  · pide los fulfillments a Shopify por lotes
  · escribe en `pedido_overrides`, que es el almacén DURABLE

Se escribe en pedido_overrides y no en el blob del caché a propósito: el blob se
reescribe en cada sync y el 27-jul aprendimos que puede quedar en blanco.
overrides sobrevive a eso, y `overrides.aplicar_a_pedido` ya lo pinta encima.

USO:
    python3 tools/rellenar_guias.py            # reporta, no escribe
    python3 tools/rellenar_guias.py --aplicar  # escribe los overrides

Idempotente: solo toca los que NO tienen guía.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

LOTE = 50          # ids por llamada a Shopify (su tope para ?ids= es 250)
TIMEOUT = 30
DESPACHADOS = ("en_transito", "entregado")


def _sb():
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_KEY", "").strip()
    if not url or not key:
        raise SystemExit("Faltan SUPABASE_URL / SUPABASE_KEY")
    return url.rstrip("/"), {"apikey": key, "Authorization": f"Bearer {key}"}


def _leer_cache() -> list[dict]:
    """Pedidos del caché, vía PostgREST. Cero llamadas a Melonn."""
    url, h = _sb()
    r = requests.get(f"{url}/rest/v1/melonn_cache?select=pedidos_json&id=eq.1",
                     headers=h, timeout=TIMEOUT)
    r.raise_for_status()
    filas = r.json()
    if not filas:
        raise SystemExit("Caché vacío")
    env = json.loads(filas[0]["pedidos_json"])
    return env.get("pedidos", env) if isinstance(env, dict) else env


def _shopify_creds() -> tuple[str, str, str]:
    from backend.services import shopify_auth
    store = os.environ.get("SHOPIFY_STORE", "").strip()
    version = os.environ.get("SHOPIFY_API_VERSION", "2024-01").strip()
    if not store:
        raise SystemExit("Falta SHOPIFY_STORE")
    return store, shopify_auth.token(), version


def _primer(*vals) -> str:
    for v in vals:
        if isinstance(v, list):
            v = v[0] if v else None
        if v:
            return str(v).strip()
    return ""


def main() -> int:
    aplicar = "--aplicar" in sys.argv
    pedidos = _leer_cache()
    print(f"caché: {len(pedidos)} pedidos\n")

    # Candidatos: despachados, con id de Shopify, sin guía.
    cands = [
        p for p in pedidos
        if p.get("sub_estado_logistico") in DESPACHADOS
        and str(p.get("external_order_id") or "").strip()
        and not str(p.get("guia_real") or "").strip()
    ]
    sin_id = [
        p for p in pedidos
        if p.get("sub_estado_logistico") in DESPACHADOS
        and not str(p.get("external_order_id") or "").strip()
        and not str(p.get("guia_real") or "").strip()
    ]
    print(f"despachados sin guía         : {len(cands) + len(sin_id)}")
    print(f"  con id de Shopify (se pueden): {len(cands)}")
    print(f"  sin id (cargados a mano)     : {len(sin_id)}  → imposible por esta vía")
    print()
    if not cands:
        print("Nada que rellenar.")
        return 0

    store, token, version = _shopify_creds()
    url = f"https://{store}/admin/api/{version}/orders.json"
    headers = {"X-Shopify-Access-Token": token}

    por_id = {str(p["external_order_id"]): p for p in cands}
    ids = list(por_id)
    encontrados: dict[str, dict] = {}
    for i in range(0, len(ids), LOTE):
        chunk = ids[i:i + LOTE]
        try:
            r = requests.get(url, headers=headers, timeout=TIMEOUT,
                             params={"ids": ",".join(chunk), "status": "any",
                                     "fields": "id,name,fulfillments"})
            r.raise_for_status()
            for o in r.json().get("orders", []):
                encontrados[str(o["id"])] = o
            print(f"  lote {i//LOTE + 1}: pedí {len(chunk)}, llegaron {len(r.json().get('orders', []))}")
        except Exception as e:
            print(f"  lote {i//LOTE + 1} FALLÓ: {str(e)[:140]}")

    # Extraer la guía de la TRANSPORTADORA REAL. Ojo: NO vale el primer
    # fulfillment que traiga número — Melonn crea el suyo con
    # tracking_company="Melonn" y su M-id interno como tracking_number, que no
    # sirve para rastrear. Si escribiéramos eso en overrides estaríamos
    # guardando basura con apariencia de guía (y pisando la real).
    from shopify_enricher import es_mid_melonn

    listos, sin_tracking, solo_mid = [], [], []
    for sid, o in encontrados.items():
        guia = carrier = ""
        for f in (o.get("fulfillments") or []):
            num = _primer(f.get("tracking_number"), f.get("tracking_numbers"))
            comp = _primer(f.get("tracking_company"))
            if not num:
                continue
            if "melonn" in comp.lower() or es_mid_melonn(num):
                continue                    # M-id: no es una guía, se ignora
            guia, carrier = num, comp
            break
        p = por_id[sid]
        orden = p.get("orden_tienda") or p.get("orden_melonn")
        if guia:
            listos.append((orden, guia, carrier))
        elif (o.get("fulfillments") or []):
            solo_mid.append(orden)
        else:
            sin_tracking.append(orden)

    if solo_mid:
        print(f"  con fulfillment pero SOLO M-id de Melonn: {len(solo_mid)} "
              f"→ se omiten (la guía real la saca el bot de tracking)")

    print()
    print(f"con guía en Shopify   : {len(listos)}")
    print(f"sin tracking aún      : {len(sin_tracking)}  (Shopify no la tiene todavía)")
    print()
    for orden, guia, carrier in listos[:10]:
        print(f"  {str(orden):12} {guia:22} {carrier}")
    if len(listos) > 10:
        print(f"  … y {len(listos) - 10} más")
    print()

    if not aplicar:
        print("MODO REPORTE. Nada se escribió.")
        print("Para aplicar: python3 tools/rellenar_guias.py --aplicar")
        return 0

    sb_url, h = _sb()
    h = {**h, "Content-Type": "application/json",
         "Prefer": "resolution=merge-duplicates"}
    ok = err = 0
    for orden, guia, carrier in listos:
        try:
            r = requests.post(
                f"{sb_url}/rest/v1/pedido_overrides",
                headers=h, timeout=TIMEOUT,
                json={"orden": str(orden), "guia_real": guia,
                      "carrier_real": carrier or None, "autor": "relleno-guias"},
            )
            if r.status_code >= 300:
                raise RuntimeError(f"HTTP {r.status_code}: {r.text[:120]}")
            ok += 1
        except Exception as e:
            err += 1
            print(f"  fallo {orden}: {str(e)[:120]}")
    print(f"\nescritos: {ok}   fallidos: {err}")
    return 0 if err == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
