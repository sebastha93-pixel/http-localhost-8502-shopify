"""
backend.core.config — Configuración centralizada (lee env vars).

Compatible con:
  - Local: lee .env del root del repo
  - Railway: env vars inyectadas directamente

Mismas variables que Streamlit usa hoy — cero migración de credentials.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT = Path(__file__).resolve().parent.parent.parent   # /repo


class Settings(BaseSettings):
    """Configuración global de la app. Se lee una sola vez por proceso."""

    # ── Hosting ────────────────────────────────────────────────────────────────
    env: str = Field(default="development", alias="APP_ENV", description="production | development")
    port: int = Field(default=8000, description="Puerto del servidor")

    # ── Auth ───────────────────────────────────────────────────────────────────
    auth_jwt_secret: str  = Field(default="dev-only-change-in-prod-XXXX")
    auth_jwt_expiry_min: int = 60 * 24 * 7      # 7 días

    # Bootstrap del primer admin (solo se usa si la tabla usuarios está vacía)
    auth_bootstrap_email:    str = Field(default="", alias="AUTH_BOOTSTRAP_EMAIL")
    auth_bootstrap_password: str = Field(default="", alias="AUTH_BOOTSTRAP_PASSWORD")
    auth_bootstrap_nombre:   str = Field(default="Administrador", alias="AUTH_BOOTSTRAP_NOMBRE")

    # ── CORS ───────────────────────────────────────────────────────────────────
    cors_origins: str = Field(
        # Solo el dominio oficial de producción: app.maledenim.com.
        # Si necesitas dev local más adelante, añade en Railway env:
        #   CORS_ORIGINS=https://app.maledenim.com,http://localhost:3000
        default="https://app.maledenim.com",
        description="Coma-separated lista de origins permitidos (frontend Next.js)",
        alias="CORS_ORIGINS",
    )

    # ── Melonn ─────────────────────────────────────────────────────────────────
    melonn_api_key: str = Field(default="", alias="MELONN_API_KEY")

    # ── Shopify ────────────────────────────────────────────────────────────────
    shopify_store:        str = Field(default="", alias="SHOPIFY_STORE")
    shopify_access_token: str = Field(default="", alias="SHOPIFY_ACCESS_TOKEN")
    shopify_api_version:  str = Field(default="2024-01", alias="SHOPIFY_API_VERSION")

    # ── MercadoPago ────────────────────────────────────────────────────────────
    mp_access_token: str = Field(default="", alias="MP_ACCESS_TOKEN")

    # ── Supabase ───────────────────────────────────────────────────────────────
    supabase_url: str = Field(default="", alias="SUPABASE_URL")
    supabase_key: str = Field(default="", alias="SUPABASE_KEY")

    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    # ── Helpers ────────────────────────────────────────────────────────────────
    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.env.lower() == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Settings singleton — instanciar una sola vez por proceso."""
    return Settings()


# Acceso rápido (uso en endpoints):
#   from backend.core.config import settings
settings = get_settings()
