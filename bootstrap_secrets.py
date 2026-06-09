"""
bootstrap_secrets.py — Genera .streamlit/secrets.toml en runtime
==================================================================
Railway (y cualquier PaaS) usan variables de entorno, no archivos toml.
Este script convierte las env vars a un secrets.toml que Streamlit puede leer.

Modos de uso:

  1) Pegar el secrets.toml ENTERO en la env var STREAMLIT_SECRETS_TOML
     (más simple — copy/paste literal del archivo local)

  2) Definir env vars individuales:
        MELONN_API_KEY, SHOPIFY_*, MP_ACCESS_TOKEN, SUPABASE_*,
        AUTH_COOKIE_NAME, AUTH_COOKIE_KEY, AUTH_EXPIRY_DAYS,
        STREAMLIT_USERS_TOML  (la sección [credentials] como TOML)

  3) Modo local: si ya existe .streamlit/secrets.toml, no hace nada.

Ejecutar antes de streamlit run.
"""
import os
import sys
from pathlib import Path

ROOT       = Path(__file__).parent
SECRETS_TO = ROOT / ".streamlit" / "secrets.toml"


def _from_full_toml() -> bool:
    """Modo 1: env var contiene todo el TOML."""
    contenido = os.environ.get("STREAMLIT_SECRETS_TOML", "")
    if not contenido.strip():
        return False
    SECRETS_TO.parent.mkdir(parents=True, exist_ok=True)
    SECRETS_TO.write_text(contenido, encoding="utf-8")
    print(f"✓ secrets.toml generado desde STREAMLIT_SECRETS_TOML ({len(contenido)} chars)")
    return True


def _from_individual_vars() -> bool:
    """Modo 2: env vars individuales."""
    parts = []

    # APIs externas
    for key in ("MELONN_API_KEY", "SHOPIFY_STORE", "SHOPIFY_ACCESS_TOKEN",
                "SHOPIFY_API_VERSION", "MP_ACCESS_TOKEN",
                "SUPABASE_URL", "SUPABASE_KEY"):
        val = os.environ.get(key)
        if val:
            parts.append(f'{key} = "{val}"')

    # Cookie auth
    cookie_lines = []
    for k_src, k_dst in (("AUTH_COOKIE_NAME", "name"),
                         ("AUTH_COOKIE_KEY",  "key"),
                         ("AUTH_EXPIRY_DAYS", "expiry_days")):
        v = os.environ.get(k_src)
        if v:
            cookie_lines.append(
                f'{k_dst} = {v}' if k_dst == "expiry_days" else f'{k_dst} = "{v}"'
            )
    if cookie_lines:
        parts.append("[cookie]")
        parts.extend(cookie_lines)

    # Usuarios (sección [credentials.usernames.X])
    users_toml = os.environ.get("STREAMLIT_USERS_TOML", "").strip()
    if users_toml:
        parts.append(users_toml)
    else:
        # Fallback admin único si no se definieron usuarios
        admin_pwd_hash = os.environ.get("ADMIN_PASSWORD_HASH", "")
        admin_name     = os.environ.get("ADMIN_NAME", "Admin")
        admin_user     = os.environ.get("ADMIN_USERNAME", "admin")
        admin_email    = os.environ.get("ADMIN_EMAIL", "admin@example.com")
        if admin_pwd_hash:
            parts.append("[credentials.usernames." + admin_user + "]")
            parts.append(f'name = "{admin_name}"')
            parts.append(f'email = "{admin_email}"')
            parts.append(f'password = "{admin_pwd_hash}"')
            parts.append('role = "admin"')
            parts.append('permisos = ["logistica","comercial","mercadopago","conciliacion"]')

    if not parts:
        return False

    SECRETS_TO.parent.mkdir(parents=True, exist_ok=True)
    SECRETS_TO.write_text("\n".join(parts) + "\n", encoding="utf-8")
    print(f"✓ secrets.toml generado desde env vars individuales")
    return True


def main():
    # Si ya existe (modo local), no sobrescribimos
    if SECRETS_TO.exists() and not os.environ.get("STREAMLIT_SECRETS_TOML"):
        print(f"• secrets.toml ya existe en {SECRETS_TO} — no se modifica")
        return 0

    if _from_full_toml():
        return 0

    if _from_individual_vars():
        return 0

    print("⚠ Sin env vars de secrets — la app correrá sin auth (modo desarrollo)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
