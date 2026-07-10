"""
Cliente REST para la API de Shopify Admin — Male Denim OS
Maneja paginación por cursor, rate limiting y reintentos automáticos.

Docs: https://shopify.dev/docs/api/admin-rest
"""

import os
import time
import json
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional, Iterator, Dict, List
from datetime import datetime, timezone

# ── Cargar .env manualmente (sin dependencias externas) ───────────────────────
def _cargar_env() -> None:
    env_path = Path(__file__).parent.parent / ".env"
    if not env_path.exists():
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

_cargar_env()

# ── Configuración ──────────────────────────────────────────────────────────────
SHOPIFY_STORE   = os.environ.get("SHOPIFY_STORE", "")
ACCESS_TOKEN    = os.environ.get("SHOPIFY_ACCESS_TOKEN", "")
API_VERSION     = os.environ.get("SHOPIFY_API_VERSION", "2024-01")

RATE_LIMIT_PAUSA  = 0.5   # 2 req/s = refill exacto de Shopify. Con 0.3s el bucket se agota y los 429+reintentos salen MÁS caros (medido: 28s vs 5s).
MAX_REINTENTOS    = 3
LIMITE_POR_PAGINA = 250   # máximo que permite Shopify


class ShopifyError(Exception):
    pass


class ShopifyRateLimitError(ShopifyError):
    pass


def _base_url() -> str:
    if not SHOPIFY_STORE:
        raise ShopifyError(
            "SHOPIFY_STORE no configurado. "
            "Edita el archivo .env con tu tienda (ej: maledenim.myshopify.com)"
        )
    return f"https://{SHOPIFY_STORE}/admin/api/{API_VERSION}"


def _headers() -> dict:
    if not ACCESS_TOKEN:
        raise ShopifyError(
            "SHOPIFY_ACCESS_TOKEN no configurado. "
            "Edita el archivo .env con tu access token."
        )
    return {
        "X-Shopify-Access-Token": ACCESS_TOKEN,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _get(endpoint: str, params: Optional[Dict] = None) -> dict:
    """
    GET a un endpoint de la API de Shopify con reintentos y rate limiting.
    Retorna el JSON parseado.
    """
    data, _ = _get_full(endpoint, params)
    return data


def _get_full(endpoint: str, params: Optional[Dict] = None):
    """
    GET con reintentos. Retorna (json_data, link_header_str).
    El Link header de Shopify contiene la URL de la siguiente página (cursor).
    """
    # Si el endpoint ya es una URL absoluta (page_info cursor), úsala directamente
    if endpoint.startswith("http"):
        url = endpoint
    else:
        url = f"{_base_url()}{endpoint}"
        if params:
            query = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
            url = f"{url}?{query}"

    for intento in range(MAX_REINTENTOS):
        try:
            req = urllib.request.Request(url, headers=_headers())
            with urllib.request.urlopen(req, timeout=30) as resp:
                time.sleep(RATE_LIMIT_PAUSA)
                link_header = resp.headers.get("Link", "")
                return json.loads(resp.read().decode("utf-8")), link_header

        except urllib.error.HTTPError as e:
            if e.code == 429:
                espera = 2 ** (intento + 1)
                print(f"  Rate limit — esperando {espera}s...")
                time.sleep(espera)
                continue
            if e.code == 401:
                raise ShopifyError("Access token inválido o sin permisos.") from e
            if e.code == 404:
                raise ShopifyError(f"Endpoint no encontrado: {endpoint}") from e
            raise ShopifyError(f"HTTP {e.code}: {e.reason}") from e

        except Exception as e:
            if intento == MAX_REINTENTOS - 1:
                raise ShopifyError(f"Error de conexión: {e}") from e
            time.sleep(1)

    raise ShopifyError("Máximo de reintentos alcanzado")


def _next_url_from_link(link_header: str) -> Optional[str]:
    """
    Extrae la URL de la próxima página del header Link de Shopify.
    Formato: <URL>; rel="next", <URL>; rel="previous"
    """
    if not link_header:
        return None
    for part in link_header.split(","):
        part = part.strip()
        if 'rel="next"' in part:
            # Extraer URL entre < >
            start = part.find("<")
            end = part.find(">")
            if start != -1 and end != -1:
                return part[start + 1:end]
    return None


def paginar(endpoint: str, clave: str, params: Optional[Dict] = None) -> Iterator[List[Dict]]:
    """
    Itera sobre todas las páginas usando paginación por cursor (Link header).
    Shopify pone la URL de la siguiente página en el header HTTP Link rel="next".
    Yields: lista de registros por página.
    """
    # Primera página con parámetros normales
    current_url = endpoint
    current_params = {"limit": LIMITE_POR_PAGINA, **(params or {})}
    use_params = True

    while True:
        if use_params:
            data, link_header = _get_full(current_url, current_params)
        else:
            # Páginas siguientes: URL absoluta del cursor, sin params adicionales
            data, link_header = _get_full(current_url)

        registros = data.get(clave, [])
        if not registros:
            break

        yield registros

        # Seguir con el cursor del Link header
        next_url = _next_url_from_link(link_header)
        if not next_url:
            break
        current_url = next_url
        use_params = False  # cursor ya viene en la URL


def verificar_conexion() -> Dict:
    """Verifica credenciales y retorna info básica de la tienda."""
    data = _get("/shop.json")
    shop = data.get("shop", {})
    return {
        "nombre":   shop.get("name"),
        "dominio":  shop.get("domain"),
        "email":    shop.get("email"),
        "plan":     shop.get("plan_name"),
        "moneda":   shop.get("currency"),
        "pais":     shop.get("country_name"),
        "timezone": shop.get("iana_timezone"),
    }


def contar_pedidos(estado: str = "any") -> int:
    """Retorna el total de pedidos en la tienda."""
    data = _get("/orders/count.json", {"status": estado})
    return data.get("count", 0)


if __name__ == "__main__":
    print("Verificando conexión con Shopify...")
    try:
        info = verificar_conexion()
        print("\n✓ Conexión exitosa:")
        for k, v in info.items():
            print(f"  {k}: {v}")
        total = contar_pedidos()
        print(f"\n  Total pedidos en la tienda: {total}")
    except ShopifyError as e:
        print(f"\n✗ Error: {e}")
        print("\nVerifica que .env tenga:")
        print("  SHOPIFY_STORE=tu-tienda.myshopify.com")
        print("  SHOPIFY_ACCESS_TOKEN=shpat_...")
