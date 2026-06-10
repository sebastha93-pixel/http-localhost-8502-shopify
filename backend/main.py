"""
backend.main — Entrypoint del API FastAPI de MALE'DENIM OS.

Uso local:
    uvicorn backend.main:app --reload --port 8000

Uso Railway:
    uvicorn backend.main:app --host 0.0.0.0 --port $PORT

Docs interactivas:
    http://localhost:8000/docs       (Swagger)
    http://localhost:8000/redoc      (ReDoc)
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.core.config import settings
from backend.api import auth, finanzas, health, melonn, metricas, pedidos
from backend.services import usuarios as usuarios_svc
from backend.core.security import hash_password


# ── Lifespan: bootstrap / cleanup ─────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print(f"🚀 MALE'DENIM OS API · env={settings.env}")
    print(f"   CORS allowed: {settings.cors_origins_list}")

    # Bootstrap del primer admin si la tabla usuarios está vacía
    try:
        if (
            settings.auth_bootstrap_email
            and settings.auth_bootstrap_password
            and usuarios_svc.contar() == 0
        ):
            usuarios_svc.crear(
                email=settings.auth_bootstrap_email,
                nombre=settings.auth_bootstrap_nombre,
                password_hash=hash_password(settings.auth_bootstrap_password),
                rol="admin",
            )
            print(f"   👤 Bootstrap admin creado: {settings.auth_bootstrap_email}")
    except Exception as e:
        print(f"   ⚠️  Bootstrap admin omitido: {e}")

    yield
    # Shutdown
    print("👋 API detenida")


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="MALE'DENIM OS · API",
    description="Backend del sistema operativo de MALE'DENIM. "
                "Centraliza logística, conciliación, ventas y operación.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)


# ── CORS — permitir que el frontend Next.js consuma este API ──────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(melonn.router)
app.include_router(metricas.router)
app.include_router(pedidos.router)
app.include_router(finanzas.router)


@app.get("/", include_in_schema=False)
def root():
    return {
        "name":    "MALE'DENIM OS API",
        "version": "0.1.0",
        "docs":    "/docs",
        "health":  "/api/health",
    }
